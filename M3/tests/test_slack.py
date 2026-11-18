"""On-call paging through the door: RBAC first, every failure mode handled, no claim data in Slack."""
from claimsense_door import slack_demo
from claimsense_door.mcp import TOOLS


def test_every_slack_scenario_is_handled_in_the_door():
    assert slack_demo.main([]) == 0


def test_notify_oncall_is_a_typed_scoped_tool():
    tool = [t for t in TOOLS if t["name"] == "notify_oncall"][0]
    assert tool["inputSchema"]["additionalProperties"] is False
    assert set(tool["inputSchema"]["required"]) == {"claim_id", "reason", "idempotency_key"}


def test_customer_service_cannot_page(door):
    _, r = door.call("dave", "notify_oncall", {"claim_id": "CLM-2024-1800", "reason": "x", "idempotency_key": "dave-p-0001"})
    assert r["isError"] and not door.b.slack.t.calls
