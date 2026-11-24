# ClaimSense AI: observation document (Submission 2)

**Engagement:** AutoSure Insurance, motor claims first-pass co-pilot · five weeks, M0 → M4 · synthetic data only ·
**Final tag:** `v1.0-final` · **Deployed console:** https://d2jfndltae6j40.cloudfront.net (graders' two logins
are in the submission form) · **Author:** Susan Wellington.

This document covers what was deployed, how it was evaluated, how it is observed, how it holds up under failure, how
it is handed over, and what we observed doing it. Every number links to evidence a grader can re-run; where
something is not yet proven, it says so.

---

## 1 · Deployment
**What runs, and where (AWS, us-east-1, one account, everything tagged `Project=ClaimSense`):**

| Component | Runs on | Notes |
|---|---|---|
| Adjuster console (Streamlit) + orchestrator (four agents, OpenAI Agents SDK) | **ECS Fargate**, one task, two containers | Console :8501 is the only thing exposed; the orchestrator is localhost-only inside the task |
| HTTPS front door | **CloudFront** → **ALB** | The ALB admits only CloudFront's origin-facing prefix list; direct access is refused |
| The governed door (MCP 2025-06-18 + REST) | **API Gateway** (HTTP API) → **Lambda** (container image) | Auth before routing; grants deny by default; per-adjuster entitlement; an audit row for every call |
| Identity | **Cognito**: 5 synthetic users in 5 groups | Each person signs in with their **own** password; no user picker (D-056) |
| Data | **S3** (policies, documents, clause corpus) · **DynamoDB** (append-only audit) | The clause manifest ships in the image, so an edited clause in S3 is quarantined |
| Secrets | **Secrets Manager**: the OpenAI key only, read at runtime by the task role | No secret in an image, the repo or a log |
| Images | **ECR**, immutable tags = commit SHAs | Pushed **only** after CI's live gate and second grader pass |

- **Deploy commands:**
  - the door: `M3/cloud/deploy.sh`, which syncs S3, ships the image and runs a post-deploy smoke as a real
    adjuster and as the agents, then **rolls itself back if the smoke fails**;
  - the frontend: `M4/cloud/frontend.py apply`, which refuses an uncommitted tree.
- **Starts from a clean checkout:** CI does exactly that on every push, and a fresh clone passed every local check in
  the M0–M4 review (tests, data validation, the 150-case replay gate, the M3 proofs).
- **Running cost:** ≈ $35–40/month for the frontend, ≈ $0–2 for the rest at pilot volume, plus ≈ $0.025 of model
  calls per claim. `destroy` / `teardown.sh` take it to $0.

**Observed while deploying:**
- App Runner was the first choice, but it has no WebSockets, which Streamlit needs, so we switched to ECS + ALB +
  CloudFront (D-049).
- A fresh account lacked the ECS service-linked role; the script now creates it.
- A 1920-px recording window doesn't fit a laptop screen, which mattered for the demo, not the system.

## 2 · Evaluation
| Suite | What | Result | Evidence |
|---|---|---|---|
| **The gate** (150 cases) | clear 60 · edge 45 · adversarial 45 in six families: prompt injection 14, cross-record leakage 10, forced auto-decision 10, entitlement refusal 5, PII 3, citation forgery 3 | **150/150 live, model required**, every case decided by the model, **3 identical runs** (release gate: 450 runs, 0 disagreements) | `M4/evidence/release-gate-live.txt`, CI's `live-eval` on every merge |
| **Gate rule** | overall ≥ 90% (a floor nobody can lower) **and** zero adversarial failures **and** every case model-decided **and** every net payable and required citation right (D-057) **and** no crashes; the exit code is the deploy decision | encoded in `M2/evals/run_evals.py`; a failing gate blocks the ECR push | `.github/workflows/eval-gate.yml` |
| **Second grader** (Promptfoo) | the agreement runner over all 150 + a live rubric judge on 7 cards | **150/150** agreement · **7/7** rubric | `M4/evidence/second-grader.txt` |
| **Judge calibration** | the rubric judge vs 40 cards with known answers, judged twice | **κ 0.95**, 39/40, 40/40 consistent | `M4/evidence/judge-calibration.txt` |
| **Held-out** (20 claims never tuned against) | labels approved by the client and **committed before** a single live run | **19/20**: clear 8/8, edge 7/7, adversarial 4/5 | `M4/evidence/holdout-live.txt` |
| **Per-agent evals** | each agent against its own labels before code corrects it | 100% (Intake 145/145, others 132/132) | `M2/evals/agent_evals.py` |
| **Continuous eval** | a daily live sample (at least one adversarial), published to the dashboard | 10/10 on each run so far | `M4/ops/continuous_eval.py` |

