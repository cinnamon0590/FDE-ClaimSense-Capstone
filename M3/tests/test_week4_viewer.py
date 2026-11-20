"""The Learning UI Viewer's Week 4 Integration checks (D-042), run offline with no model in the loop:
  * RBAC: an adjuster reads only the claims ASSIGNED to them; a senior adjuster reads every claim.
  * The two-user test in the viewer's shape: alice -> 403 on a claim not assigned to alice, bob -> 200 with full data.
  * Every call's audit row (user, action, resource) is also a CloudWatch-bound `AUDIT {json}` log line."""
import json

from claimsense_door.door import GrantedBoundary

BOB_CLAIM = "CLM-2024-5001"           # in the senior adjuster's queue (M1 fixtures/claim_assignments.json)


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_every_claim_has_one_owner_and_alice_owns_all_but_the_senior_queue():
    b = GrantedBoundary()
    assert set(b.adjuster_of) == set(b.claims)
    assert {c for c, who in b.adjuster_of.items() if who != "alice"} == {"CLM-2024-5001", "CLM-2024-5002"}


def test_an_adjuster_reads_only_their_assigned_claims_and_the_refusal_is_audited(door):
    _, r = door.call("alice", "get_claim", {"claim_id": BOB_CLAIM})
    err = r["structuredContent"]["error"]
    assert r["isError"] and err["code"] == "not_found_or_forbidden"
    row = [x for x in door.audit() if x["request_id"] == err["request_id"]][0]
    assert (row["user_id"], row["action"], row["resource"], row["decision"], row["reason"]) == \
           ("alice", "get_claim", BOB_CLAIM, "deny", "not_entitled")
    _, own = door.call("alice", "get_claim", {"claim_id": "CLM-2024-1800"})
    assert own["structuredContent"]["claim_id"] == "CLM-2024-1800"


def test_the_senior_adjuster_reads_the_same_claim_in_full(door):
    _, r = door.call("bob", "get_claim", {"claim_id": BOB_CLAIM})
    sc = r["structuredContent"]
    assert not r.get("isError") and sc["claim_id"] == BOB_CLAIM and sc["document_ids"] and sc["policy_id"]


def test_alice_keeps_every_claim_assigned_to_alice():
    b = GrantedBoundary()
    alice = b.caller("alice")
    mine = [c for c, who in b.adjuster_of.items() if who == "alice"]
    assert mine and all(b.entitled(alice, b.claims[c]) for c in mine)


def test_a_claim_with_no_assignment_is_denied_to_every_adjuster():
    b = GrantedBoundary()
    del b.adjuster_of["CLM-2024-1800"]
    assert not b.entitled(b.caller("alice"), b.claims["CLM-2024-1800"])
    assert b.entitled(b.caller("bob"), b.claims["CLM-2024-1800"])          # senior adjuster: every claim


def test_rest_returns_403_for_forbidden_and_missing_alike_and_200_for_bob(app_and_tokens):
    client, tok, _ = app_and_tokens
    forbidden = client.get(f"/claims/{BOB_CLAIM}", headers=H(tok("alice")))
    missing = client.get("/claims/CLM-2099-0001", headers=H(tok("alice")))
    assert forbidden.status_code == missing.status_code == 403
    fe, me = forbidden.json()["error"], missing.json()["error"]
    assert (fe["code"], fe["message"]) == (me["code"], me["message"]) == \
           ("not_found_or_forbidden", "No claim is available for this request.")
    ok = client.get(f"/claims/{BOB_CLAIM}", headers=H(tok("bob")))
    assert ok.status_code == 200 and ok.json()["claim_id"] == BOB_CLAIM


def test_mcp_keeps_json_rpc_semantics_for_a_refusal(app_and_tokens):
    client, tok, _ = app_and_tokens
    r = client.post("/mcp", headers=H(tok("alice")), json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                            "params": {"name": "get_claim",
                                                                       "arguments": {"claim_id": BOB_CLAIM}}})
    assert r.status_code == 200 and r.json()["result"]["isError"] is True


def test_every_audit_row_is_also_a_cloudwatch_log_line(monkeypatch, capsys, tmp_path):
    from claimsense import audit_trail
    monkeypatch.setenv("CLAIMSENSE_AUDIT_STDOUT", "1")
    rid = audit_trail.append(audit_trail.row("alice", ["adjuster"], "get_claim", BOB_CLAIM, "deny", "not_entitled"),
                             path=tmp_path / "a.jsonl")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("AUDIT ")]
    rec = json.loads(lines[-1][len("AUDIT "):])
    assert (rec["request_id"], rec["user_id"], rec["action"], rec["resource"], rec["decision"]) == \
           (rid, "alice", "get_claim", BOB_CLAIM, "deny")


def test_the_echo_is_on_by_default_only_on_aws_and_can_be_switched_off(monkeypatch):
    from claimsense import audit_trail
    monkeypatch.delenv("CLAIMSENSE_AUDIT_STDOUT", raising=False)
    assert audit_trail._echo("claimsense-audit") and not audit_trail._echo(None)
    monkeypatch.setenv("CLAIMSENSE_AUDIT_STDOUT", "0")
    assert not audit_trail._echo("claimsense-audit")


def test_the_viewer_shaped_two_user_test_passes_offline(tmp_path):
    from claimsense_door import two_analyst_test
    out = tmp_path / "viewer.txt"
    assert two_analyst_test.main(["--viewer", "--out", str(out)]) == 0
    text = out.read_text()
    assert text.index("User B: alice") < text.index("User A: bob")              # alice asks first, as in the viewer
    assert "403 DENIED — alice may not access CLM-2024-5001" in text and "RESULT: PASS — scope holds" in text
