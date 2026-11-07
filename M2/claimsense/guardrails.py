"""M1's guardrail rules (reference_guardrails.py) wired into the Agents SDK as tripwires.

  input  · untrusted_input_scan       every agent: G1 on the text the agent is about to receive
  output · intake_injection_tripwire  Intake: G1 hits found inside documents by the tool scan
  output · coverage_citation_tripwire Coverage: cited clause IDs must have been retrieved (G5)
  output · decision_safety_tripwire   Decision Draft: G5 citations, G6 finalisation, G7 cross-record

A tripped wire raises in the SDK; the pipeline catches it and fails CLOSED to a senior adjuster,
then `apply_guardrails` (the M1 spec, unchanged) makes the final, code-owned pass on every card.
"""
import json

from agents import GuardrailFunctionOutput, input_guardrail, output_guardrail

from ._m1 import guardrails as G


def _text(x):
    return x if isinstance(x, str) else json.dumps(x, default=str)


@input_guardrail(name="untrusted_input_scan")
async def untrusted_input_scan(ctx, agent, input):
    hits = G.scan_injection(_text(input))
    return GuardrailFunctionOutput(output_info={"guardrail": "G1", "hits": hits}, tripwire_triggered=bool(hits))


@output_guardrail(name="intake_injection_tripwire")
async def intake_injection_tripwire(ctx, agent, output):
    hits = list(ctx.context.injection_hits) + G.scan_injection(_text(output.model_dump()))
    return GuardrailFunctionOutput(output_info={"guardrail": "G1", "hits": hits}, tripwire_triggered=bool(hits))


@output_guardrail(name="coverage_citation_tripwire")
async def coverage_citation_tripwire(ctx, agent, output):
    bad = [c for c in output.cited_clause_ids if c not in ctx.context.retrieved_clause_ids]
    return GuardrailFunctionOutput(output_info={"guardrail": "G5", "not_retrieved": bad},
                                   tripwire_triggered=bool(bad))


@output_guardrail(name="decision_safety_tripwire")
async def decision_safety_tripwire(ctx, agent, output):
    c = ctx.context
    card = {"claim_id": c.claim_id, "outcome": output.outcome, "reasoning": output.reasoning,
            "citations": [x.model_dump() for x in output.citations]}
    problems = G.check_citations(card, c.retrieved_clause_ids, {d["doc_id"] for d in c.documents})
    foreign = G.foreign_claim_references(card)
    if foreign:
        problems.append(f"references {len(foreign)} other claim(s)")
    if G.scan_injection(output.reasoning):          # report it, never repeat it
        problems.append("the draft repeats instruction-like text from the claim file")
    return GuardrailFunctionOutput(output_info={"guardrail": "G5/G7", "problems": problems},
                                   tripwire_triggered=bool(problems))
