"""RBAC on the RUNNING stack (D-030), mirroring the reference UI's example pairings:

    CLM-2024-1800 alice · adjuster          CLM-2024-1873 carol · fraud-investigator
    CLM-2024-1946 eve · total-loss-appraiser CLM-2024-2019 bob · senior-adjuster

For each claim: the specialist is refused before the hand-off; alice runs the first pass and a human confirms the
draft; the claim moves to the specialist's group; the specialist can now run their own assessment and alice can't.
Then the identity rules: no token, a forged/self-promoted token and a body naming someone else are all refused.
$0 on the replay brain. Writes M2/evidence/rbac-checks.txt; exit 1 on any failure.

    cd M2 && MOCK_BRAIN=1 docker compose up --build -d --wait && python evals/rbac_check.py
"""
import base64
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import BOUNDARY, auth, token  # noqa: E402

ORCH = "http://localhost:8003"
M2 = Path(__file__).resolve().parents[1]
PAIRS = [("CLM-2024-1800", "alice", "adjuster"), ("CLM-2024-1873", "carol", "fraud-investigator"),
         ("CLM-2024-1946", "eve", "total-loss-appraiser"), ("CLM-2024-2019", "bob", "senior-adjuster")]


def run(claim, user):
    return httpx.post(f"{ORCH}/claims/{claim}/recommend", json={}, headers=auth(user), timeout=180)


def main():
    out, ok = [f"ClaimSense RBAC checks on the running stack · {time.strftime('%Y-%m-%d %H:%M:%S')}",
               f"orchestrator brain={httpx.get(f'{ORCH}/healthz').json()['brain']} · identity: signed JWT (dev issuer, "
               "Cognito-shaped) · groups from the directory, never from the client", ""], True

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        out.append(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))

    for claim, user, group in PAIRS:
        out.append(f"{claim} · {user} · {group}")
        if user in ("carol", "eve"):                  # specialists; bob (senior) sees every claim by design
            before = run(claim, user).json()
            check(f"{user} refused before any hand-off", before["response"].get("outcome") == "refused")
        elif user == "bob":
            before = run(claim, user).json()
            check("bob (senior) can open it before any hand-off, by design",
                  before["response"].get("outcome") not in (None, "refused"))
        first = run(claim, "alice").json()
        card, rec = first["response"], first.get("receipt") or {}
        route = card.get("route_to") or "-"
        out.append(f"     alice first pass: {card['outcome']} → {route} · draft {rec.get('recommendation_id')}")
        conf = httpx.post(f"{BOUNDARY}/recommendations/{rec['recommendation_id']}/confirm", json={"action": "confirm"},
                          headers=auth("alice", **{"Idempotency-Key": uuid.uuid4().hex})).json()
        moved = conf.get("handed_off")
        check("a human (alice) confirms", conf.get("confirmed_by") == "alice",
              f"handed off {moved['from']} -> {moved['to']}" if moved else "stays with the adjuster")
        mine = run(claim, user).json()
        check(f"{user} ({group}) can now run the assessment", mine["response"].get("outcome") not in (None, "refused"),
              f"{mine['response'].get('outcome')} · {mine['decided_by']}")
        if user != "alice":
            again = run(claim, "alice").json()
            check("alice no longer can (least privilege)", again["response"].get("outcome") == "refused")
        out.append("")

    out.append("Identity rules")
    check("no token -> 401", httpx.post(f"{ORCH}/claims/CLM-2024-1800/recommend", json={"user_id": "bob"}).status_code == 401)
    check("bare X-User-Id header at the boundary -> 401",
          httpx.get(f"{BOUNDARY}/claims/CLM-2024-1800", headers={"X-User-Id": "bob"}).status_code == 401)
    head, body, sig = token("alice").split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    claims["cognito:groups"] = ["senior-adjuster"]                       # alice promotes herself, keeps the signature
    forged = ".".join([head, base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("="), sig])
    check("self-promoted (tampered) token -> 401",
          httpx.get(f"{BOUNDARY}/claims/CLM-2024-2019", headers={"Authorization": f"Bearer {forged}"}).status_code == 401)
    check("alice's token with body user_id=bob -> 403",
          httpx.post(f"{ORCH}/claims/CLM-2024-1800/recommend", json={"user_id": "bob"}, headers=auth("alice")).status_code == 403)
    dave = run("CLM-2024-1800", "dave").json()
    check("dave (customer service) gets no claim data", dave["response"].get("outcome") == "refused"
          and not dave["response"].get("returns_claim_data", False))
    audit = httpx.get(f"{BOUNDARY}/audit?limit=100000", headers=auth("bob")).json()["rows"]
    reassigned = [a for a in audit if a["action"] == "reassign_claim"]
    denied = [a for a in audit if a["action"] == "authenticate" and a["decision"] == "deny"]
    check("hand-offs and refused logins are in the audit trail", reassigned and denied,
          f"{len(reassigned)} reassignments, {len(denied)} refused authentications")

    out += ["", f"RBAC CHECKS: {'PASS' if ok else 'FAIL'}"]
    text = "\n".join(out)
    print(text)
    (M2 / "evidence" / "rbac-checks.txt").write_text(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
