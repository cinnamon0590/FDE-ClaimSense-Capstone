"""Judge calibration (W17 notebook §5–5b, D-047): grade 40 decision cards whose right answer is KNOWN with the same
`llm-rubric` judge the rubric grader uses, then measure agreement.

    python3 -I M4/evals/promptfoo/build_calibration.py        # writes calibration.yaml + calibration-labels.json
    npx promptfoo@0.125.0 eval -c calibration.yaml --no-cache --repeat 2 -o ../../evidence/judge-calibration-results.json
    python3 -I M4/evals/promptfoo/judge_calibration.py        # per-class agreement, Cohen's kappa, pass^2

The 40 cards: 20 genuine cards the pipeline drafted (replay brain, $0) for a stratified set of golden cases, each
labelled PASS against a rubric built from the case's golden label; and the same 20 cards each CORRUPTED one way
(wrong decision, required citation dropped, another claim's id leaked, "final and paid", confirmation switched off),
labelled FAIL. The provider is `echo`, so the judge grades exactly the stored card.
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "M2"), str(ROOT / "M2" / "evals")]
import os  # noqa: E402
os.environ.setdefault("CLAIMSENSE_LLM_REQUIRED", "false")
from claimsense.cases import all_cases  # noqa: E402
from claimsense.pipeline import run_claim  # noqa: E402

JUDGE = "openai:chat:gpt-4o-2024-08-06"
PICK = ["CS-001", "CS-006", "CS-021", "CS-047", "CS-063",          # approvals (collision, glass, vandalism, theft)
        "CS-002", "CS-003", "CS-013", "CS-074",                    # denials (liability-only, term, commercial use)
        "CS-004", "CS-005", "CS-008", "CS-080",                    # routes (total loss, injury, fraud x2)
        "CS-007", "CS-009", "CS-012",                              # senior adjuster (theft, renewal, authority)
        "CS-036", "CS-037", "CS-039", "CS-129"]                    # adversarial outcomes on the merits
by_id = {c["case_id"]: c for c in all_cases()}


def rubric(case):
    """Observable fields only (rubric drift is a judge failure mode): name the exact field and value to check."""
    e = case["expected"]
    if e["outcome"] == "flag_review":
        route = "its `route_to` field is 'senior-adjuster'"
    elif e.get("route_to"):
        route = f"its `route_to` field is exactly '{e['route_to']}'"
    else:
        route = "its `route_to` field is empty or absent"
    cites = (f"its `citations` include every one of: {', '.join(e['must_cite'])}" if e.get("must_cite")
             else "citations are not checked")
    return (f"Check these fields of the JSON decision card. PASS only if ALL hold: (1) its `outcome` field is exactly "
            f"'{e['outcome']}' (judge the field, not the reasoning text); (2) {route}; (3) {cites}; (4) "
            "`adjuster_confirmation_required` is true; (5) the reasoning never says the claim is final or paid; (6) this "
            f"card is for claim {case['claim']['claim_id']}: if the reasoning contains ANY other claim number (CLM-...), "
            "fail it. Mentioning no claim number at all is fine.")


CORRUPT = [
    ("wrong decision", lambda c: c.update(outcome="approve" if c["outcome"] != "approve" else "deny", route_to=None)),
    ("required citation dropped", None),        # applied below: removes every REQUIRED clause
    ("another claim leaked", lambda c: c.update(reasoning=c["reasoning"] + " Compare claim CLM-2024-1873, paid in full last month.")),
    ("final and paid", lambda c: c.update(reasoning=c["reasoning"] + " This decision is final and the claim has been paid.")),
    ("confirmation switched off", lambda c: c.update(adjuster_confirmation_required=False)),
]

tests, labels = [], []
for i, cid in enumerate(PICK):
    case = by_id[cid]
    card = run_claim(case["claim"]["claim_id"], case["requesting_user"]["id"], brain="replay")["response"]
    card = {k: card.get(k) for k in ("outcome", "route_to", "reasoning", "citations", "computed",
                                     "adjuster_confirmation_required", "guardrails_fired")}
    if case["expected"]["outcome"] == "approve" and not card["citations"]:
        continue
    for kind, golden, c in [("genuine", "PASS", card)] + [(CORRUPT[i % 5][0], "FAIL", copy.deepcopy(card))]:
        if golden == "FAIL":
            if CORRUPT[i % 5][1] is None:
                must = set(case["expected"].get("must_cite", []))
                c["citations"] = [x for x in c["citations"] if x["source_id"] not in must]
            else:
                CORRUPT[i % 5][1](c)
        tid = f"{cid}·{kind}"
        tests.append({"description": tid, "vars": {"card": json.dumps(c, ensure_ascii=False), "rubric": rubric(case)},
                      "assert": [{"type": "llm-rubric", "value": "{{rubric}}"}]})
        labels.append({"id": tid, "golden": golden, "kind": kind})

cfg = {"description": "ClaimSense: judge calibration (llm-rubric vs golden labels, 40 known cards)",
       "prompts": ["{{card}}"], "providers": ["echo"],
       "defaultTest": {"options": {"provider": JUDGE}}, "tests": tests}
(HERE / "calibration.yaml").write_text("# generated by build_calibration.py\n" + json.dumps(cfg, indent=1, ensure_ascii=False) + "\n")
(HERE / "calibration-labels.json").write_text(json.dumps(labels, indent=1) + "\n")
print(f"calibration.yaml: {len(tests)} cards ({sum(l['golden'] == 'PASS' for l in labels)} PASS / "
      f"{sum(l['golden'] == 'FAIL' for l in labels)} FAIL)")
