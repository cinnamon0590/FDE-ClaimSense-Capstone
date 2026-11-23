"""The data boundary: ClaimSense's ONE governed door to AutoSure's systems of record (M3, D-036).

Two protocols, one door, one set of rules:
  * REST (this file): the adjuster console and the orchestrator's human-facing paths
  * MCP  (claimsense_door.http, mounted at /mcp): the agents' tools, spec 2025-06-18, OAuth 2.1 resource server
Behind both: GrantedBoundary (M3/door): explicit grants (deny-by-default) -> the M1 entitlement rule -> data, an
append-only audit row on EVERY call (allow, deny, replay, error, unauthenticated), identical answers for missing and
forbidden records, idempotent writes, human-only confirmation. Identity is a verified JWT (D-030; Cognito on AWS).
Records come from the mock systems of record; escalations go to the SIU ticketing system (the 4th backend), whose
status changes arrive as signed webhooks.
"""
import json
import os
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from claimsense import audit_trail, doc_store, metrics
from claimsense.identity import TOKEN_TTL_S, DevIssuer, IdentityError, Verifier, resolve
from claimsense_door.door import GrantedBoundary, shared_secret
from claimsense_door.http import build_router
from claimsense_door.obo import TokenService, resolve_principal
from claimsense_door.ticketing import TicketingClient

SYSTEMS = os.environ.get("SYSTEMS_URL", "http://mock-systems:8001")
AUDIT_LOG = Path(os.environ.get("AUDIT_LOG", "/state/audit.jsonl"))
os.environ.setdefault("AUDIT_LOG", str(AUDIT_LOG))
STATE_DB = Path(os.environ.get("BOUNDARY_STATE", str(AUDIT_LOG.parent / "boundary.db")))
TICKETING = os.environ.get("TICKETING_URL", "")


class SourcedBoundary(GrantedBoundary):
    """GrantedBoundary whose records come from the mock systems of record (SYSTEMS_URL=local: the image's own
    synthetic fixtures, for a self-contained Lambda deployment)."""

    def __init__(self, url):
        self.escalations, self.webhook_events, self.recommendations, self._idem = {}, {}, {}, {}
        if url == "local":
            super().__init__(None)                     # the reference loader: fixtures baked into the image
            # on AWS the Document Store and policy records live in S3 (D-044); claims, users and assignments stay
            # with Claims Management (the image's fixtures)
            if (pol := doc_store.load("policies")) is not None:
                self.policies = {p["policy_id"]: p for p in pol["records"]}
            if (docs := doc_store.load("documents")) is not None:
                self.documents = {d["doc_id"]: d for d in docs["records"]}
        else:
            for attempt in range(30):
                try:
                    get = lambda p: httpx.get(f"{url}{p}", timeout=5).json()["records"]
                    self.claims = {c["claim_id"]: c for c in get("/claims-management/claims")}
                    self.policies = {p["policy_id"]: p for p in get("/policy-administration/policies")}
                    self.documents = {d["doc_id"]: d for d in get("/document-store/documents")}
                    self.users = {u["user_id"]: u for u in get("/directory/users")}
                    self.adjuster_of = {a["claim_id"]: a["assigned_adjuster"]
                                        for a in get("/claims-management/assignments")}
                    break
                except (httpx.HTTPError, KeyError):
                    time.sleep(1)
            else:
                raise RuntimeError(f"mock systems unreachable at {url}")
        # restart-survivable state (D-027): drafts, idempotency, hand-offs, escalations, webhook dedupe in SQLite
        self.persist(STATE_DB)
        self.audit = audit_trail.read()                # the shared append-only trail, reloaded
        self.ticketing = TicketingClient(TICKETING, lambda: shared_secret("ticketing_api")) if TICKETING else None
        self._clause_index = None
        from claimsense_door.slack import SlackNotifier, transport_from_env
        t, mode = transport_from_env()                 # mock unless M3/.slack.env provides a token or webhook
        self.slack = SlackNotifier(self, t, mode)


B = SourcedBoundary(SYSTEMS)
app = FastAPI(title="ClaimSense data boundary (the governed door)")

# ── identity (D-030): the caller comes from a verified JWT; groups are the directory's, never the client's ─────
DEV_ISSUER_ON = os.environ.get("CLAIMSENSE_DEV_ISSUER", "0") == "1"      # stand-in for Cognito hosted login
ISSUER = DevIssuer(AUDIT_LOG.parent / "dev-issuer")
VERIFIER = Verifier(jwks_url=os.environ["COGNITO_JWKS_URL"]) if os.environ.get("COGNITO_JWKS_URL") \
    else Verifier(jwks=ISSUER.jwks())
STS = TokenService(Path(os.environ.get("CLAIMSENSE_STS_KEYS", str(AUDIT_LOG.parent / "door-sts"))))  # OBO (D-039)

