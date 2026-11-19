"""Mock SIU / escalation ticketing system: AutoSure's 4th system of record (M3 stretch, D-038). ServiceNow-style.

  POST /tickets                      create (Idempotency-Key required; same key -> the ORIGINAL ticket, marked)
  GET  /tickets/{id}                 read
  POST /tickets/{id}/transition      change status -> PUSHES a signed webhook to the door (the stretch goal)
  GET  /healthz

Realism the door must handle (the W16 integration contract):
  * flaky like the lab's FlakyLegacyCore: the FIRST attempt for each new idempotency key gets a structured 503
    (TICKETING_FAIL_FIRST=1), so the door's retry/backoff runs on every real escalation
  * a service credential (bearer) shared with the door through the private secrets volume, never the repo or env
  * webhooks signed `t=<unix>,v1=<HMAC-SHA256(secret, "t.body")>`, retried with backoff, each with a unique event_id
    and a monotonic per-ticket seq so the receiver can dedupe and order them

The ticket never holds claim data: a claim id, a reason and who asked. The specialist opens the claim through the door.
Admin actions for the proofs (redeliver = a duplicate, out-of-order, stale signature) run INSIDE this container
(`python -m ticketing.admin ...`), so the secrets never leave it.
"""
import hmac
import json
import os
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from claimsense_door.door import shared_secret, sign

STATE = Path(os.environ.get("TICKETING_STATE", "/state/ticketing.json"))
WEBHOOK = os.environ.get("DOOR_WEBHOOK_URL", "http://boundary:8002/webhooks/ticketing")
FAIL_FIRST = os.environ.get("TICKETING_FAIL_FIRST", "1") == "1"
STATUSES = ("open", "assigned", "in_review", "resolved")
_lock = threading.Lock()
app = FastAPI(title="Mock SIU escalation ticketing (synthetic)")


def _load():
    return json.loads(STATE.read_text()) if STATE.exists() else {"tickets": {}, "by_key": {}, "attempts": {},
                                                                  "events": [], "n": 0}


def _save(db):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db))
    tmp.replace(STATE)


def _authorized(authorization):
    want = f"Bearer {shared_secret('ticketing_api').decode()}"
    return bool(authorization) and hmac.compare_digest(authorization, want)


def _deny():
    return JSONResponse({"error": {"code": "unauthenticated", "message": "service credential required"}},
                        status_code=401)


@app.get("/healthz")
def healthz():
    db = _load()
    return {"ok": True, "tickets": len(db["tickets"]), "events_sent": len(db["events"]), "fail_first": FAIL_FIRST}


@app.post("/tickets")
async def create(request: Request, authorization: str | None = Header(None), idempotency_key: str | None = Header(None)):
    if not _authorized(authorization):
        return _deny()
    if not idempotency_key:
        return JSONResponse({"error": {"code": "invalid_request", "message": "Idempotency-Key required"}}, status_code=400)
    body = await request.json()
    with _lock:
        db = _load()
        if idempotency_key in db["by_key"]:
            return dict(db["tickets"][db["by_key"][idempotency_key]], idempotent_replay=True)
        db["attempts"][idempotency_key] = db["attempts"].get(idempotency_key, 0) + 1
        if FAIL_FIRST and db["attempts"][idempotency_key] == 1:
            _save(db)        # the 1990s middleware: structured 503 on the first try, never a stack trace
            return JSONResponse({"error": {"code": "upstream_unavailable", "message": "ticketing busy",
                                           "retry_after_s": 0.05}}, status_code=503)
        db["n"] += 1
        tid = f"SIU-{9000 + db['n']}"
        t = {"ticket_id": tid, "claim_id": body.get("claim_id"), "reason": body.get("reason"),
             "priority": body.get("priority", "normal"), "requested_by": body.get("requested_by"),
             "status": "open", "seq": 1, "created_at": time.time()}
        db["tickets"][tid], db["by_key"][idempotency_key] = t, tid
        _save(db)
    return JSONResponse(dict(t), status_code=201)


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, authorization: str | None = Header(None)):
    if not _authorized(authorization):
        return _deny()
    t = _load()["tickets"].get(ticket_id)
    return t or JSONResponse({"error": {"code": "not_found"}}, status_code=404)


@app.post("/tickets/{ticket_id}/transition")
async def transition(ticket_id: str, request: Request, authorization: str | None = Header(None)):
    if not _authorized(authorization):
        return _deny()
    body = await request.json()
    status = body.get("status")
    if status not in STATUSES:
        return JSONResponse({"error": {"code": "invalid_request", "message": f"status must be one of {STATUSES}"}},
                            status_code=400)
    with _lock:
        db = _load()
        t = db["tickets"].get(ticket_id)
        if t is None:
            return JSONResponse({"error": {"code": "not_found"}}, status_code=404)
        t["status"], t["seq"] = status, t["seq"] + 1
        event = {"event_id": f"evt-{uuid.uuid4().hex[:16]}", "ticket_id": ticket_id, "claim_id": t["claim_id"],
                 "status": status, "seq": t["seq"], "ts": time.time()}
        db["events"].append(event)
        _save(db)
    delivered = deliver(event) if body.get("deliver", True) else None
    return {"ticket": t, "event": event, "delivered": delivered}


def deliver(event, attempts=3, ts=None):
    """POST the signed event to the door; retry with backoff on transient failures. Returns the door's answer."""
    raw = json.dumps(event).encode()
    delay, last = 0.1, None
    for attempt in range(1, attempts + 1):
        headers = {"Content-Type": "application/json",
                   "X-Ticketing-Signature": sign(shared_secret("ticketing_webhook"), raw, ts)}
        try:
            r = httpx.post(WEBHOOK, content=raw, headers=headers, timeout=5)
            last = {"status": r.status_code, "body": r.json()}
            if r.status_code < 500:
                return last
        except httpx.HTTPError as e:
            last = {"status": None, "error": type(e).__name__}
        time.sleep(delay)
        delay *= 2
    return last
