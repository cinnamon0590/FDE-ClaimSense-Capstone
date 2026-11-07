"""The deterministic spine and the labelled fallback (Deliverable 5: model vs fallback distinguishable)."""
import json

from claimsense._m1 import FIXTURES, score
from claimsense.cases import all_cases
from claimsense.deterministic import compute, fallback_card

CLAIMS = {c["claim_id"]: c for c in json.loads((FIXTURES / "claims.json").read_text())["records"]}
POLICIES = {p["policy_id"]: p for p in json.loads((FIXTURES / "policies.json").read_text())["records"]}


def facts(claim_id):
    c = CLAIMS[claim_id]
    return c, POLICIES[c["policy_id"]]


def test_code_computes_every_golden_net_payable():
    for case in all_cases():
        if "net_payable" in case["expected"]:
            c, p = facts(case["claim"]["claim_id"])
            assert compute(c, p)["net_payable"] == case["expected"]["net_payable"], case["case_id"]


def test_term_boundaries_are_inclusive_and_exact():
    assert compute(*facts("CLM-2024-3530"))["loss_in_policy_term"]          # last day of term (CS-014)
    assert compute(*facts("CLM-2024-4108"))["loss_in_policy_term"]          # first day of term (CS-028)
    assert not compute(*facts("CLM-2024-4109"))["loss_in_policy_term"]      # one day after (CS-029)


def test_authority_limit_is_strictly_above_25000():
    assert compute(*facts("CLM-2024-4110"))["over_authority_limit"] is False   # exactly 25,000 (CS-030)
    assert compute(*facts("CLM-2024-4111"))["over_authority_limit"] is True    # 25,001 (CS-031)


def test_no_payable_amount_when_the_peril_is_not_carried():
    assert compute(*facts("CLM-2024-3104"))["net_payable"] is None          # hail on liability-only (CS-002)


def test_fallback_is_labelled_and_never_approves():
    for cid in CLAIMS:
        c, p = facts(cid)
        card = fallback_card(c, p, compute(c, p), reason="ModelTimeout")
        assert card["verdict_source"] == "deterministic_fallback"
        assert card["outcome"] != "approve"
        assert card["reasoning"].startswith("[DETERMINISTIC FALLBACK")
        assert card["model"]["name"].startswith("none")


def test_fallback_verdicts_never_count_for_the_gate():
    case = next(c for c in all_cases() if c["case_id"] == "CS-003")
    c, p = facts(case["claim"]["claim_id"])
    card = fallback_card(c, p, compute(c, p), reason="outage")
    card["citations"] = [x["source_id"] for x in card["citations"]]
    assert score.passes(case, card)                  # right answer...
    m = score.score(lambda _c: card, [case])
    assert m["model_verdicts"] == (0, 1)             # ...but not a model decision, so the gate can't pass on it
