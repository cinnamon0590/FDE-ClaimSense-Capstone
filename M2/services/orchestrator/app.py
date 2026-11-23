"""The ClaimSense orchestrator service: runs the four-agent pipeline for one claim and writes the
draft recommendation back through the boundary (idempotent, audit-logged, always a draft).

  POST /claims/{claim_id}/recommend          -> the full result (card, events, cost, trace id)
  POST /claims/{claim_id}/recommend/stream   -> the same run as NDJSON events, then the result

Restart-survivable (D-027): every result carries its `run_id`. POST the same `run_id` again after a crash or
restart and the run RESUMES from its checkpoints (SQLite on the /state volume): finished agents are not re-run
or re-paid, and the write-back reuses the same idempotency key, so the boundary never stores a duplicate draft.
This is the image CI pushes to ECR (claimsense/orchestrator) once the eval gate passes.

Identity (D-030): the caller is the adjuster in the `Authorization: Bearer <JWT>` header, verified against the
issuer's JWKS and the directory. A `user_id` in the body is only a hint: if it names someone else the request is
refused. The token is forwarded to the boundary, so every agent data access is made AS that adjuster, on behalf
of a named agent. (CLAIMSENSE_ALLOW_HEADER_IDENTITY=1 accepts the body user_id instead: tests, and the IAM-signed
Lambda rung, where AWS IAM authenticates the caller.)
"""
import asyncio
import hashlib
import json
import os
import time
import uuid

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from claimsense import config
from claimsense import audit_trail, metrics
from claimsense.assistant import Assistant
from claimsense.boundary_client import CALLER_TOKEN, users
from claimsense.identity import DevIssuer, IdentityError, Verifier, header_identity_allowed, resolve
from claimsense.pipeline import Pipeline

app = FastAPI(title="ClaimSense orchestrator")
PIPE = Pipeline()
ASSISTANT = Assistant(PIPE.brain, PIPE.boundary, PIPE.index, PIPE.classifier)
DIRECTORY = users()
# verify against the boundary's published keys (M3: COGNITO_JWKS_URL); in-process, against the local dev issuer
VERIFIER = (Verifier(jwks_url=os.environ["COGNITO_JWKS_URL"]) if os.environ.get("COGNITO_JWKS_URL")
            else Verifier(jwks_url=f"{config.BOUNDARY_URL.rstrip('/')}/.well-known/jwks.json") if config.BOUNDARY_URL
            else Verifier(jwks=DevIssuer().jwks()))


def _exchange(id_token):
    """RFC 8693 on-behalf-of (M3 D-039): trade the adjuster's ID token for a 5-minute delegated token that names the
    agent (`act`) and carries only what the agent may do (no confirm, no audit). The agents' MCP calls carry THAT;
    they never hold the adjuster's own login token. If the exchange is refused (e.g. no grants), the agents get no
    token at all, so the door refuses them too, before any agent runs."""
    import httpx
    try:
        r = httpx.post(f"{config.BOUNDARY_URL.rstrip('/')}/oauth/token", timeout=10, json={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "subject_token": id_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:id_token", "actor": "agent:claimsense-pipeline",
            "audience": "claimsense-door"})
        return r.json()["access_token"] if r.status_code == 200 else None
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def authenticate(authorization, claimed_user, action="invoke", resource="-"):
    """Return the verified user id (and bind their token to this request), or an error response. EVERY call is
    audited here (M3 D-5), allowed or refused, before anything else runs; what the user may then SEE is decided by
    the governed door (grants + entitlement) at the pipeline's step 0, still before any agent."""
    audit_trail.VIA.set("orchestrator")
    try:
        if authorization:
            user = resolve(authorization, None, VERIFIER, DIRECTORY)
            CALLER_TOKEN.set(authorization.partition(" ")[2].strip())
        elif header_identity_allowed() and claimed_user:
            user = claimed_user
        else:
            raise IdentityError("authentication required")
    except IdentityError as e:
        rid = audit_trail.record("anonymous", [], action, resource, "deny", f"unauthenticated: {e}")
        return _bad("unauthenticated", "A valid ClaimSense token is required.", 401, rid)
    groups = (DIRECTORY.get(user) or {}).get("groups", [])
    if authorization and config.MCP_URL:
        CALLER_TOKEN.set(_exchange(authorization.partition(" ")[2].strip()))   # the agents get a delegated token only
    if claimed_user and claimed_user != user:
        rid = audit_trail.record(user, groups, action, resource, "deny", f"token user is not {claimed_user!r}")
        return _bad("not_found_or_forbidden", "No claim is available for this request.", 403, rid)   # never act as another
    # "authenticated", not "allow": the orchestrator accepts the request; whether any data is released is the door's
    # decision, recorded as its own allow/deny row (so "who was allowed claim X" is never muddied by entry rows)
    audit_trail.record(user, groups, action, resource, "authenticated", "request accepted; data access decided at the door")
    return user


