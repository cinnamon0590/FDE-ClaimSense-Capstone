"""Derive the per-agent golden labels (D-031) for every eval case: evals/agent-labels.json.

Labels come from the synthetic FIXTURES and the CODE RULES, never from what a model said (that would be circular):
  * Document Intake:  documents_on_file (fixture documents), missing_documents (the required-documents checklist),
                      injury_indicated (claim record), has_inconsistencies (cases whose documents contradict each
                      other: the fraud-referral cases)
  * Coverage Check:   coverage_finding, by explicit rules from the case's expected outcome. The rules that need
                      adjuster judgment are marked `signoff_required` for the Senior Adjuster (Susan) to confirm.
  * Claim Assessment: fraud_suspected (expected fraud referral), total_loss (code: repair / ACV >= 1),
                      injury_exposure (claim record), recommended_route (the routing business rule, fraud > injury >
                      total loss, applied to those true facts)
  * Decision Draft:   outcome + route_to + must_cite, as the case already states
Cases where the agents never run (boundary refusals, injection holds at Intake) carry `agents_run` = the agents
that do run, so they are scored only on those.

    python M2/evals/derive_agent_labels.py      # rewrites evals/agent-labels.json (deterministic)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from claimsense._m1 import FIXTURES  # noqa: E402
from claimsense.cases import all_cases  # noqa: E402
from claimsense.deterministic import compute, missing_documents, route_priority  # noqa: E402

ALL = ["Document Intake", "Coverage Check", "Claim Assessment", "Decision Draft"]
# flag_review cases are where "covered" vs "ambiguous" is a judgment, so each gets an explicit, signed-off reason
FLAG_REVIEW_COVERAGE = {
    "CS-007": ("ambiguous", "theft without a police report: the theft condition (CLS-THF-008) is unmet until it is filed"),
    "CS-009": ("ambiguous", "renewal submitted but not processed: whether the policy was in force is unresolved"),
    "CS-012": ("covered", "the loss is covered; it is flagged only because net payable exceeds the $25K authority"),
    "CS-027": ("covered", "the loss is covered; it is flagged only because the glass invoice is missing"),
    "CS-031": ("covered", "the loss is covered; it is flagged only because net payable is $1 over the authority"),
}


def coverage_label(case):
    exp = case["expected"]
    o = exp["outcome"]
    if case["case_id"] in FLAG_REVIEW_COVERAGE:
        finding, why = FLAG_REVIEW_COVERAGE[case["case_id"]]
        return {"coverage_finding": finding, "basis": why, "signoff_required": True}
    if o == "flag_review" and exp.get("must_cite"):          # M4 additions (D-046): the same rule, written once
        unresolved = {"CLS-THF-008", "CLS-REN-011"} & set(exp["must_cite"])
        return ({"coverage_finding": "ambiguous", "basis": "a condition of cover is unresolved ("
                 + ", ".join(sorted(unresolved)) + ")", "signoff_required": True} if unresolved else
                {"coverage_finding": "covered", "basis": "the loss is covered; it is flagged only for the authority "
                 "limit or a missing document", "signoff_required": True})
    if o == "approve":
        return {"coverage_finding": "covered", "basis": "expected approve: the loss is covered", "signoff_required": False}
    if o == "deny":
        return {"coverage_finding": "not_covered", "basis": "expected deny: no cover (peril, term, use or a false clause)",
                "signoff_required": False}
    if o == "route":
        return {"coverage_finding": "covered", "basis": f"expected route to {exp['route_to']}: the loss is covered; the "
                "specialist values, treats or investigates it", "signoff_required": exp["route_to"] == "fraud-investigator"}
    return None


def main():
    claims = {c["claim_id"]: c for c in json.loads((FIXTURES / "claims.json").read_text())["records"]}
    policies = {p["policy_id"]: p for p in json.loads((FIXTURES / "policies.json").read_text())["records"]}
    docs = json.loads((FIXTURES / "documents.json").read_text())["records"]
    labels = {}
    for case in all_cases():
        cid, exp = case["case_id"], case["expected"]
        claim = claims[case["claim"]["claim_id"]]
        if exp["outcome"] == "refused":
            labels[cid] = {"agents_run": [], "note": "refused at the boundary: no agent runs"}
            continue
        on_file = sorted(d["doc_type"] for d in docs if d["claim_id"] == claim["claim_id"])
        fraud = exp.get("route_to") == "fraud-investigator"
        computed = compute(claim, policies[claim["policy_id"]])
        entry = {
            "agents_run": ALL,
            "Document Intake": {"documents_on_file": on_file,
                                "missing_documents": sorted(missing_documents(claim["loss_type"], on_file)),
                                "injury_indicated": bool(claim.get("injury_reported")),
                                "has_inconsistencies": fraud},
            "Coverage Check": coverage_label(case),
            "Claim Assessment": {"fraud_suspected": fraud,
                                 "total_loss": computed["repair_to_acv_ratio"] >= 1,
                                 "injury_exposure": bool(claim.get("injury_reported")),
                                 "recommended_route": route_priority(fraud, bool(claim.get("injury_reported")), computed)},
            "Decision Draft": {"outcome": exp["outcome"], "route_to": exp.get("route_to"),
                               "must_cite": exp.get("must_cite", [])},
        }
        if "injection_detected" in (exp.get("guardrail") or []) or case["case_id"] in ("CS-016", "CS-035"):
            entry["agents_run"] = ["Document Intake"]          # held at Intake by design: later agents never run
            entry["note"] = "injection hold: only Document Intake runs; scored on the hold, not on extraction"
        labels[cid] = entry
    need = [cid for cid, e in labels.items() if (e.get("Coverage Check") or {}).get("signoff_required")]
    signoff = {"by": None, "role": "Senior Adjuster", "note": "confirm every label with signoff_required"}
    prev_path = HERE / "agent-labels.json"
    if prev_path.exists():                                  # keep a sign-off only while the signed labels are unchanged
        prev = json.loads(prev_path.read_text())
        old = prev.get("signoff") or {}
        if old.get("by") and old.get("cases") == need and all(
                (prev["labels"].get(c) or {}).get("Coverage Check") == labels[c].get("Coverage Check") for c in need):
            signoff = old
    out = {"version": 1, "derived_by": "evals/derive_agent_labels.py", "signoff": signoff, "labels": labels}
    (HERE / "agent-labels.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"sign-off: {signoff['by'] or 'PENDING'} · wrote agent-labels.json: {len(labels)} cases · {len(need)} coverage labels need sign-off: {', '.join(need)}")


if __name__ == "__main__":
    main()
