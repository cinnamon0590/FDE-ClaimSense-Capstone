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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from claimsense import config
from claimsense.pipeline import Pipeline

app = FastAPI(title="ClaimSense orchestrator")
PIPE = Pipeline()


# Test-only fault injection for the restart-survival proof (evals/restart_survival.py). Off unless the
# container is started with CLAIMSENSE_FAULT_INJECTION=1; never set in CI's image push, Lambda or the console.
FAULT_INJECTION = os.environ.get("CLAIMSENSE_FAULT_INJECTION") == "1"


class RunRequest(BaseModel):
    user_id: str
    run_id: str | None = None             # resume this run if it has checkpoints; else start it with this id
    crash_after_step: str | None = None   # fault injection only (ignored unless FAULT_INJECTION)


def _plan(claim_id, req):
    run_id = req.run_id or f"{claim_id}:{uuid.uuid4().hex[:12]}"
    return run_id, PIPE.checkpoints.has(run_id)


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
    run_id, resume = _plan(claim_id, req)
    result = await PIPE.run(claim_id, req.user_id, run_id=run_id, resume=resume, on_event=_crash_hook(req))
    result["resumed"] = resume
    result["receipt"] = write_back(result)
    return result


@app.post("/claims/{claim_id}/recommend/stream")
async def recommend_stream(claim_id: str, req: RunRequest):
    q: asyncio.Queue = asyncio.Queue()

    async def run():
        try:
            run_id, resume = _plan(claim_id, req)
            res = await PIPE.run(claim_id, req.user_id, run_id=run_id, resume=resume,
                                 on_event=_crash_hook(req, q.put_nowait))
            res["resumed"] = resume
            res["receipt"] = write_back(res)
            await q.put({"kind": "result", "result": res})
        except Exception as e:  # surfaced to the console, never swallowed
            await q.put({"kind": "error", "error": f"{type(e).__name__}: {e}"})
        await q.put(None)

    async def gen():
        task = asyncio.create_task(run())
        while (ev := await q.get()) is not None:
            yield json.dumps(ev, default=str) + "\n"
        await task
    return StreamingResponse(gen(), media_type="application/x-ndjson")
