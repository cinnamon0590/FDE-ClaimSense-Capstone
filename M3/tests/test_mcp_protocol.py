"""The MCP door speaks the protocol (JSON-RPC 2.0, spec 2025-06-18) and its HTTP transport is an OAuth 2.1 resource
server; and the agents' pipeline really reaches its data through it."""
import json

from claimsense_door.mcp import McpDoor, TOOLS


def rpc(client, token, method, params=None, mid=1, **headers):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    h.update(headers)
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}, headers=h)


def test_lifecycle_and_errors_in_process(door):
    d = door.door
    init = d.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, "alice")
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    old = d.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}}, "alice")
    assert old["result"]["protocolVersion"] == "2025-06-18"                     # server offers its own version
    assert d.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, "alice") is None
    assert d.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}, "alice")["error"]["code"] == -32601
    assert d.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "drop_tables"}},
                    "alice")["error"]["code"] == -32602
    assert d.handle({"id": 5, "method": "ping"}, "alice")["error"]["code"] == -32600   # not JSON-RPC 2.0
    assert len(d.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/list"}, "alice")["result"]["tools"]) == len(TOOLS)


def test_schema_validation_refuses_bad_arguments_with_an_audited_error(door):
    for args in ({}, {"claim_id": "CLM-2024-1800", "extra": 1}, {"claim_id": "../etc/passwd"}, {"claim_id": 1800}):
        _, r = door.call("alice", "get_claim", args)
        assert r["isError"] and r["structuredContent"]["error"]["code"] == "invalid_request"


def test_http_transport_is_an_oauth_resource_server(app_and_tokens):
    client, mint, _ = app_and_tokens
    r = rpc(client, None, "tools/list")
    assert r.status_code == 401 and 'resource_metadata="' in r.headers["www-authenticate"]
    meta = client.get("/.well-known/oauth-protected-resource").json()
    assert meta["resource"].endswith("/mcp") and meta["authorization_servers"]
    assert rpc(client, "not.a.jwt", "tools/list").status_code == 401
    ok = rpc(client, mint("alice"), "tools/list")
    assert ok.status_code == 200 and len(ok.json()["result"]["tools"]) == len(TOOLS)
    assert client.get("/mcp", headers={"Authorization": f"Bearer {mint('alice')}"}).status_code == 405
    assert client.get("/mcp").status_code == 401
    bad_ver = rpc(client, mint("alice"), "ping", **{"MCP-Protocol-Version": "1999-01-01"})
    assert bad_ver.status_code == 400
    batch = client.post("/mcp", content=json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}]),
                        headers={"Authorization": f"Bearer {mint('alice')}"})
    assert batch.status_code == 400
    note = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                       headers={"Authorization": f"Bearer {mint('alice')}"})
    assert note.status_code == 202


def test_two_users_over_http_same_question_different_answers(app_and_tokens):
    client, mint, _ = app_and_tokens
    q = {"name": "get_claim", "arguments": {"claim_id": "CLM-2024-1800"}}
    a = rpc(client, mint("alice"), "tools/call", q).json()["result"]
    c = rpc(client, mint("carol"), "tools/call", q).json()["result"]
    assert not a["isError"] and a["structuredContent"]["claim_id"] == "CLM-2024-1800"
    assert c["isError"] and "claim_id" not in c["structuredContent"]


def test_webhook_receiver_refuses_unsigned_and_forged(app_and_tokens):
    client, _, _ = app_and_tokens
    assert client.post("/webhooks/ticketing", content=b"{}").status_code == 401
    assert client.post("/webhooks/ticketing", content=b"{}",
                       headers={"X-Ticketing-Signature": "t=1,v1=" + "0" * 64}).status_code == 401


def test_the_pipeline_reaches_its_data_only_through_the_mcp_door(app_and_tokens, monkeypatch):
    """The real Pipeline with McpBoundary, its HTTP client wired to the real door app: the claim is decided, and every
    data access the agents made is an audited MCP tool call made as the adjuster."""
    client, mint, appmod = app_and_tokens
    from claimsense.boundary_client import CALLER_TOKEN, McpBoundary
    from claimsense.pipeline import Pipeline, run_sync
    mb = McpBoundary("http://testserver")
    mb.http = client
    CALLER_TOKEN.set(mint("alice"))
    n0 = len(appmod.B.audit)
    res = run_sync(Pipeline(brain="replay", boundary=mb).run("CLM-2024-1800", "alice"))
    assert res["response"]["outcome"] == "approve" and res["decided_by"] == "agents"
    new = appmod.B.audit[n0:]
    data_rows = [r for r in new if r["action"] in ("get_claim", "get_policy", "list_documents", "get_document",
                                                    "search_policy_clauses")]
    assert data_rows and all(r["via"] == "mcp" and r["user_id"] == "alice" and r["decision"] == "allow"
                             for r in data_rows)
    assert {"get_claim", "list_documents", "search_policy_clauses"} <= {r["action"] for r in data_rows}
    # identity is the TOKEN: with carol's token bound, the same pipeline is refused at step 0, before any agent
    CALLER_TOKEN.set(mint("carol"))
    refused = run_sync(Pipeline(brain="replay", boundary=mb).run("CLM-2024-1800", "carol"))
    assert refused["response"]["outcome"] == "refused" and refused["decided_by"] == "boundary_refusal"
    assert not refused["usage"] and refused["cost_usd"] == 0