**Against the M0 success criteria:**
- SC-1 accuracy: 100% (baseline rule table 25%);
- SC-2 p95: 13 s (target 90 s; baseline 3.2 h median);
- SC-3 confirmable as written: 84/84 (proxy; real confirmation is measured in the pilot);
- SC-4 fraud recall: 12/12 with 0/133 false routes;
- SC-5 adversarial: 45/45.

**Observed:**
- **The 150 were tuned to 100%, so they can't show generalisation.** The held-out set does: 19/20. The one miss
  was a real privacy defect (international PII formats reached the model unmasked), fixed with tests that fail on
  the old code.
- **A second grader earned its place.** Calibrating the judge took four rounds, because vague rubrics ("other than
  X") produced confident wrong verdicts. Field-named rubrics fixed that.
- **Moving Intake to the smart model** (m2-v13) was what stopped run-to-run inconsistency on contradiction
  spotting. Prompt edits alone kept trading one failure for another.

## 3 · Observability
- **One CloudWatch dashboard, `ClaimSense-Operations`:**
  - call volume;
  - error rate (5xx ÷ requests), with **both** the app's own count and the edge's (API Gateway);
  - door and claim latency p50/p95;
  - live eval pass rate;
  - cost per claim;
  - refusals, fallbacks and guardrail holds.
- **Metrics without an agent:** EMF lines from Lambda; `PutMetricData` from ECS.
- **SLOs, each from an M0 success criterion, drawn on the dashboard:**
  - eval pass ≥ 90% with zero adversarial failures (SC-1, SC-5, which is also the deploy gate);
  - claim p95 < 90 s (SC-2);
  - door errors < 5% (the alarm).
- **One alarm,** `ClaimSense-door-error-rate`: the worse of the app's and the edge's error rate, over 5% in 2 of 3
  minutes, goes to SNS email. Both ALARM and OK emails reached the owner during drill 2.
- **Audit and traces:**
  - every call, granted or refused, is a row in DynamoDB and an `AUDIT` line in CloudWatch Logs;
  - every claim run is a trace that can be rebuilt span by span (`M2/evidence/trace.txt`).

**Observed:** the first alarm was **blind** to the failure that mattered most. A door that can't start prints no
metrics of its own, and "missing data" counted as "not breaching". Only a drill found that (see §4). Watching
the edge as well fixed it.

## 4 · Platform reliability
| Event | Detected by | Time to verified recovery | What it changed |
|---|---|---|---|
| **Drill 1:** a bad config release (wrong document bucket) | the canary in 31 s; **the alarm never fired** | **481 s** | the alarm watches the edge too; door outages say "unavailable", not "refused"; post-deploy smoke + auto-rollback |
| **Drill 2:** the same fault, fixes in place | **the alarm at +2 min 22 s** (email delivered) | **279 s** | — |
| **Real incident:** first deployed claim runs ended with no card (the gateway rejected the agents' delegated token on `/mcp`) | the client, in the browser | **31 min 38 s** | `/mcp` verified by the door; the smoke and the deployed route check now **use** the agents' token |

- **Fail-closed held every time:** no decision, no data from the wrong place, no model spend.
- **Each incident added a test that fails on the old code:** IC-001; `[RCA-2]`; HO-20's PII test.
- **One-page RCAs:** `M4/drill/RCA-2026-11-23.md`, `RCA-2026-11-23-2-mcp-gateway.md`.
- **Rollback is one command, with no rebuild:** `M4/ops/rollback.py`. The door takes ≈ 15 s and the frontend
  ≈ 2.5 min, each tested both ways on AWS.
- **Restart survival:** the orchestrator, killed mid-claim, resumes from checkpoints without re-billing (CI tests
  it on every push).
- **The packaged drill** (`M4/drill/incident_drill.py`) lets AutoSure's team re-run it themselves.
- **A managed guardrail (G9, OpenAI moderation)** sits in front of the agents and can only hold a claim. On the live
  gate it held 0 of 150 legitimate claims while recording 16 crash descriptions as "violence"; a live threat was
  held (D-059).

**Observed:** both production-path failures were **integration gaps between things that were each tested alone**: a
config change outside the release path, and a token valid at the door but not at the gateway. The fix was the same
both times: test the path a real user and a real agent take, after every deploy.

## 5 · Handover
`M4/handover/` is written for someone who never met us:
- a **start-here page** with a one-hour first day;
- an **artefact index** (M0–M4);
- the **eval suite as contract**: both graders, commands, cadence, who may change labels;
- an **escalation map**: where each card goes, SEV-1..4 with owners from the M0 RACI;
- **ten monthly signals**, each with its trigger and action;
- an **RCA template and incident archive**.

The **runbook** (`M4/RUNBOOK.md`) has six procedures, and **each was executed on the real system before it was
written down**:
- add or remove a user;
- roll back a deployment;
- escalate a flagged claim manually;
- update the policy corpus;
- the door alarm;
- eval pass below SLO.

Testing them **found two bugs**: queued escalations were never delivered, and the console would crash on an
"unavailable" card. Both are fixed and covered by tests. There is also a 6-slide **steering-committee deck**, value
first, with speaker notes and a backup plan, and a **9 min 54 s recording** of the deployed system.

## 6 · Observations
1. **Our own gate had a blind spot, and only breaking it on purpose showed it.** A deliberate deductible bug
   (multi-release drill) went red only because unit tests caught it. The 150-case gate and the second grader scored
   decisions, not money or citations, and would have passed a wrong payout. Both now score the net payable and the
   required citations (D-057); the same bug now blocks the gate (85/150).
2. **Evidence beats assurance, but only evidence of the right thing.** We had 150/150, a second grader and green CI,
   and still shipped two failures that no test exercised: the alarm's blind spot and the gateway gap. Each was
   caught by doing the real thing (a drill, a person using the deployed system), and each became a permanent check.
3. **Held-out data is the honest number.** Tuning to 100% on the suite is easy to misread. Pre-registering 20 unseen
   claims cost $0.50 and gave the figure a steering committee should trust, plus a real defect.
4. **The client found the most important security issue.** The demo-mode user picker let one shared passcode
   unlock every identity. The door still enforced each identity's rights, but nobody could say *who* acted. Replacing
   it with each person's own password took an afternoon, and it is exactly the kind of issue an FDE should invite
   the client to find.
5. **Determinism where it counts.** Access, dates and money in code were never the problem. Every surprise was in
   integration or operations. That is where the next engagement's time should go: a smoke test that exercises the
   full user path, from day one.
6. **What is still open:**
   - **SC-3 (adjuster confirmation) and completeness** can only be measured with real adjusters. That is the
     proposed 30-day pilot, after Security signs off.
   - **SIU ticketing on AWS** is a local mock; the runbook has the manual fallback.
   - **One Fargate task** is fine for a pilot. Production needs a second task and autoscaling.
7. **Cost discipline held:** ≈ $70 of model spend for the whole engagement (every live run, both graders, drills,
   held-out, the demo), with the replay brain making most CI runs $0.

**Versions:**
- `v1.0-rc1`: release candidate, gate-green.
- A deliberately introduced regression was **caught red** by the gate in between (`M4/evidence/multi-release.txt`).
- `v1.0-final`: this submission, gate-green, with CI on the tagged commit.
