"""Escalate a flagged claim to SIU by hand (runbook "Escalate a flagged claim manually", M4), as a named person:
the same door call as the console's "Escalate to SIU" button, for on-call and for when the console is down.

    python M4/ops/escalate.py --as bob --claim CLM-2025-1084 --reason "inconsistent repair timeline" [--priority high]
    python M4/ops/escalate.py --as bob --claim CLM-2025-1084 --status         # where is the ticket?
    # --door http://localhost:8002 (default: the local stack, dev issuer) · --door aws (the deployed door, Cognito)

The door decides: grant (customer service can't escalate), entitlement (only someone who may open the claim), an
Idempotency-Key (re-running never opens a second ticket), an audit row. The ticket carries the claim id and the
reason, never claim data. If ticketing is down the escalation is queued and delivered later (`pending_delivery`).
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def token(door, user):
    if door == "aws":
        sys.path[:0] = [str(ROOT / "M3" / "door"), str(ROOT / "M2")]
        from claimsense_door.cognito import token_for
        return json.loads((Path.home() / ".claimsense" / "deploy.json").read_text())["door_url"], token_for(user)
    return door, httpx.post(f"{door}/dev/token", json={"user_id": user}, timeout=10).json()["token"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as", dest="user", required=True)
    ap.add_argument("--claim", required=True)
    ap.add_argument("--reason", default="")
    ap.add_argument("--priority", default="normal", choices=["normal", "high"])
    ap.add_argument("--key", default=None, help="Idempotency-Key (default: a new one; reuse it to retry safely)")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--door", default="http://localhost:8002")
    a = ap.parse_args()
    door, tok = token(a.door, a.user)
    h = {"Authorization": f"Bearer {tok}"}
    if a.status:
        r = httpx.get(f"{door}/claims/{a.claim}/escalation", headers=h, timeout=20)
    else:
        if not a.reason.strip():
            sys.exit("--reason is required: it goes on the ticket (never claim data)")
        key = a.key or f"manual-{a.claim}-{uuid.uuid4().hex[:8]}"
        r = httpx.post(f"{door}/claims/{a.claim}/escalations", json={"reason": a.reason, "priority": a.priority},
                       headers={**h, "Idempotency-Key": key}, timeout=30)
        print(f"Idempotency-Key: {key}")
    print(f"HTTP {r.status_code} {json.dumps(r.json())}")
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
