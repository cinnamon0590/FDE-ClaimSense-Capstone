# M0: Discovery and Scoping (course Week 13)

> **Naming:** the ClaimSense brief calls this stage **"Milestone 1 — Discovery and scoping (Week 1)"**.
> This repo numbers milestones by course week: **M0 = W13** (capstone Week 1), M1 = W14, M2 = W15,
> M3 = W16, M4 = W17 (capstone Week 5). "Week 4" and "Week 5" in these documents mean capstone weeks.

Goal: establish what the client actually needs and what success will be measured against, before
any design or build, and leave an initial evaluation baseline.

## Deliverable checklist

| # | Brief requirement | File | Beyond the requirement |
|---|---|---|---|
| 1 | Engagement charter (1–2 pages) naming the three client systems and their integration points | [`1-engagement-charter.md`](1-engagement-charter.md) (2 pages, print-tested) | Names the throughput bottleneck with a measured baseline; code-vs-model boundary table; typed integration points per system; framing table (who / job / target / constraints / first slice) |
| 2 | Stakeholder map and RACI: approver, reviewer of co-pilot output, daily user, who can block rollout | [`2-stakeholders-raci.md`](2-stakeholders-raci.md) | One Accountable per row; veto types (hard / quiet / bandwidth) incl. the off-org-chart veto; engagement cadence; post-handover owner |
| 3 | Four quantified criteria: decision accuracy, pipeline latency, adjuster confirmation rate, fraud routing accuracy | [`3-success-criteria.md`](3-success-criteria.md) | Measured rule-table baseline per criterion; pass counts at 20 and 150 cases; criterion → case traceability; label-dispute rules; adversarial gate rule (SC-5) |
| 4 | DECISIONS.md with ≥ 3 dated architectural decisions and the reason for each | [`DECISIONS.md`](DECISIONS.md) (7 entries, dated 2026-11-04) | Every entry has rejected alternatives and a revisit trigger |
| 5 | 20 evaluation cases spanning all four decision outcomes, including adversarial cases | [`evals/cases.json`](evals/cases.json) · [`evals/README.md`](evals/README.md) | Validator recomputes dates and money in code; scoring harness with 9 self-tests; **initial baseline measured** ([`evals/baseline-results.txt`](evals/baseline-results.txt)); CI workflow |

Supporting:
- [`discovery-notes.md`](discovery-notes.md): the class template filled in, with a process map
  (system vs shadow steps) and open questions for the client.
- [`charter-confirmation-email.md`](charter-confirmation-email.md): the 24-hour written confirmation request.
- [`../.github/workflows/eval-gate.yml`](../.github/workflows/eval-gate.yml): change control from day one.

## Headline numbers

| | Legacy rule table (measured today) | Co-pilot target |
|---|---|---|
| Decision accuracy (overall) | **25%** (5/20) | ≥ 85% |
| Fraud recall | **0%** (0/2) | ≥ 90% |
| Confirmable as written (SC-3 proxy) | **0%** (0/13) | ≥ 80% (human-confirmed) |
| Adversarial pass | **20%** (1/5) | 100% |
| First-decision time | ≈ 3.2 h (assumed) | p95 ≤ 90 s |

## Verify (stdlib Python 3.10+, no installs, $0)

```bash
cd M0/evals
python3 -I validate_cases.py       # suite valid: shape, coverage, computed facts → exit 0
python3 -I score.py --verbose      # baseline: legacy rule table per case → DEPLOY GATE: BLOCKED (expected)
python3 test_harness.py -v         # 9 self-tests: gate passes a perfect system, blocks bad ones
```

## Quality checks run on these drafts

- **W13 notebook scorers:** all 5 criteria `MEASURABLE`, criteria set `FLOOR_PASS`. RACI has exactly
  one Accountable plus a hidden veto. All 7 decisions pass `lint_decision`. The process map passes
  `score_process_map`.
- **Validator sabotage test:** a lapsed-policy approve, a wrong payout and a missed total-loss
  boundary are all rejected.
- **Harness self-tests (9/9):** a perfect system passes the gate. Injection-obeying, leaking,
  auto-deciding, fallback and wrong-reason responses all fail.

## Notes for the reviewer

- **All data is synthetic** and designed by the FDE. No fixtures were issued (DECISIONS D-006).
- Baselines marked **(A)** in the discovery notes are assumptions to validate with the client. The
  rule-table figures are **measured** on the seed suite.
- **AutoSure Insurance** is the fictional client from the instructor's worked example
  ("ClaimSense at AutoSure Insurance"). ClaimSense AI is the product being built, not the client.
