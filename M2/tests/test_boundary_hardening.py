"""Found in the pre-review guardrail audit (see README "Found and fixed"): the boundary is the last door, so it
must not trust the caller's headers or the writer's numbers."""
import copy
import uuid

import pytest
from pydantic import ValidationError

from claimsense.boundary_client import LocalBoundary
from claimsense.models import DecisionDraft
from claimsense.pipeline import run_claim


def _draft(b, claim_id="CLM-2024-1800", user="alice", card=None):
    card = card or run_claim(claim_id, user, brain="replay")["response"]
    return b.recommend(user, claim_id, card, uuid.uuid4().hex)


def _confirm(b, rec_id, user="alice", agent=None):
    return b.confirm(user, {"recommendation_id": rec_id, "action": "confirm", "idempotency_key": uuid.uuid4().hex},
                     agent=agent)


def test_an_agent_acting_for_a_human_cannot_confirm():
    b = LocalBoundary()
    rec = _draft(b)
    refused = _confirm(b, rec["recommendation_id"], agent="agent:decision-draft")
    assert refused["error"]["code"] == "human_confirmation_required"
    assert b.audit[-1]["decision"] == "deny" and b.audit[-1]["user_id"] == "agent:decision-draft"
    assert _confirm(b, rec["recommendation_id"])["confirmed_by"] == "alice"           # the human still can


def test_boundary_recomputes_the_numbers_so_a_forged_card_cannot_dodge_the_authority_limit():
    b = LocalBoundary()
    card = run_claim("CLM-2024-1800", "alice", brain="replay")["response"]
    honest = card["computed"]
    forged = copy.deepcopy(card)
    forged["computed"].update(net_payable=1, over_authority_limit=False)               # writer lies about money
    rec = _draft(b, card=forged)
    assert b.recommendations[rec["recommendation_id"]]["card"]["computed"] == honest


def test_boundary_rejects_a_draft_that_is_not_a_valid_card_for_this_claim():
    b = LocalBoundary()
    card = run_claim("CLM-2024-1800", "alice", brain="replay")["response"]
    no_confirm = dict(card, adjuster_confirmation_required=False)                       # G6 at the door
    other_claim = dict(card, claim_id="CLM-2024-1873")
    for bad in (no_confirm, other_claim, {"outcome": "approve"}):
        assert _draft(b, card=bad)["error"]["code"] == "invalid_request"
    assert not b.recommendations


def test_the_decision_agent_cannot_even_express_a_dollar_figure():
    """G4 is structural: the model's typed output has no `computed` field, and strict parsing refuses one."""
    assert "computed" not in DecisionDraft.model_json_schema()["properties"]
    with pytest.raises(ValidationError):
        DecisionDraft.model_validate({"claim_id": "CLM-2024-3602", "outcome": "approve", "route_to": None,
                                      "reasoning": "x", "citations": [], "computed": {"net_payable": 18000}})
