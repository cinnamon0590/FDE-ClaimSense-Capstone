"""The ClaimSense orchestrator service: runs the four-agent pipeline for one claim and writes the
draft recommendation back through the boundary (idempotent, audit-logged, always a draft).

  POST /claims/{claim_id}/recommend          -> the full result (card, events, cost, trace id)
  POST /claims/{claim_id}/recommend/stream   -> the same run as NDJSON events, then the result
This is the image CI pushes to ECR (claimsense/orchestrator) once the eval gate passes.
"""
import asyncio
import hashlib
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from claimsense import config
from claimsense.pipeline import Pipeline

app = FastAPI(title="ClaimSense orchestrator")
PIPE = Pipeline()


class RunRequest(BaseModel):
    user_id: str


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
    result = await PIPE.run(claim_id, req.user_id)
    result["receipt"] = write_back(result)
    return result


@app.post("/claims/{claim_id}/recommend/stream")
async def recommend_stream(claim_id: str, req: RunRequest):
    q: asyncio.Queue = asyncio.Queue()

    async def run():
        try:
            res = await PIPE.run(claim_id, req.user_id, on_event=q.put_nowait)
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
