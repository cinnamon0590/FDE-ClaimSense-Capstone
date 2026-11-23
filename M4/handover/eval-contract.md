# The eval suite is the contract

The SoW's acceptance criteria are not a paragraph: they are 150 executable cases plus a held-out set. A change ships
only if both graders pass. This page is how AutoSure re-runs them, on what schedule, and who may change them.

## What "passing" means (the gate, encoded in `M2/evals/run_evals.py`)
- **overall ≥ 90%** (floor; `EVAL_THRESHOLD` can only raise it, never lower it);
- **AND zero adversarial failures.** One failure in any family (prompt injection, cross-record leakage, forced
  auto-decision, entitlement refusal, PII, citation forgery) blocks the release, whatever the rate;
- **AND every case decided by the model.** A rule-engine fallback never counts as an AI pass;
- **AND every case's money and evidence are right:** the code-computed net payable equals the label, and every
  required citation is present (D-057; added after a deliberate deductible bug passed a decision-only scorer);
- **AND no crashes.** The exit code is the deploy decision.

Origins (M0): SC-1 accuracy, SC-4 fraud routing, SC-5 adversarial zero-tolerance; SC-2 latency is on the dashboard.

## The two graders
| Grader | What it checks | Command | Cost |
|---|---|---|---|
| **1 · The gate** | 150 cases through the real pipeline: outcome, route, net payable, required citations, guardrails, things that must never appear | `cd M2 && python evals/run_evals.py --suite full --concurrency 6` (live) · `--brain replay` with `CLAIMSENSE_LLM_REQUIRED=false` ($0) · `--repeat 3` (release gate: every case stable) | ≈ $3.65 live |
| **2 · Promptfoo** | **agreement:** the same 150 through an independent runner must match the gate 150/150 · **rubric:** 7 live cards judged by `llm-rubric` (gpt-4o) plus deterministic asserts | `cd M4/evals/promptfoo && npx promptfoo@0.125.0 eval -c promptfoo-golden.yaml --no-cache` · rubric: `CLAIMSENSE_BRAIN=live npx promptfoo@0.125.0 eval -c promptfoo.yaml --no-cache` (Node ≥ 22.22) | $0 · ≈ $0.30 |
| **Judge calibration** | is the rubric judge still trustworthy? 40 cards with known answers, judged twice | `cd M4/evals/promptfoo && python judge_calibration.py` | ≈ $0.40 |
| **Held-out** | 20 claims never tuned against: reported, not gated | `cd M2 && python evals/run_evals.py --suite holdout` | ≈ $0.50 |
| **Per-agent evals** | each agent scored against its own labels before code corrects it (floors 100%) | `cd M2 && python evals/agent_evals.py` | ≈ $3 |

## Cadence
| When | What runs | Who looks | Blocks |
|---|---|---|---|
| **Every pull request** | tests, replay gate (150, $0), Promptfoo agreement, container stack, door checks | the author | the merge |
| **Every merge to `main`** | the **live** gate (150, model required) inside the built image, Promptfoo rubric (live), then the image push | CI | the image push to ECR |
| **Daily** (cron or GitHub `schedule:`) | `python M4/ops/continuous_eval.py`: 10 random live cases, at least one adversarial, published to the dashboard | on-call, if it exits 1 | runbook §6 |
| **Monthly** | full live gate `--repeat 3`, per-agent evals, judge calibration (κ must stay ≥ 0.8) | the claims-ops lead | a model/prompt change if κ or stability drops |
| **Every model snapshot or prompt change** | all of the monthly set, **before** the change merges | the author + Senior Adjuster | the change |
| **Quarterly** | write **10 new held-out claims** (labels approved and committed **before** the run), run once, report as is; retire the oldest into the 150 if it found nothing | Senior Adjuster + engineer | nothing (it's a measurement) |

## Changing the contract
- **Labels:** the Senior Adjuster is Accountable (RACI). A label change needs their written approval in the PR,
  and the reason goes in `DECISIONS.md`. The FDE drafted the labels; the client signed them off (D-046, D-052).
- **Adding cases:** any incident or miss adds its case *before* the fix, so the gate guards the repeat. Examples:
  IC-001 (drill), `[RCA-2]` (gateway), HO-20 (PII).
- **Never:** lower the 90% floor, allow an adversarial failure, count a fallback as a pass, or tune against the
  held-out set. Each of these is enforced in code or by the protocol above.
