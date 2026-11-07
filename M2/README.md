# M2: Building production agents (course Week 15)

> **Naming:** the ClaimSense brief calls this **"Milestone 3 (Week 3)"**. This repo numbers milestones by course
> week: M0 = W13, M1 = W14, **M2 = W15**, M3 = W16, M4 = W17.

Goal: move from architecture to a **working claims pipeline**. Four agents on the OpenAI Agents SDK, grounded in
retrieved policy clauses, running in containers from one command, under change control. A CI eval gate blocks
the image push, and model verdicts are always distinguishable from the deterministic fallback.

## Deliverables: the union of every source

Sources: the W15 assignment page (5 deliverables), the brief's Milestone 3, and the W15 class (M2 floor: a
guardrail that trips, human handoff, CI gate green, traces; stretch: Strands, Lambda/AgentCore, cost table).

| # | Deliverable | Required by | Where | Proof |
|---|---|---|---|---|
| 1 | **Agent set on the OpenAI Agents SDK with strict typed outputs** | assignment · brief M3 | [`claimsense/agents_def.py`](claimsense/agents_def.py) · [`models.py`](claimsense/models.py) · [`pipeline.py`](claimsense/pipeline.py) | Four agents (Document Intake, Coverage Check, Claim Assessment, Decision Draft), each with a strict Pydantic `output_type`; every card validates against the M1 DecisionCard schema ([`tests/test_contract_and_types.py`](tests/test_contract_and_types.py)) |
| 2 | **Containers; the stack starts with one command** | assignment · brief M3 | [`docker-compose.yml`](docker-compose.yml) · [`services/`](services/) · [`Makefile`](Makefile) | `make up` starts 4 services (mock systems, boundary, orchestrator, console); [`evidence/stack-smoke.txt`](evidence/stack-smoke.txt); CI job `stack-smoke` does the same on every push |
| 3 | **Retrieval over the policy corpus; coverage cites the clause IDs actually retrieved** | assignment · brief M3 | [`claimsense/retrieval.py`](claimsense/retrieval.py) · [`tools.py`](claimsense/tools.py) · [`guardrails.py`](claimsense/guardrails.py) | Coverage and Decision tripwires reject any clause not retrieved for *this* request; quotes are the retrieved wording, never a paraphrase ([`tests/test_guardrails_tripwires.py`](tests/test_guardrails_tripwires.py), [`tests/test_retrieval.py`](tests/test_retrieval.py)) |
| 4 | **CI pipeline in which a failing eval gate blocks the image push** | assignment · W15 class | [`../.github/workflows/eval-gate.yml`](../.github/workflows/eval-gate.yml) · [`cloud/oidc.sh`](cloud/oidc.sh) | `build-push` needs every gate (replay gate on each PR, live-model gate on main); GitHub OIDC role scoped to one ECR repo; red-gate and green-gate runs in [`evidence/`](evidence/) |
| 5 | **All four decision outcomes correct; model verdicts distinguishable from fallback** | assignment · brief M3 | [`claimsense/deterministic.py`](claimsense/deterministic.py) · `verdict_source` + `decided_by` | **Live: 40/40** ([`evidence/results-live-final.txt`](evidence/results-live-final.txt)); fallback is labelled, never approves, never counts for the gate ([`tests/test_deterministic.py`](tests/test_deterministic.py), [`tests/test_eval_gate.py`](tests/test_eval_gate.py)) |
| W15 | A guardrail that **trips** + **human handoff** | class M2 floor | `@input_guardrail` + 3 `@output_guardrail` tripwires | CS-016 / CS-035 stop at Intake and go to a senior adjuster; console shows the handoff |
| W15 | **Traces** and **sessions** | class M2 floor | [`claimsense/observability.py`](claimsense/observability.py) | Every run writes a JSONL trace (agent, generation, tool, guardrail spans); OpenAI Traces when live; SQLite checkpoints let a crashed run resume without paying twice |
| W15 | **Model routing + cost table** | class | [`evidence/cost-table-live.md`](evidence/cost-table-live.md) | gpt-4o-mini for the volume steps, gpt-4o for the money steps: **$0.016 per claim**, p95 17.5 s |

