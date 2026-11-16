"""The data boundary (MCP-style single door), local twin of the M3 API Gateway + Lambda service.

Wraps the M1 reference boundary (entitlement before data, identical errors for missing/forbidden,
append-only audit including denials, idempotent writes, human-only confirmation) and sources its
records from the mock systems. Identity arrives as X-User-Id today; M3 replaces it with a verified
Cognito JWT and keeps every rule below unchanged.
"""
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from claimsense.boundary_client import LocalBoundary
from claimsense.identity import TOKEN_TTL_S, DevIssuer, IdentityError, Verifier, resolve

SYSTEMS = os.environ.get("SYSTEMS_URL", "http://mock-systems:8001")
AUDIT_LOG = Path(os.environ.get("AUDIT_LOG", "/state/audit.jsonl"))
STATE_DB = Path(os.environ.get("BOUNDARY_STATE", str(AUDIT_LOG.parent / "boundary.db")))


class SourcedBoundary(LocalBoundary):
    def __init__(self, url):
        for attempt in range(30):
            try:
                get = lambda p: httpx.get(f"{url}{p}", timeout=5).json()["records"]
                self.claims = {c["claim_id"]: c for c in get("/claims-management/claims")}
                self.policies = {p["policy_id"]: p for p in get("/policy-administration/policies")}
                self.documents = {d["doc_id"]: d for d in get("/document-store/documents")}
                self.users = {u["user_id"]: u for u in get("/directory/users")}
                break
            except (httpx.HTTPError, KeyError):
                time.sleep(1)
        else:
            raise RuntimeError(f"mock systems unreachable at {url}")
        # restart-survivable state on the /state volume (D-027): drafts + idempotency in SQLite, audit reloaded
        self.persist(STATE_DB)
        self.audit = [json.loads(line) for line in AUDIT_LOG.read_text().splitlines() if line.strip()] \
            if AUDIT_LOG.exists() else []

    def _audit(self, *a, **kw):
        rid = super()._audit(*a, **kw)
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(self.audit[-1]) + "\n")
        return rid


B = SourcedBoundary(SYSTEMS)
app = FastAPI(title="ClaimSense data boundary")

# ── identity (D-030): the caller comes from a verified JWT; groups are the directory's, never the client's ─────
DEV_ISSUER_ON = os.environ.get("CLAIMSENSE_DEV_ISSUER", "0") == "1"      # stand-in for Cognito hosted login
ISSUER = DevIssuer(AUDIT_LOG.parent / "dev-issuer")
VERIFIER = Verifier(jwks_url=os.environ["COGNITO_JWKS_URL"]) if os.environ.get("COGNITO_JWKS_URL") \
    else Verifier(jwks=ISSUER.jwks())


class Unauthenticated(Exception):
    pass


@app.exception_handler(Unauthenticated)
async def _unauthenticated(request, exc):
    rid = B._audit({"user_id": "anonymous", "groups": []}, "authenticate", request.url.path, "deny", str(exc))
    return JSONResponse(B._error("unauthenticated", "A valid ClaimSense token is required.", rid), status_code=401)


def caller_id(authorization: str | None = Header(None), x_user_id: str | None = Header(None)) -> str:
    try:
        return resolve(authorization, x_user_id, VERIFIER, B.users)
    except IdentityError as e:
        raise Unauthenticated(str(e)) from None


@app.get("/.well-known/jwks.json")
def jwks():
    """Public keys for verifying ClaimSense tokens (Cognito publishes the same document; M3 points here)."""
    return ISSUER.jwks()


@app.post("/dev/token")
async def dev_token(request: Request):
    """DEV ONLY (CLAIMSENSE_DEV_ISSUER=1): mint a synthetic user's ID token, standing in for Cognito's hosted
    login on the synthetic sandbox. Groups always come from the directory. Absent in any other deployment."""
    if not DEV_ISSUER_ON:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    body = await _json_object(request) or {}
    user = body.get("user_id")
    if user not in B.users:
        return JSONResponse(B._error("not_found_or_forbidden", "No such user.", "-"), status_code=404)
    groups = B.users[user]["groups"]
    B._audit({"user_id": user, "groups": groups}, "mint_dev_token", user, "allow", "dev issuer")
    return {"token": ISSUER.mint(user, groups), "user_id": user, "groups": groups, "expires_in": TOKEN_TTL_S,
            "issuer": "dev issuer (stand-in for Cognito hosted login)"}


@app.get("/healthz")
def healthz():
    return {"ok": True, "claims": len(B.claims), "audit_rows": len(B.audit)}


@app.get("/claims/{claim_id}")
def claim(claim_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return B.claim(x_user_id, claim_id, x_on_behalf_of_agent)


@app.get("/policies/{policy_id}")
def policy(policy_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return B.policy(x_user_id, policy_id, x_on_behalf_of_agent)


@app.get("/claims/{claim_id}/documents")
def documents(claim_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return B.documents_for(x_user_id, claim_id, x_on_behalf_of_agent)


@app.get("/documents/{doc_id}")
def document(doc_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return B.document(x_user_id, doc_id, x_on_behalf_of_agent)


async def _json_object(request):
    """The request body as a dict, or None when it is missing or not a JSON object (answered with a 400,
    never a crash)."""
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _bad_request(caller_id, action, target, message):
    rid = B._audit(B.caller(caller_id), action, target, "error", "invalid_request")
    return JSONResponse(B._error("invalid_request", message, rid), status_code=400)


@app.post("/claims/{claim_id}/recommendations")
async def recommend(claim_id: str, request: Request, x_user_id: str = Depends(caller_id), idempotency_key: str = Header(),
                    x_on_behalf_of_agent: str = Header("agent:decision-draft")):
    body = await _json_object(request)
    if body is None or not isinstance(body.get("decision_card"), dict):
        return _bad_request(x_user_id, "post_recommendation", claim_id, "Body must be a JSON object with a decision_card.")
    return B.recommend(x_user_id, claim_id, body["decision_card"], idempotency_key, x_on_behalf_of_agent)


@app.post("/recommendations/{rec_id}/confirm")
async def confirm(rec_id: str, request: Request, x_user_id: str = Depends(caller_id), idempotency_key: str = Header(),
                  x_on_behalf_of_agent: str | None = Header(None)):
    body = await _json_object(request)
    if body is None or body.get("action") not in ("confirm", "override"):
        return _bad_request(x_user_id, "confirm_recommendation", rec_id, 'Body must be {"action": "confirm" | "override", ...}.')
    return B.confirm(x_user_id, dict(body, recommendation_id=rec_id, idempotency_key=idempotency_key),
                     agent=x_on_behalf_of_agent)


@app.get("/recommendations")
def pending(x_user_id: str = Depends(caller_id), status: str = "pending"):
    """The adjuster queue: undecided drafts on claims the caller is entitled to."""
    if status != "pending":
        return _bad_request(x_user_id, "list_pending_recommendations", "queue", "Only status=pending is supported.")
    return B.pending(x_user_id)


@app.get("/claims/{claim_id}/recommendations/latest")
def latest(claim_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return B.draft(x_user_id, claim_id, x_on_behalf_of_agent)


@app.get("/audit")
def audit(x_user_id: str = Depends(caller_id), limit: int = 50):
    caller = B.caller(x_user_id)
    if "senior-adjuster" not in caller["groups"]:
        B._audit(caller, "read_audit", "audit", "deny", "senior-adjuster only")
        return B._error("not_found_or_forbidden", "No audit view is available for this request.", "-")
    return {"rows": B.audit[-limit:]}
