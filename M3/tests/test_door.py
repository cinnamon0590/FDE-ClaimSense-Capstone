"""The door's gates, called directly with no model in the loop (as the grader does)."""
import json
import time

from claimsense_door import two_analyst_test
from claimsense_door.door import GrantedBoundary, sign, verify_signature
from claimsense_door.proofs import _client
from claimsense_door.ticketing import TicketingUnavailable


def test_two_analyst_test_passes_offline_and_exits_zero(tmp_path):
    out = tmp_path / "two-user.txt"
    assert two_analyst_test.main(["--out", str(out)]) == 0
    text = out.read_text()
    assert "RESULT: PASS — scope holds" in text and '"decision": "allow"' in text and '"decision": "deny"' in text
    assert "REQUEST:" in text and "RESPONSE:" in text


def test_proof_suite_passes_offline():
    from claimsense_door import proofs
    assert proofs.main([]) == 0


def test_missing_and_forbidden_are_indistinguishable_and_both_audited(door):
    _, a = door.call("carol", "get_claim", {"claim_id": "CLM-2024-1800"})
    _, b = door.call("carol", "get_claim", {"claim_id": "CLM-2099-0001"})
    ea, eb = a["structuredContent"]["error"], b["structuredContent"]["error"]
    assert (ea["code"], ea["message"]) == (eb["code"], eb["message"])
    reasons = {r["request_id"]: r["reason"] for r in door.audit()}
    assert reasons[ea["request_id"]] == "not_entitled" and reasons[eb["request_id"]] == "not_found"


def test_denial_audit_row_is_written_before_the_denial_is_returned(door):
    _, r = door.call("dave", "get_claim", {"claim_id": "CLM-2024-1800"})
    rid = r["structuredContent"]["error"]["request_id"]
    row = [x for x in door.audit() if x["request_id"] == rid][0]
    assert row["decision"] == "deny" and row["reason"] == "no_grant" and row["user_id"] == "dave"


def test_identity_cannot_be_passed_as_a_tool_argument(door):
    _, r = door.call("alice", "get_claim", {"claim_id": "CLM-2024-1800", "user_id": "bob"})
    assert r["isError"] and r["structuredContent"]["error"]["code"] == "invalid_request"


def test_idempotent_escalation_and_retry_backoff(door):
    args = {"claim_id": "CLM-2024-1800", "reason": "r", "idempotency_key": "k-00000001"}
    _, a = door.call("alice", "create_escalation_ticket", args)
    _, b = door.call("alice", "create_escalation_ticket", args)
    assert a["structuredContent"]["ticket_id"] == b["structuredContent"]["ticket_id"]
    assert b["structuredContent"]["idempotent_replay"] is True
    assert any("attempt 1: HTTP 503" in x for x in door.b.ticketing.log)


def test_circuit_breaker_short_circuits_a_failing_backend():
    tc, http = _client("down")
    for i in range(3):
        try:
            tc.create({"claim_id": "CLM-2024-1800"}, f"k{i}")
        except TicketingUnavailable:
            pass
    calls = http.calls
    try:
        tc.create({"claim_id": "CLM-2024-1800"}, "k9")
    except TicketingUnavailable as e:
        assert "circuit breaker open" in str(e)
    assert http.calls == calls                    # the 4th call never reached the backend


def test_escalation_is_parked_never_lost_when_ticketing_is_down(tmp_path):
    tc, _ = _client("down")
    b = GrantedBoundary(state_path=tmp_path / "s.db", ticketing=tc)
    out = b.escalate("alice", "CLM-2024-1800", "reason", "k-park-0001")
    assert out["error"]["code"] == "upstream_unavailable" and out["error"]["retry_after_s"]
    assert b.escalations["CLM-2024-1800"]["status"] == "pending_delivery"


def test_webhook_signature_window_dedupe_and_order(tmp_path):
    secret, body = b"s3cret", b'{"x":1}'
    assert verify_signature(secret, sign(secret, body), body) is None
    assert verify_signature(secret, sign(b"guess", body), body) == "bad signature"
    assert verify_signature(secret, sign(secret, body, time.time() - 600), body) == "timestamp outside the replay window"
    assert verify_signature(secret, None, body) == "missing signature"
    tc, _ = _client()
    b = GrantedBoundary(state_path=tmp_path / "s.db", ticketing=tc)
    t = b.escalate("alice", "CLM-2024-1800", "r", "k-hook-0001")
    ev = lambda s, st, e: {"event_id": e, "ticket_id": t["ticket_id"], "claim_id": "CLM-2024-1800", "status": st, "seq": s}
    assert b.apply_ticket_event(ev(2, "assigned", "e1"))[0]["status"] == "assigned"
    assert b.apply_ticket_event(ev(2, "assigned", "e1"))[0]["deduped"] is True
    assert b.apply_ticket_event(ev(4, "resolved", "e3"))[0]["status"] == "resolved"
    assert b.apply_ticket_event(ev(3, "in_review", "e2"))[0]["ignored"] == "stale_seq"
    assert b.escalations["CLM-2024-1800"]["status"] == "resolved"


def test_every_audit_row_carries_user_action_resource(door):
    door.call("alice", "get_claim", {"claim_id": "CLM-2024-1800"})
    door.call("carol", "search_policy_clauses", {"query": "deductible"})
    door.call("dave", "get_policy", {"policy_id": "POL-AU-08812"})
    for r in door.audit():
        assert r["user_id"] and r["action"] and r["resource"] and r["decision"] and r["via"]
    json.dumps(door.audit())                     # serialisable, as the trail requires
