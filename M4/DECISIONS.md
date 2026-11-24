# DECISIONS.md: ClaimSense AI engagement (M4 entries)

Continues the engagement decision log. D-001 to D-007 are in [`../M0/DECISIONS.md`](../M0/DECISIONS.md), D-008 to
D-016 in [`../M1/DECISIONS.md`](../M1/DECISIONS.md), D-017 to D-035 and D-045 in [`../M2/DECISIONS.md`](../M2/DECISIONS.md),
D-036 to D-044 in [`../M3/DECISIONS.md`](../M3/DECISIONS.md). Newest first.

---

## D-058 · 2026-11-24 · Final M4 review: four gaps closed to exceed the checklist
- **Why:** before the final tag, every M4 source was re-read: the W17 assignment, the brief (Milestone 5,
  Submission 2, acceptance criteria, rubric A–E), the graded M4 checklist (all tiers), the W17 deck and the
  handover-artifacts slide. Four gaps were closed.
- **Decision:**
  1. **The gate bar in CI is 95%** (the checklist's `--min-pass 0.95`) for both the replay and live gates. The
     runner's floor stays 90%, and we score 100%.
  2. **`ADV-*` names:** `M4/evals/adversarial-index.md/.json` maps the 45 adversarial cases to ADV-01..45, each
     traced to the incident it guards against, including the two W16 class incidents (an injected document; an
     uncited money claim). `M2/tests/test_adversarial_index.py` keeps the index equal to the gate's cases.
  3. **Fresh gate evidence:** `gate-run.txt` (replay at the 95% bar) and `gate-run-live.txt` (the live gate on
     `main` @ 24d8f5a, run 45284368168) both include D-057's money-and-evidence line, 150/150.
  4. **The handover pack holds the steering deck** (`steering-deck.pdf` + speaker notes and backup plan) and
     links the recording, the observation document, the `ADV-*` index and the release history.
- **Left for the owner to decide** (each changes settings or adds scope):
  - making the eval gate a **required** status check (branch protection on `main`);
  - the optional Architect item "managed guardrails".
- **Owner:** Susan Wellington.

---

## D-057 · 2026-11-23 · Multi-release evidence, and the gate now scores the money and the citations
- **Why:** the W17 Architect tier asks for two tagged releases, both gate-green, with the eval suite catching a
  deliberately introduced regression in between.
- **What happened:**
  - `v1.0-rc1` was tagged on b0391d1, with every CI job green, including the live 150 and the second grader.
  - PR #33 (DO NOT MERGE) introduced a realistic money bug: the net payable no longer subtracted the deductible.
  - CI went **red** and the image push was **blocked**, but **only because unit tests caught it**: 5 money tests in
    `pipeline-tests` and `m3-door`.
  - The 150-case gate and the Promptfoo agreement runner would have **passed** it. Both use
    `score.fail_reason`, which compared the decision, route, forbidden content and guardrails, but never the net
    payable or the required citations, although the labels carry both.
- **Decision:**
  - `score.evidence_fail(case, resp)`: the code-computed net payable must equal the label, and every required
    citation must be present (when the decision is right).
  - The gate (`run_evals.py`), the second grader (`golden_provider.py`) and the continuous eval all require it.
    Each run prints a "money and evidence: N/150 right" line.
  - SC-1 keeps its M0 definition (decision codes), so the rule-table baseline (25%) stays comparable.
- **Proof:**
  - the real system: 150/150 with money and evidence 150/150;
  - the same deductible bug, re-run locally: money and evidence 85/150 right, **DEPLOY GATE: BLOCKED**, exit 1;
  - `M0/evals/test_harness.py` pins both checks;
  - `M4/evidence/multi-release.txt` has the red CI runs.
- **Owner:** Susan Wellington.

---

## D-056 · 2026-11-23 · Each person signs in as themself: no user picker, no shared passcode (replaces D-049's demo mode)
- **Why:** the owner spotted it. D-049's demo mode let anyone holding one shared passcode **pick any synthetic user**
  from a dropdown. Each pick did get that user's own Cognito token, and the door enforced that user's rights. But one
  secret unlocked every identity, so the system couldn't say *who* was acting, and the audit trail recorded the
  chosen identity, not the human. That is impersonation, and it would weaken the trust-boundary area (D) under
  grading.
- **Decision:**
  - **The console** has a Username + Password form (cleared on submit) and, once signed in, "Signed in as <user>"
    with a Sign out button. There is **no user dropdown** on AWS (the local stack keeps its dev-issuer picker, which
    exists only on localhost). Switching users means signing out and signing in with the other person's password.
  - **The orchestrator's `POST /signin`:** checks the user is in the directory (an unknown user never reaches
    Cognito), then calls Cognito `AdminInitiateAuth` with the password supplied, then returns that user's token with
    the directory's groups.
    - One message for every refusal, and an audit row for allow and deny. The password is never logged.
    - 5 refused tries a minute per username, or 20 overall, gives a 429.
    - Off (404) unless the pool and client are configured.
  - **Retired:** the `claimsense/demo-signin` secret (7-day recovery window) and the task role's access to it.
    - The task role now reads only the OpenAI key.
    - `M4/ops/set_password.py` gives a person a strong, typeable password (≈ 95 bits), set in Cognito, kept only in
      `~/.claimsense` (0600), never printed. Graders get two users' logins (alice, carol) in the submission form.
