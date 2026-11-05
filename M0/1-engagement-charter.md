# ENGAGEMENT CHARTER: ClaimSense AI

**Client:** AutoSure Insurance, motor claims *(the course's fictional client; synthetic data)* · **FDE:** Susan Wellington · **Date:** 2026-11-04
**Status:** DRAFT, to be sent to the Claims Director for written confirmation within 24 h of discovery. Any
requested change is a scope change and is logged in `DECISIONS.md`.

## Problem statement

Every motor claim's first pass is done by one adjuster acting as the integration layer between three
systems that don't talk to each other. A first decision takes about 3.2 hours*, two adjusters disagree
on about 18%* of the same files, and no one can audit why. Fraud referral fires on a score threshold
rather than a reading of the file, and claims on lapsed policies get approved because a status field
is stale.

**The bottleneck that governs throughput is file assembly, not deciding.** About 45 of an adjuster's
55 active minutes* go on opening each system, re-keying IDs and cross-checking dates and documents.
Unrecorded reasoning then causes rework at senior review. A faster rule table can't fix this. We ran
the client's current rule table against our 20-case seed suite: it scores **25%**, catches
**0 of 2** fraud files, and **approves a claim on a lapsed policy** (`evals/baseline-results.txt`). Coverage
turns on clause wording, and fraud turns on whether the narrative holds together.
*\*Discovery estimate, to be confirmed by the client (`discovery-notes.md`). Rule-table figures are measured.*

| Who | Job | Target | Constraints | First slice |
|---|---|---|---|---|
| Claims adjusters (daily user) and the Senior Adjuster (reviewer) | Get a defensible first decision on a claim without hand-assembling the file | Minutes, not hours, with the reasoning written down and a licensed adjuster accountable | Synthetic data only · identity, access, dates and money in code · every judgment cited | All four agents end-to-end on the seed suite against mocked systems: read-only, draft recommendations only (M2) |

**What we are building:** a claims-adjudication **co-pilot**. Given a claim, it returns a first
decision (approve / flag_review / route / deny), the reasoning, and citations to the evidence. It
refuses users who aren't entitled to the claim. **A licensed adjuster confirms every outcome.**

## Success criteria
*(Definitions, baselines, tests and pass counts: `3-success-criteria.md`. Each maps to eval cases.)*

1. **Decision accuracy:** ≥ 90% clear / ≥ 75% edge / ≥ 85% overall correct decision codes, model
   verdicts only, measured on the eval suite (20 → 150). Rule table today: 38% / 14% / 25%.
2. **Pipeline latency:** p95 ≤ 90 s and p50 ≤ 45 s from FNOL to decision card, measured on ≥ 150
   deployed runs (today ≈ 3.2 h).
3. **Adjuster confirmation rate:** ≥ 80% of recommendations confirmed unchanged, measured on ≥ 50
   claims in the capstone Week 5 review. 100% of outcomes carry a confirmation, with zero auto-decisions.
4. **Fraud routing accuracy:** ≥ 90% recall to the fraud investigator with ≤ 10% false-route rate,
   measured on the suite's fraud and non-fraud subsets (rule table today: 0% recall).
5. **Gate rule:** 100% of adversarial cases pass, with zero obeyed injections, leaks or
   auto-decisions, measured on the adversarial family. One failure blocks deploy.

## Systems in scope and integration points

Agents reach all three systems **only** through one authenticated data boundary (MCP-style). It checks
entitlement in code before any agent runs, returns only the claim in scope, and audits every call.

| System | Purpose | Integration points (typed tools at the boundary) | Owner |
|---|---|---|---|
| **Claims management** | FNOL, claim record, claimant history, assignment | `get_claim` · `get_claim_history` (read) · `post_recommendation(claim_id, card, idempotency_key)`: write, draft pending confirmation, never a final status | Claims Operations |
| **Policy administration** | Term, coverages, deductible, limits, use class, renewal state, policy wording | `get_policy` (read; feeds the date and money checks) · `search_clauses(query)` (read; wording indexed as a cited `CLS-…` corpus) | Underwriting / Policy Admin |
| **Document store** | Police reports, estimates, invoices, photos and metadata, medical notes, statements | `list_documents` · `get_document` (read). Text is untrusted and scanned for injection before it reaches model context | Claims Ops / Records |

**Flow:** Console → (claim + user token) → **boundary authorises** (or refuses and audits) →
orchestrator → agents ↔ boundary tools ↔ 3 systems → decision card → **adjuster confirms** →
`post_recommendation` to claims management.

## Who decides what: code vs model

| Deterministic code (exact, testable) | Model judgment (always cited) | Licensed adjuster |
|---|---|---|
| Identity and entitlement · loss date inside policy term · net payable = gross − deductible, limits · repair ÷ ACV (total loss) · > $25K authority check · audit rows | Does the clause wording cover this loss? · Is the narrative consistent across documents (fraud)? · Injury exposure · Which evidence supports the draft · The written reasoning | Confirms or overrides every outcome. Owns flag_review and > $25K cases |

Each decision card labels its fields `computed` or `judgment` and carries `verdict_source`
(`model` / `deterministic_fallback`).

## Four agent roles

- **Document Intake:** assembles the file from all three systems, extracts dates, amounts, parties
  and injuries, and flags missing documents.
- **Coverage Check:** decides whether the policy responds to this loss, citing only retrieved
  clauses. Code supplies the date check and net payable.
- **Claim Assessment:** reads the whole file for fraud inconsistencies, injury and total loss, and
  uses code for the ACV and $25K checks.
- **Decision Draft:** produces the structured decision card for the adjuster to confirm, with code,
  reasoning, citations and next step.

**Out of scope:** auto-payment or any final status · real or personally identifiable data · customer
correspondence · total-loss valuation and injury reserving (routed to specialists).

## Top risks

1. **Security review delays capstone Week 4 integration**: **High**. Mitigation: consult Security on the auth model in M1; synthetic data only; audit designed up front.
2. **Model verdicts silently replaced by rule-engine fallback**: **Medium**. Mitigation:
   `verdict_source` on every card, and SC-1 scores fallback as a miss.
3. **Ungrounded or poisoned citations**: **Medium**. Mitigation: cite only retrieved IDs, quarantine
   unprovenanced chunks, CS-016/CS-020 gated at 100%.
4. **Low adjuster trust and confirmation**: **Medium**. Mitigation: evidence-first card; overrides become eval cases.
5. **Synthetic data unlike real files**: **Medium**. Mitigation: edge cases reviewed by the Senior Adjuster;
   60 edge cases by M4.

## Decisions made
**D-002** deterministic spine (identity, access, dates, money in code; judgment in the model, cited) · **D-003** coverage via cited retrieval over a clause corpus; uncited or unprovenanced content blocked · **D-004** access control in code at one audited data boundary, before any agent runs. *(Full entries with alternatives: `DECISIONS.md`.)*

**Sign-off:** Claims Director ____________ (date ______) · FDE: Susan Wellington