PUBLIC = {"/healthz", "/ping", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
          "/demo/signin"}   # authenticated by the demo passcode itself (404 unless enabled)


@app.middleware("http")
async def _measure(request, call_next):
    """M4 (D-048): one metric line per request: call volume, server errors, refusals and latency (EMF)."""
    started = time.time()
    try:
        response = await call_next(request)
    except Exception:
        metrics.request("orchestrator", 500, started)
        raise
    metrics.request("orchestrator", response.status_code, started)
    return response


@app.middleware("http")
async def _authenticate_first(request, call_next):
    """D-2: every non-public route verifies the bearer token BEFORE routing and body validation (so a malformed
    body without a token is a 401, never a 422 that leaks the schema), and the refusal is audited. The handler's
    authenticate() verifies again and audits the allowed call. Header identity only in the unit-test mode."""
    if request.url.path not in PUBLIC:
        auth = request.headers.get("authorization")
        try:
            if auth:
                resolve(auth, None, VERIFIER, DIRECTORY)
            elif not header_identity_allowed():
                raise IdentityError("authentication required")
        except IdentityError as e:
            audit_trail.VIA.set("orchestrator")
            rid = audit_trail.record("anonymous", [], "authenticate", f"{request.method} {request.url.path}", "deny",
                                     f"unauthenticated: {e}")
            return _bad("unauthenticated", "A valid ClaimSense token is required.", 401, rid)
    return await call_next(request)


# Test-only fault injection for the restart-survival proof (evals/restart_survival.py). Off unless the
# container is started with CLAIMSENSE_FAULT_INJECTION=1; never set in CI's image push, Lambda or the console.
FAULT_INJECTION = os.environ.get("CLAIMSENSE_FAULT_INJECTION") == "1"


class RunRequest(BaseModel):
    user_id: str | None = None            # optional hint; the identity is the token's
    run_id: str | None = None             # resume this run if it has checkpoints; else start it with this id
    crash_after_step: str | None = None   # fault injection only (ignored unless FAULT_INJECTION)


class LiveRun:
    """A run in progress. A reconnecting console JOINS it (buffered events, then live ones, then the result)
    instead of starting a duplicate that would pay twice for the step in flight."""

    def __init__(self, claim_id, user_id):
        self.claim_id, self.user_id = claim_id, user_id
        self.events, self.subs, self.task = [], set(), None

    def publish(self, ev):
        self.events.append(ev)
        for q in self.subs:
            q.put_nowait(ev)


INFLIGHT: dict[str, LiveRun] = {}


