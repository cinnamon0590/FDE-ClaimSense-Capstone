"""Run one claim end to end: boundary -> Intake -> Coverage -> Assessment -> Decision Draft -> guardrails.

The order is fixed in code (M1 D-011), not left to model handoffs: every claim gets every check, and
each step's typed output is the next step's input. What decided the verdict is always explicit:

  decided_by = "agents"            the four agents produced it (verdict_source="model"); guardrails
                                   may still have rerouted it, and guardrails_fired says which
               "guardrail_hold"    a tripwire stopped the run and routed it to a senior adjuster
                                   (fail closed); still the co-pilot's own decision path ("model")
               "boundary_refusal"  the caller isn't entitled: no agent ran, no claim data returned
               "fallback"          the model failed or the budget cap hit: rule engine,
                                   verdict_source="deterministic_fallback", never counted as AI
"""
import asyncio
import json
import time
import uuid

from agents import (AgentsException, InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered, RunConfig, Runner,
                    trace)

from . import PROMPT_VERSION, config
from ._m1 import SCHEMAS, guardrails as G, jsonschema_lite
from .agents_def import ALL_SPECS as SPECS, build_agents, model_name
from .injection_classifier import InjectionClassifier
from .boundary_client import AGENT_IDS, make_boundary
from .deterministic import (compute, coverage_questions, fallback_card, missing_documents, route_priority,
                            verified_facts)
from .models import AssessmentResult, CoverageResult, DecisionCard, DecisionDraft, IntakeResult
from .observability import Checkpoints, configure_tracing, cost_usd
from .retrieval import get_index
from .tools import RunCtx, claim_packet, screen_packet

COMMON = json.loads((SCHEMAS / "common.schema.json").read_text())
TYPES = {"intake": IntakeResult, "coverage": CoverageResult, "assessment": AssessmentResult, "decision": DecisionDraft,
         "decision_check": DecisionDraft}


class BudgetExceeded(RuntimeError):
    pass


def schema_errors(card):
    return jsonschema_lite.validate(card, {"$ref": "#/$defs/DecisionCard", "$defs": COMMON["$defs"]}, root=COMMON)


def _policy_view(p):
    return {k: p.get(k) for k in ("coverages", "deductible", "use_class", "term_start", "term_end", "status_field", "renewal")}


