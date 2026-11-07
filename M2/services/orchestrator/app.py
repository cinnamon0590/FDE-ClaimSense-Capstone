"""The ClaimSense orchestrator service: runs the four-agent pipeline for one claim and writes the
draft recommendation back through the boundary (idempotent, audit-logged, always a draft).

  POST /claims/{claim_id}/recommend          -> the full result (card, events, cost, trace id)
  POST /claims/{claim_id}/recommend/stream   -> the same run as NDJSON events, then the result

Restart-survivable (D-027): every result carries its `run_id`. POST the same `run_id` again after a crash or
restart and the run RESUMES from its checkpoints (SQLite on the /state volume): finished agents are not re-run
or re-paid, and the write-back reuses the same idempotency key, so the boundary never stores a duplicate draft.
This is the image CI pushes to ECR (claimsense/orchestrator) once the eval gate passes.
"""
import asyncio
import hashlib
import json
import os
import uuid

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from claimsense import config
from claimsense.assistant import Assistant
from claimsense.pipeline import Pipeline

app = FastAPI(title="ClaimSense orchestrator")
PIPE = Pipeline()
ASSISTANT = Assistant(PIPE.brain, PIPE.boundary, PIPE.index, PIPE.classifier)


# Test-only fault injection for the restart-survival proof (evals/restart_survival.py). Off unless the
# container is started with CLAIMSENSE_FAULT_INJECTION=1; never set in CI's image push, Lambda or the console.
FAULT_INJECTION = os.environ.get("CLAIMSENSE_FAULT_INJECTION") == "1"


class RunRequest(BaseModel):
    user_id: str
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


def _bad(code, message, status=400):
    return JSONResponse({"error": {"code": code, "message": message, "request_id": "-"}}, status_code=status)


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


@app.get("/healthz")
def healthz():
    return {"ok": True, "brain": PIPE.brain, "boundary": config.BOUNDARY_URL or "in-process",
            "models": {"fast": config.MODEL_FAST, "smart": config.MODEL_SMART}, "retrieval": PIPE.index.backend}


@app.post("/claims/{claim_id}/recommend")
async def recommend(claim_id: str, req: RunRequest):
    started = _start_or_join(claim_id, req)
    if isinstance(started, JSONResponse):
        return started
    run_id, live, joined = started
    res = await asyncio.shield(live.task)          # a dropped client never cancels the shared run
    return dict(res, joined=joined)


@app.post("/claims/{claim_id}/recommend/stream")
async def recommend_stream(claim_id: str, req: RunRequest):
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
    user_id: str
    question: str


@app.post("/claims/{claim_id}/ask")
async def ask(claim_id: str, req: AskRequest):
    """Ask ClaimSense (D-028): streamed NDJSON (agent switches, tool calls, the handoff, text deltas, then the
    answer). The conversation is an SDK SQLiteSession per adjuster per claim, so it survives restarts."""
    if not req.question.strip() or len(req.question) > 2000:
        return _bad("invalid_request", "Ask a question of 1 to 2,000 characters.")
    q: asyncio.Queue = asyncio.Queue()

    async def run():
        try:
            await ASSISTANT.ask(claim_id, req.user_id, req.question, on_event=q.put_nowait)
        except Exception as e:  # surfaced to the console, never swallowed
            await q.put({"kind": "error", "error": f"{type(e).__name__}: {e}"})
        await q.put(None)

    async def gen():
        task = asyncio.create_task(run())
        while (ev := await q.get()) is not None:
            yield json.dumps(ev, default=str) + "\n"
        await task
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/claims/{claim_id}/ask/history")
async def ask_history(claim_id: str, user_id: str):
    claim = PIPE.boundary.claim(user_id, claim_id, "agent:ask-claimsense")     # entitlement first
    if "error" in claim:
        return _bad("not_found_or_forbidden", "No conversation is available for this request.", 404)
    return {"session_id": f"{claim_id}:{user_id}", "messages": await ASSISTANT.history(claim_id, user_id)}