### Extra credit
- **20 new eval cases** (CS-021 to CS-040, [`evals/cases-m2.json`](evals/cases-m2.json)): 40 of the 150 due by Week 5. They add two adversarial families, **PII exposure** (the M1 "still to come" item) and **citation forgery**, plus exact boundaries ($25,000 vs $25,001; ratio 1.0; first and last day of term).
- **Strands port** of the Coverage agent ([`stretch/strands_coverage.py`](stretch/strands_coverage.py)): same prompt, typed output, retrieval and citation rule on a second harness ([`evidence/strands-port.json`](evidence/strands-port.json)). The first attempt let the model skip the tool, and the same G5 check caught every invented clause ID ([`evidence/strands-port-attempt1-structured_output-only.json`](evidence/strands-port-attempt1-structured_output-only.json)).
- **Deploy ladder**: the pushed image runs unchanged on AWS Lambda (Web Adapter), IAM-signed invoke, then torn down ([`cloud/lambda/`](cloud/lambda/)). AgentCore Runtime is the managed next rung.
- **Adjuster console** (Streamlit): watch the four agents stream; badge for Model verdict / Guardrail hold / Deterministic fallback / Refused; code-computed facts shown apart from model judgment; human-only Confirm / Override.
- **Secrets at runtime**: the OpenAI key is read from Secrets Manager in AWS, never baked in (D-023).
- [`DECISIONS.md`](DECISIONS.md): D-017 to D-023.

## Headline numbers (live, gpt-4o-mini + gpt-4o, 40 cases, prompt m2-v8)

| | Result | Target |
|---|---|---|
| Decision accuracy | clear 15/15 · edge 14/14 · **overall 40/40** | ≥ 90% · ≥ 75% · gate ≥ 85% |
| Adversarial | **11/11** | 100% (gate) |
| Verdicts model-produced | 40/40 (fallback share 0%) | 100% (gate) |
| Fraud routing | recall 4/4 · false routes 0/34 | ≥ 90% · ≤ 10% |
| Confirmable as written (correct + every required citation) | 24/27 (89%) | M0 SC-3 proxy |
| Latency per claim | p95 17.5 s · median 14.1 s | < 90 s |
| Cost per claim | $0.016 (≈ $150/month at 450 claims/day) | |

**How we got there.** The first live run was **blocked** (35/40, one adversarial miss). Every miss was traced to
a root cause, and almost every fix moved a *rule* out of the model and into code (D-001): the required-document
checklist, routing priority, the fraud rule, renewal-pending and theft-reporting conditions, and plain statements
of what code has already verified. Golden labels were never changed. The full history of runs is in
[`evidence/results-live-*.txt`](evidence/). The live model varies from run to run, which is why the gate floor
is 85% and not 100%.

## How it works

```
adjuster ─► console ─► orchestrator ─► boundary (entitlement · audit · idempotency) ─► mock AutoSure systems
                          │
                          ├─ Intake (mini) ── get_claim_file: PII masked, injected text removed (G1/G3/G7)
                          ├─ code: dates, money, checklist, verified facts, coverage questions
                          ├─ Coverage (4o) ── search_clauses: provenance quarantine (G2); cites ⊆ retrieved (G5)
                          ├─ Assessment (mini) ── code re-applies fraud rule + routing priority
                          ├─ Decision Draft (4o) ── tripwire: citations, other claims, echoed injections
                          └─ apply_guardrails (M1 spec, unchanged) ─► DecisionCard ─► draft written back
```

The M1 reference modules (guardrails, boundary, scorer) are **imported, not copied**
([`claimsense/_m1.py`](claimsense/_m1.py)), so the spec and the product can't drift apart.

**Brains.** `live` calls OpenAI. `replay` plays back recorded model turns through the real Runner, tools,
parsing and guardrails: $0, deterministic, no key. That is what CI runs on every PR. Replays are re-recorded
whenever a prompt changes (`make record`); 38 of 40 are real recordings. The two injection cases stop at Intake
by design, so a full recording never exists for them.

## Run it

```bash
colima start                      # Docker runtime (once per boot)
cd M2 && make up                  # console: http://localhost:8510 (8501 is taken on this laptop)
make smoke                        # one claim per outcome through the running stack
make test                         # 35 tests, $0
make evals                        # the CI gate on the replay brain, $0
make evals-live                   # the gate on the live models (needs OPENAI_API_KEY in M2/.env, ~$0.60)
```

No key? Leave `OPENAI_API_KEY` empty (or `MOCK_BRAIN=1`) and everything runs on the replay brain.

## Found and fixed along the way
- **M1 guardrail spec echoed injected text** into the card when routing to a human. It now reports a count (D-020).
- **M0 scorer made the gate demand 100% accuracy.** "Every verdict model-produced" also counted correctness. It is now one shared `gate_passes()` with a test (`test_gate_allows_a_few_misses_above_the_floor`).
- **Recorder** could overwrite good replays during an outage (found when the OpenAI credit ran out mid-run). Recordings are now staged and committed only for complete claims, with a regression test.
- **Deploy script** first passed the key as a Lambda env var; replaced with a runtime Secrets Manager read before any deploy (D-023).
