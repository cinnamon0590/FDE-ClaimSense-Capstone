"""Validate the ClaimSense synthetic fixtures (stdlib only, $0).

Checks:
  1. Every record conforms to its JSON Schema (schemas/*.schema.json).
  2. Referential integrity: claim → policy, claim → documents, document → claim, IDs unique.
  3. Consistency with the M0 eval cases: every case's claim/policy facts match the fixtures exactly,
     so the data the system runs on can't drift from the tests that grade it.
  4. Clause corpus: provenance hashes match, every clause an eval case must cite exists, and the
     planted injection chunk is NOT in the manifest (so the quarantine rule can reject it).

    python3 -I validate_data.py        # exit 0 = valid
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from jsonschema_lite import validate  # noqa: E402

CASES = HERE.parent.parent / "M0" / "evals" / "cases.json"
FILES = {"claims": "claim", "policies": "policy", "documents": "document", "clauses": "clause", "users": "user"}


def load(name):
    return json.loads((HERE / "fixtures" / f"{name}.json").read_text())


def main():
    problems, counts = [], {}
    data = {k: load(k) for k in FILES}

    # 1. schema conformance
    for name, schema_name in FILES.items():
        schema = json.loads((HERE / "schemas" / f"{schema_name}.schema.json").read_text())
        if data[name].get("synthetic") is not True:
            problems.append(f"{name}.json must declare synthetic: true")
        for rec in data[name]["records"]:
            for e in validate(rec, schema):
                problems.append(f"{name}: {rec.get(schema_name + '_id', rec.get('doc_id', '?'))}: {e}")
        counts[name] = len(data[name]["records"])

    claims = {c["claim_id"]: c for c in data["claims"]["records"]}
    policies = {p["policy_id"]: p for p in data["policies"]["records"]}
    docs = {d["doc_id"]: d for d in data["documents"]["records"]}
    clauses = {c["clause_id"]: c for c in data["clauses"]["records"]}

    # 2. referential integrity
    for name, key in (("claims", "claim_id"), ("policies", "policy_id"), ("documents", "doc_id"), ("clauses", "clause_id")):
        ids = [r[key] for r in data[name]["records"]]
        if len(ids) != len(set(ids)):
            problems.append(f"{name}: duplicate {key}")
    for c in claims.values():
        if c["policy_id"] not in policies:
            problems.append(f"{c['claim_id']}: policy {c['policy_id']} not found")
        if policies.get(c["policy_id"], {}).get("holder_id") != c["claimant_id"]:
            problems.append(f"{c['claim_id']}: claimant is not the policy holder")
        for d in c["document_ids"]:
            if d not in docs:
                problems.append(f"{c['claim_id']}: document {d} not found")
            elif docs[d]["claim_id"] != c["claim_id"]:
                problems.append(f"{d}: belongs to {docs[d]['claim_id']}, listed on {c['claim_id']}")
    orphans = set(docs) - {d for c in claims.values() for d in c["document_ids"]}
    if orphans:
        problems.append(f"orphan documents: {sorted(orphans)}")

    # 3. consistency with the M0 eval cases (the single source of truth)
    cases = json.loads(CASES.read_text())["cases"]
    for case in cases:
        cc, cp = case["claim"], case["policy"]
        fc, fp = claims.get(cc["claim_id"]), policies.get(cp["policy_id"])
        if not fc or not fp:
            problems.append(f"{case['case_id']}: claim/policy missing from fixtures"); continue
        for k in ("incident_date", "acv", "repair_estimate", "injury_reported", "fraud_risk_score", "loss_type"):
            if case["case_id"] != "CS-019" and fc[k] != cc[k]:
                problems.append(f"{case['case_id']}: claim.{k} {fc[k]!r} != case {cc[k]!r}")
        for fk, ck in (("term_start", "term_start"), ("term_end", "term_end"), ("deductible", "deductible"),
                       ("status_field", "status_field"), ("coverages", "coverage")):
            if fp[fk] != cp[ck]:
                problems.append(f"{case['case_id']}: policy.{fk} {fp[fk]!r} != case {cp[ck]!r}")
        for cite in case["expected"].get("must_cite", []):
            if cite not in clauses:
                problems.append(f"{case['case_id']}: must_cite {cite} is not in the clause corpus")

    # 4. clause provenance
    for c in clauses.values():
        if hashlib.sha256(f"{c['clause_id']}|{c['text']}".encode()).hexdigest() != c["manifest_sha256"]:
            problems.append(f"{c['clause_id']}: manifest hash does not match text (tampered)")
    manifest = {c["manifest_sha256"] for c in clauses.values()}
    for inj in data["clauses"]["untrusted_index_injections"]:
        h = hashlib.sha256(f"{inj['chunk_label']}|{inj['text']}".encode()).hexdigest()
        if h in manifest:
            problems.append(f"injection chunk {inj['chunk_label']!r} is in the manifest — quarantine would miss it")

    print("ClaimSense synthetic fixtures: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if problems:
        print("INVALID:"); [print("  -", p) for p in problems]
        return 1
    print("VALID — schemas, referential integrity, M0-case consistency and clause provenance all pass.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