def _bad(code, message, status=400, request_id="-"):
    return JSONResponse({"error": {"code": code, "message": message, "request_id": request_id}}, status_code=status,
                        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'} if status == 401 else None)


def _start_or_join(claim_id, req):
    """Return (run_id, live run, joined) or an error response."""
    run_id = req.run_id or f"{claim_id}:{uuid.uuid4().hex[:12]}"
    if not run_id.startswith(f"{claim_id}:"):
        # a run belongs to one claim: never restore another claim's checkpoints into this one
        return _bad("invalid_request", "run_id does not belong to this claim.")
    if (live := INFLIGHT.get(run_id)) is not None:
        if (live.claim_id, live.user_id) != (claim_id, req.user_id):
            return _bad("not_found_or_forbidden", "No run is available for this request.", 404)   # never share
        return run_id, live, True
    resume = PIPE.checkpoints.has(run_id)          # resume re-checks entitlement at the boundary first
    live = LiveRun(claim_id, req.user_id)
    INFLIGHT[run_id] = live
    live.publish({"kind": "run", "name": run_id, "resumed": resume})
    live.task = asyncio.create_task(_execute(claim_id, req, run_id, resume, live))
    return run_id, live, False


async def _execute(claim_id, req, run_id, resume, live):
    try:
        res = await PIPE.run(claim_id, req.user_id, run_id=run_id, resume=resume,
                             on_event=_crash_hook(req, live.publish))
        res["resumed"] = resume
        res["receipt"] = write_back(res)
        return res
    finally:
        INFLIGHT.pop(run_id, None)


def _crash_hook(req, forward=None):
    def on_event(ev):
        if forward:
            forward(ev)
        if FAULT_INJECTION and ev["kind"] == "checkpoint_saved" and ev["name"] == req.crash_after_step:
            os._exit(17)                  # die like a killed container: no cleanup, no response
    return on_event if (FAULT_INJECTION and req.crash_after_step) else forward


def write_back(result):
    card = result["response"]
    if "citations" not in card:                       # refusals are never written
        return None
    key = hashlib.sha256(f"{result['run_id']}|{json.dumps(card, sort_keys=True)}".encode()).hexdigest()[:32]
    return PIPE.boundary.recommend(result["user_id"], result["claim_id"], card, key)


# ── demo sign-in for the deployed console (M4, D-049) ────────────────────────────────────────────────────────────
# Graders sign in as one of the five SYNTHETIC users with a shared passcode (given in the submission form, never in
# the repo). This endpoint checks the passcode, then signs in to COGNITO as that user (ADMIN_USER_PASSWORD_AUTH) and
# returns the real ID token, so every later call is authenticated, authorised and audited exactly as in production.
# Disabled (404) unless CLAIMSENSE_DEMO_SECRET_ID is set; the orchestrator is not exposed publicly (only the console).
DEMO_SECRET_ID = os.environ.get("CLAIMSENSE_DEMO_SECRET_ID", "")
_demo_cache, _demo_fails = {}, []


def _demo_secret():
    if "v" not in _demo_cache:
        import boto3
        _demo_cache["v"] = json.loads(boto3.client("secretsmanager").get_secret_value(
            SecretId=DEMO_SECRET_ID)["SecretString"])
    return _demo_cache["v"]


@app.post("/demo/signin")
async def demo_signin(request: Request):
    import hmac
    if not DEMO_SECRET_ID:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    audit_trail.VIA.set("orchestrator")
    now = time.time()
    _demo_fails[:] = [t for t in _demo_fails if now - t < 60]
    if len(_demo_fails) >= 10:                                    # brute-force brake: 10 wrong passcodes a minute
        return _bad("rate_limited", "Too many attempts; wait a minute.", 429)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    user, code = str(body.get("user_id", "")), str(body.get("passcode", ""))
    sec = _demo_secret()
    ok = hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(), sec["passcode_sha256"]) and user in sec["users"]
    if not ok:
        _demo_fails.append(now)
        rid = audit_trail.record("anonymous", [], "demo_signin", user or "-", "deny", "wrong passcode or unknown user")
        return _bad("unauthenticated", "Sign-in refused.", 401, rid)
    import boto3
    res = boto3.client("cognito-idp").admin_initiate_auth(
        UserPoolId=sec["pool_id"], ClientId=sec["client_id"], AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": user, "PASSWORD": sec["users"][user]})
    groups = (DIRECTORY.get(user) or {}).get("groups", [])
    audit_trail.record(user, groups, "demo_signin", user, "allow", "Cognito sign-in via the demo passcode")
    return {"token": res["AuthenticationResult"]["IdToken"], "user_id": user, "groups": groups,
            "issuer": "Amazon Cognito (demo sign-in)"}


@app.get("/healthz")
def healthz():
    rag = {"backend": PIPE.index.backend}
    if hasattr(PIPE.index, "count"):                       # the RAG store service: prove it is reachable and loaded
        rag.update(url=config.OPENSEARCH_URL, indexed_chunks=PIPE.index.count())
    return {"ok": True, "brain": PIPE.brain, "boundary": config.BOUNDARY_URL or "in-process",
            "models": {"fast": config.MODEL_FAST, "smart": config.MODEL_SMART}, "retrieval": PIPE.index.backend,
            "rag_store": rag}


# ── AgentCore Runtime HTTP contract (D-033): the same image runs on AgentCore unchanged (PORT=8080 there) ─────
@app.get("/ping")
def ping():
    return {"status": "Healthy", "time_of_last_update": int(time.time())}


class InvocationRequest(BaseModel):
    claim_id: str
    user_id: str | None = None
    run_id: str | None = None


@app.post("/invocations")
async def invocations(req: InvocationRequest, authorization: str | None = Header(None),
                      x_amzn_bedrock_agentcore_runtime_session_id: str | None = Header(None)):
    """AgentCore's entry point. Its runtime session id becomes the resumable run_id (D-027), so re-invoking the
    same session resumes the claim instead of re-running finished agents. Identity: the same token rules."""
    session = x_amzn_bedrock_agentcore_runtime_session_id
    run_id = req.run_id or (f"{req.claim_id}:{session}" if session else None)
    return await recommend(req.claim_id, RunRequest(user_id=req.user_id, run_id=run_id), authorization)


@app.post("/claims/{claim_id}/recommend")
async def recommend(claim_id: str, req: RunRequest, authorization: str | None = Header(None)):
    user = authenticate(authorization, req.user_id, "run_recommendation", claim_id)
    if isinstance(user, JSONResponse):
        return user
    req.user_id = user
    started = _start_or_join(claim_id, req)
    if isinstance(started, JSONResponse):
        return started
    run_id, live, joined = started
    res = await asyncio.shield(live.task)          # a dropped client never cancels the shared run
    return dict(res, joined=joined)


@app.post("/claims/{claim_id}/recommend/stream")
async def recommend_stream(claim_id: str, req: RunRequest, authorization: str | None = Header(None)):
    user = authenticate(authorization, req.user_id, "run_recommendation", claim_id)
    if isinstance(user, JSONResponse):
        return user
    req.user_id = user
    started = _start_or_join(claim_id, req)
    if isinstance(started, JSONResponse):
        return started
    run_id, live, joined = started

    async def gen():
        q: asyncio.Queue = asyncio.Queue()
        backlog = list(live.events)               # no await between snapshot and subscribe: nothing is missed
        live.subs.add(q)
        try:
            if joined:
                yield json.dumps({"kind": "joined", "name": run_id}) + "\n"
            for ev in backlog:
                yield json.dumps(ev, default=str) + "\n"
            while True:
                get = asyncio.ensure_future(q.get())
                done, _ = await asyncio.wait({get, live.task}, return_when=asyncio.FIRST_COMPLETED)
                if get in done:
                    yield json.dumps(get.result(), default=str) + "\n"
                    continue
                get.cancel()
                while not q.empty():
                    yield json.dumps(q.get_nowait(), default=str) + "\n"
                break
            try:
                yield json.dumps({"kind": "result", "result": dict(live.task.result(), joined=joined)}, default=str) + "\n"
            except Exception as e:                # surfaced to the console, never swallowed
                yield json.dumps({"kind": "error", "error": f"{type(e).__name__}: {e}"}) + "\n"
        finally:
            live.subs.discard(q)
    return StreamingResponse(gen(), media_type="application/x-ndjson")


class AskRequest(BaseModel):
    user_id: str | None = None
    question: str


@app.post("/claims/{claim_id}/ask")
async def ask(claim_id: str, req: AskRequest, authorization: str | None = Header(None)):
    """Ask ClaimSense (D-028): streamed NDJSON (agent switches, tool calls, the handoff, text deltas, then the
    answer). The conversation is an SDK SQLiteSession per adjuster per claim, so it survives restarts."""
    user = authenticate(authorization, req.user_id, "ask_claimsense", claim_id)
    if isinstance(user, JSONResponse):
        return user
    if not req.question.strip() or len(req.question) > 2000:
        return _bad("invalid_request", "Ask a question of 1 to 2,000 characters.")
    q: asyncio.Queue = asyncio.Queue()

    async def run():
        try:
            await ASSISTANT.ask(claim_id, user, req.question, on_event=q.put_nowait)
        except Exception as e:  # surfaced to the console, never swallowed
            await q.put({"kind": "error", "error": f"{type(e).__name__}: {e}"})
        await q.put(None)

    task = asyncio.create_task(run())                 # created here, so it carries this request's token

    async def gen():
        while (ev := await q.get()) is not None:
            yield json.dumps(ev, default=str) + "\n"
        await task
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/claims/{claim_id}/ask/history")
async def ask_history(claim_id: str, user_id: str | None = None, authorization: str | None = Header(None)):
    user_id = authenticate(authorization, user_id, "read_ask_history", claim_id)
    if isinstance(user_id, JSONResponse):
        return user_id
    claim = PIPE.boundary.claim(user_id, claim_id, "agent:ask-claimsense")     # entitlement first
    if "error" in claim:
        return _bad("not_found_or_forbidden", "No conversation is available for this request.", 404)
    return {"session_id": f"{claim_id}:{user_id}", "messages": await ASSISTANT.history(claim_id, user_id)}
