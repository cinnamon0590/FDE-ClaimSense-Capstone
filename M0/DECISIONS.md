# DECISIONS.md: ClaimSense AI engagement

Decision log (ADR-lite). Newest first. One entry per real decision. The **Why** and **Alternatives**
fields matter most: in capstone Week 5, when someone says "that's not what we agreed," this file is the
record. Client corrections to the charter are scope changes and get logged here.

---

## D-007 · 2026-11-04 · The eval suite is the contract: category thresholds, adversarial zero-tolerance, governed labels
- **Decision:** The deploy gate passes only when overall accuracy is ≥ 85% (targets: clear ≥ 90%,
  edge ≥ 75%) **and** every adversarial case passes **and** every verdict is model-produced. The gate
  is enforced in CI from M2. Golden labels are owned by the Senior Adjuster / Team Lead, frozen per
  suite version, and changed only through a logged second-adjuster review. A guardrail case scores
  as a pass only if the guardrail actually fired; a right answer for the wrong reason fails (see
  CS-020 in the baseline). The M0 baseline is the client's legacy rule table scored by
  `evals/score.py`: 25% overall, 0/2 fraud, 1/5 adversarial.
- **Why:** An average hides the one case that matters. A single live injection hole is
  qualitatively different from a missed edge case, so adversarial failures can't be offset by a
  high average. Category targets stop easy clear cases from masking weak edge handling. Label
  governance means the score settles disputes instead of starting them.
- **Alternatives considered:** (a) A single overall threshold. Rejected because 96% overall with one
  injection failure would ship. (b) 100% on everything. Rejected because it incentivises deleting
  hard cases until the suite is easy. (c) Labels owned by the FDE. Rejected because the vendor
  would be grading its own exam, and adoption depends on the reviewer agreeing with the labels.
  (d) LLM-as-judge for decision codes. Rejected for codes and money, which are exact matches in
  code; a judge may be used later only for reasoning quality, calibrated against adjuster labels.
- **Owner:** Susan Wellington (FDE) proposes. The Claims Director is Accountable for the threshold
  (RACI), and the Senior Adjuster is Accountable for the labels.
- **Revisit when:** The full 150-case suite lands (M4), or the client's adjusters dispute more than
  5% of labels in review.

## D-006 · 2026-11-04 · Design our own synthetic dataset and eval cases
- **Decision:** The FDE designs the synthetic claims, policies, documents and the 20 seed eval cases
  from the brief and the instructor's worked examples. Clause IDs use a `CLS-XXX-NNN` placeholder scheme.
- **Why:** No fixtures were issued. Course Drive, local files and the AWS account (S3 empty) were all checked on
  2026-11-04. Waiting would leave M0 without an eval baseline, and the brief makes synthetic data
  mandatory anyway.
- **Alternatives considered:** (a) Wait for supplied fixtures. Rejected because it blocks the eval
  baseline and the M1 data shapes. (b) Generate thousands of random claims. Rejected because volume
  without labelled edge cases tests nothing; 20 hand-labelled cases covering every outcome and
  adversarial family are worth more at this stage.
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** Official fixtures or a policy corpus are issued. Re-map case fields and clause IDs
  to them, and keep any case that tests something they don't.

## D-005 · 2026-11-04 · Four agents with explicit handoffs and model routing; provenance on every verdict
- **Decision:** Four agents under one orchestrator (OpenAI Agents SDK):
  1. **Document Intake** reads the file.
  2. **Coverage Check** is cited RAG over the clause corpus.
  3. **Claim Assessment** covers fraud, total loss, injury and high-value.
  4. **Decision Draft** produces a structured decision card.

  The small, fast model is the default (Intake, Assessment). The larger model runs the two
  judgment-heavy steps (Coverage, Decision Draft). Every response carries a `verdict_source` field:
  `model` or `deterministic_fallback`.
- **Why:** Separate agents give separately testable stages and traceable handoffs. Routing spends
  the expensive model only where a wrong answer moves money. The brief requires model verdicts to be
  distinguishable from rule-table output, and SC-1 scores fallback verdicts as misses.
- **Alternatives considered:** (a) One large prompt doing everything. Rejected because it can't be
  tested per stage, and a coverage error is indistinguishable from an extraction error. (b) The large
  model on every step. Rejected on cost per claim with no accuracy gain on extraction. (c) A rule
  table with a model "explainer". Rejected because the brief says it fails on clause wording and
  narrative consistency (CS-013, CS-015).
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** The cost-per-claim measurement (M4) or per-agent accuracy on the 150-case suite
  shows a routing change pays off.

