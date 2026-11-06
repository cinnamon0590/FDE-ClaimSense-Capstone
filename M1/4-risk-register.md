# M1 Deliverable 4: Risk register

**Engagement:** ClaimSense AI · AutoSure Insurance (motor) · **FDE:** Susan Wellington · **Date:** 2026-11-05

The brief asks for 5 risks and the class notes ask for at least 6. This register has **8**, ranked by
score (likelihood × impact, each 1–5). Data-access delay is on top, as the class guidance requires.
Every mitigation names an owner, an early-warning signal and the proof: an eval case or a control
we can demonstrate. The register is reviewed weekly in the Claims Director readout.

| # | Risk | L | I | Score | Mitigation | Owner | Early warning | Proof |
|---|---|:-:|:-:|:-:|---|---|---|---|
| **R1** | **Security/Compliance review or cloud permissions delay the capstone Week 4 (M3) integration** (data access is the long pole) | 4 | 5 | **20** | Consult Security on the auth model in M1 (questionnaire answered now); synthetic data only, so nothing waits on production access; buffer this line at 1.8× in the estimate; Security is Accountable for the auth model in the RACI | FDE + Security | No auth-model review booked by end of W14; IAM requests open > 3 days | Security questionnaire, contract tests (17), cloud evidence |
| **R2** | **Ungrounded or poisoned citations**: the model cites a clause it didn't retrieve, or a tampered chunk steers coverage | 3 | 5 | **15** | Citation check in code (cited IDs ⊆ retrieved IDs); provenance manifest quarantines unknown chunks; clause IDs are stable keys | FDE | Any `uncited_claim_blocked` spike; quarantine count > 0 in production | CS-016, CS-020 at 100% (gate); `validate_data.py` provenance check |
| **R3** | **Model verdicts silently replaced by the rule-engine fallback** (an outage or timeout makes the "AI" a rule table again) | 3 | 4 | **12** | `verdict_source` on every card; fallback verdicts scored as misses in SC-1; alarm on fallback rate > 5% | FDE | Fallback share rising on the dashboard | `score.py` model-verdict counting; harness test `fallback_verdict_never_counts` |
| **R4** | **Adjusters don't trust the drafts**, so confirmation stays low and they route around the tool (the quiet veto) | 3 | 4 | **12** | Evidence-first card (computed vs judgment, citations); Senior Adjuster owns the golden labels; override reasons become eval cases; weekly hands-on sessions | Senior Adjuster + FDE | SC-3 proxy flat; override reasons cluster on one cause | SC-3 (≥ 80% confirmed unchanged) |
| **R5** | **Cross-record data leakage**: a response includes another claimant's data (PII exposure under synthetic or real data) | 2 | 5 | **10** | Entitlement in code before any agent; boundary returns only the claim in scope; anti-enumeration errors; PII masking in prompts and logs | FDE + Security | Any audit `deny` burst from one user; PII detector hits in traces | CS-017, CS-019; contract tests `missing_and_unentitled_look_identical` |
| **R6** | **Latency or cost overrun**: four model calls per claim breach p95 90 s or the token budget | 3 | 3 | **9** | Small model by default, large only on Coverage/Decision; per-claim token cap; budget alarm; mock brain in CI except the gate run | FDE + IT/Cloud | p95 > 60 s on the smoke set; daily spend > budget/30 | SC-2 measured on ≥ 150 runs; AWS Budgets alarm |
| **R7** | **Synthetic data doesn't reflect real claim files**, so the system passes the suite but fails on real files | 3 | 3 | **9** | Edge cases reviewed by the Senior Adjuster; suite grows to 60 edge cases by M4; Phase 2 shadow run on masked real files only after Security approval | Senior Adjuster | Adjusters say "real files don't look like this" | Edge-case pass rate on the 150-case suite |
| **R8** | **Scope creep from a nervous, regulated client** (auto-payment, customer letters, more systems) erodes the fixed floor | 2 | 3 | **6** | Explicit out-of-scope list in the SoW; change control (written request → estimate → price → approval before work); topology revisit trigger logged | FDE + Legal/Procurement | Requests that start "while you're in there…" | SoW §4 out of scope, §10 change control; DECISIONS log |

## Heat map

| Impact → / Likelihood ↓ | 3 | 4 | 5 |
|---|---|---|---|
| **4** | | | **R1** |
| **3** | R6, R7 | R3, R4 | R2 |
| **2** | R8 | | R5 |

## What would trigger re-planning

- **R1 fires:** M3 slips by more than one week. Use the change-control clause; the fixed floor
  isn't reduced, but the M3 payment milestone moves.
- **R2 or R5 fires in any test:** release blocked by the adversarial gate (SC-5); a root-cause
  analysis and a new eval case are written before the next build.
- **Fallback share above 5% or p95 above 90 s for 2 consecutive days:** roll back to the last green
  image (M4 runbook) and investigate.
