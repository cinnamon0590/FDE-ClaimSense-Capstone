"""Stretch goals on the running stack: a 4th backend (SIU escalation ticketing) through the same door, and
webhook-driven updates from it. Every admin action runs INSIDE the ticketing container, so no secret leaves it.

  1  alice escalates CLM-2024-1800 as an MCP tool call; ticketing 503s the first attempt; the door retries
  2  the same call again (same idempotency key) returns the ORIGINAL ticket, marked replay
  3  ticketing moves the ticket to `assigned` and PUSHES a signed webhook; the door applies it
  4  the same webhook delivered again (a duplicate)                -> deduped, no double update
  5  two changes delivered newest-first (out of order)             -> the late, older one is ignored by seq
  6  a correctly signed but 10-minute-old webhook (a replay attack) -> 401, refused, audited
  7  a webhook signed with a guessed key, from outside             -> 401, refused, audited
  8  the adjuster reads the escalation status through the door      -> current, with its history
  9  carol (not her claim) asks for that escalation                 -> the identical not-found-or-forbidden denial

    python evals/webhook_check.py
"""
import json
import sys
import time
import uuid

import httpx

from _common import DOOR, Report, in_container, tokens


def mcp(token, name, args, n=[0]):
    n[0] += 1
    r = httpx.post(f"{DOOR}/mcp", headers={"Authorization": f"Bearer {token}"}, timeout=30,
                   json={"jsonrpc": "2.0", "id": n[0], "method": "tools/call", "params": {"name": name, "arguments": args}})
    return r.json()["result"]


def admin(*argv):
    return json.loads(in_container("ticketing", "python", "-m", "ticketing.admin", *argv).strip().splitlines()[-1])


def main():
    R = Report(7, "ticketing-backend-and-webhooks", "Stretch: a 4th backend (SIU ticketing) + webhook-driven updates")
    tok = tokens()
    alice, carol, bob = tok("alice"), tok("carol"), tok("bob")
    key = f"esc-1800-{uuid.uuid4().hex[:8]}"
    args = {"claim_id": "CLM-2024-1800", "reason": "Impact side in the photos contradicts the narrative.",
            "priority": "high", "idempotency_key": key}
    r1 = mcp(alice, "create_escalation_ticket", args)
    t1 = r1["structuredContent"]
    state = json.loads(in_container("ticketing", "cat", "/state/ticketing.json"))
    attempts = state["attempts"].get(key)
    R.say("1  " + json.dumps(t1), f"   ticketing saw {attempts} attempts for this key (the first was a structured 503)")
    R.check("escalation created through the door despite the flaky backend (retry/backoff)",
            not r1["isError"] and t1["ticket_id"].startswith("SIU-") and attempts == 2)
    t2 = mcp(alice, "create_escalation_ticket", args)["structuredContent"]
    R.say("2  " + json.dumps(t2))
    R.check("same key again -> the ORIGINAL ticket, marked replay", t2["ticket_id"] == t1["ticket_id"]
            and t2["idempotent_replay"] is True)
    tid = t1["ticket_id"]
    a3 = admin("transition", tid, "assigned")
    R.say("3  " + json.dumps(a3))
    R.check("ticketing pushed a signed webhook and the door applied it", a3["door"]["status"] == 200
            and a3["door"]["body"].get("status") == "assigned")
    a4 = admin("redeliver", a3["event"]["event_id"])
    R.say("4  " + json.dumps(a4["door"]))
    R.check("duplicate delivery -> deduped (no second update)", a4["door"]["body"].get("deduped") is True)
    a5 = admin("out-of-order", tid, "in_review", "resolved")
    R.say("5  newer first: " + json.dumps(a5["door_first"]), "   older second: " + json.dumps(a5["door_second"]))
    R.check("out of order -> the late older event is ignored by seq", a5["door_first"]["body"].get("status") == "resolved"
            and a5["door_second"]["body"].get("ignored") == "stale_seq")
    a6 = admin("stale", tid, "open")
    R.say("6  " + json.dumps(a6["door"]))
    R.check("10-minute-old signed webhook -> 401 (replay window)", a6["door"]["status"] == 401)
    raw = json.dumps({"event_id": "evt-forged", "ticket_id": tid, "claim_id": "CLM-2024-1800", "status": "open",
                      "seq": 99, "ts": time.time()}).encode()
    forged = httpx.post(f"{DOOR}/webhooks/ticketing", content=raw,
                        headers={"X-Ticketing-Signature": f"t={int(time.time())},v1={'0' * 64}"})
    R.say("7  " + json.dumps({"status": forged.status_code, "body": forged.json()}))
    R.check("forged signature from outside -> 401", forged.status_code == 401)
    st = mcp(alice, "get_escalation", {"claim_id": "CLM-2024-1800"})["structuredContent"]
    R.say("8  " + json.dumps(st))
    R.check("the adjuster sees the current status, with its history",
            st["status"] == "resolved" and [h["status"] for h in st["history"]][-2:] == ["assigned", "resolved"])
    c = mcp(carol, "get_escalation", {"claim_id": "CLM-2024-1800"})
    R.say("9  " + json.dumps(c["structuredContent"]))
    R.check("carol (not her claim) gets the identical denial", c["isError"]
            and c["structuredContent"]["error"]["code"] == "not_found_or_forbidden")
    rows = httpx.get(f"{DOOR}/audit", params={"limit": 1000, "claim_id": "CLM-2024-1800"},
                     headers={"Authorization": f"Bearer {bob}"}).json()["rows"]
    hooks = [r for r in rows if r["action"] == "ticket_webhook"]
    allrows = httpx.get(f"{DOOR}/audit", params={"limit": 1000}, headers={"Authorization": f"Bearer {bob}"}).json()["rows"]
    refused = [r for r in allrows if r["action"] == "ticket_webhook" and r["user_id"] == "unverified-webhook"]
    R.say("", "audit rows for the webhooks (system:ticketing acts only through its single grant):",
          *["   " + json.dumps({k: r[k] for k in ("user_id", "action", "resource", "decision", "reason", "via")})
            for r in hooks[-5:]],
          *["   " + json.dumps({k: r[k] for k in ("user_id", "action", "resource", "decision", "reason", "via")})
            for r in refused[-2:]])
    R.check("every webhook (applied, deduped, ignored, refused) is audited",
            {"allow", "replay"} <= {r["decision"] for r in hooks} and len(refused) >= 2)
    return R.finish("python evals/webhook_check.py")


if __name__ == "__main__":
    sys.exit(main())