- **Proof:** `M4/evidence/signin-per-user.txt`:
  - real Cognito: alice's own password → alice; alice's password for carol → refused; carol's own → carol;
  - the owner's browser test on AWS, with its audit rows;
  - `M2/tests/test_signin.py` (11). The M3 route check now covers `/signin`.
- The demo video was re-recorded with the new sign-in: alice and carol each type their own password, and the
  carol scene shows a sign-out, then her sign-in (9 min 54 s).
- **Owner:** Susan Wellington.

---

## D-055 · 2026-11-23 · The client presentation: a 6-slide steering deck and a 9-minute recording of the deployed system
- **Why:** brief Milestone 5 #5 ("client presentation with a live demonstration") and Submission 2's "demonstration
  recording of no more than ten minutes". The W17 floor: steering deck ≤ 6 slides, business value first, no
  architecture in the first three slides.
- **Decision:**
  - **The deck** (Slides artifact, private to the owner until shared; source in `M4/presentation/deck/`) has six
    slides: cover, the outcome in four numbers, the SoW scorecard (6 of 8 met, 2 to be measured in the pilot, said
    plainly), the safety record, how it works (the first architecture, on slide 5), and the ask (a 30-day
    controlled pilot after Security signs off).
    - Every figure is from the evidence.
    - Every slide has **speaker notes**, and the last carries the **backup plan** (the client asked for both, even
      though no live session is expected).
  - **The recording** (`M4/presentation/make_demo.py`):
    - real screen capture of the **deployed** console: 9 scenes covering approve, typed agent outputs, Ask
      ClaimSense, confirm, total loss, fraud, injection held, and an unentitled user refused;
    - checked against every requirement source before review; three gaps were then added: the adversarial
      families by name (prompt injection, cross-record leakage, forced auto-decision), the SLOs with their M0
      origin, and the one-page RCA itself;
    - stills of the deck and **real output**: the DynamoDB audit rows of the calls just recorded, CI's log on
      `main`, the live dashboard, the rollback listing with the drill timeline, the held-out run, the handover pack;
    - OpenAI TTS narration (`narration.json`), soft English captions plus an `.srt`.
    - **9 min 54 s**, under the 10-minute limit; the owner asked for close to 10 minutes.
  - **No credential handled by the tooling:** the owner typed the demo passcode in the browser window, and the
    footage before sign-in is cut.
- **What the takes found:**
  - a 1920-px window doesn't fit a laptop screen and breaks the layout, so recording is at 1280×720, upscaled at
    assembly;
  - a chat panel that is already open must not be clicked shut;
  - Streamlit's combobox can drop a selection, so every selection is verified and retried;
  - scenes fail soft, and a single scene can be re-taken and spliced (`record fraud`).
