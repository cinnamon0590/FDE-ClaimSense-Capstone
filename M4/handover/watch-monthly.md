# What to watch monthly

A 30-minute review on the first Monday of each month: the claims-ops lead and the engineer, with the CloudWatch
dashboard `ClaimSense-Operations`, the audit table and the last continuous-eval runs open. Each signal has where to
read it, the line that triggers action, and the action.

| # | Signal | Kind | Where | Healthy | Act when | Action |
|---|---|---|---|---|---|---|
| 1 | **Eval pass rate** (daily live sample) | drift | dashboard "Eval pass rate"; `continuous_eval.py` | ≥ 95%, adversarial 100% | < 90% on any day, or any adversarial failure | runbook §6; full live gate `--repeat 3` |
| 2 | **Adjuster confirmation rate** (SC-3) and **override reasons** | trust | audit table: `confirm_recommendation` rows, action confirm vs override | ≥ 80% confirmed as drafted | < 80%, or one override reason > 20% | read the overrides with the Senior Adjuster; add the pattern as eval cases |
| 3 | **Hold and fallback share** | drift | dashboard "Held for a person" | holds < 5%, fallbacks 0 | holds > 10% or any fallback | M2 runbook "Hold spike" / "Model outage" |
| 4 | **Fraud routing** (SC-4): routes vs SIU's verdicts | accuracy | SIU outcomes vs `route → fraud-investigator` | recall ≥ 90%, false routes ≤ 10% | SIU reports > 10% of referrals unfounded | relabel with SIU; add cases |
| 5 | **Cost per claim** | cost | dashboard "Cost per claim" | ≈ $0.025 | > $0.05 sustained a week | M2 runbook "Cost spike" (prompt growth, retries, model change) |
| 6 | **p95 claim latency** (SC-2) | speed | dashboard "Claim latency" | ≈ 17 s | > 60 s (SLO 90 s) | check model-provider latency; G1b cache; concurrency |
| 7 | **Door error rate and alarm count** | reliability | dashboard "Error rate" (app **and** edge lines); alarm history | 0 alarms | any alarm | RCA if over 15 min; check the action items closed |
| 8 | **Corpus growth vs retrieval**: clauses, quarantined chunks, citations per decision | recall | KB audit rows (`N kept, M quarantined`); the corpus version | 0 quarantined; required citations present (SC-3 proxy 100%) | any quarantined chunk; a new clause never retrieved for its topic | runbook §4; check the manifest and S3 match (`s3_doc_store_check.py --deployed`) |
| 9 | **Refusals** (401/403) by user | access | dashboard "Refusals"; audit `deny` rows | low and explained | a spike from one user, or refusals for someone who should have access | review the directory (runbook §1); Security if probing |
| 10 | **Model deprecation notices** and snapshot age | dependency | OpenAI deprecations page; `M2/claimsense/config.py` pinned snapshots | > 90 days to retirement | < 90 days to retirement | M2 runbook "Adopt a new model snapshot": the full eval set before switching |

**Also quarterly:**
- run every runbook procedure once (proposed risk R10: operations code that only runs during failures);
- refresh the held-out set ([eval-contract.md](eval-contract.md#cadence));
- re-run the incident drill (`python M4/drill/incident_drill.py run --label <quarter>`) and compare its time to
  verified recovery with 279 s.
