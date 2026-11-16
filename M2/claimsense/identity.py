"""Who is calling: a signed JWT, never a form field or a bare header (D-030).

Tokens are Cognito-shaped ID tokens (RS256; claims `cognito:username`, `cognito:groups`, `iss`, `aud`,
`token_use`, `exp`), so M3 swaps the issuer for the Cognito user pool M1 provisioned without touching any
verifier. Until then a local DEV ISSUER stands in for Cognito's hosted login: an RSA key pair on the /state
volume, a JWKS endpoint, and a mint endpoint that only exists when CLAIMSENSE_DEV_ISSUER=1 (synthetic sandbox).

Verification rules (fail closed):
  * RS256 only, signature checked against the issuer's JWKS; `alg: none` and HS256 key-confusion are refused
  * issuer, audience, `token_use=id` and expiry are required and checked
  * the user must exist in the directory, and the token's groups must equal the directory's groups, so a
    stale or tampered group claim can never widen access (group = role = entitlement, decided server-side)
A bare `X-User-Id` header is accepted ONLY when CLAIMSENSE_ALLOW_HEADER_IDENTITY=1 (unit tests, the in-process
pipeline); the running containers require a token.
"""
import json
import os
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from . import config

ISSUER = os.environ.get("CLAIMSENSE_JWT_ISSUER", "https://claimsense.local/dev-issuer")   # M3: Cognito pool URL
AUDIENCE = os.environ.get("CLAIMSENSE_JWT_AUDIENCE", "claimsense-console")                # M3: app client id
TOKEN_TTL_S = int(os.environ.get("CLAIMSENSE_JWT_TTL_S", "3600"))
KID = "claimsense-dev-1"


def header_identity_allowed():
    return os.environ.get("CLAIMSENSE_ALLOW_HEADER_IDENTITY", "0") == "1"


class IdentityError(Exception):
    """Raised for any identity failure; the message is safe to log, never echoed with token contents."""


class DevIssuer:
    """Local stand-in for Cognito: an RSA key pair persisted on the state volume (private key 0600)."""

    def __init__(self, key_dir=None):
        self.dir = Path(key_dir or config.STATE_DIR / "dev-issuer")
        self.dir.mkdir(parents=True, exist_ok=True)
        priv = self.dir / "private.pem"
        if not priv.exists():
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            priv.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
            os.chmod(priv, 0o600)
        self._key = serialization.load_pem_private_key(priv.read_bytes(), password=None)

    def mint(self, user_id, groups, ttl=TOKEN_TTL_S):
        now = int(time.time())
        claims = {"sub": f"dev-{user_id}", "cognito:username": user_id, "cognito:groups": sorted(groups),
                  "iss": ISSUER, "aud": AUDIENCE, "token_use": "id", "iat": now, "exp": now + ttl}
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": KID})

    def jwks(self):
        pub = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        return {"keys": [dict(pub, kid=KID, alg="RS256", use="sig")]}


class Verifier:
    """Verifies tokens against a JWKS (a dict, or fetched from a URL like Cognito's /.well-known/jwks.json)."""

    def __init__(self, jwks=None, jwks_url=None):
        self._jwks, self._client = jwks, (jwt.PyJWKClient(jwks_url, cache_keys=True) if jwks_url else None)

    def _key(self, token):
        if self._client:
            return self._client.get_signing_key_from_jwt(token).key
        kid = jwt.get_unverified_header(token).get("kid")
        for k in self._jwks["keys"]:
            if k.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k))
        raise IdentityError("unknown signing key")

    def claims(self, token):
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise IdentityError("only RS256 tokens are accepted")
            c = jwt.decode(token, self._key(token), algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER,
                           options={"require": ["exp", "iss", "aud", "cognito:username"]})
        except IdentityError:
            raise
        except jwt.PyJWTError as e:
            raise IdentityError(f"invalid token: {type(e).__name__}") from None
        if c.get("token_use") != "id":
            raise IdentityError("not an ID token")
        return c


def resolve(authorization, x_user_id, verifier, directory):
    """Return the caller's user id. `directory` maps user_id -> {"groups": [...]}. Raises IdentityError."""
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise IdentityError("Authorization must be 'Bearer <token>'")
        c = verifier.claims(token.strip())
        user = c["cognito:username"]
        if user not in directory:
            raise IdentityError("token user is not in the directory")
        if sorted(c.get("cognito:groups", [])) != sorted(directory[user]["groups"]):
            raise IdentityError("token groups do not match the directory (stale or tampered token)")
        return user
    if x_user_id and header_identity_allowed():
        return x_user_id
    raise IdentityError("authentication required")