- **Delivered:**
  - `M4/presentation/out/ClaimSense-demo.mp4` (27 MB, 1080p) is kept out of git and uploaded by the owner for the
    submission;
  - the script and storyline (`demo-script.md`, with the final cut's timestamps) are in git.
- **Cost:** ≈ $0.40 (narration and the recorded live runs). **Owner:** Susan Wellington.

---

## D-054 · 2026-11-23 · The handover pack
- **Why:** brief Milestone 5 #6 ("handover pack consolidating all engagement artefacts") and the M4 floor:
  eval-suite-as-contract, an escalation map, "what to watch monthly" (≥ 4 signals), an RCA template and incident
  archive. The test is the CIO's: "my team runs this after your people roll off".
- **Decision:** `M4/handover/` holds six documents:
  - **README:** start here, with a one-hour first day, access and secrets (where, never what), running costs and
    known limits;
  - **artefact index:** M0–M4;
  - **eval contract:** what passing means, both graders' commands and costs, the cadence (PR, merge, daily,
    monthly, per change, quarterly held-out refresh), and who may change labels;
  - **escalation map:** where each card goes, and SEV-1..4 with owners from the M0 RACI and targets;
  - **10 monthly signals:** each with where to read it, the healthy value, the trigger and the action;
  - **RCA template and incident archive:** two RCAs plus the held-out defect.
  - Every command and path in the pack was checked against the repo.
- **Owner:** Susan Wellington.

---

## D-053 · 2026-11-23 · Review follow-ups: a second RCA, the risk register looked back on, the M2 evidence gaps
- **Why:** the full M0–M4 review found these gaps:
  - the M4 Builder tier's "second RCA";
  - the rubric's "risk register anticipates failures that later occurred";
  - two M2 floor artefacts that were never committed (a trace file, a local AgentCore capture).
- **Decision:**
  - **RCA-2** (`M4/drill/RCA-2026-11-23-2-mcp-gateway.md`): the **real** Step 4 incident. The gateway's Cognito
    authorizer rejected the agents' delegated token on `/mcp`, so the first deployed runs ended with no card.
    - Detected by the client; time to verified recovery 31 min 38 s.
    - New eval case: `deployed_route_check.py` now **uses** the delegated token on `/mcp` (`[RCA-2]`, PASS).
    - Prevention: `door_smoke.py` runs the agents' path too, so `deploy.sh` rolls back a release that breaks it.
  - **Risk retrospective** (`M4/risk-retrospective.md`, linked from the M1 register):
    - R2, R5, R6 and R8 held;
    - R3 and R7 **happened** (the drill's outage label, HO-20's international PII) and were caught before any real
      file;
    - R1 was friction only;
    - R4 is open until real confirmation data exists;
    - four unanticipated failures are listed, and two new risks proposed (R9, R10).
  - **M2 evidence:**
    - `M2/evidence/agentcore-local.txt`: `/ping` and `/invocations` with a session id, live models through the
      deployed door; re-invoking the session resumes at $0 in 1.1 s; no token → 401;
    - `M2/evidence/trace.txt` (+ `trace-sample.jsonl`): that run reconstructed span by span, with every agent,
      tool and guardrail.
- **Owner:** Susan Wellington.

---

## D-052 · 2026-11-23 · A held-out set: 20 claims never tuned against, pre-registered, run once
- **Why:** the brief's area C asks for correct outcomes "on claims it was not tuned against". The 150 were all used
  while tuning the prompts to 100%, so they can't show that (found by the M0–M4 review).
- **Decision:** `M4/evals/build_cases_holdout.py` writes HO-01..HO-20 (8 clear, 7 edge, 5 adversarial: one per
  family), on scenarios that appear nowhere in the 150. They are labelled by the same `label()` rules (imported,
  not copied), and spot-checked and approved by the client.
  - The labels were **committed before the run** (b488ebf), run **once**, live, model required
    (`run_evals.py --suite holdout`), and reported as they came out.
  - The set is kept out of the 150-case gate, so it stays unseen.
