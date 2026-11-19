"""OBO via the IdP's OWN RFC 8693 exchange (Keycloak standard token exchange, D-041), offline: a throwaway RSA key
stands in for the realm's signing key, so CI needs no Keycloak. The live run is evals/keycloak_obo_check.py."""
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from claimsense.identity import IdentityError

ISS = "http://localhost:8180/realms/claimsense"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWKS = {"keys": [dict(json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())), kid="kc-1", alg="RS256")]}


def kc_token(user="alice", groups=("adjuster",), scope="get_claim search_policy_clauses profile", aud="claimsense-door",
             azp="claimsense-orchestrator", iss=ISS, ttl=300, key=KEY):
    now = int(time.time())
    return jwt.encode({"iss": iss, "aud": aud, "azp": azp, "sub": "6f1c-uuid", "preferred_username": user,
                       "groups": list(groups), "scope": scope, "iat": now, "exp": now + ttl, "typ": "Bearer"},
                      key, algorithm="RS256", headers={"kid": "kc-1"})


@pytest.fixture()
def idp():
    from claimsense_door.obo import IdPExchange
    return IdPExchange(ISS, jwks=JWKS)


@pytest.fixture()
def directory():
    return {"alice": {"groups": ["adjuster"]}, "carol": {"groups": ["fraud-investigator"]},
            "dave": {"groups": ["customer-service"]}}


def test_a_keycloak_exchanged_token_yields_the_user_its_narrowed_scope_and_the_agent(idp, directory):
    user, scope, actor = idp.verify(kc_token(), directory)
    assert (user, scope, actor) == ("alice", {"get_claim", "search_policy_clauses"}, "agent:claimsense-orchestrator")


def test_never_delegated_actions_are_dropped_even_if_the_idp_put_them_in_scope(idp, directory):
    _, scope, _ = idp.verify(kc_token(scope="get_claim confirm_recommendation read_audit ticket_webhook"), directory)
    assert scope == {"get_claim"}


@pytest.mark.parametrize("bad, why", [
    (dict(aud="claimsense-orchestrator"), "the sign-in token itself (not exchanged for the door)"),
    (dict(azp="claimsense-console"), "exchanged by a client that may not act for users"),
    (dict(iss="http://evil.example/realms/claimsense"), "another issuer"),
    (dict(groups=("senior-adjuster",)), "groups disagree with the directory"),
    (dict(user="mallory"), "user not in the directory"),
    (dict(ttl=-10), "expired"),
    (dict(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)), "forged signature"),
])
def test_anything_else_is_refused(idp, directory, bad, why):
    with pytest.raises(IdentityError):
        idp.verify(kc_token(**bad), directory)


def test_the_exchanged_tokens_scope_drives_authorize_and_the_audit(idp, door):
    """alice is GRANTED get_policy, but her exchanged token does not carry it: refused, and audited as such."""
    from claimsense_door.obo import TOKEN_ACTOR, TOKEN_SCOPE, resolve_principal
    b = door.b
    tok = kc_token(scope="get_claim")
    user = resolve_principal(f"Bearer {tok}", None, None, b.users, None, idp_exchange=idp)
    try:
        assert user == "alice" and TOKEN_SCOPE.get() == {"get_claim"}
        assert "claim_id" in b.claim(user, "CLM-2024-1800")
        out = b.policy(user, "POL-AU-10418")
        assert out["error"]["code"] == "not_found_or_forbidden"
        row = [r for r in b.audit if r["request_id"] == out["error"]["request_id"]][0]
        assert row["decision"] == "deny" and row["reason"] == "outside the delegated token's scope"
        assert row["on_behalf_of_agent"] == "agent:claimsense-orchestrator" and row["acting_identity"] == "alice"
    finally:
        TOKEN_SCOPE.set(None)
        TOKEN_ACTOR.set(None)
