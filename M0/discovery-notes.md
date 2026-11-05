# DISCOVERY NOTES: ClaimSense AI

*(Class template, filled in. This is a synthetic engagement: "interviews" are reconstructed from the
client brief, the kickoff slides and the instructor's guidance. Every figure marked **(A)** is a
discovery assumption to validate with the client before the SoW.)*

**Date:** 2026-11-04 | **Interviewees:** Claims Director; Senior Adjuster / Team Lead | **Role:** FDE (Susan Wellington)

## CURRENT PROCESS ("show me how you do this today")

1. **Notice of loss** logged in the claims management system (who: claims intake / adjuster, time: ~10 min **(A)**)
2. **Gather the file:** open the document store, find which documents exist and which are missing, re-key
   the claim ID (who: adjuster, time: ~20 min **(A)**)
3. **Check coverage:** open policy admin, check term dates, coverages, deductible, then read the clause
   wording (who: adjuster, time: ~15 min **(A)**)
4. **Assess risk:** fraud, total loss, injury, from documents and claim history (who: adjuster, time: ~10 min **(A)**)
5. **First decision:** approve / flag / route / deny, with the reasoning written in an email or inbox,
   not in the system (who: adjuster, then senior adjuster if escalated, time: queue wait dominates; ~3.2 h
   from assignment to decision **(A)**)

### Process map: how a claim actually gets worked (system vs shadow)

| # | Step | System touched | Shadow? |
|---|---|---|---|
| 1 | Open the FNOL and claim record | Claims management | |
| 2 | Re-key the claim ID and claimant into the document store; list what exists and what's missing | Document store | **shadow: manual re-keying, adjuster is the integration layer** |
| 3 | Pull claimant claim history (prior losses, frequency) | Claims management | |
| 4 | Open policy admin and check the term dates *against the loss date*, ignoring the status field | Policy administration | **shadow: habit-only check; the status field is trusted by the rule table** |
| 5 | Read the clause wording for the loss type and exclusions | Policy administration (wording) | |
| 6 | Cross-check documents against the narrative (dates, photos, medical notes) | Document store | **shadow: the real fraud check; the system only has a score** |
| 7 | Ask a senior adjuster "is this covered?" when unsure | none (chat / walk-over) | **shadow: undocumented escalation** |
| 8 | Write the first decision and the reasoning | Claims management (code only) + email (reasoning) | **shadow: reasons live in an inbox** |

Success definition (from the Claims Director): *first decision in minutes, not hours, on every claim,
with ≥ 85% decisions correct and 0 auto-decisions; a licensed adjuster confirms each one.*
(Class self-check `score_process_map()`: **FLOOR_PASS**, with 5 shadow steps, 3 systems and a measurable success definition.)

**Shadow steps (not in any system):** the adjuster is the integration layer, re-keying IDs between
three systems. The reasoning lives in inboxes. Senior adjusters answer junior "is this covered?"
questions ad hoc. Fraud referral is a score threshold that adjusters second-guess by gut feel.

## PAIN POINTS

- Every step is manual; the queue waits on one pair of hands (frequency: every claim)
- Two adjusters reach different decisions on the same file; reasons aren't auditable (frequency: ~18% of files **(A)**)
- Fraud referral fires on `fraud_risk_score ≥ 0.5`, which misses contradictory files and floods SIU with clean ones (frequency: ~30% of confirmed fraud never referred, ~70% of referrals cleared **(A)**)
- Stale policy status fields lead to payment on lapsed policies (frequency: rare but costly; the brief's CLM-2024-2822)

## VOLUMES (approx.)

Claims per day: **~450 (A)** | Avg decision time: **~3.2 h elapsed / ~55 min active (A)** | Fraud rate: **~4% of claims confirmed fraudulent (A)**
Adjusters: **~40 (A)**, plus senior adjusters / team leads

## SYSTEMS MENTIONED

- Claims management system: FNOL, claim records, history (access: read + write recommendation via the data boundary; owner Claims Ops)
- Policy administration system: terms, coverages, deductibles, wording (access: read-only; owner Underwriting / Policy Admin)
- Document store: reports, estimates, photos, medical notes (access: read-only; owner Claims Ops / Records; contains untrusted text)

## CORRECTIONS / SURPRISES

- The problem isn't "slow deciding". It's **file assembly across three disconnected systems**, plus rework because reasoning isn't recorded.
- **Status fields lie in both directions:** "Active" after expiry (CS-003), "Expired" on a covered last-day loss (CS-014). Dates must be computed.
- **The fraud score misses the files that matter** (CS-008 at 0.44, CS-015 at 0.22). The signal is narrative inconsistency across documents.
- **No fixtures were issued**, so the FDE designs the synthetic data → DECISIONS D-006.
- **Security can block capstone Week 4 (M3)** → consult them on the auth model in M1 (RACI practical rule).

## QUESTIONS STILL OPEN FOR THE CLIENT

1. Confirm the baselines marked (A), especially decision time, the disagreement rate and fraud-referral precision.
2. Settlement authority: is $25K net payable the correct senior sign-off limit?
3. Renewal rule: does a renewal submitted before expiry but unprocessed keep cover in force? (drives CS-009)
4. Which adjuster groups may see fraud-routed claims? (drives the RBAC matrix in M3)
5. Who is the client-side owner ("catcher") of the eval suite after handover?
