# M4 · Evaluation, observability, reliability and handover (W17 · Brief Milestone 5)

The last milestone: prove the system is safe to operate, observable when something goes wrong, recoverable after
a failure, and usable by someone other than its author. Requirements are the union of the Week 17 assignment, the
brief's Milestone 5 and Submission 2, the W17 deck and notebook, and the graded `milestone-M4-capstone.md`.

| # | Deliverable | Status | Evidence |
|---|---|---|---|
| 1 | **150-case suite incl. prompt injection, cross-record leakage, forced auto-decision; the gate passes with the model required** | ✅ | [`evidence/release-gate-live.txt`](evidence/release-gate-live.txt), [`gate-run-live.txt`](evidence/gate-run-live.txt), [`gate-run.txt`](evidence/gate-run.txt) |
| 2 | **Second grader (Promptfoo) + calibrated judge** | ✅ | [`evidence/second-grader.txt`](evidence/second-grader.txt), [`judge-calibration.txt`](evidence/judge-calibration.txt) |
| 3 | **Dashboard (error rate, call volume, p95 latency, eval pass, cost per claim) + one alarm** | ✅ live | [`evidence/dashboard.png`](evidence/dashboard.png) |
| 4 | **Incident drill + one-page RCA with time to verified recovery + the eval case it spawned** | ✅ two drills on AWS; recovery 481 s → 279 s | [`drill/RCA-2026-11-23.md`](drill/RCA-2026-11-23.md), [`evidence/incident-drill-2.txt`](evidence/incident-drill-2.txt) |
| 5 | Runbook: add a user, roll back, escalate a flagged claim manually, update the policy corpus | planned | |
| 6 | Client presentation with a live demonstration (+ the ≤10-minute recording) | planned | |
| 7 | Handover pack | planned | |
| F1 | **Deployed frontend URL** (console + orchestrator on AWS) | ✅ https://d2jfndltae6j40.cloudfront.net | [`evidence/frontend-deployed.txt`](evidence/frontend-deployed.txt) |
| F | Final submission: observation document, final tag, CI on the submitted commit | planned | |

## 1 · The 150-case suite and the gate

```
golden suite — 150 cases · gate >= 90% AND 0 adversarial failures
  clear        60/60
  edge         45/45
  adversarial  45/45
    citation_forgery       3/3
    cross_record_leakage   10/10
    entitlement_refusal    5/5
    forced_auto_decision   10/10
    pii_exposure           3/3
    prompt_injection       14/14
  adversarial failures: none
```

- **Live, model required, 3 runs:** 150/150 in every run, every case the same answer every time, 0 of 450 second
  opinions disagreed, every verdict from the model (release gate PASS; $10.96, $0.024 per claim).
- **Each agent on its own, before code corrects it** (D-031, floors 100%): Intake 145/145, Coverage 132/132,
  Assessment 132/132, Decision 132/132, 0 code overrides.
- **Headline numbers (live):** fraud recall 12/12, false fraud routes 0/133; confirmable as written 84/84;
  p95 latency 12–13 s per claim (target < 90 s).
- **How the cases were built and labelled:** `evals/build_cases_m4.py` (stratified by outcome × loss type × the
  boundaries that decide cases); labels derived from the business rules and **signed off by the Senior Adjuster**
  (15 sampled + all 34 new adversarial cases + 16 coverage judgments: [`evals/label-review.md`](evals/label-review.md)).
- **Zero tolerance is code:** `run_evals.py` blocks the release on any adversarial failure whatever the average
  (`score.gate_passes` + the named list in the report); CI runs the replay gate on every PR and **all 150 cases live** on
  every merge to `main`, and pushes the image only when both graders pass (D-047).
- Prompt **m2-v13** (D-046 in [`DECISIONS.md`](DECISIONS.md)): what the larger suite exposed and how each slip was
  fixed without lowering a gate.

Run it: `python M2/evals/run_evals.py` (live gate) · `CLAIMSENSE_LLM_REQUIRED=false python M2/evals/run_evals.py
--brain replay` ($0) · `python M2/evals/run_evals.py --repeat 3` (release gate) · `python M2/evals/agent_evals.py`.

## 2 · The second grader: Promptfoo (D-047)

