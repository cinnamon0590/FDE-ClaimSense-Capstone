"""RBAC (D-030): role decides access; a confirmed route hands the claim to the specialist group; identity comes
from a verified JWT whose groups must match the directory. Mirrors the reference UI's examples:
CLM-2024-1800 alice·adjuster · 1873 carol·fraud-investigator · 1946 eve·total-loss-appraiser · 2019 bob·senior-adjuster."""
import importlib.util
import json
import time
import uuid
from pathlib import Path

import jwt
import pytest

from claimsense import identity as I
from claimsense.boundary_client import LocalBoundary
from claimsense.pipeline import run_claim

M2 = Path(__file__).resolve().parents[1]
REFERENCE = {"CLM-2024-1800": "alice", "CLM-2024-1873": "carol", "CLM-2024-1946": "eve", "CLM-2024-2019": "bob"}
USERS = ["alice", "bob", "carol", "eve", "dave"]


def first_pass(b, claim_id, action=None):
    """alice runs the co-pilot and a HUMAN (alice) confirms the draft, as in the console."""
    card = run_claim(claim_id, "alice", brain="replay")["response"]
    rec = b.recommend("alice", claim_id, card, f"draft-{claim_id}")
    return b.confirm("alice", dict(action or {"action": "confirm"}, recommendation_id=rec["recommendation_id"],
                                   idempotency_key=f"confirm-{claim_id}"))


def matrix(b):
    return {u: {c: b.entitled(b.caller(u), b.claims[c]) for c in REFERENCE} for u in USERS}


def test_routing_hands_each_claim_to_the_reference_ui_specialist(tmp_path):
    b = LocalBoundary(tmp_path / "boundary.db")
    before = matrix(b)
    assert not before["carol"]["CLM-2024-1873"] and not before["eve"]["CLM-2024-1946"]   # the gap this fixes
    receipts = {c: first_pass(b, c) for c in REFERENCE}
    assert receipts["CLM-2024-1873"]["handed_off"] == {"claim_id": "CLM-2024-1873", "from": "adjuster",
                                                       "to": "fraud-investigator"}
    assert receipts["CLM-2024-1946"]["handed_off"]["to"] == "total-loss-appraiser"
    assert receipts["CLM-2024-2019"]["handed_off"]["to"] == "senior-adjuster"
    assert "handed_off" not in receipts["CLM-2024-1800"]                                   # approve stays put
    after = matrix(b)
    for claim, user in REFERENCE.items():
        assert after[user][claim], f"{user} must reach {claim}"                            # every reference pairing
    assert not after["alice"]["CLM-2024-1873"] and not after["alice"]["CLM-2024-1946"]      # least privilege
    assert not after["carol"]["CLM-2024-1800"]                                              # CS-038
    assert not any(after["dave"].values())                                                  # customer service: none
    assert all(after["bob"].values())                                                       # senior: all
    assert [a["reason"] for a in b.audit if a["action"] == "reassign_claim"] == [
        "adjuster -> fraud-investigator (confirmed route)", "adjuster -> total-loss-appraiser (confirmed route)",
        "adjuster -> senior-adjuster (confirmed flag_review)"]
    restarted = LocalBoundary(tmp_path / "boundary.db")                                    # survives a restart
    assert matrix(restarted) == after


def test_an_override_to_route_hands_off_to_the_override_target(tmp_path):
    b = LocalBoundary(tmp_path / "boundary.db")
    out = first_pass(b, "CLM-2024-1800", {"action": "override", "final_outcome": "route",
                                          "route_to": "fraud-investigator", "override_reason": "SIU tip-off"})
    assert out["handed_off"]["to"] == "fraud-investigator"
    assert b.entitled(b.caller("carol"), b.claims["CLM-2024-1800"])


def test_the_deciders_resubmit_still_replays_after_the_claim_moved_away(tmp_path):
    b = LocalBoundary(tmp_path / "boundary.db")
    first = first_pass(b, "CLM-2024-1946")
    rid = first["recommendation_id"]
    again = b.confirm("alice", {"recommendation_id": rid, "action": "confirm", "idempotency_key": "confirm-CLM-2024-1946"})
    assert again["idempotent_replay"] is True and again["confirmed_at"] == first["confirmed_at"]
    assert b.claim("alice", "CLM-2024-1946")["error"]["code"] == "not_found_or_forbidden"   # but no new access


# ── identity: a verified token, groups from the directory ────────────────────────────────────────────────
@pytest.fixture
def issuer(tmp_path):
    return I.DevIssuer(tmp_path / "keys")


def _directory():
    return LocalBoundary().users


def test_a_valid_token_identifies_the_user(issuer):
    tok = issuer.mint("carol", ["fraud-investigator"])
    assert I.resolve(f"Bearer {tok}", None, I.Verifier(jwks=issuer.jwks()), _directory()) == "carol"


@pytest.mark.parametrize("label, make", [
    ("self-promoted group", lambda iss: iss.mint("alice", ["senior-adjuster"])),
    ("expired", lambda iss: iss.mint("alice", ["adjuster"], ttl=-60)),
    ("unknown user", lambda iss: iss.mint("mallory", ["senior-adjuster"])),
    ("alg none", lambda iss: jwt.encode({"cognito:username": "bob", "cognito:groups": ["senior-adjuster"],
                                         "iss": I.ISSUER, "aud": I.AUDIENCE, "token_use": "id",
                                         "exp": int(time.time()) + 600}, None, algorithm="none")),
    ("wrong audience", lambda iss: jwt.encode({"cognito:username": "alice", "cognito:groups": ["adjuster"],
                                               "iss": I.ISSUER, "aud": "someone-else", "token_use": "id",
                                               "exp": int(time.time()) + 600}, iss._key, algorithm="RS256",
                                              headers={"kid": I.KID})),
    ("signed by another key", lambda iss: I.DevIssuer(Path(iss.dir).parent / "other").mint("bob", ["senior-adjuster"])),
])
def test_forged_or_stale_tokens_are_refused(issuer, label, make):
    with pytest.raises(I.IdentityError):
        I.resolve(f"Bearer {make(issuer)}", None, I.Verifier(jwks=issuer.jwks()), _directory())


def test_without_a_token_nobody_gets_in_unless_header_identity_is_explicitly_allowed(issuer, monkeypatch):
    v = I.Verifier(jwks=issuer.jwks())
    monkeypatch.setenv("CLAIMSENSE_ALLOW_HEADER_IDENTITY", "0")
    with pytest.raises(I.IdentityError):
        I.resolve(None, "bob", v, _directory())                    # a bare header claiming to be bob
    monkeypatch.setenv("CLAIMSENSE_ALLOW_HEADER_IDENTITY", "1")
    assert I.resolve(None, "bob", v, _directory()) == "bob"


def test_the_orchestrator_takes_identity_from_the_token_and_never_acts_as_someone_else(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CLAIMSENSE_ALLOW_HEADER_IDENTITY", "0")
    spec = importlib.util.spec_from_file_location("orch_rbac", M2 / "services" / "orchestrator" / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    c = TestClient(app.app)
    alice = {"Authorization": f"Bearer {I.DevIssuer().mint('alice', ['adjuster'])}"}
    assert c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "bob"}).status_code == 401      # no token
    assert c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "bob"}, headers=alice).status_code == 403
    ok = c.post("/claims/CLM-2024-1800/recommend", json={}, headers=alice).json()
    assert ok["user_id"] == "alice" and ok["response"]["outcome"] == "approve"
    assert c.get("/claims/CLM-2024-1800/ask/history", params={"user_id": "alice"}).status_code == 401
