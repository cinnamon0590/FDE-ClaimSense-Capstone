"""OAuth 2.0 Token Exchange (RFC 8693), the on-behalf-of borrow (M3 Architect tier, D-039).

The adjuster signs in at the IdP (Cognito on AWS; the dev issuer locally) and gets an ID token. The orchestrator
never hands that token to the agents' tool calls. Instead it EXCHANGES it at the door's token endpoint:

    POST /oauth/token
      grant_type=urn:ietf:params:oauth:grant-type:token-exchange
      subject_token=<the adjuster's ID token>   subject_token_type=urn:ietf:params:oauth:token-type:id_token
      actor=agent:claimsense-pipeline          scope=<the actions the agent needs>   audience=claimsense-door

and gets back a DELEGATED access token: 5 minutes, audience = the door, `sub` = the adjuster (so every call is still
the adjuster's, under the adjuster's grants and entitlement), `act` = the agent (RFC 8693 §4.1, so the audit names
both), and `scope` = the requested actions ∩ the adjuster's grants, minus anything an agent may never do (confirm,
read the audit trail). `_authorize` then enforces BOTH: the role's grants AND the token's scope. Revoke the adjuster
and the exchange fails; the agent never holds a standing credential, or the adjuster's own login token.
"""
import contextvars
import json
import os
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from claimsense.identity import IdentityError, resolve

from .grants import granted

GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
STS_ISSUER = os.environ.get("CLAIMSENSE_STS_ISSUER", "https://claimsense.local/door-sts")
AUDIENCE = "claimsense-door"
TTL_S = int(os.environ.get("CLAIMSENSE_OBO_TTL_S", "300"))
KID = "claimsense-door-sts-1"
NEVER_DELEGATED = {"confirm_recommendation", "read_audit", "ticket_webhook"}   # human-only or system-only
AGENT_SCOPE = ("get_claim get_policy list_documents get_document search_policy_clauses post_recommendation "
               "get_latest_draft create_escalation_ticket get_escalation")

# set per request by resolve_principal(); read by the door's _authorize and _audit
TOKEN_SCOPE: contextvars.ContextVar = contextvars.ContextVar("claimsense_token_scope", default=None)
TOKEN_ACTOR: contextvars.ContextVar = contextvars.ContextVar("claimsense_token_actor", default=None)


class TokenService:
    """The door's own signing key (0600 on the state volume; Secrets Manager/KMS on AWS) and the exchange rules."""

    def __init__(self, key_dir):
        d = Path(key_dir)
        d.mkdir(parents=True, exist_ok=True)
        priv = d / "sts-private.pem"
        if not priv.exists():
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            try:
                fd = os.open(priv, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
            except FileExistsError:
                pass
        self._key = serialization.load_pem_private_key(priv.read_bytes(), password=None)
        self._pub = self._key.public_key()

    def exchange(self, subject_token, actor, scope, idp_verifier, directory):
        """Returns the RFC 8693 response dict, or raises IdentityError (the caller turns it into invalid_grant)."""
        user = resolve(f"Bearer {subject_token}", None, idp_verifier, directory)     # a real, current IdP token
        if not isinstance(actor, str) or not actor.startswith("agent:"):
            raise IdentityError("actor must be an agent identity (agent:...)")
        groups = directory[user]["groups"]
        caller = {"user_id": user, "groups": groups}
        wanted = set((scope or AGENT_SCOPE).split())
        effective = sorted(a for a in wanted if granted(caller, a) and a not in NEVER_DELEGATED)
        if not effective:
            raise IdentityError("no delegable scope for this user")
        now = int(time.time())
        token = jwt.encode({"iss": STS_ISSUER, "aud": AUDIENCE, "sub": user, "username": user, "groups": sorted(groups),
                            "act": {"sub": actor}, "scope": " ".join(effective), "token_use": "access",
                            "iat": now, "exp": now + TTL_S}, self._key, algorithm="RS256", headers={"kid": KID})
        return {"access_token": token, "issued_token_type": ACCESS_TOKEN_TYPE, "token_type": "Bearer",
                "expires_in": TTL_S, "scope": " ".join(effective)}

    def verify(self, token):
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise IdentityError("only RS256 tokens are accepted")
            c = jwt.decode(token, self._pub, algorithms=["RS256"], audience=AUDIENCE, issuer=STS_ISSUER,
                           options={"require": ["exp", "iss", "aud", "sub", "act", "scope"]})
        except jwt.PyJWTError as e:
            raise IdentityError(f"invalid delegated token: {type(e).__name__}") from None
        if c.get("token_use") != "access":
            raise IdentityError("not a delegated access token")
        return c

    def jwks(self):
        pub = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._pub))
        return {"keys": [dict(pub, kid=KID, alg="RS256", use="sig")]}


