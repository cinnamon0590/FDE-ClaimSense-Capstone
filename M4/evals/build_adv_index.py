"""The adversarial cases as `ADV-*` (the W17 graded checklist's naming), traceable to the incidents they guard against.

    python3 -I M4/evals/build_adv_index.py      # writes M4/evals/adversarial-index.json and adversarial-index.md

Each ADV-NN is one of the 45 adversarial golden cases (gate: every one must pass, zero tolerance). The `incident`
column traces it to the failure it prevents: the W16 class incidents (a poisoned or injected document reaching the
model; an uncited money-moving claim) and the ClaimSense ones (cross-record leakage, forced auto-decision,
entitlement, PII). The case ids stay CS-NNN everywhere else, so nothing that scores them changes.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["M0/evals/cases.json", "M2/evals/cases-m2.json", "M4/evals/cases-m4.json"]
INCIDENT = {
    "prompt_injection": "W16 incident 1: an injected instruction in a document reaches the model (guard: G1/G1b quarantine, run stops, senior adjuster)",
    "cross_record_leakage": "another claimant's data in a response (guard: G7 masks foreign claim ids; entitlement at the door)",
    "forced_auto_decision": "pressure to pay without a person (guard: confirm is human-only; auto-decision text detected)",
    "entitlement_refusal": "an unentitled user gets claim data (guard: entitlement in code before any agent; same error for missing/forbidden)",
    "pii_exposure": "personal data reaches the model or logs (guard: G3 masking, international formats since D-052)",
    "citation_forgery": "W16 incident 2: an uncited or invented clause drives a money decision (guard: G5 citations must be retrieved; manifest provenance)",
}


def family(c):
    if c.get("adversarial_family"):
        return c["adversarial_family"]
    t = (c.get("title", "") + " " + json.dumps(c.get("expected", {}))).lower()
    if "refused" in t or c["expected"].get("outcome") == "refused":
        return "entitlement_refusal"
    if "poison" in t or "injection" in t or "injected" in t or "instruction" in t:
        return "prompt_injection"
    if "pii" in t or "ssn" in t:
        return "pii_exposure"
    if "auto" in t or "pre-authori" in t or "pay now" in t:
        return "forced_auto_decision"
    if "another" in t or "other claim" in t or "cross" in t or "leak" in t:
        return "cross_record_leakage"
    return "citation_forgery"


def main():
    adv = [c for f in FILES for c in json.loads((ROOT / f).read_text())["cases"] if c["category"] == "adversarial"]
    rows = [{"adv_id": f"ADV-{i:02d}", "case_id": c["case_id"], "family": family(c), "title": c.get("title", ""),
             "expected": c["expected"]["outcome"] + (f" → {c['expected']['route_to']}" if c["expected"].get("route_to") else ""),
             "guardrail": c["expected"].get("guardrail", ""), "incident": INCIDENT[family(c)]}
            for i, c in enumerate(adv, 1)]
    out = ROOT / "M4" / "evals"
    (out / "adversarial-index.json").write_text(json.dumps({"note": "ADV-* names for the 45 adversarial golden cases "
                                                             "(build_adv_index.py)", "cases": rows}, indent=1) + "\n")
    md = ["# Adversarial cases as `ADV-*` (zero tolerance: one failure blocks the release)", "",
          f"{len(rows)} adversarial golden cases. Gate: all must pass (`run_evals.py`). Families: "
          + ", ".join(f"{f} {sum(r['family'] == f for r in rows)}" for f in INCIDENT) + ".", "",
          "| ADV | Case | Family | Scenario | Expected | Guardrail | Incident it guards against |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['adv_id']} | {r['case_id']} | {r['family']} | {r['title']} | {r['expected']} | {r['guardrail'] or '—'} | {r['incident']} |"
           for r in rows]
    (out / "adversarial-index.md").write_text("\n".join(md) + "\n")
    print(f"wrote adversarial-index.md: {len(rows)} ADV cases")


if __name__ == "__main__":
    main()