- **Result: 19/20 (95%).**
  - Clear 8/8, edge 7/7: every decision was correct and model-produced.
  - Adversarial 4/5: injection, leakage, forced auto-decision and refusal passed.
  - Fraud recall 2/2, p95 17 s, $0.025 per claim.
  - **HO-20 failed:** the decision was right ($1,330), but `pii_masked` didn't fire. G3 only knew US formats, so a
    UK passport number and a UK mobile reached the model unmasked. This is the M1 risk register's R7 ("synthetic
    data doesn't reflect real claim files") happening.
- **Fix (next release, not back into this set):**
  - G3 masks international formats: passport, licence and ID numbers when named next to their keyword (a bare
    number is left alone), UK and international phones, NI numbers and IBANs;
  - new tests fail on the old masker: 2 in M1 and `M2/tests/test_holdout_ho20_pii.py`;
  - checks after the fix: pytest 220, replay 150/150, fuzz gate PASS (PII 270/270, 0/468 false positives);
  - HO-20 re-run live after the fix: PASS, masked, no raw value in the output
    (`M4/evidence/holdout-ho20-postfix.txt`, kept separate from the pre-registered result).
- **Cost:** $0.53. **Owner:** Susan Wellington.

---

## D-051 · 2026-11-23 · The runbook's four procedures, each executed before it was written
- **Why:** W17 / brief Milestone 5: a runbook covering adding a user, rolling back a deployment, escalating a
  flagged claim manually and updating the policy corpus (the M4 floor adds symptom → signal → decision → command).
- **Decision:** `M4/RUNBOOK.md` has the four procedures, plus the door error rate alarm and eval-pass-below-SLO
  procedures that the alarm and continuous eval already point to. Each procedure was run on the real system first,
  and each links its evidence. Tooling where a procedure had none:
  - **Users:** the directory became data (`M1/6-synthetic-data/source/users.json`). `deploy.sh` now also
    **off-boards** (global sign-out, disable, delete) Cognito users who left the directory. The console lists the
    directory's users instead of a hard-coded list.
  - **Rollback:** `M4/ops/rollback.py` re-points the door or the frontend to any gated image (immutable commit
    tags, no rebuild) and checks it.
  - **Escalation:** a human-only **🚩 Escalate to SIU (manual)** panel in the console, and `M4/ops/escalate.py`
    for on-call. Both make the same door call: grant + entitlement + idempotency key + audit, no claim data on
    the ticket.
  - **Corpus:** no new tool (the generator signs the manifest; `deploy.sh` syncs S3 and ships the manifest
    together). The two tests and the container wiring check that hard-coded "12 clauses" now derive the size, so a
    corpus change doesn't break them (the wiring check was caught by CI on this PR).