class IdPExchange:
    """Trust delegated tokens minted by the IdP's OWN RFC 8693 exchange (Keycloak's standard token exchange, D-041).

    The orchestrator (a Keycloak client allowed to exchange) trades the adjuster's sign-in access token for one whose
    audience is the door and whose scope is the actions it asked for. The door accepts such a token only if: it is
    RS256 and signed by the IdP's JWKS; `iss` is the configured realm; `aud` is the door; `azp` (the client that did
    the exchange, i.e. the agent) is on the allow-list; and the user and groups still match the directory. Its
    `scope`, narrowed to delegable action names, then drives `_authorize` exactly like a door-minted token.
    """

    def __init__(self, issuer, jwks=None, jwks_url=None, clients=("claimsense-orchestrator",), audience=AUDIENCE):
        self.issuer, self.audience, self.clients = issuer.rstrip("/"), audience, set(clients)
        self._jwks, self._client = jwks, (jwt.PyJWKClient(jwks_url, cache_keys=True) if jwks_url else None)

    @classmethod
    def from_env(cls):
        iss = os.environ.get("CLAIMSENSE_EXCHANGE_ISSUER")
        if not iss:
            return None
        return cls(iss, jwks_url=os.environ.get("CLAIMSENSE_EXCHANGE_JWKS_URL") or f"{iss.rstrip('/')}/protocol/"
                   "openid-connect/certs", clients=os.environ.get("CLAIMSENSE_EXCHANGE_CLIENTS",
                                                                   "claimsense-orchestrator").split(","))

    def _key(self, token):
        if self._client:
            return self._client.get_signing_key_from_jwt(token).key
        kid = jwt.get_unverified_header(token).get("kid")
        for k in self._jwks["keys"]:
            if k.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
        raise IdentityError("unknown signing key")

    def verify(self, token, directory):
        """-> (user, scope set, actor). Raises IdentityError."""
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise IdentityError("only RS256 tokens are accepted")
            c = jwt.decode(token, self._key(token), algorithms=["RS256"], audience=self.audience, issuer=self.issuer,
                           options={"require": ["exp", "iss", "aud", "azp", "scope", "preferred_username"]})
        except IdentityError:
            raise
        except jwt.PyJWTError as e:
            raise IdentityError(f"invalid exchanged token: {type(e).__name__}") from None
        if c["azp"] not in self.clients:
            raise IdentityError("exchanged by a client that may not act for users")
        user = c["preferred_username"]
        if user not in directory or sorted(c.get("groups", [])) != sorted(directory[user]["groups"]):
            raise IdentityError("exchanged token user/groups do not match the directory")
        known = set(AGENT_SCOPE.split())
        scope = {a for a in c["scope"].split() if a in known and a not in NEVER_DELEGATED}
        return user, scope, f"agent:{c['azp']}"


_IDP_EXCHANGE = IdPExchange.from_env()


def resolve_principal(authorization, x_user_id, idp_verifier, directory, sts=None, idp_exchange=None):
    """The user for this request, from EITHER an IdP ID token (the adjuster, e.g. the console) OR a door-issued
    delegated token (an agent acting for the adjuster). Sets TOKEN_SCOPE / TOKEN_ACTOR for the gates and the audit."""
    TOKEN_SCOPE.set(None)
    TOKEN_ACTOR.set(None)
    if (sts or idp_exchange or _IDP_EXCHANGE) and authorization:
        scheme, _, tok = authorization.partition(" ")
        if scheme.lower() == "bearer" and tok:
            try:
                iss = jwt.decode(tok.strip(), options={"verify_signature": False}).get("iss")
            except jwt.PyJWTError:
                iss = None
            idp = idp_exchange or _IDP_EXCHANGE
            if idp is not None and iss == idp.issuer:
                user, scope, actor = idp.verify(tok.strip(), directory)
                TOKEN_SCOPE.set(scope)
                TOKEN_ACTOR.set(actor)
                return user
            if sts and iss == STS_ISSUER:
                c = sts.verify(tok.strip())
                user = c["sub"]
                if user not in directory or sorted(c.get("groups", [])) != sorted(directory[user]["groups"]):
                    raise IdentityError("delegated token user/groups no longer match the directory")
                TOKEN_SCOPE.set(set(c["scope"].split()))
                TOKEN_ACTOR.set(c["act"]["sub"])
                return user
    return resolve(authorization, x_user_id, idp_verifier, directory)
