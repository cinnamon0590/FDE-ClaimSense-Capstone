"""The deterministic spine: dates, money and thresholds are computed by code, never by a model.

Two jobs:
  1. `compute(claim, policy)` fills the card's `computed` section (guardrail G4 enforces it).
  2. `fallback_card(...)` is the rule-engine verdict used ONLY when the model is unavailable
     (timeout, outage, budget cap, unparseable output). It is stamped
     verdict_source="deterministic_fallback" so it can never pass as a model decision (D-007,
     risk R3), and it never approves: an approval needs model judgment plus a human.
"""
from datetime import date

AUTHORITY_LIMIT = 25_000
PERIL_COVERAGE = {"collision": "collision", "glass": "comprehensive", "hail": "comprehensive",
                  "theft": "comprehensive", "vandalism": "comprehensive"}
FRAUD_SCORE_ROUTE = 0.7
REQUIRED_DOCS = {  # loss type -> groups of acceptable document types (one of each group must be on file)
    "collision": [("repair_estimate", "repair_invoice")], "vandalism": [("repair_estimate", "repair_invoice")],
    "hail": [("repair_estimate", "repair_invoice")], "glass": [("glass_invoice",)], "theft": [("police_report",)],
}


def missing_documents(loss_type, doc_types):
    """Required-document checklist (code, not judgment): every claim needs an FNOL form plus the loss-type set."""
    missing = [] if "fnol_form" in doc_types else ["fnol_form"]
    return missing + [grp[0] for grp in REQUIRED_DOCS.get(loss_type, []) if not any(t in doc_types for t in grp)]


def route_priority(fraud_suspected, injury, computed):
    """Routing priority is a business rule: fraud > injury > total loss. The model judges the flags;
    code applies the order and the total-loss threshold."""
    if fraud_suspected:
        return "fraud-investigator"
    if injury:
        return "injury-specialist"
    if computed["repair_to_acv_ratio"] >= 1:
        return "total-loss-appraiser"
    return None


def verified_facts(claim, policy, computed, missing, inconsistencies=()):
    """Plain-language statements of what code has already established, so no agent re-derives them."""
    facts = [("The loss date IS inside the policy period" if computed["loss_in_policy_term"] else
              "The loss date is OUTSIDE the policy period")
             + f" (incident {claim['incident_date']}; cover runs 00:01 on {policy['term_start']} through 23:59 on "
               f"{policy['term_end']}, so the end date itself is covered). The status_field may be stale; ignore it.",
             f"Repair-to-ACV ratio is {computed['repair_to_acv_ratio']}: "
             + ("a TOTAL LOSS (ratio >= 1.0)." if computed["repair_to_acv_ratio"] >= 1 else "NOT a total loss (ratio < 1.0)."),
             ]
    net = computed["net_payable"]
    if net is None:
        facts.append("There is no payable amount: the loss is out of term or the peril is not on the policy.")
    else:
        basis = claim["acv"] if computed["repair_to_acv_ratio"] >= 1 else claim["repair_estimate"]
        facts.append(f"Net payable if covered: {net} = {basis} - {policy['deductible']} deductible. The deductible has "
                     "ALREADY been subtracted; do not subtract it again. "
                     + ("This is ABOVE the $25,000 authority limit: needs senior-adjuster sign-off." if computed["over_authority_limit"]
                        else "This is within the $25,000 authority limit."))
    if inconsistencies or claim.get("fraud_risk_score", 0) >= FRAUD_SCORE_ROUTE:
        facts.append("Fraud is SUSPECTED (fraud score >= 0.7 or material inconsistencies in the file). The inconsistency "
                     "clause requires REFERRAL to the fraud investigator before any payment. That is a referral, NOT an "
                     "exclusion: inconsistencies are never a reason to deny, and they don't make coverage ambiguous.")
    if claim["loss_type"] == "theft" and "police_report" in missing:
        facts.append("The police report is MISSING. The policy says a theft claim cannot be SETTLED until a police "
                     "report reference is received: that is a pending condition, so coverage is AMBIGUOUS. It is NOT an "
                     "exclusion and NOT grounds to deny.")
    ren = policy.get("renewal") or {}
    if ren.get("submitted") and not ren.get("processed") and not computed["loss_in_policy_term"]:
        facts.append(f"A renewal was SUBMITTED on {ren['submitted']} but NOT yet processed: whether cover continues is "
                     "unresolved, so coverage is AMBIGUOUS. Do not deny on the policy period.")
    facts.append("Required documents missing: " + ", ".join(missing) if missing else "All required documents are on file.")
    return facts


def in_policy_term(claim, policy):
    """Cover runs from term_start through 23:59 local time on term_end (inclusive)."""
    d = date.fromisoformat(claim["incident_date"])
    return date.fromisoformat(policy["term_start"]) <= d <= date.fromisoformat(policy["term_end"])