| Grader | What it checks | Result |
|---|---|---|
| Agreement runner (`evals/promptfoo/promptfoo-golden.yaml`) | all 150 golden cases through the real pipeline, `equals: PASS` | **150/150**, identical to the gate |
| Rubric grader (`evals/promptfoo/promptfoo.yaml`) | 7 **live** decision cards: clean approval, fraud referral, and every adversarial family; deterministic asserts + `llm-rubric` | **7/7** |
| Judge calibration (`evals/promptfoo/build_calibration.py`) | the judge vs 40 cards with known answers, twice | **κ 0.95**, 39/40, 40/40 consistent |

Run it (Node ≥ 22.22): `cd M4/evals/promptfoo && npx promptfoo@0.125.0 eval -c promptfoo-golden.yaml --no-cache`;
the rubric grader adds `CLAIMSENSE_BRAIN=live` and an `OPENAI_API_KEY`. CI job `second-grader` runs both and gates
the image push.

## 3 · Observability: dashboard, alarm, continuous eval (D-048)

![ClaimSense-Operations dashboard](evidence/dashboard.png)

- **Dashboard `ClaimSense-Operations`** (CloudWatch): call volume · error rate (5xx ÷ requests) · door and claim
  latency p50/p95 · eval pass rate · cost per claim · refusals · fallbacks and holds.
- **SLOs (from M0):** eval pass ≥ 90% and zero adversarial failures (SC-1, SC-5) · claim p95 < 90 s (SC-2) · door
  error rate < 5% (the alarm).
- **One alarm:** `ClaimSense-door-error-rate`, door 5xx > 5% in 2 of 3 minutes → SNS email.
- **Metrics:** EMF lines from both services (`M2/claimsense/metrics.py`), no agent. **Continuous eval:**
  `python M4/ops/continuous_eval.py` (first run 10/10, published).
- Rebuild: `ALARM_EMAIL=… python M4/ops/observability.py apply` · snapshot: `python M4/ops/dashboard_snapshot.py`.

## 4 · The deployed frontend (D-049)

**https://d2jfndltae6j40.cloudfront.net** · sign in with the demo passcode (given in the submission form, never in
this repo), pick one of the five synthetic users, choose a claim, **Run co-pilot**.

```
browser ──HTTPS──▶ CloudFront ──▶ ALB (CloudFront-only ingress) ──▶ ECS Fargate task
                                                                     ├─ console       :8501  (Streamlit)
                                                                     └─ orchestrator  :8003  (localhost only)
                                                                           │ 5-min delegated token, MCP
                                                                           ▼
                                                     the door: API Gateway → Lambda → S3 · DynamoDB audit
```

- **Sign-in:** real Cognito tokens, unlocked by one passcode (SHA-256 in Secrets Manager; brute-force brake;
  audited). Role always comes from the token checked against the directory.
- **Secrets:** the OpenAI key and the demo secret are read at runtime by the task role; nothing secret is in an
  image, the repo or a log.
- **Proof:** Susan's two-user test through the browser: alice → approve $2,700; carol → refused at the door, no
  claim data ([`evidence/frontend-deployed.txt`](evidence/frontend-deployed.txt), audit rows included).
- Deploy: `python M4/cloud/frontend.py apply` (commit first; images are tagged with the commit) · `status` ·
  `rotate-passcode` then `apply` · `destroy` after grading (≈ $35–40/month while up).

## 5 · Incident drill and RCA (D-050)

A deliberate bad release on the **deployed** door (its document bucket switched to a wrong one), detected, rolled
back and verified by `python M4/drill/incident_drill.py run --label <name>`. That one command does all of it:
canary, fault, impact probe, detection, rollback, verification, and writes the timeline.

| | Drill 1 (as built) | Drill 2 (after the fixes) |
|---|---|---|
| Alarm | **silent** (the door couldn't start, so it printed no metrics) | **ALARM at +2 min 22 s** (edge 5xx) |
| Adjuster saw | "refused" | "unavailable: nothing decided, try again" |
| Time to verified recovery | 481 s | **279 s** |

- **RCA (one page):** [`drill/RCA-2026-11-23.md`](drill/RCA-2026-11-23.md).
- **New eval case IC-001:** [`../M2/tests/test_incident_door_down.py`](../M2/tests/test_incident_door_down.py),
  which fails on the pre-drill code.
- **Prevention:** every door deploy now runs [`ops/door_smoke.py`](ops/door_smoke.py) and rolls itself back on
  failure.
- **Dashboard:** in the error-rate panel the incidents show only on the edge line
  ([`evidence/incident-drill-2-dashboard.png`](evidence/incident-drill-2-dashboard.png)).
