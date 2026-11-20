"""The Learning UI Viewer's Week 4 Integration checks, run against a live door exactly as the viewer words them (D-042).

  RBAC          "adjusters only read their assigned claims": alice asks for a claim that is NOT assigned to alice
                (CLM-2024-5001, in the senior adjuster's queue) and gets 403; bob (senior-adjuster) asks for the
                same claim and gets 200 with the full data. Over REST (GET /claims/{id}) AND over MCP (tools/call).
  Audit trail   "every MCP call logs user ID, action and resource ID": every call above has its row in the trail,
                and the same row is an `AUDIT {json}` log line: CloudWatch Logs on AWS (/aws/lambda/claimsense-door),
                the door container's log locally.

    python evals/viewer_week4_check.py               # the local stack (dev tokens)          -> evidence/20
    python evals/viewer_week4_check.py --deployed    # API Gateway + Lambda (Cognito tokens) -> evidence/21
                                                     #   needs `aws login` + M3/cloud/deploy.sh
Tokens are never printed (the requests show `Bearer <redacted JWT>`). Synthetic data only.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

DEPLOYED = "--deployed" in sys.argv
if DEPLOYED:
    os.environ["DOOR_URL"] = json.loads((Path.home() / ".claimsense" / "deploy.json").read_text())["door_url"]
    os.environ["CLAIMSENSE_COGNITO"] = "1"

from _common import COMPOSE, DOOR, Report, tokens  # noqa: E402
from claimsense_door import two_analyst_test  # noqa: E402
from claimsense_door.clients import Http  # noqa: E402

CLAIM = "CLM-2024-5001"           # assigned to bob (M1 fixtures/claim_assignments.json); alice owns every other claim
OWN = "CLM-2024-1800"             # one of alice's own claims
LOG_GROUP = "/aws/lambda/claimsense-door"
FIELDS = ("ts", "request_id", "user_id", "groups", "action", "resource", "decision", "reason", "via")


def rest_get(token_for, user, path):
    r = httpx.get(f"{DOOR}{path}", headers={"Authorization": f"Bearer {token_for(user)}"}, timeout=30)
    return r, {"method": "GET", "url": f"{DOOR}{path}", "headers": {"Authorization": "Bearer <redacted JWT>"}}


def door_log_lines(since_ms):
    """`AUDIT {json}` lines the door wrote since `since_ms`: CloudWatch Logs on AWS, the container log locally."""
    if DEPLOYED:
        import boto3
        logs, out, kw = boto3.client("logs"), [], {"logGroupName": LOG_GROUP, "startTime": since_ms,
                                                    "filterPattern": '"AUDIT"'}
        while True:
            page = logs.filter_log_events(**kw)
            out += [e["message"] for e in page["events"]]
            if "nextToken" not in page:
                return out
            kw["nextToken"] = page["nextToken"]
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since_ms / 1000)) + "Z"
    return subprocess.run(COMPOSE + ["logs", "--no-log-prefix", "--since", since, "boundary"],
                          capture_output=True, text=True, check=True).stdout.splitlines()


def parse_audit(lines):
    rows = {}
    for ln in lines:
        i = ln.find("AUDIT {")
        if i >= 0:
            try:
                r = json.loads(ln[i + len("AUDIT "):].strip())
                rows[r["request_id"]] = r
            except ValueError:
                pass
    return rows


def main():
    where = "AWS: API Gateway (Cognito JWT authorizer) -> Lambda -> the door" if DEPLOYED else "the local stack"
    R = Report(21 if DEPLOYED else 20, "viewer-week4-deployed" if DEPLOYED else "viewer-week4-stack",
               f"the Learning UI Viewer's Week 4 Integration checks on {where}")
    tok = tokens(cognito=DEPLOYED)
    start_ms = int(time.time() * 1000) - 2000
    R.say(f"door: {DOOR}", f"claim: {CLAIM} (assigned to bob, the senior adjuster; NOT assigned to alice)", "")

    # 1. REST, as the viewer words it: alice 403, bob 200 with full data
    R.say("1  RBAC over REST: GET /claims/{id}")
    a, a_req = rest_get(tok, "alice", f"/claims/{CLAIM}")
    b, b_req = rest_get(tok, "bob", f"/claims/{CLAIM}")
    for who, req, r in (("alice", a_req, a), ("bob", b_req, b)):
        R.say(f"   --- {who} ---", "   REQUEST:  " + json.dumps(req), f"   RESPONSE: HTTP {r.status_code}",
              "   " + json.dumps(r.json(), indent=2).replace("\n", "\n   "))
    ae = a.json().get("error") or {}
    R.check("alice (adjuster) asks for a claim not assigned to alice -> 403, no claim data",
            a.status_code == 403 and ae.get("code") == "not_found_or_forbidden" and "claim_id" not in a.json(),
            f"HTTP {a.status_code} {ae.get('code')}")
    bj = b.json()
    full = all(bj.get(k) for k in ("claim_id", "policy_id", "loss_type", "document_ids", "vehicle", "repair_estimate"))
    R.check("bob (senior-adjuster) asks for the same claim -> 200 with the full data", b.status_code == 200 and full,
            f"HTTP {b.status_code} · {len(bj)} fields")
    own, _ = rest_get(tok, "alice", f"/claims/{OWN}")
    R.check(f"alice still reads a claim assigned to alice, {OWN} -> 200", own.status_code == 200 and own.json().get("claim_id") == OWN,
            f"HTTP {own.status_code}")
    missing, _ = rest_get(tok, "alice", "/claims/CLM-2099-0001")
    R.check("a claim that does not exist looks exactly like a forbidden one (403, same message)",
            missing.status_code == 403 and (missing.json().get("error") or {}).get("message") == ae.get("message"),
            f"HTTP {missing.status_code}")

    # 2. MCP, the agents' door: the same question as a tools/call, alice first (the viewer's order)
    R.say("", "2  RBAC over MCP: the two-user test in the viewer's shape (alice first, then bob)")
    ok, text = two_analyst_test.run(Http(DOOR, tok), CLAIM, "bob", "alice", deny_first=True)
    R.say("   " + text.replace("\n", "\n   "))
    R.check("the two-user test over MCP: alice denied, bob allowed, matching audit rows", ok)

    # 3. the audit trail: every call above has a row with user, action, resource; and the same row is a log line
    R.say("", "3  The audit trail: one row per call, carrying user ID, action and resource ID")
    time.sleep(2)
    trail = httpx.get(f"{DOOR}/audit", params={"claim_id": CLAIM, "limit": 200},
                      headers={"Authorization": f"Bearer {tok('bob')}"}, timeout=30).json().get("rows", [])
    since_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(start_ms / 1000))
    mine = [r for r in trail if r.get("ts", "") >= since_iso and r.get("action") == "get_claim"
            and r.get("user_id") in ("alice", "bob")]
    for r in mine:
        R.say("   " + json.dumps({k: r.get(k) for k in FIELDS}))
    seen = {(r["user_id"], r["decision"]) for r in mine}
    R.check("the trail holds alice's denials and bob's allows for this claim (REST and MCP: 2 each)",
            sum(1 for r in mine if r["user_id"] == "alice" and r["decision"] == "deny") >= 2
            and sum(1 for r in mine if r["user_id"] == "bob" and r["decision"] == "allow") >= 2, str(sorted(seen)))
    R.check("every row carries user ID, action and resource ID",
            mine and all(r.get("user_id") and r.get("action") and r.get("resource") == CLAIM for r in mine))

    sink = f"CloudWatch Logs ({LOG_GROUP})" if DEPLOYED else "the door container's log (CloudWatch's local twin)"
    R.say("", f"4  The same rows in {sink}")
    found, deadline = {}, time.time() + (90 if DEPLOYED else 10)
    while time.time() < deadline:
        found = parse_audit(door_log_lines(start_ms))
        if all(r["request_id"] in found for r in mine):
            break
        time.sleep(5)
    for r in mine:
        line = found.get(r["request_id"])
        R.say("   AUDIT " + (json.dumps({k: line.get(k) for k in ("request_id", "user_id", "action", "resource",
                                                                     "decision")}) if line else f"<missing {r['request_id']}>"))
    R.check(f"every one of those calls is in {sink} with user ID, action and resource ID",
            mine and all((found.get(r["request_id"]) or {}).get("user_id") == r["user_id"]
                         and found[r["request_id"]].get("action") == r["action"]
                         and found[r["request_id"]].get("resource") == r["resource"] for r in mine),
            f"{sum(r['request_id'] in found for r in mine)}/{len(mine)} found")
    blob = "\n".join(R.lines)
    R.check("no token, secret or account id in this evidence",
            "eyJ" not in blob and "mrdn_" not in blob and not any(c.isdigit() and len(c) == 12 for c in blob.split()))
    return R.finish("python evals/viewer_week4_check.py" + (" --deployed" if DEPLOYED else ""))


if __name__ == "__main__":
    sys.exit(main())