# Every route and what it is (D-2: "authorisation on every route"). tests/test_route_auth.py fails the build if a
# route exists that is not listed here, or if a "public" route is anything but health, keys, or discovery metadata.
PUBLIC = {"/healthz", "/.well-known/jwks.json", "/.well-known/oauth-protected-resource",
          "/.well-known/oauth-protected-resource/mcp", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
ROUTE_ACTIONS = {
    ("GET", "/claims/{claim_id}"): "get_claim",
    ("GET", "/policies/{policy_id}"): "get_policy",
    ("GET", "/claims/{claim_id}/documents"): "list_documents",
    ("GET", "/documents/{doc_id}"): "get_document",
    ("GET", "/policy-kb/search"): "search_policy_clauses",
    ("POST", "/claims/{claim_id}/recommendations"): "post_recommendation",
    ("POST", "/recommendations/{rec_id}/confirm"): "confirm_recommendation",
    ("GET", "/recommendations"): "list_pending_recommendations",
    ("GET", "/claims/{claim_id}/recommendations/latest"): "get_latest_draft",
    ("POST", "/claims/{claim_id}/escalations"): "create_escalation_ticket",
    ("GET", "/claims/{claim_id}/escalation"): "get_escalation",
    ("POST", "/claims/{claim_id}/oncall"): "notify_oncall",
    ("GET", "/audit"): "read_audit",
    ("POST", "/mcp"): "mcp (per tool: see claimsense_door.mcp.TOOL_ACTION)",
    ("GET", "/mcp"): "405 (no server-initiated stream)",
    ("POST", "/webhooks/ticketing"): "ticket_webhook (HMAC-signed service call)",
    ("POST", "/oauth/token"): "token_exchange (RFC 8693; authenticated by the subject_token, audited)",
    ("POST", "/dev/token"): "dev issuer only (CLAIMSENSE_DEV_ISSUER=1); 404 otherwise",
}


class Unauthenticated(Exception):
    pass


# webhook: HMAC-signed; dev token: 404 unless sandbox; /oauth/token: authenticated by the subject_token it exchanges
BEARER_EXEMPT = PUBLIC | {"/webhooks/ticketing", "/dev/token", "/oauth/token"}
META = f'{os.environ.get("CLAIMSENSE_PUBLIC_URL", "http://localhost:8002").rstrip("/")}/.well-known/oauth-protected-resource'


@app.middleware("http")
async def _measure(request, call_next):
    """M4 (D-048): one metric line per request: call volume, server errors, refusals and latency (EMF)."""
    started = time.time()
    try:
        response = await call_next(request)
    except Exception:
        metrics.request("door", 500, started)
        raise
    metrics.request("door", response.status_code, started)
    return response


@app.middleware("http")
async def _authenticate_first(request, call_next):
    """D-2, the API-Gateway-authorizer pattern: every non-public route verifies the bearer token HERE, before
    routing, body validation or any handler runs, so no route can answer (not even a 422) without authentication.
    The handlers verify again (defense in depth) and the refusal is audited either way."""
    audit_trail.VIA.set("mcp" if request.url.path == "/mcp" else "rest")
    if request.url.path not in BEARER_EXEMPT:
        try:
            resolve_principal(request.headers.get("authorization"), request.headers.get("x-user-id"), VERIFIER,
                              B.users, STS)
        except IdentityError as e:
            rid = B._audit({"user_id": "anonymous", "groups": []}, "authenticate",
                           f"{request.method} {request.url.path}", "deny", str(e))
            body = B._error("unauthenticated", "A valid ClaimSense token is required.", rid)
            if request.url.path == "/mcp":
                body = {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": body["error"]["message"],
                                                                "data": {"request_id": rid}}}
            return JSONResponse(body, status_code=401, headers={
                "WWW-Authenticate": f'Bearer resource_metadata="{META}", error="invalid_token"'})
    return await call_next(request)


@app.exception_handler(Unauthenticated)
async def _unauthenticated(request, exc):
    rid = B._audit({"user_id": "anonymous", "groups": []}, "authenticate", request.url.path, "deny", str(exc))
    return JSONResponse(B._error("unauthenticated", "A valid ClaimSense token is required.", rid), status_code=401,
                        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})


def caller_id(authorization: str | None = Header(None), x_user_id: str | None = Header(None)) -> str:
    try:
        return resolve_principal(authorization, x_user_id, VERIFIER, B.users, STS)
    except IdentityError as e:
        raise Unauthenticated(str(e)) from None


app.include_router(build_router(B, VERIFIER, sts=STS))       # POST /mcp, protected-resource metadata, the ticketing webhook