def peril_on_policy(claim, policy):
    return PERIL_COVERAGE.get(claim["loss_type"]) in policy["coverages"]


def compute(claim, policy):
    """Code-owned numbers. Net payable = min(repair, ACV) - deductible, only for an in-term loss whose
    peril the policy carries (otherwise there is nothing to pay, so it's null rather than a guess)."""
    ratio = round(claim["repair_estimate"] / claim["acv"], 4) if claim["acv"] else 0.0
    in_term = in_policy_term(claim, policy)
    net = None
    if in_term and peril_on_policy(claim, policy):
        basis = claim["acv"] if ratio >= 1 else claim["repair_estimate"]
        net = max(int(basis) - int(policy["deductible"]), 0)
    return {"loss_in_policy_term": in_term, "net_payable": net, "repair_to_acv_ratio": ratio,
            "over_authority_limit": net is not None and net > AUTHORITY_LIMIT}


def fallback_card(claim, policy, computed, reason, guardrails_fired=()):
    """Rule-engine verdict when the model can't be used. Conservative by design: it denies only on a
    structural fact (out of term, peril not carried), routes on hard thresholds, and otherwise sends
    the claim to a senior adjuster. It NEVER approves."""
    def card(outcome, route_to, cite, why):
        return {"claim_id": claim["claim_id"], "outcome": outcome, "route_to": route_to,
                "reasoning": f"[DETERMINISTIC FALLBACK: {reason}] {why} An adjuster must review.",
                "citations": [{"source_id": c, "quote": ""} for c in cite],
                "computed": dict(computed),
                "judgment": {"coverage_finding": "ambiguous", "fraud_signals": [],
                             "injury_exposure": bool(claim.get("injury_reported")), "missing_documents": []},
                "verdict_source": "deterministic_fallback", "guardrails_fired": sorted(set(guardrails_fired)),
                "adjuster_confirmation_required": True,
                "model": {"name": "none (rule engine)", "prompt_version": "n/a"}}

    renewal_pending = (policy.get("renewal") or {}).get("submitted") and not (policy.get("renewal") or {}).get("processed")
    if not computed["loss_in_policy_term"] and not renewal_pending:
        return card("deny", None, ["CLS-PER-006"], "Loss date falls outside the policy period.")
    if computed["loss_in_policy_term"] and not peril_on_policy(claim, policy) and policy["coverages"] == ["liability"]:
        return card("deny", None, ["CLS-LIA-012"], "Policy carries liability cover only.")
    if claim.get("injury_reported"):
        return card("route", "injury-specialist", ["CLS-INJ-005"], "Bodily injury is reported.")
    if computed["repair_to_acv_ratio"] >= 1:
        return card("route", "total-loss-appraiser", ["CLS-TL-004"], "Repair cost meets or exceeds ACV.")
    if claim.get("fraud_risk_score", 0) >= FRAUD_SCORE_ROUTE:
        return card("route", "fraud-investigator", ["CLS-FRD-007"], "Fraud risk score at or above 0.7.")
    return card("flag_review", "senior-adjuster", [], "No model judgment is available, so no approval is drafted.")


def coverage_questions(claim, policy, computed, missing, inconsistencies=()):
    """The coverage questions these facts raise, worked out by code so the agent can't skip one.
    The agent still searches the wording and judges; this is a checklist, not an answer."""
    q = [f"Is {claim['loss_type']} damage to the insured's own car covered by this policy's coverages {policy['coverages']}?"]
    if policy["coverages"] == ["liability"]:
        q.append("Does a liability-only policy pay for damage to the insured's own car?")
    if computed["net_payable"] is not None:
        q.append("How does the deductible apply to the payment?")
    d, start, end = claim["incident_date"], policy["term_start"], policy["term_end"]
    if not computed["loss_in_policy_term"] or d in (start, end):
        q.append("Is the loss date inside the policy period?")
    ren = policy.get("renewal") or {}
    if ren.get("submitted") and not ren.get("processed"):
        q.append("Does cover continue when a renewal was submitted but not processed?")
    if claim.get("injury_reported"):
        q.append("How must a claim involving bodily injury be handled?")
    if computed["repair_to_acv_ratio"] >= 0.95:
        q.append("When is the car a total loss compared with its actual cash value?")
    if computed["over_authority_limit"]:
        q.append("Who must sign off a settlement above the authority limit?")
    if claim["loss_type"] == "theft":
        q.append("What reporting is required before a theft claim is settled?")
    if inconsistencies or claim.get("fraud_risk_score", 0) >= FRAUD_SCORE_ROUTE:
        q.append("What happens when the claim file contains material inconsistencies (possible fraud)?")
    return q
