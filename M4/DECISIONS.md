# DECISIONS.md: ClaimSense AI engagement (M4 entries)

Continues the engagement decision log. D-001 to D-007 are in [`../M0/DECISIONS.md`](../M0/DECISIONS.md), D-008 to
D-016 in [`../M1/DECISIONS.md`](../M1/DECISIONS.md), D-017 to D-035 and D-045 in [`../M2/DECISIONS.md`](../M2/DECISIONS.md),
D-036 to D-044 in [`../M3/DECISIONS.md`](../M3/DECISIONS.md). Newest first.

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
  CI's live gate runs 150 cases on each merge to `main`. Step 1 live spend, including the tuning rounds: $40.92 in
  full-suite runs (spend ledger) plus ≈ $7 of targeted probes; total OpenAI spend to date $58.61 (`SPEND.txt`).
- **Owner:** Susan Wellington.
