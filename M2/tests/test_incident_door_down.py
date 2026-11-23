"""IC-001, the eval case incident-drill-1 spawned (M4 step 5, RCA `M4/drill/RCA-2026-11-23.md`).

A bad config release made the deployed door crash at start-up: API Gateway answered every call with a bare
`500 {"message": "Internal Server Error"}`. The pipeline failed closed (nothing decided) but told the adjuster
"refused", which reads as "you have no access". The contract now: a door outage is `unavailable` (retryable), never
a refusal and never a decision; no agent runs and nothing is spent. Replayed over both transports the orchestrator
uses (MCP on AWS, REST locally), with the exact response the gateway gave in the drill.
"""
import httpx
import pytest

from claimsense.boundary_client import HttpBoundary, McpBoundary
from claimsense.pipeline import run_claim

GATEWAY_500 = httpx.Response(500, json={"message": "Internal Server Error"})


def down(request):
    return GATEWAY_500


@pytest.mark.parametrize("kind", ["mcp", "rest"])
def test_ic001_door_down_is_unavailable_not_refused_and_nothing_is_decided(kind, monkeypatch):
    monkeypatch.setattr("claimsense.pipeline.asyncio.sleep", _no_sleep)
    b = McpBoundary("https://door.example", "https://door.example/mcp") if kind == "mcp" else HttpBoundary("https://door.example")
    b.http = httpx.Client(base_url="https://door.example", transport=httpx.MockTransport(down))
    r = run_claim("CLM-2024-1800", "alice", brain="replay", boundary=b)
    card = r["response"]
    assert r["decided_by"] == "unavailable" and card["outcome"] == "unavailable"
    assert card["retryable"] is True and card["returns_claim_data"] is False
    assert card["error"]["code"] == "upstream_unavailable"
    assert "refus" not in card["message"].lower()
    assert not [e for e in r["events"] if e["kind"] == "agent_start"] and not r["usage"] and r["cost_usd"] == 0


def test_ic001_a_real_refusal_is_still_a_refusal():
    r = run_claim("CLM-2024-1800", "carol", brain="replay")
    assert r["decided_by"] == "boundary_refusal" and r["response"]["outcome"] == "refused"


async def _no_sleep(_):
    return None
