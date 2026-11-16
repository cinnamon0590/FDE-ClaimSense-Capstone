"""Tokens for scripts against the running stack: the dev issuer stands in for Cognito's hosted login (D-030)."""
import functools

import httpx

BOUNDARY = "http://localhost:8002"


@functools.lru_cache(maxsize=None)
def token(user):
    r = httpx.post(f"{BOUNDARY}/dev/token", json={"user_id": user}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def auth(user, **extra):
    """Headers for `user`: a signed ID token (the only identity the stack accepts) plus any extra headers."""
    return {"Authorization": f"Bearer {token(user)}"} | extra
