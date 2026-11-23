# M4 · Evaluation, observability, reliability and handover (W17 · Brief Milestone 5)

The last milestone: prove the system is safe to operate, observable when something goes wrong, recoverable after
a failure, and usable by someone other than its author. Requirements are the union of the Week 17 assignment, the
brief's Milestone 5 and Submission 2, the W17 deck and notebook, and the graded `milestone-M4-capstone.md`.

| # | Deliverable | Status | Evidence |
|---|---|---|---|
| 1 | **150-case suite incl. prompt injection, cross-record leakage, forced auto-decision; the gate passes with the model required** | ✅ | [`evidence/release-gate-live.txt`](evidence/release-gate-live.txt), [`gate-run-live.txt`](evidence/gate-run-live.txt), [`gate-run.txt`](evidence/gate-run.txt) |
| 2 | Second grader (Promptfoo) | next | |
| 3 | Dashboard (error rate, call volume, p95 latency) + one alarm | planned | |
| 4 | Incident drill + one-page RCA with time to verified recovery | planned | |
| 5 | Runbook: add a user, roll back, escalate a flagged claim manually, update the policy corpus | planned | |
| 6 | Client presentation with a live demonstration (+ the ≤10-minute recording) | planned | |
| 7 | Handover pack | planned | |
| F | Final submission: deployed frontend URL, observation document, final tag, CI on the submitted commit | planned | |

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
  (`score.gate_passes` + the named list in the report); CI runs the replay gate on every PR and the live gate on
  every merge to `main`, and pushes the image only when both pass.
- Prompt **m2-v13** (D-046 in [`DECISIONS.md`](DECISIONS.md)): what the larger suite exposed and how each slip was
  fixed without lowering a gate.

Run it: `python M2/evals/run_evals.py` (live gate) · `CLAIMSENSE_LLM_REQUIRED=false python M2/evals/run_evals.py
--brain replay` ($0) · `python M2/evals/run_evals.py --repeat 3` (release gate) · `python M2/evals/agent_evals.py`.
