"""Deny-by-default grants, and "authorisation on every route" as a build-breaking table check (D-2, D-037)."""
from claimsense_door.grants import actions, granted, matrix, table
from claimsense_door.mcp import TOOL_ACTION, TOOLS


def test_grants_file_is_deny_by_default_and_only_grants_declared_actions():
    t = table()
    assert t["default"] == "deny"
    for who, acts in matrix().items():
        assert set(acts) <= actions(), who


def test_nothing_is_granted_without_an_explicit_grant():
    assert not granted({"user_id": "x", "groups": []}, "get_claim")                       # no group
    assert not granted({"user_id": "x", "groups": ["claims-superuser"]}, "get_claim")     # unknown group
    assert not granted({"user_id": "bob", "groups": ["senior-adjuster"]}, "delete_claim")  # undeclared action
    assert not granted({"user_id": "dave", "groups": ["customer-service"]}, "get_claim")   # role with no grants
    assert granted({"user_id": "alice", "groups": ["adjuster"]}, "get_claim")


def test_scope_matrix_traps():
    # trap 1: customer service never reads claim files (so never sees fraud scores)
    assert matrix()["customer-service"] == []
    # trap 2: no human role and no service can WRITE the audit trail; only senior adjusters READ it
    assert not [a for acts in matrix().values() for a in acts if "audit" in a and a != "read_audit"]
    assert [r for r, acts in matrix().items() if "read_audit" in acts] == ["senior-adjuster"]
    # human-only confirmation: no specialist or service may confirm
    assert {r for r, acts in matrix().items() if "confirm_recommendation" in acts} == {"adjuster", "senior-adjuster"}
    # the ticketing system's identity may deliver webhooks and nothing else
    assert matrix()["system:ticketing"] == ["ticket_webhook"]


def test_every_mcp_tool_maps_to_a_declared_action():
    assert {t["name"] for t in TOOLS} == set(TOOL_ACTION)
    assert set(TOOL_ACTION.values()) <= actions()
    for t in TOOLS:                                   # identity is never a tool argument
        assert not {"user_id", "user", "groups", "token"} & set(t["inputSchema"]["properties"])
        assert t["inputSchema"]["additionalProperties"] is False


def test_every_route_is_listed_and_only_health_keys_and_discovery_are_public(app_and_tokens):
    _, _, appmod = app_and_tokens
    routes = {(m, r.path) for r in appmod.app.routes if hasattr(r, "methods") for m in r.methods - {"HEAD"}}
    unlisted = {rt for rt in routes if rt not in appmod.ROUTE_ACTIONS and rt[1] not in appmod.PUBLIC}
    assert not unlisted, f"routes with no authorisation entry: {unlisted}"
    assert appmod.PUBLIC <= {"/healthz", "/.well-known/jwks.json", "/.well-known/oauth-protected-resource",
                             "/.well-known/oauth-protected-resource/mcp", "/openapi.json", "/docs",
                             "/docs/oauth2-redirect", "/redoc"}
    for (m, path), action in appmod.ROUTE_ACTIONS.items():
        base = action.split(" ")[0]
        # token_exchange is authentication (RFC 8693), not a grantable action: it can only NARROW the user's grants
        assert base in actions() or base in ("mcp", "405", "dev", "ticket_webhook", "token_exchange"), (m, path, action)


def test_every_guarded_route_refuses_no_token_before_validation(app_and_tokens):
    client, _, appmod = app_and_tokens
    for (method, path) in appmod.ROUTE_ACTIONS:
        if path in ("/webhooks/ticketing", "/dev/token", "/oauth/token"):   # HMAC / sandbox-only / RFC 6749 400
            continue
        url = path.replace("{claim_id}", "CLM-2024-1800").replace("{policy_id}", "POL-AU-08812") \
            .replace("{doc_id}", "DOC-2024-1800-FNOL-FORM").replace("{rec_id}", "REC-x")
        r = client.request(method, url, content=b"{not json")      # no token AND a malformed body
        assert r.status_code == 401, (method, path, r.status_code)  # never a 422 that leaks the schema
        assert "resource_metadata" in r.headers["www-authenticate"]


def test_dev_token_endpoint_is_absent_unless_the_sandbox_flag_is_set(app_and_tokens):
    client, _, _ = app_and_tokens
    assert client.post("/dev/token", json={"user_id": "alice"}).status_code == 404
