"""Streamable-HTTP transport for the MCP door, plus the ticketing webhook receiver (FastAPI router).

MCP's own authorization model (spec 2025-06-18; W16 notebook §2.1): a remote MCP server is an OAuth 2.1 RESOURCE
SERVER. Every request carries a bearer token that is verified BEFORE any tool runs; a missing or invalid token gets
401 with `WWW-Authenticate: Bearer resource_metadata=...`, and the server publishes RFC 9728 protected-resource
metadata naming the authorization server that issues its tokens (Cognito on AWS; the dev issuer locally). That
answers "may this client call the door at all"; the door's grants + entitlement answer "may this USER see this
RECORD". Both are needed, and both refusals are audited.
"""
import json
import os

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response

from claimsense import audit_trail
from claimsense.identity import ISSUER, IdentityError

from .door import shared_secret, verify_signature
from .mcp import PROTOCOL_VERSIONS, McpDoor
from .obo import GRANT_TYPE, STS_ISSUER, resolve_principal

ANON = {"user_id": "anonymous", "groups": []}


def build_router(boundary, verifier, public_url=None, sts=None):
    router = APIRouter()
    resolve = lambda a, x, v, d: resolve_principal(a, x, v, d, sts)          # IdP token OR delegated token
    door = McpDoor(boundary)
    base = (public_url or os.environ.get("CLAIMSENSE_PUBLIC_URL", "http://localhost:8002")).rstrip("/")
    metadata_url = f"{base}/.well-known/oauth-protected-resource"

    def _unauthorized(path, reason, mid=None):
        audit_trail.VIA.set("mcp")
        rid = boundary._audit(ANON, "authenticate", path, "deny", reason)
        body = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": "A valid ClaimSense token is "
                                                      "required.", "data": {"request_id": rid}}}
        return JSONResponse(body, status_code=401,
                            headers={"WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}", '
                                                         'error="invalid_token"'})

    @router.get("/.well-known/oauth-protected-resource")
    @router.get("/.well-known/oauth-protected-resource/mcp")
    def protected_resource():
        """RFC 9728: which authorization server issues tokens for this MCP server, and how to present them."""
        return {"resource": f"{base}/mcp", "authorization_servers": [os.environ.get("CLAIMSENSE_AUTH_SERVER", ISSUER)]
                + ([STS_ISSUER] if sts else [])
                + ([os.environ["CLAIMSENSE_EXCHANGE_ISSUER"]] if os.environ.get("CLAIMSENSE_EXCHANGE_ISSUER") else []),
                "bearer_methods_supported": ["header"], "scopes_supported": ["openid"],
                "resource_name": "ClaimSense governed door (AutoSure, synthetic data)",
                "resource_documentation": f"{base}/docs"}

    @router.get("/mcp")
    def mcp_get(authorization: str | None = Header(None), x_user_id: str | None = Header(None)):
        # authenticated first (like every route); then: no server-initiated SSE stream is offered (spec-allowed 405)
        try:
            resolve(authorization, x_user_id, verifier, boundary.users)
        except IdentityError as e:
            return _unauthorized("GET /mcp", str(e))
        return Response(status_code=405, headers={"Allow": "POST"})

    @router.post("/mcp")
    async def mcp_post(request: Request, authorization: str | None = Header(None),
                       x_user_id: str | None = Header(None), x_on_behalf_of_agent: str | None = Header(None),
                       mcp_protocol_version: str | None = Header(None)):
        try:
            raw = await request.body()
            msg = json.loads(raw or b"null")
        except (ValueError, UnicodeDecodeError):
            msg = None
        mid = msg.get("id") if isinstance(msg, dict) else None
        # 1 · who is calling: the token, verified before anything else happens (no tool runs without it)
        try:
            user_id = resolve(authorization, x_user_id, verifier, boundary.users)
        except IdentityError as e:
            return _unauthorized("/mcp", str(e), mid)
        audit_trail.VIA.set("mcp")
        if mcp_protocol_version and mcp_protocol_version not in PROTOCOL_VERSIONS:
            return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32600, "message": f"unsupported MCP-Protocol-Version {mcp_protocol_version}"}}, status_code=400)
        if isinstance(msg, list):
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {
                "code": -32600, "message": "JSON-RPC batching is not supported (MCP 2025-06-18)"}}, status_code=400)
        if not isinstance(msg, dict):
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}},
                                status_code=400)
        out = door.handle(msg, user_id, x_on_behalf_of_agent)
        if out is None:
            return Response(status_code=202)                    # a notification: accepted, no body
        return JSONResponse(out, headers={"MCP-Protocol-Version": PROTOCOL_VERSIONS[0]})

    @router.post("/oauth/token")
    async def token_exchange(request: Request):
        """RFC 8693 token exchange (the OBO borrow, D-039): an IdP ID token in, a 5-minute delegated token out, scoped
        to the requested actions ∩ the user's grants, naming the agent as `act`. Audited, allowed or refused."""
        audit_trail.VIA.set("sts")
        raw = await request.body()
        try:
            from urllib.parse import parse_qsl
            form = dict(parse_qsl(raw.decode())) if "form" in request.headers.get("content-type", "") \
                else (json.loads(raw) if raw else {})
            form = form if isinstance(form, dict) else {}
        except (ValueError, UnicodeDecodeError):
            form = {}
        anon = {"user_id": "anonymous", "groups": []}
        if sts is None or form.get("grant_type") != GRANT_TYPE or not form.get("subject_token"):
            rid = boundary._audit(anon, "token_exchange", "/oauth/token", "deny", "unsupported or incomplete request")
            return JSONResponse({"error": "invalid_request", "request_id": rid}, status_code=400)
        actor = form.get("actor") or form.get("actor_token") or ""
        try:
            out = sts.exchange(form["subject_token"], actor, form.get("scope"), verifier, boundary.users)
        except IdentityError as e:
            who = anon
            try:                                        # name the user when the subject token itself was valid
                from claimsense.identity import resolve as idp_resolve
                u = idp_resolve(f"Bearer {form['subject_token']}", None, verifier, boundary.users)
                who = boundary.caller(u)
            except IdentityError:
                pass
            reason = ("no_grant: " if "no delegable scope" in str(e) else "") + str(e)
            rid = boundary._audit(who, "token_exchange", actor or "-", "deny", reason)
            return JSONResponse({"error": "invalid_grant", "error_description": str(e), "request_id": rid},
                                status_code=400)
        from .obo import TOKEN_ACTOR
        user = sts.verify(out["access_token"])["sub"]
        TOKEN_ACTOR.set(actor)
        boundary._audit(boundary.caller(user), "token_exchange", actor, "allow",
                        f"delegated {out['expires_in']}s; scope: {out['scope']}")
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    @router.post("/webhooks/ticketing")
    async def ticket_webhook(request: Request, x_ticketing_signature: str | None = Header(None)):
        """Webhook-driven updates (stretch, D-038): the ticketing system PUSHES status changes. Signed with HMAC-SHA256
        over the timestamp and body (shared secret on the private secrets volume), replay window 5 minutes,
        idempotent per event_id, ordered by seq. Anything unverified is refused and audited; nothing is applied."""
        audit_trail.VIA.set("webhook")
        body = await request.body()
        problem = verify_signature(shared_secret("ticketing_webhook"), x_ticketing_signature, body)
        if problem:
            rid = boundary._audit({"user_id": "unverified-webhook", "groups": []}, "ticket_webhook",
                                  "/webhooks/ticketing", "deny", problem)
            return JSONResponse(boundary._error("unauthenticated", "Webhook signature rejected.", rid), status_code=401)
        try:
            event = json.loads(body)
            assert isinstance(event, dict) and {"event_id", "ticket_id", "claim_id", "status", "seq"} <= event.keys()
        except (ValueError, AssertionError):
            rid = boundary._audit({"user_id": "system:ticketing", "groups": []}, "ticket_webhook",
                                  "/webhooks/ticketing", "error", "malformed event")
            return JSONResponse(boundary._error("invalid_request", "Malformed ticket event.", rid), status_code=400)
        out, status = boundary.apply_ticket_event(event)
        return JSONResponse(out, status_code=status)

    return router
