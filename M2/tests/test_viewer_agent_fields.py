"""m2-v10 (D-045 in M2/DECISIONS.md): the Learning UI Viewer's agent descriptions, made literal.
Claim Assessment surfaces fraud indicators (late night, no police report, prior claims) and a high-value flag;
Document Intake reports vehicle, incident, damage, estimate and policy details. Code owns the rules and the money."""
import json

import pytest

from claimsense._m1 import FIXTURES
from claimsense.deterministic import risk_indicators
from claimsense.models import AssessmentResult, IntakeResult
from claimsense.pipeline import run_claim

CLAIMS = {c["claim_id"]: c for c in json.loads((FIXTURES / "claims.json").read_text())["records"]}


def base(**kw):
    return dict({"loss_type": "collision", "incident_time": None, "prior_claims_24m": 0}, **kw)


@pytest.mark.parametrize("claim, docs, want", [
    (base(incident_time="02:14"), ["police_report"], ["Late-night"]),
    (base(incident_time="23:00"), [], ["Late-night"]),
    (base(incident_time="22:59"), [], []),
    (base(incident_time="05:00"), [], []),
    (base(loss_type="theft"), ["fnol_form"], ["No police report"]),
    (base(loss_type="vandalism"), ["police_report"], []),
    (base(loss_type="collision"), [], []),                  # a collision without a police report is ordinary
    (base(prior_claims_24m=2), [], ["2 prior claims"]),
    (base(prior_claims_24m=1), [], []),
])
def test_risk_indicators_are_code_rules(claim, docs, want):
    got = risk_indicators(claim, docs)
    assert len(got) == len(want) and all(g.startswith(w) or w in g for g, w in zip(got, want))


def test_the_fixtures_carry_claims_history():
    assert {"CLM-2024-1873", "CLM-2024-3577", "CLM-2024-4106", "CLM-2024-4114"} <= \
           {c for c, r in CLAIMS.items() if r["prior_claims_24m"] >= 2}        # + M4 cases that set it explicitly


def test_the_new_output_fields_are_strict():
    assert {"vehicle", "incident", "damage", "repair_estimate_usd", "policy_details"} <= set(IntakeResult.model_fields)
    assert "high_value" in AssessmentResult.model_fields
    assert list(AssessmentResult.model_fields).index("high_value") > \
           list(AssessmentResult.model_fields).index("recommended_route")     # decided after the route, never before


def test_indicators_reach_the_adjuster_card_and_never_refer_on_their_own():
    """CS-007: a theft with no police report shows the indicator but stays flag_review (not a fraud referral)."""
    r = run_claim("CLM-2024-3355", "bob", brain="replay")
    card = r["response"]
    assert any("No police report" in s for s in card["judgment"]["fraud_signals"])
    assert (card["outcome"], card.get("route_to")) == ("flag_review", "senior-adjuster")


def test_a_fraud_referral_shows_every_indicator():
    card = run_claim("CLM-2024-1873", "bob", brain="replay")["response"]
    sig = " | ".join(card["judgment"]["fraud_signals"])
    assert "Late-night incident (02:14" in sig and "3 prior claims" in sig and card["route_to"] == "fraud-investigator"


def test_a_clean_claim_has_no_indicators():
    assert run_claim("CLM-2024-1800", "alice", brain="replay")["response"]["judgment"]["fraud_signals"] == []


def test_intake_reports_the_details_and_code_owns_the_estimate():
    r = run_claim("CLM-2024-1800", "alice", brain="replay")
    assert not [e for e in r["events"] if e.get("kind") == "code_override"]    # the recorded model got them right
    from claimsense.brains import ReplayStore
    intake = ReplayStore().load("CLM-2024-1800")["agents"]["intake"]["turns"][-1]["final"]
    assert intake["repair_estimate_usd"] == CLAIMS["CLM-2024-1800"]["repair_estimate"]
    assert "Toyota" in intake["vehicle"] and "POL-AU-10418" in intake["policy_details"]


def test_a_repeated_claim_file_call_is_answered_without_a_second_read():
    import asyncio
    from claimsense.boundary_client import make_boundary
    from claimsense.tools import RunCtx, get_claim_file
    ctx = RunCtx(boundary=make_boundary(), user_id="alice", claim_id="CLM-2024-1800", index=None)
    ctx.claim = ctx.boundary.claim("alice", "CLM-2024-1800")

    from agents.tool_context import ToolContext
    w = ToolContext(context=ctx, tool_name="get_claim_file", tool_call_id="t1", tool_arguments="{}")
    first = json.loads(asyncio.run(get_claim_file.on_invoke_tool(w, "{}")))
    second = json.loads(asyncio.run(get_claim_file.on_invoke_tool(w, "{}")))
    assert "documents" in first and "note" in second and "documents" not in second