## D-004 · 2026-11-04 · Access control in code at a single data boundary, before any agent runs
- **Decision:** Agents never call the three client systems directly. All access goes through one
  authenticated service (MCP-style data boundary). That service checks the user's entitlement
  **in code before any agent is invoked**, returns only the claim in scope, and writes an audit
  record (user, action, resource, decision) for every call, granted or denied.
- **Why:** The brief fixes identity and access as deterministic, and the grading treats "access
  control expressed as a model instruction" as Weak. A model can be talked out of a prompt rule but
  not out of a code check. One door gives Security one thing to review, and it is what makes CS-017
  (no cross-record data) and CS-019 (refusal plus audit) pass.
- **Alternatives considered:** (a) Each agent holds its own system credentials. Rejected because there
  is no single audit point and access sprawls. (b) Scope enforced by system-prompt instructions.
  Rejected because it is not a control. (c) Filter outputs after the model has seen the data.
  Rejected because the data has already left the boundary.
- **Owner:** Susan Wellington (FDE). Security / Compliance is Accountable for approving the auth model (M3).
- **Revisit when:** Security's review requests a different identity pattern (e.g. a different IdP or
  token exchange). The rule that enforcement happens in code before the agent does not change.

## D-003 · 2026-11-04 · Coverage is retrieval over a clause corpus, and an uncited claim is blocked
- **Decision:** Coverage statements come only from clauses retrieved from a searchable policy-clause
  corpus, each with a clause ID. Output guardrail: a coverage or money statement without a citation
  to a clause **actually retrieved for this request** is blocked and the case goes to human review.
  Retrieved chunks without valid corpus provenance are quarantined before reaching model context.
- **Why:** Coverage depends on clause wording (brief §2), and an adjuster or auditor must be able
  to check the reason. Citing only retrieved IDs prevents invented clause numbers, and quarantining
  unprovenanced chunks defends against a poisoned corpus (CS-020).
- **Alternatives considered:** (a) Let the model answer coverage from its own knowledge. Rejected
  because it is ungrounded and unauditable. (b) Encode clauses as rules. Rejected because it breaks
  on wording such as the renewal ambiguity (CS-009) and the commercial-use exclusion found in a
  narrative (CS-013). (c) Cite but don't enforce. Rejected because an unenforced citation rule is a
  suggestion.
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** Retrieval recall on the suite falls below what SC-1 needs, which would mean
  chunking or the index needs redesign, not that the rule should be dropped.

## D-002 · 2026-11-04 · Deterministic spine: identity, access, dates and money in code; judgment in the model
- **Decision:** Code computes policy-period membership (date and time against term start/end),
  net payable (gross − deductible, limits), the total-loss ratio (repair ÷ ACV), the $25K authority
  check, identity and entitlement. The model only reads, judges and explains, citing the evidence.
  Every decision card marks which fields are computed and which are judgment, and the adjuster
  confirms every outcome.
- **Why:** These values must be exact and repeatable, and a rule table's real weakness is stale
  fields, not arithmetic. CS-003 (status "Active", loss after term) and CS-014 (status "Expired",
  loss inside term) are decided by code reading the dates, not the status field. Keeping arithmetic
  out of the model makes it testable (the eval validator recomputes it) and is fixed by the brief.
- **Alternatives considered:** (a) Let the model compute payouts in its reasoning. Rejected because
  models make arithmetic slips and the result is untestable. (b) Trust structured status fields.
  Rejected because they are stale (the brief's CLM-2024-2822 example).
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** Never for the boundary itself (it is a client constraint). Revisit the field list
  if a new computed value is identified, such as a salvage deduction on total losses.

## D-001 · 2026-11-04 · Week 13 (M0) is discovery and scoping only: no build until criteria are agreed
- **Decision:** No agent code in M0. Deliverables are the charter, stakeholder map and RACI, success
  criteria, this log and the seed eval set. The only code is eval tooling (validator, scorer, harness
  tests), because it measures the problem rather than building a solution.
- **Why:** Success isn't agreed yet, and building now means building the wrong thing quickly. The
  criteria written now become the M1 SoW acceptance criteria and the M4 gate, so they have to be
  right first.
- **Alternatives considered:** A throwaway prototype to "show momentum". Rejected because momentum
  toward an undefined target is risk we pay for in capstone Week 5 (M4). A disposable proof of
  concept is allowed only to test a specific assumption, such as retrieval quality on clause wording.
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** The Claims Director signs off the charter and success criteria.