- **What the tests found (fixed):**
  - queued escalations were **never delivered**: nothing called the outbox flush, despite its docstring. Now the
    health check (in the background, never blocking), escalation reads and new escalations deliver it
    (`M3/tests/test_escalation_outbox_delivery.py`);
  - the console would have **crashed on an `unavailable` card** (D-050's new outcome had no reasoning to show).
- **Results:**
  - **users:** frank added → claim approved $2,700 → removed → old token refused at once;
  - **rollback:** door 15 s and frontend 2.5 min each way;
  - **escalation:** SIU tickets, an idempotent replay, and a queue delivered after a ticketing outage;
  - **corpus:** 2024.2 (CLS-RNT-013) passed the replay gate 150/150 and a live sample 10/10, and is served with
    manifest provenance and 0 quarantined on AWS.
- **Owner:** Susan Wellington.

---

## D-050 · 2026-11-23 · Incident drill on the deployed system: the alarm watches the edge, outages say "unavailable", deploys smoke-test themselves
- **Why:** brief Milestone 5 / W17: a deliberate regression → detection → rollback → a one-page RCA with time to
  verified recovery and the eval case it spawned. Builder tier: the drill is packaged for the client's team.
- **Decision:**
  - **The drill** (`M4/drill/incident_drill.py`): a bad config release on the deployed door (document bucket →
    `<bucket>-staging`), a canary (alice, real Cognito token, 4 door routes every 5 s), one real claim during the
    incident, detection by the alarm or the canary, roll back to the saved last-good config, verification by the M3
    deployed checks and a real claim. Timeline written by the script, not by hand.
  - **Drill 1 found two gaps**:
    - the alarm never fired, because a door that can't start prints no metrics of its own;
    - the adjuster was told "refused" during the outage.
  - **Fixes:**
    - the alarm is the worse of the app's (EMF) and the **edge's** (API Gateway `5xx` / `Count`) error rate, and
      the dashboard shows both;
    - a door 5xx is `upstream_unavailable`; after 2 quick retries the pipeline returns
      `decided_by: "unavailable"` (retryable, no agent run, $0), never `boundary_refusal`;
    - `deploy.sh` runs a post-deploy smoke as a real adjuster (`M4/ops/door_smoke.py`) and restores the previous
      image and configuration if it fails.
  - **Drill 2, same fault, fixes in place:** alarm `ALARM` at +2 min 22 s, adjuster saw `unavailable`, verified
    recovery in **279 s** (drill 1: 481 s).
  - **IC-001** (`M2/tests/test_incident_door_down.py`): the gateway's exact 500 over MCP and REST → `unavailable`,
    nothing decided, nothing spent. It fails on the pre-drill code and runs in CI on every push.
- **Proof:** `M4/drill/RCA-2026-11-23.md`, `M4/evidence/incident-drill-1.txt`, `incident-drill-2.txt`,
  `incident-drill-2-dashboard.png`, `M4/drill/runs/*.json`.
- **Cost:** ≈ $0.10 of model calls for both drills; edge metrics are free (API Gateway publishes them).
- **Owner:** Susan Wellington.

---

## D-049 · 2026-11-23 · The deployed frontend: ECS Fargate + ALB + CloudFront, demo sign-in, /mcp verified by the door
- **Why:** Submission 2 asks for a deployed frontend URL that stays reachable until grading ends, and acceptance
  criterion 5 is a person running a claim through it. Until now only the door was on AWS.
- **Decision:**
  - **Hosting:** one ECS Fargate task (1 vCPU, 2 GB) with two containers: the Streamlit console (:8501) and the
    orchestrator (:8003, reachable only on localhost inside the task). Behind an internet-facing ALB whose security
    group admits only the AWS-managed CloudFront origin-facing prefix list, and CloudFront for HTTPS on
    `*.cloudfront.net` (caching off, all headers forwarded, WebSockets). App Runner was rejected because it doesn't
    support WebSockets, which Streamlit needs. `M4/cloud/frontend.py apply | status | destroy | rotate-passcode`.
  - **Sign-in for graders (Susan's choice: demo picker + passcode):** the console asks for one passcode, then signs in
    as one of the five synthetic users through **real Cognito** (`ADMIN_USER_PASSWORD_AUTH`, called by the
    orchestrator's `/demo/signin`). The passcode exists only as a SHA-256 hash in Secrets Manager
    (`claimsense/demo-signin`, with the synthetic users' passwords) and in the owner's `~/.claimsense/demo.json`;
    10 wrong tries per minute → 429; every attempt is audited. Role still comes from the token checked against the
    directory, never from the picker. Off unless `CLAIMSENSE_DEMO_SECRET_ID` is set. Passcode alphabet avoids
    look-alike characters, and pasted quotes or spaces are forgiven (found in the first real sign-in).
  - **Least privilege:** the task role may read only the two secrets, call `AdminInitiateAuth` on the one pool,
    write and scan the audit table, and `PutMetricData` in the `ClaimSense` namespace. Images are tagged with the
    commit (a dirty tree is refused). Metrics go by `PutMetricData` from a background thread
    (`CLAIMSENSE_METRICS=cloudwatch`), since the awslogs driver doesn't extract EMF.
  - **`POST /mcp` on API Gateway is now verified by the door, not the Cognito authorizer.** Found on the first
    deployed run: the agents call `/mcp` with the door's *own* 5-minute delegated token, which a Cognito authorizer
    can't verify, so API Gateway answered `{"message":"Unauthorized"}` and the run ended with no card. The door
    already authenticates every request before routing (401 + audit row for none, forged or expired). Re-proved:
    no token → 401, forged → 401, delegated → 200; M3's route, Week 4 viewer and S3 checks all PASS on AWS. The
    orchestrator now turns a non-JSON-RPC gateway refusal into a structured error instead of crashing.
  - Console hardening from the same first run: **Run co-pilot** is disabled until signed in, the passcode survives a
    user or claim switch, and a refused run shows the reason instead of a stack trace.
- **Proof:** `M4/evidence/frontend-deployed.txt`: Susan ran the two-user test in her browser on 2026-11-23: alice →
  approve, $2,700, drafted by the agents through the door; carol → refused (`not_entitled`), no claim data. Every
  step is in the DynamoDB audit trail. The orchestrator panels of the dashboard now fill
  (`M4/evidence/dashboard.png`).
- **Cost:** ≈ $35–40/month while up (ALB ≈ $16, Fargate ≈ $20, CloudFront and Secrets Manager pennies). `destroy`
  removes all of it after grading.
- **Owner:** Susan Wellington.

---

## D-048 · 2026-11-22 · Observability: EMF metrics, one CloudWatch dashboard, one alarm, continuous eval
- **Why:** brief Milestone 5 #2 ("an operational dashboard reporting error rate, call volume and p95 latency, with one
  alarm defined") and the M4 floor (eval-pass, latency p50/p95 and cost per resolution, with the SLO stated and its
  M0 origin cited).
- **Decision:**
  - **Metrics without an agent:** both services print one CloudWatch Embedded Metric Format line per HTTP request
    (`Requests`, `ServerErrors`, `Refusals`, `LatencyMs`) and the pipeline one per claim (`ClaimRuns`,
    `ClaimLatencyMs`, `CostUSD`, `Fallbacks`, `GuardrailHolds`); namespace `ClaimSense`, dimension `Service`.
    Lambda (and App Runner) ship stdout to CloudWatch, which extracts the metrics: no SDK call, no extra IAM.
    Values are counts, milliseconds and dollars only.
  - **Dashboard `ClaimSense-Operations`** (`M4/ops/observability.py apply`): call volume, error rate (metric math
    5xx ÷ requests), door and claim latency p50/p95, eval pass rate, cost per claim, refusals, fallbacks and holds.
    SLO lines from M0: eval pass ≥ 90% with zero adversarial failures (SC-1, SC-5: the deploy gate), claim p95 <
    90 s (SC-2), door error rate < 5% (the alarm).
  - **One alarm `ClaimSense-door-error-rate`:** door 5xx rate > 5% in 2 of 3 one-minute periods (no traffic is not a
    breach), to SNS `claimsense-alerts` with an email subscriber (the address comes from the environment, never the
    repo). Chosen on the door because every data access crosses it: if it fails, nothing works.
  - **Continuous eval** (`M4/ops/continuous_eval.py`, Builder tier): a random sample of golden cases (always at least
    one adversarial) re-graded against the live system, `EvalPassRate` published, exit 1 below 90% or on any
    adversarial failure. First run: 10/10. Schedulable by cron or a GitHub Actions `schedule:` trigger.
  - **Evidence without a browser:** `M4/ops/dashboard_snapshot.py` renders the live dashboard with
    `GetMetricWidgetImage` into `M4/evidence/dashboard.png`.
  - CI: the image build now retries with backoff, because public.ecr.aws throttles anonymous pulls
    ("toomanyrequests") and had failed three builds.
- **Cost:** ≈ $0 (CloudWatch free tier: 3 dashboards, 10 alarms; custom metrics from EMF ≈ $0.30 per metric-month
  beyond the free 10).
- **Owner:** Susan Wellington.

---

## D-047 · 2026-11-22 · The second grader (Promptfoo), a calibrated judge, and the full live suite in CI
- **Why:** the W17 deck's deploy rule is two graders, cross-checked ("no single judge is gospel"), and the graded M4
  floor asks for `promptfoo.yaml` with ≥ 4 tests incl. adversarial ones, one run committed, and a judge-trust entry.
- **Decision:**
  - **Agreement runner** (`M4/evals/promptfoo/promptfoo-golden.yaml`, 150 tests): a Promptfoo Python provider runs
    each golden case through the real pipeline (replay brain, $0) and returns PASS/FAIL from the same scorer. Run
    once: **150/150, identical to the gate's per-case verdicts.**
  - **Rubric grader** (`promptfoo.yaml`, 7 tests): the LIVE pipeline drafts a decision card for a clean approval, a
    fraud referral and one case per adversarial family (prompt injection, cross-record leakage, forced
    auto-decision, poisoned corpus, entitlement). Each test has deterministic asserts (javascript on the card's
    fields, `not-contains` on leaked ids and "final"/"has been paid") plus an `llm-rubric` judge. **7/7.**
  - **Judge calibrated, not trusted by default** (`judge-calibration.txt`): 40 cards with known answers (20
    genuine, 20 corrupted five ways), graded twice. First pass κ 0.85 with 2 flips; the misses were rubric wording
    (a claim-number rule the judge read backwards; a field the rubric didn't name), so rubrics now name exact fields
    and values. **Final: κ 0.95, 39/40 agreement, 40/40 identical across repeats.** The one miss (a card saying
    "final and paid" passed) is why that rule is a deterministic assert, never left to the judge.
  - **Judge choice:** gpt-4o-2024-08-06 is the same family as the system (self-preference risk); mitigated by the
    calibration above and by keeping every safety-critical rule deterministic. A different-family judge would
    need a second provider key; recorded as an option, not done.
  - **Promptfoo 0.125.0, pinned** (Node ≥ 22.22). CI job `second-grader`: the agreement runner on every push ($0);
    the live rubric grader on `main` (~$0.25). `push-image` needs it: both graders green or nothing ships.
  - **Correction:** CI's live gate ran only the 20-case smoke set. It now runs **all 150 cases live** on every merge
    to `main` (~$3.70), so the submitted commit carries its own full, model-required run; and the 150-case file is
    now copied into the tested image.
- **Owner:** Susan Wellington.

---

## D-046 · 2026-11-22 · The 150-case suite: how it was built, labelled and gated
- **Why:** the brief's Milestone 5 asks for "an evaluation suite of 150 cases including adversarial families: prompt
  injection, cross-record leakage and forced auto-decision", with the gate passing with the model required. The
  suite had 40.
- **Decision:**
  - **Constructed, not collected** (the W17 notebook's method). 110 new cases (CS-041..CS-150) written in
    `M4/evals/build_cases_m4.py`, stratified by outcome × loss type × the boundaries that decide cases (first and
    last day of term, one day either side, repair/ACV at 0.98, 0.995, 1.0 and 1.01, net payable at $24,999,
    $25,000 and $25,001, fraud score 0.69 and 0.70, injury + total loss, fraud + injury, renewal pending, commercial
    use found only in a statement or police report). All synthetic; the fixture generator builds each claim,
    policy, document set, assignment and claims history from the case.
  - **Mix:** clear 60 · edge 45 · adversarial 45. Adversarial families: prompt injection 14 (documents, narrative,
    base64, corpus), cross-record leakage 10, forced auto-decision 10, entitlement refusal 5, PII 3, citation
    forgery 3. Every family has a `must_not` and, where a control must fire, a `guardrail` the case checks.
  - **Labels from the rules, signed off by the client.** `label()` derives each expected decision from the rule
    order the Decision agent applies; the Senior Adjuster (Susan) spot-checked 15 sampled cases, every new
    adversarial case and the 16 new coverage judgments, and signed off on 2026-11-22 (`label-review.md`;
    `agent-labels.json` sign-off now covers 25 coverage labels).
  - **One label was a bad case, not a bad model:** CS-108's statement could be read as the other driver's, which
    agrees with the narrative. It was rewritten as the policyholder's signed statement before sign-off.
  - **The gate:** overall ≥ 90% (never lower) **and** zero adversarial failures, every verdict model-produced. The
    report now breaks results down by category and adversarial family and names any adversarial failure: one
    failure vetoes the release whatever the average.
  - **Prompt m2-v11** fixed the two model misses the first live run exposed (148/150): the Decision agent now
    applies "cover unresolved → senior adjuster" before any specialist route (CS-083), and Intake compares every
    statement with the narrative fact by fact (CS-108).
  - **m2-v12 → m2-v13, after the per-agent evals.** With 150 cases the end-to-end result was 150/150, but scoring
    each agent before code corrects it (D-031, floors at 100%) exposed slips the larger suite reached for the first
    time: Intake missed photos dated before the loss (CS-026) and gave the wrong checklist for photo-only collision
    and hail claims (CS-084/085); Coverage didn't cite the policy-period clause on a renewal case (CS-102).
    - One label rule was wrong, not the agent: "has inconsistencies" was set on every fraud referral, including the
      five referred on the score alone, whose files contain no contradiction. Now set only when the referral isn't
      explained by the score.
    - Comparing lists and dates is code's job (D-001): the claim file carries `code_checks` (the document checklist
      for the loss type, and every document or photo dated before the incident). Intake uses them **in addition to**
      reading the documents. A first wording (v12) let Intake treat code's checks as the whole job and it stopped
      reading content (3 contradiction cases slipped); a forced "agrees/contradicts" field then over-flagged harmless
      demands and personal details as contradictions (6 false referrals). Both were caught in testing and reverted.
    - **The remaining slips were the fast model being inconsistent run to run** (the same claim right one run, wrong
      the next), which wording can't fix. **Intake now runs on the smart model** (gpt-4o, like Coverage and
      Decision): about +$0.005 per claim, judged worth it for an agent whose miss sends a fraud case to approval.
    - Coverage cites the policy-period clause whenever the period or a renewal is in question.
    - **Intake no longer sees the policy term.** It sometimes listed "loss before the policy start" as a document
      inconsistency. The policy period is Coverage's and code's question, so Intake's view of the policy now has
      the id, coverages, deductible, limits and use class only; Coverage and the Ask assistant still see the term.
    - Some cases were re-worded after sign-off, labels unchanged, because the wording (not the rule) was the problem:
      CS-108's statement is now explicitly the policyholder's; CS-133's caption asks to *see* another claim's photos
      rather than saying "these photos are from" it (which reads as evidence from a different claim, a fraud
      signal); and nine term-boundary narratives no longer announce their own trap ("the day before my policy
      began"), which no real claimant writes.
    - Every candidate was tested on the 79 riskiest claims (statements, police reports, notes, referrals, the
      adversarial families) before a full gate; the floors stayed at 100% and none was lowered.
- **Result (prompt m2-v13):** live release gate 150/150 in each of 3 runs, every case stable, adversarial 45/45,
  0 of 450 second opinions disagreed; every agent 100% on its own with 0 code overrides; fraud recall 12/12, false
  fraud routes 0/133; p95 12–13 s per claim.
- **Cost:** one live 150-case run ≈ $3.65 ($0.024 per claim with the smart Intake); the 3-run release gate ≈ $11;
  CI's live gate runs all 150 cases on each merge to `main` (it ran only the 20-case smoke set until D-047
  corrected it; this entry first said otherwise). Step 1 live spend, including the tuning rounds: $40.92 in
  full-suite runs (spend ledger) plus ≈ $7 of targeted probes; total OpenAI spend to date $58.61 (`SPEND.txt`).
- **Owner:** Susan Wellington.
