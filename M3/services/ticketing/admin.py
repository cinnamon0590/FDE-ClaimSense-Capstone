"""Proof actions for the webhook stretch goal, run INSIDE the ticketing container so no secret leaves it.

    python -m ticketing.admin transition <ticket_id> <status>         a real status change (signed, delivered)
    python -m ticketing.admin redeliver <event_id>                    deliver an event AGAIN (a duplicate)
    python -m ticketing.admin out-of-order <ticket_id> <s1> <s2>      make two changes, deliver the newer one FIRST
    python -m ticketing.admin stale <ticket_id> <status>              a correctly signed event with a 10-minute-old
                                                                      timestamp (a captured-and-replayed webhook)
Prints JSON only (the door's answers); never the secret.
"""
import json
import sys
import time

import httpx

from claimsense_door.door import shared_secret

from .app import STATE, deliver

BASE = "http://localhost:8004"


def _h():
    return {"Authorization": f"Bearer {shared_secret('ticketing_api').decode()}"}


def _transition(tid, status, deliver_now=True):
    r = httpx.post(f"{BASE}/tickets/{tid}/transition", json={"status": status, "deliver": deliver_now},
                   headers=_h(), timeout=10)
    return r.json()


def main(argv):
    cmd = argv[0]
    if cmd == "transition":
        out = _transition(argv[1], argv[2])
        print(json.dumps({"event": out["event"], "door": out["delivered"]}))
    elif cmd == "redeliver":
        ev = next(e for e in json.loads(STATE.read_text())["events"] if e["event_id"] == argv[1])
        print(json.dumps({"event": ev, "door": deliver(ev)}))
    elif cmd == "out-of-order":
        older = _transition(argv[1], argv[2], deliver_now=False)["event"]
        newer = _transition(argv[1], argv[3], deliver_now=False)["event"]
        first, second = deliver(newer), deliver(older)
        print(json.dumps({"delivered_first": newer, "door_first": first, "delivered_second": older,
                          "door_second": second}))
    elif cmd == "stale":
        ev = _transition(argv[1], argv[2], deliver_now=False)["event"]
        print(json.dumps({"event": ev, "door": deliver(ev, attempts=1, ts=time.time() - 600)}))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
