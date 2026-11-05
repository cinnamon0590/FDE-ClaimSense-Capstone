"""Validate the ClaimSense M0 seed evaluation set (stdlib only, $0, no network).

Two kinds of checks:
  1. Shape and coverage: 20 cases, all four decision outcomes, the adversarial families present.
  2. Deterministic facts, recomputed IN CODE. Policy dates, net payable and the
     total-loss ratio are never left to a model (brief constraint #1), so the
     expected labels must agree with what code computes from the case data.

Usage:  python3 -I validate_cases.py [path/to/cases.json]
Exit code 0 = valid, 1 = problems found.
"""
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

DECISION_OUTCOMES = {"approve", "flag_review", "route", "deny"}
ALL_OUTCOMES = DECISION_OUTCOMES | {"refused"}
CATEGORIES = {"clear", "edge", "adversarial"}
REQUIRED_FAMILIES = {"prompt_injection", "cross_record_leakage",
                     "forced_auto_decision", "entitlement_refusal"}
CRITERIA = {"SC-1", "SC-2", "SC-3", "SC-4", "SC-5"}
REQUIRED_FIELDS = ("case_id", "category", "title", "claim", "policy",
                   "documents", "requesting_user", "expected", "rationale",
                   "criterion_ids")
EXPECTED_CASES = 20
MIN_PER_OUTCOME = 3
MIN_ADVERSARIAL = 5
AUTHORITY_LIMIT = 25_000  # net payable above this needs senior sign-off (CLS-AUTH-010)


def d(s):
    return date.fromisoformat(s)


def check_case(c, problems):
    cid = c.get("case_id", "?")
    for f in REQUIRED_FIELDS:
        if f not in c:
            problems.append(f"{cid}: missing field '{f}'")
    if problems and problems[-1].startswith(f"{cid}: missing"):
        return
    exp, claim, pol = c["expected"], c["claim"], c["policy"]
    outcome = exp.get("outcome")

    if c["category"] not in CATEGORIES:
        problems.append(f"{cid}: unknown category {c['category']!r}")
    if outcome not in ALL_OUTCOMES:
        problems.append(f"{cid}: unknown outcome {outcome!r}")
    if not set(c["criterion_ids"]) <= CRITERIA:
        problems.append(f"{cid}: unknown criterion id in {c['criterion_ids']}")
    if c["category"] == "adversarial" and c.get("adversarial_family") not in REQUIRED_FAMILIES:
        problems.append(f"{cid}: adversarial case needs a known adversarial_family")
    if outcome == "route" and not exp.get("route_to"):
        problems.append(f"{cid}: route outcome needs route_to")
    if outcome in DECISION_OUTCOMES and not exp.get("must_cite") and not exp.get("guardrail"):
        problems.append(f"{cid}: a decision must cite a clause (or name the guardrail that fired)")

    # Refusals return no claim data, so the deterministic checks below don't apply.
    if outcome == "refused":
        if not exp.get("audit", {}).get("decision") == "deny":
            problems.append(f"{cid}: a refusal must expect a 'deny' audit row")
        return

    # Deterministic: is the loss inside the policy term? (dates are code, not model)
    in_term = d(pol["term_start"]) <= d(claim["incident_date"]) <= d(pol["term_end"])
    renewal_pending = bool(pol.get("renewal_submitted")) and not pol.get("renewal_processed")
    if not in_term and not renewal_pending and outcome != "deny":
        problems.append(f"{cid}: loss is outside the policy term but expected outcome is {outcome!r}")
    if in_term and outcome == "deny" and "CLS-PER-006" in exp.get("must_cite", []):
        problems.append(f"{cid}: denies on policy period although the loss is inside the term")

    # Deterministic: total loss when repair >= ACV (only meaningful while in cover).
    if in_term and claim.get("repair_estimate", 0) >= claim["acv"] > 0:
        if not (outcome == "route" and exp.get("route_to") == "total-loss-appraiser"):
            problems.append(f"{cid}: repair >= ACV must route to total-loss-appraiser")

    # Deterministic: net payable = gross - deductible.
    if "net_payable" in exp:
        net = claim["repair_estimate"] - pol["deductible"]
        if exp["net_payable"] != net:
            problems.append(f"{cid}: net_payable {exp['net_payable']} != computed {net}")
        if outcome == "approve" and net > AUTHORITY_LIMIT:
            problems.append(f"{cid}: approve above the {AUTHORITY_LIMIT} authority limit")
    elif outcome == "approve":
        problems.append(f"{cid}: approve must state the code-computed net_payable")


def main(path):
    data = json.loads(Path(path).read_text())
    cases = data["cases"]
    problems = []

    ids = [c.get("case_id") for c in cases]
    if len(cases) != EXPECTED_CASES:
        problems.append(f"expected {EXPECTED_CASES} cases, found {len(cases)}")
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    if dupes:
        problems.append(f"duplicate case ids: {dupes}")

    for c in cases:
        check_case(c, problems)

    outcomes = Counter(c["expected"]["outcome"] for c in cases)
    for o in sorted(DECISION_OUTCOMES):
        if outcomes[o] < MIN_PER_OUTCOME:
            problems.append(f"outcome '{o}' appears {outcomes[o]}x (need >= {MIN_PER_OUTCOME})")
    adversarial = [c for c in cases if c["category"] == "adversarial"]
    if len(adversarial) < MIN_ADVERSARIAL:
        problems.append(f"{len(adversarial)} adversarial cases (need >= {MIN_ADVERSARIAL})")
    missing = REQUIRED_FAMILIES - {c.get("adversarial_family") for c in adversarial}
    if missing:
        problems.append(f"adversarial families missing: {sorted(missing)}")
    # Every success criterion must be testable by eval cases (if it isn't, it is too vague).
    per_criterion = Counter(cid for c in cases for cid in c["criterion_ids"])
    for crit in sorted(CRITERIA):
        if per_criterion[crit] < 2:
            problems.append(f"criterion {crit} is tested by {per_criterion[crit]} case(s) (need >= 2)")

    # Coverage table: outcome x category
    cats = ["clear", "edge", "adversarial"]
    print(f"ClaimSense M0 seed eval set — {len(cases)} cases\n")
    print(f"{'outcome':<13}" + "".join(f"{k:>13}" for k in cats) + f"{'total':>8}")
    for o in ["approve", "flag_review", "route", "deny", "refused"]:
        row = [sum(1 for c in cases if c['expected']['outcome'] == o and c['category'] == k) for k in cats]
        print(f"{o:<13}" + "".join(f"{n:>13}" for n in row) + f"{sum(row):>8}")
    print(f"{'total':<13}" + "".join(f"{sum(1 for c in cases if c['category'] == k):>13}" for k in cats)
          + f"{len(cases):>8}")
    print("\nadversarial families:", ", ".join(sorted({c['adversarial_family'] for c in adversarial})))
    print("cases per criterion: ", ", ".join(f"{k} {per_criterion[k]}" for k in sorted(CRITERIA)))

    if problems:
        print("\nINVALID:")
        for p in problems:
            print("  -", p)
        return 1
    print("\nVALID — all shape, coverage and deterministic-fact checks passed.")
    return 0


if __name__ == "__main__":
    default = Path(__file__).with_name("cases.json")
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else default))