@app.get("/.well-known/jwks.json")
def jwks():
    """Public keys for verifying ClaimSense tokens (Cognito publishes the same document on AWS)."""
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
    if hasattr(B, "flush_outbox_in_background"):
        B.flush_outbox_in_background()          # deliver escalations queued while ticketing was down (M4 runbook)
    return {"ok": True, "claims": len(B.claims), "audit_rows": len(B.audit), "mcp": "/mcp",
            "ticketing": bool(B.ticketing), "documents": len(B.documents), "document_store": doc_store.source()}


# REST status codes for the door's structured errors (D-042). Missing and forbidden are BOTH 403 with the same body,
# so the status code leaks nothing the message does not (anti-enumeration holds). /mcp is not affected: a refused
# tool call stays a JSON-RPC result with isError, as the MCP spec requires.
REST_STATUS = {"not_found_or_forbidden": 403, "human_confirmation_required": 403, "invalid_request": 400,
               "idempotency_conflict": 409, "already_confirmed": 409, "upstream_unavailable": 503}


def _rest(result):
    err = result.get("error") if isinstance(result, dict) else None
    if isinstance(err, dict) and err.get("code") in REST_STATUS:
        return JSONResponse(result, status_code=REST_STATUS[err["code"]])
    return result


@app.get("/claims/{claim_id}")
def claim(claim_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return _rest(B.claim(x_user_id, claim_id, x_on_behalf_of_agent))


@app.get("/policies/{policy_id}")
def policy(policy_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return _rest(B.policy(x_user_id, policy_id, x_on_behalf_of_agent))


@app.get("/claims/{claim_id}/documents")
def documents(claim_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return _rest(B.documents_for(x_user_id, claim_id, x_on_behalf_of_agent))


@app.get("/documents/{doc_id}")
def document(doc_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return _rest(B.document(x_user_id, doc_id, x_on_behalf_of_agent))


@app.get("/policy-kb/search")
def policy_kb_search(q: str, k: int = 3, x_user_id: str = Depends(caller_id),
                     x_on_behalf_of_agent: str | None = Header(None)):
    return _rest(B.search_clauses(x_user_id, q, k, x_on_behalf_of_agent))


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
    return _rest(B.recommend(x_user_id, claim_id, body["decision_card"], idempotency_key, x_on_behalf_of_agent))


@app.post("/recommendations/{rec_id}/confirm")
async def confirm(rec_id: str, request: Request, x_user_id: str = Depends(caller_id), idempotency_key: str = Header(),
                  x_on_behalf_of_agent: str | None = Header(None)):
    body = await _json_object(request)
    if body is None or body.get("action") not in ("confirm", "override"):
        return _bad_request(x_user_id, "confirm_recommendation", rec_id, 'Body must be {"action": "confirm" | "override", ...}.')
    return _rest(B.confirm(x_user_id, dict(body, recommendation_id=rec_id, idempotency_key=idempotency_key),
                           agent=x_on_behalf_of_agent))


@app.get("/recommendations")
def pending(x_user_id: str = Depends(caller_id), status: str = "pending"):
    """The adjuster queue: undecided drafts on claims the caller is entitled to."""
    if status != "pending":
        return _bad_request(x_user_id, "list_pending_recommendations", "queue", "Only status=pending is supported.")
    return _rest(B.pending(x_user_id))


@app.get("/claims/{claim_id}/recommendations/latest")
def latest(claim_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return _rest(B.draft(x_user_id, claim_id, x_on_behalf_of_agent))


@app.post("/claims/{claim_id}/escalations")
async def escalate(claim_id: str, request: Request, x_user_id: str = Depends(caller_id),
                   idempotency_key: str = Header(), x_on_behalf_of_agent: str | None = Header(None)):
    body = await _json_object(request) or {}
    return _rest(B.escalate(x_user_id, claim_id, body.get("reason"), idempotency_key, body.get("priority", "normal"),
                            x_on_behalf_of_agent))


@app.post("/claims/{claim_id}/oncall")
async def oncall(claim_id: str, request: Request, x_user_id: str = Depends(caller_id), idempotency_key: str = Header(),
                 x_on_behalf_of_agent: str | None = Header(None)):
    body = await _json_object(request) or {}
    return _rest(B.slack.notify(x_user_id, claim_id, body.get("reason"), idempotency_key, x_on_behalf_of_agent))


@app.get("/claims/{claim_id}/escalation")
def escalation(claim_id: str, x_user_id: str = Depends(caller_id), x_on_behalf_of_agent: str | None = Header(None)):
    return _rest(B.escalation(x_user_id, claim_id, x_on_behalf_of_agent))


@app.get("/audit")
def audit(x_user_id: str = Depends(caller_id), limit: int = 50, claim_id: str | None = None):
    """The append-only trail (senior adjusters only; the request is itself audited). ?claim_id= answers "who
    accessed claim X"."""
    return _rest(B.audit_rows(x_user_id, min(max(limit, 1), 1000), claim_id))