class Pipeline:
    def __init__(self, brain=None, boundary=None, record=False, index=None, store=None):
        configure_tracing()
        self.brain = brain or config.brain_name()
        self.boundary = boundary or make_boundary(config.BOUNDARY_URL)
        self.agents, self.store = build_agents(self.brain, record=record, store=store)
        self.record = record
        self.index = index or get_index("lexical" if self.brain == "replay" else None)
        self.checkpoints = Checkpoints()
        self.classifier = InjectionClassifier(self.brain) if config.G1B_CLASSIFIER else None

    def model_label(self, key, claim_id):
        tier = SPECS[key][3]
        if self.brain == "replay":
            try:
                rec = self.store.load(claim_id)["agents"][key].get("model", model_name(tier))
            except (LookupError, KeyError):
                rec = model_name(tier)
            return f"replay:{rec}"
        return model_name(tier)

    async def _step(self, key, payload, ctx, usage, run_id, resume):
        if resume and (saved := self.checkpoints.get(run_id, key)) is not None:
            ctx.emit("checkpoint", f"{SPECS[key][0]} restored from checkpoint")
            if key == "intake":                  # re-read the file through the boundary and re-screen it
                await screen_packet(ctx, claim_packet(ctx), meter=False)    # G1b verdicts cached: no model call
            if key == "coverage" and (ret := self.checkpoints.get(run_id, "retrieval")):
                ctx.retrieved_clause_ids, ctx.quarantined = set(ret["ids"]), ret["quarantined"]
                ctx.retrieved_chunks = ret.get("chunks", {})
            return TYPES[key].model_validate(saved)
        name = SPECS[key][0]
        ctx.emit("agent_start", name, model=self.model_label(key, ctx.claim_id))
        t0 = time.time()
        m = self.model_label(key, ctx.claim_id)

        def meter(u):
            usage.append({"agent": name, "model": m, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                          "requests": u.requests, "usd": cost_usd(m, u.input_tokens, u.output_tokens)})
        try:
            res = await Runner.run(self.agents[key], json.dumps(payload) if not isinstance(payload, str) else payload,
                                   context=ctx, max_turns=10,
                                   run_config=RunConfig(workflow_name="claimsense", trace_include_sensitive_data=False))
        except AgentsException as e:          # a tripped wire still spent tokens: meter them, then re-raise
            if getattr(e, "run_data", None) is not None:
                meter(e.run_data.context_wrapper.usage)
            raise
        meter(res.context_wrapper.usage)
        spent = sum(x["usd"] for x in usage)
        out = res.final_output
        ctx.emit("agent_end", name, seconds=round(time.time() - t0, 2), output=out.model_dump())
        if key == "coverage":
            # the retrieved TEXT too: after a resume, citation quotes must still be the retrieved wording
            self.checkpoints.put(run_id, "retrieval", {"ids": sorted(ctx.retrieved_clause_ids), "quarantined": ctx.quarantined,
                                                       "chunks": ctx.retrieved_chunks})
        self.checkpoints.put(run_id, key, out.model_dump())
        ctx.emit("checkpoint_saved", key)
        if self.brain == "live" and spent > config.CASE_BUDGET_USD:
            raise BudgetExceeded(f"case budget ${config.CASE_BUDGET_USD:.2f} exceeded (${spent:.4f})")
        return out

    async def run(self, claim_id, user_id, on_event=None, run_id=None, resume=False):
        t0 = time.time()
        run_id = run_id or f"{claim_id}:{uuid.uuid4().hex[:8]}"
        ctx = RunCtx(boundary=self.boundary, user_id=user_id, claim_id=claim_id, index=self.index, on_event=on_event,
                     classifier=self.classifier)
        usage = []
        result = {"claim_id": claim_id, "user_id": user_id, "run_id": run_id, "brain": self.brain,
                  "replay_source": self.store.source(claim_id) if self.brain == "replay" else None}

        with trace("ClaimSense claim", group_id=claim_id, metadata={"claim_id": claim_id, "brain": self.brain}) as tr:
            result["trace_id"] = tr.trace_id
            # 0 · entitlement, in code, before any agent (A2/A3). Same error for missing and forbidden.
            claim = self.boundary.claim(user_id, claim_id, AGENT_IDS["intake"])
            if "error" in claim:
                ctx.emit("refusal", "boundary", code=claim["error"]["code"])
                return self._finish(result, ctx, usage, t0, decided_by="boundary_refusal", response={
                    "outcome": "refused", "returns_claim_data": False, "verdict_source": "model",
                    "error": claim["error"]})
            ctx.claim = claim
            if self.record:
                self.store.start_recording(claim_id)

            try:
                intake = await self._step("intake", f"Claim {claim_id}: run document intake.", ctx, usage, run_id, resume)
                computed = compute(ctx.claim, ctx.policy)
                # code owns checklists and thresholds: overwrite the model where a rule, not judgment, decides
                missing = missing_documents(ctx.claim["loss_type"], [d["doc_type"] for d in ctx.documents])
                if sorted(missing) != sorted(intake.missing_documents):
                    ctx.emit("code_override", "intake.missing_documents", model=intake.missing_documents, code=missing)
                    intake = intake.model_copy(update={"missing_documents": missing})
                facts = verified_facts(ctx.claim, ctx.policy, computed, missing, intake.inconsistencies)
                ctx.emit("computed", "deterministic spine", **computed)
                cov = await self._step("coverage", {"claim_id": claim_id, "verified_facts": facts,
                                                    "coverage_questions": coverage_questions(ctx.claim, ctx.policy, computed, missing,
                                                                                         intake.inconsistencies),
                                                    "intake": intake.model_dump(),
                                                    "computed": computed, "policy": _policy_view(ctx.policy)},
                                       ctx, usage, run_id, resume)
                asm = await self._step("assessment", {"claim_id": claim_id, "verified_facts": facts,
                                                      "intake": intake.model_dump(), "coverage": cov.model_dump(),
                                                      "computed": computed, "fraud_risk_score": ctx.claim["fraud_risk_score"]},
                                       ctx, usage, run_id, resume)
                fraud = (asm.fraud_suspected or ctx.claim["fraud_risk_score"] >= 0.7 or bool(intake.inconsistencies))
                route = route_priority(fraud, asm.injury_exposure, computed)
                if fraud != asm.fraud_suspected:
                    ctx.emit("code_override", "assessment.fraud_suspected", model=asm.fraud_suspected, code=fraud)
                    asm = asm.model_copy(update={"fraud_suspected": fraud,
                                                 "fraud_signals": asm.fraud_signals or list(intake.inconsistencies)})
                if route != asm.recommended_route or asm.total_loss != (computed["repair_to_acv_ratio"] >= 1):
                    ctx.emit("code_override", "assessment.recommended_route", model=asm.recommended_route, code=route)
                    asm = asm.model_copy(update={"recommended_route": route,
                                                 "total_loss": computed["repair_to_acv_ratio"] >= 1})
                try:
                    decision_in = {"claim_id": claim_id, "verified_facts": facts, "intake": intake.model_dump(),
                                   "coverage": cov.model_dump(), "assessment": asm.model_dump(), "computed": computed}
                    draft = await self._step("decision", decision_in, ctx, usage, run_id, resume)
                    tripped = None
                    disagreement = await self._second_opinion(claim_id, draft, decision_in, ctx, usage, run_id, resume)
                except OutputGuardrailTripwireTriggered as e:
                    disagreement = None
                    draft, tripped = e.guardrail_result.agent_output, e.guardrail_result.output.output_info
                    ctx.emit("guardrail", "decision_safety_tripwire", tripped=True, **tripped)
                    ctx.emit("handoff", "Decision Draft -> senior adjuster (human)")
                card = self._card(claim_id, draft, cov, asm, intake, computed)
                # code owns the quotes too: an adjuster sees the clause wording actually retrieved, never a paraphrase
                for cit in card["citations"]:
                    if cit["source_id"] in ctx.retrieved_chunks:
                        cit["quote"] = ctx.retrieved_chunks[cit["source_id"]]["text"][:240]
                if tripped:
                    card["reasoning"] = ("Model draft withheld by the decision safety guardrail: "
                                         + "; ".join(tripped["problems"]) + ".")
                decided_by = "agents"
                if disagreement:
                    # the model is not sure: a coin-flip case goes to a person, never out as a confident verdict
                    card.update(outcome="flag_review", route_to="senior-adjuster",
                                guardrails_fired=card["guardrails_fired"] + ["model_disagreement"],
                                reasoning=(f"Two independent drafts disagreed ({disagreement}), so a senior adjuster decides. "
                                           f"First draft: {card['reasoning']}")[:2000])
                    ctx.emit("handoff", "Decision Draft disagreed with itself -> senior adjuster (human)")
                    decided_by = "consistency_hold"
            except (InputGuardrailTripwireTriggered, OutputGuardrailTripwireTriggered) as e:
                info = e.guardrail_result.output.output_info or {}
                where = e.guardrail_result.agent.name if hasattr(e.guardrail_result, "agent") else "pipeline"
                ctx.emit("guardrail", type(e).__name__, tripped=True, agent=where, guardrail=info.get("guardrail"),
                         hits=len(info.get("hits", [])), not_retrieved=info.get("not_retrieved", []))
                ctx.emit("handoff", f"{where} -> senior adjuster (human)")
                computed = compute(ctx.claim, ctx.policy) if ctx.policy else self._blank_computed(ctx)
                card = self._hold_card(claim_id, computed, where, info)
                decided_by = "guardrail_hold"
            except Exception as e:                       # model outage, bad output, budget cap, missing replay
                ctx.emit("fallback", type(e).__name__, error=str(e)[:200])
                if not ctx.policy:
                    pol = self.boundary.policy(user_id, ctx.claim["policy_id"], AGENT_IDS["intake"])
                    ctx.policy = pol if "error" not in pol else {}
                computed = compute(ctx.claim, ctx.policy) if ctx.policy else self._blank_computed(ctx)
                card = fallback_card(ctx.claim, ctx.policy, computed, reason=type(e).__name__)
                decided_by = "fallback"

            if self.record:
                if decided_by == "agents" and self.store.commit_recording(claim_id, PROMPT_VERSION):
                    ctx.emit("recorded", "replay file updated")
                else:
                    self.store.discard_recording(claim_id)
            # Fallback citations come from the code rule table and the clause manifest (not from retrieval), so
            # they count as grounded for G5; a model citation must still have been retrieved for this request.
            grounded = set(ctx.retrieved_clause_ids)
            if decided_by == "fallback":
                grounded |= {c["source_id"] for c in card["citations"]}
            # final code-owned pass: the M1 spec, unchanged, on every card (G4, G5, G6, G7 + G1/G2 records)
            card, _ = G.apply_guardrails(card, computed=computed, retrieved_clause_ids=grounded,
                                         claim_doc_ids={d["doc_id"] for d in ctx.documents} or set(ctx.claim.get("document_ids", [])),
                                         untrusted_texts=ctx.untrusted_texts or [ctx.claim.get("narrative", "")],
                                         quarantined=len(ctx.quarantined))
            extra = (["pii_masked"] if ctx.pii_masked else []) + (["cross_record_blocked"] if ctx.foreign_claims_masked else [])
            extra += (["injection_detected"] if any(cat == "ai_instruction" for cat, _ in ctx.g1b) else []) + \
                     (["auto_decision_blocked"] if any(cat == "pressure_to_skip_review" for cat, _ in ctx.g1b) else [])
            card["guardrails_fired"] = sorted(set(card["guardrails_fired"]) | set(extra))
            for gname in card["guardrails_fired"]:
                ctx.emit("guardrail", gname, fired=True)
            card = DecisionCard.model_validate(card).contract_dict()
            errs = schema_errors(card)
            if errs:
                raise ValueError(f"card failed the M1 schema: {errs}")
            return self._finish(result, ctx, usage, t0, decided_by=decided_by, response=card)

    def wants_second_opinion(self, claim_id):
        if self.brain == "live":
            return config.CONSISTENCY_CHECK
        try:
            return "decision_check" in self.store.load(claim_id)["agents"]
        except (LookupError, KeyError):
            return False

    async def _second_opinion(self, claim_id, first, payload, ctx, usage, run_id, resume):
        """Return None when a second independent draft agrees on outcome and route, else a short description."""
        if not self.wants_second_opinion(claim_id):
            return None
        try:
            second = await self._step("decision_check", payload, ctx, usage, run_id, resume)
        except OutputGuardrailTripwireTriggered:
            ctx.emit("guardrail", "decision_safety_tripwire", tripped=True, agent="second opinion")
            return "the second draft failed the decision safety check"
        a = first.outcome + (f"→{first.route_to}" if first.route_to else "")
        b = second.outcome + (f"→{second.route_to}" if second.route_to else "")
        ctx.emit("consistency", "Decision Draft second opinion", agree=a == b, first=a, second=b)
        return None if a == b else f"{a} vs {b}"

    def _blank_computed(self, ctx):
        return {"loss_in_policy_term": False, "net_payable": None, "repair_to_acv_ratio": 0.0, "over_authority_limit": False}

    def _card(self, claim_id, draft, cov, asm, intake, computed):
        return {"claim_id": claim_id, "outcome": draft.outcome, "route_to": draft.route_to,
                "reasoning": draft.reasoning if len(draft.reasoning) >= 20 else draft.reasoning + " (see citations)",
                "citations": [c.model_dump() for c in draft.citations], "computed": computed,
                "judgment": {"coverage_finding": cov.coverage_finding, "fraud_signals": asm.fraud_signals,
                             "injury_exposure": asm.injury_exposure, "missing_documents": intake.missing_documents},
                "verdict_source": "model", "guardrails_fired": [], "adjuster_confirmation_required": True,
                "model": {"name": self.model_label("decision", claim_id), "prompt_version": PROMPT_VERSION}}

    def _hold_card(self, claim_id, computed, where, info):
        why = {"G1": f"{len(info.get('hits', []))} instruction-like passage(s) in untrusted claim text",
               "G5": "cited clause(s) that were not retrieved: " + ", ".join(info.get("not_retrieved", []))}.get(
            info.get("guardrail"), "a guardrail tripped")
        return {"claim_id": claim_id, "outcome": "flag_review", "route_to": "senior-adjuster",
                "reasoning": f"Stopped at {where} before a decision was drafted" + ("." if info.get("guardrail") == "G1" else f": {why}.")
                             + " The affected text is highlighted for the adjuster in the audit trail.",
                "citations": [], "computed": computed,
                "judgment": {"coverage_finding": "ambiguous", "fraud_signals": [], "injury_exposure": False,
                             "missing_documents": []},
                "verdict_source": "model", "guardrails_fired": [], "adjuster_confirmation_required": True,
                "model": {"name": self.model_label("decision", claim_id), "prompt_version": PROMPT_VERSION}}

    def _finish(self, result, ctx, usage, t0, decided_by, response):
        usage = [dict(u, usd=cost_usd(u["model"], u["input_tokens"], u["output_tokens"])) for u in ctx.g1b_usage] + usage
        result.update(response=response, decided_by=decided_by, events=ctx.events, usage=usage,
                      cost_usd=round(sum(u["usd"] for u in usage), 6), latency_s=round(time.time() - t0, 2),
                      retrieved_clause_ids=sorted(ctx.retrieved_clause_ids), quarantined=ctx.quarantined)
        return result


_LOOP = None


def run_sync(coro):
    """Run a coroutine on ONE event loop per process. asyncio.run() makes a new loop each call, but the
    OpenAI SDK's shared HTTP client keeps pooled connections bound to the first loop, so the next run's
    first calls fail with "Event loop is closed" and fall back (found by the 3-run release gate)."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP.run_until_complete(coro)


def run_claim(claim_id, user_id, **kw):
    """Synchronous convenience wrapper (CLI, tests, the eval runner)."""
    run_kw = {k: kw.pop(k) for k in ("on_event", "run_id", "resume") if k in kw}
    return run_sync(Pipeline(**kw).run(claim_id, user_id, **run_kw))
