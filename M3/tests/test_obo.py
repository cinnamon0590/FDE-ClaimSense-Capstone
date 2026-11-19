"""On-behalf-of token exchange (RFC 8693, Architect tier): the delegated token's scope drives _authorize."""
import jwt

GT = "urn:ietf:params:oauth:grant-type:token-exchange"


def exchange(client, subject, actor="agent:claimsense-pipeline", scope=None):
    body = {"grant_type": GT, "subject_token": subject, "actor": actor}
    if scope:
        body["scope"] = scope
    return client.post("/oauth/token", json=body)


def call(client, token, name, args):
    return client.post("/mcp", headers={"Authorization": f"Bearer {token}"},
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": name, "arguments": args}}).json()["result"]


def test_exchange_issues_a_short_lived_narrowed_token_naming_the_agent(app_and_tokens):
    client, mint, _ = app_and_tokens
    r = exchange(client, mint("alice"))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    tok = r.json()
    claims = jwt.decode(tok["access_token"], options={"verify_signature": False})
    assert claims["sub"] == "alice" and claims["act"] == {"sub": "agent:claimsense-pipeline"}
    assert claims["exp"] - claims["iat"] <= 300 and claims["aud"] == "claimsense-door"
    scope = set(tok["scope"].split())
    assert "get_claim" in scope and not scope & {"confirm_recommendation", "read_audit", "ticket_webhook"}


def test_the_delegated_tokens_scope_drives_authorize(app_and_tokens):
    client, mint, appmod = app_and_tokens
    narrow = exchange(client, mint("alice"), scope="get_claim").json()["access_token"]
    ok = call(client, narrow, "get_claim", {"claim_id": "CLM-2024-1800"})
    assert not ok["isError"]
    out = call(client, narrow, "list_claim_documents", {"claim_id": "CLM-2024-1800"})   # alice may; the token may not
    assert out["isError"]
    rid = out["structuredContent"]["error"]["request_id"]
    row = [r for r in appmod.B.audit if r["request_id"] == rid][0]
    assert row["reason"] == "outside the delegated token's scope" and row["on_behalf_of_agent"] == "agent:claimsense-pipeline"


def test_the_delegated_token_never_widens_access(app_and_tokens):
    client, mint, _ = app_and_tokens
    carol = exchange(client, mint("carol"), scope="get_claim read_audit confirm_recommendation").json()
    assert carol["scope"] == "get_claim"                              # asked for more, got only what may be delegated
    assert call(client, carol["access_token"], "get_claim", {"claim_id": "CLM-2024-1800"})["isError"]  # still not hers


def test_exchange_refuses_bad_subjects_actors_and_users_with_no_grants(app_and_tokens):
    client, mint, appmod = app_and_tokens
    assert exchange(client, "not-a-token").status_code == 400
    assert exchange(client, mint("alice"), actor="bob").status_code == 400               # actor must be an agent
    dave = exchange(client, mint("dave"))
    assert dave.status_code == 400 and dave.json()["error"] == "invalid_grant"
    row = [r for r in appmod.B.audit if r["request_id"] == dave.json()["request_id"]][0]
    assert row["user_id"] == "dave" and row["action"] == "token_exchange" and row["reason"].startswith("no_grant")


def test_a_delegated_token_is_refused_once_the_users_groups_change(app_and_tokens):
    client, mint, appmod = app_and_tokens
    tok = exchange(client, mint("alice")).json()["access_token"]
    appmod.B.users["alice"]["groups"] = ["customer-service"]            # revoked/re-roled at the IdP and directory
    try:
        r = client.post("/mcp", headers={"Authorization": f"Bearer {tok}"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401
    finally:
        appmod.B.users["alice"]["groups"] = ["adjuster"]
