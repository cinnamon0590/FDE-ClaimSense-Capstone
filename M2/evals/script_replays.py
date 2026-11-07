"""Write SCRIPTED replay files: hand-authored model turns that exercise the real harness (Runner,
tools, strict parsing, guardrails, boundary) before any live run exists.

    python M2/evals/script_replays.py            # writes M2/evals/replays/<claim_id>.json (source="scripted")

Honesty rules for these files:
  * they are labelled source="scripted" and the eval report counts them separately;
  * a recorded live run (`run_evals.py --brain live --record`) overwrites them with source="recorded";
  * passing the replay gate proves the HARNESS (tools, guardrails, routing, contract), not the model.
    Only the live gate proves the model.
Turns are written the way a well-behaved model would answer: one tool call per turn, then the typed
output. Coverage queries are plain language (never the clause ID), so retrieval has to find the clause.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from claimsense._m1 import FIXTURES  # noqa: E402
from claimsense.cases import all_cases  # noqa: E402
from claimsense.deterministic import compute  # noqa: E402

QUERY = {
    "CLS-COL-001": "collision damage to the insured's own car",
    "CLS-DED-002": "deductible subtracted from the payment for each loss",
    "CLS-CMP-003": "broken window glass damage not caused by collision",
    "CLS-TL-004": "repair cost compared with actual cash value total loss",
    "CLS-INJ-005": "bodily injury to a person in the accident",
    "CLS-PER-006": "loss date outside the policy period",
    "CLS-FRD-007": "material inconsistencies in documents dated before the loss",
    "CLS-THF-008": "stolen car police report",
    "CLS-USE-009": "carrying passengers for a fee ride-hail app",
    "CLS-AUTH-010": "settlement amount above 25000 senior adjuster sign-off",
    "CLS-REN-011": "renewal submitted but not processed",
    "CLS-LIA-012": "liability only no cover for own vehicle",
}
EXTRA_QUERIES = {"CS-020": ["is a lapsed policy still covered after the end date"]}
CLAUSES = {c["clause_id"]: c for c in json.loads((FIXTURES / "clauses.json").read_text())["records"]}
CLAIMS = {c["claim_id"]: c for c in json.loads((FIXTURES / "claims.json").read_text())["records"]}
POLICIES = {p["policy_id"]: p for p in json.loads((FIXTURES / "policies.json").read_text())["records"]}
DOCS = {d["doc_id"]: d for d in json.loads((FIXTURES / "documents.json").read_text())["records"]}
REQUIRED = {"collision": [("repair_estimate", "repair_invoice")], "vandalism": [("repair_estimate", "repair_invoice")],
            "glass": [("glass_invoice",)], "theft": [("police_report",)], "hail": [("repair_estimate", "repair_invoice")]}


def est(obj):
    return max(1, len(json.dumps(obj)) // 4)


def replay_for(case):
    exp, claim = case["expected"], CLAIMS[case["claim"]["claim_id"]]
    pol = POLICIES[claim["policy_id"]]
    docs = [DOCS[d] for d in claim["document_ids"]]
    types = [d["doc_type"] for d in docs]
    computed = compute(claim, pol)
    missing = (["fnol_form"] if "fnol_form" not in types else []) + [
        alts[0] for alts in REQUIRED.get(claim["loss_type"], []) if not any(a in types for a in alts)]
    facts = case.get("document_facts", {})
    inconsist = [f"{k}: {v}" for k, v in facts.items()
                 if "BEFORE" in v or "metadata dates" in v or "different vehicle" in v]
    commercial = "CLS-USE-009" in exp.get("must_cite", [])
    intake = {"claim_id": claim["claim_id"], "loss_type": claim["loss_type"], "documents_on_file": types,
              "missing_documents": missing, "injury_indicated": claim["injury_reported"],
              "commercial_use_indicated": commercial, "inconsistencies": inconsist,
              "summary": f"{claim['loss_type'].title()} claim with {len(docs)} document(s) on file. "
                         + ("Inconsistencies noted." if inconsist else "No contradictions found in the documents.")}

    outcome, route = exp["outcome"], exp.get("route_to")
    cites = list(exp.get("must_cite", []))
    if outcome == "approve":
        base = ["CLS-COL-001"] if claim["loss_type"] == "collision" else ["CLS-CMP-003"]
        cites = list(dict.fromkeys(base + ["CLS-DED-002"] + cites))
    if outcome == "flag_review" and computed["over_authority_limit"] and "CLS-AUTH-010" not in cites:
        cites.append("CLS-AUTH-010")
    queries = [QUERY[c] for c in cites] + EXTRA_QUERIES.get(case["case_id"], []) or [QUERY["CLS-COL-001"]]
    finding = ("not_covered" if outcome == "deny" else
               "ambiguous" if outcome == "flag_review" and not computed["over_authority_limit"] else "covered")
    coverage = {"claim_id": claim["claim_id"], "coverage_finding": finding,
                "basis": {"not_covered": "An exclusion or the policy period removes cover for this loss.",
                          "ambiguous": "Cover depends on a condition that is not yet resolved.",
                          "covered": "The peril is on the policy and the loss is inside the policy term."}[finding],
                "cited_clause_ids": cites,
                "exclusion_or_condition": None if finding == "covered" else (cites[0] if cites else None)}

    fraud = route == "fraud-investigator"
    assessment = {"claim_id": claim["claim_id"], "fraud_signals": inconsist if fraud else [],
                  "fraud_suspected": fraud, "total_loss": computed["repair_to_acv_ratio"] >= 1,
                  "injury_exposure": claim["injury_reported"],
                  "recommended_route": route if outcome == "route" else None,
                  "rationale": "Routing follows the priority fraud, injury, total loss."}

    why = {"approve": "The loss is covered under the cited clauses; the deductible applies. "
                      f"Net payable is {computed['net_payable']} as computed by the system.",
           "deny": "The cited clause removes cover for this loss, so a denial is recommended.",
           "route": f"This claim needs a specialist review by the {route} under the cited clause.",
           "flag_review": "Coverage or authority cannot be settled at first pass; a senior adjuster should review."}[outcome]
    decision = {"claim_id": claim["claim_id"], "outcome": outcome,
                "route_to": route if outcome == "route" else ("senior-adjuster" if outcome == "flag_review" else None),
                "reasoning": why + " An adjuster confirms or overrides this recommendation.",
                "citations": [{"source_id": c, "quote": CLAUSES[c]["text"].split(".")[0][:160]} for c in cites]}

    def turns(calls, final):
        t = [{"tool_calls": [c], "usage": {"input_tokens": 900, "output_tokens": 30}} for c in calls]
        return t + [{"final": final, "usage": {"input_tokens": 900 + 400 * len(calls), "output_tokens": est(final)}}]

    return {"claim_id": claim["claim_id"], "source": "scripted", "case_id": case["case_id"],
            "note": "Hand-authored turns to exercise the harness. Token counts are estimates.",
            "agents": {
                "intake": {"model": "gpt-4o-mini", "turns": turns([{"name": "get_claim_file", "arguments": "{}"}], intake)},
                "coverage": {"model": "gpt-4o", "turns": turns(
                    [{"name": "search_clauses", "arguments": json.dumps({"query": q})} for q in queries], coverage)},
                "assessment": {"model": "gpt-4o-mini", "turns": turns([], assessment)},
                "decision": {"model": "gpt-4o", "turns": turns([], decision)}}}


def complete(d):
    ag = d.get("agents", {})
    return d.get("source") == "recorded" and all(
        a in ag and ag[a]["turns"] and "final" in ag[a]["turns"][-1] for a in ("intake", "coverage", "assessment", "decision"))


def main():
    out = HERE / "replays"
    out.mkdir(exist_ok=True)
    n = 0
    for case in all_cases():
        if case["expected"]["outcome"] == "refused":
            continue
        p = out / f"{case['claim']['claim_id']}.json"
        if p.exists() and complete(json.loads(p.read_text())):
            continue                                    # never overwrite a complete real recording
        p.write_text(json.dumps(replay_for(case), indent=1) + "\n")
        n += 1
    print(f"wrote {n} scripted replay file(s) to {out}")


if __name__ == "__main__":
    main()
