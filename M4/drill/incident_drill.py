"""Incident drill on the DEPLOYED system (W17: deliberate regression -> detection -> rollback -> verified recovery;
Builder tier: packaged so the client's team can run it themselves). Writes the timeline the RCA is built from.

    python M4/drill/incident_drill.py run --label drill-1     # ~10-15 min; needs `aws login`; ~$0.05 of model calls
    python M4/drill/incident_drill.py rollback                # emergency: restore the last-good door config by hand

The fault (a realistic bad release): a configuration change points the door at the wrong document bucket
(`<bucket>-staging`, the kind of copy-paste that ships in a hurry). Nothing else changes. Then, exactly as on call:

  1. preflight   alarm OK, canary green, the last-good Lambda config (image + environment) saved
  2. canary      a synthetic adjuster (alice, real Cognito token) calls 4 door routes every 5 s, all run long
  3. inject      T0: the bad config is released
  4. impact      one real claim through the orchestrator during the incident (must fail closed: never a decision)
  5. detect      first of: the alarm goes to ALARM · the canary sees 3 failures in a row
  6. roll back   restore the saved config (runbook "Roll back a release"); no rebuild
  7. verify      canary green 5 in a row · M3 deployed route check + S3 document-store check PASS · the claim decides
                 again (alice: approve, $2,700) · then the alarm state is recorded
The timeline goes to M4/drill/runs/<label>.json and M4/evidence/incident-<label>.txt (account id masked).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[2]
CONF = Path.home() / ".claimsense"
LASTGOOD = CONF / "drill-lastgood.json"                 # account-specific: kept out of the repo
REGION = os.environ.get("AWS_REGION", "us-east-1")
FN, ALARM = "claimsense-door", "ClaimSense-door-error-rate"
CANARY = ["/claims/CLM-2024-1800", "/policies/POL-AU-10418", "/claims/CLM-2024-1800/documents",
          "/policy-kb/search?q=collision"]
sys.path[:0] = [str(ROOT / "M2"), str(ROOT / "M3" / "door")]

now = lambda: datetime.now(timezone.utc)
iso = lambda t: t.strftime("%H:%M:%S") if t else "-"
lam = lambda: boto3.client("lambda", region_name=REGION)
cw = lambda: boto3.client("cloudwatch", region_name=REGION)


class Canary(threading.Thread):
    """A synthetic adjuster: every 5 s one authenticated read through the door, round-robin over 4 routes."""

    def __init__(self, door):
        super().__init__(daemon=True)
        from claimsense_door.cognito import token_for
        self.door, self.token_for, self.rows, self.stop, self._tok, self._tok_at = door, token_for, [], False, None, 0

    def token(self):
        if time.time() - self._tok_at > 1800:
            self._tok, self._tok_at = self.token_for("alice"), time.time()
        return self._tok

    def run(self):
        i = 0
        while not self.stop:
            path = CANARY[i % len(CANARY)]
            t = now()
            try:
                code = httpx.get(self.door + path, headers={"Authorization": f"Bearer {self.token()}"}, timeout=30).status_code
            except httpx.HTTPError as e:
                code = type(e).__name__
            self.rows.append((t, path, code))
            i += 1
            time.sleep(5)

    def streak(self, ok, n):
        """When the last n results were all ok (or all failing), the time of the n-th; else None."""
        tail = self.rows[-n:]
        if len(tail) == n and all((r[2] == 200) == ok for r in tail):
            return tail[-1][0]
        return None


def alarm_state():
    a = cw().describe_alarms(AlarmNames=[ALARM])["MetricAlarms"][0]
    return a["StateValue"], a["StateUpdatedTimestamp"]


def lambda_config():
    f = lam().get_function(FunctionName=FN)
    return {"image": f["Code"].get("ImageUri"), "env": f["Configuration"]["Environment"]["Variables"]}


def set_env(env):
    lam().update_function_configuration(FunctionName=FN, Environment={"Variables": env})
    lam().get_waiter("function_updated_v2").wait(FunctionName=FN)


def rollback(saved=None):
    saved = saved or json.loads(LASTGOOD.read_text())
    cur = lambda_config()
    if cur["image"] != saved["image"]:
        lam().update_function_code(FunctionName=FN, ImageUri=saved["image"])
        lam().get_waiter("function_updated_v2").wait(FunctionName=FN)
    set_env(saved["env"])


def claim(user="alice", claim_id="CLM-2024-1800"):
    out = subprocess.run([sys.executable, str(ROOT / "M4/drill/claim_probe.py"), user, claim_id], capture_output=True,
                         text=True, timeout=600)
    lines = [l for l in out.stdout.splitlines() if l.startswith("{")]
    return json.loads(lines[-1]) if lines else {"outcome": None, "error": (out.stderr.strip().splitlines() or ["?"])[-1][:200]}


def check(script, *args):
    r = subprocess.run([sys.executable, script, *args], cwd=ROOT / "M3", capture_output=True, text=True, timeout=900)
    return r.returncode == 0, (r.stdout.strip().splitlines() or ["?"])[-1]


def run(label):
    T = {}
    log = []

    def mark(key, msg):
        T[key] = now()
        log.append(f"{iso(T[key])}  {msg}")
        print(log[-1], flush=True)

    def note(msg):
        log.append(f"{iso(now())}  {msg}")
        print(log[-1], flush=True)

    door = json.loads((CONF / "deploy.json").read_text())["door_url"]
    # 1 preflight
    state, _ = alarm_state()
    cfg = lambda_config()
    bucket = cfg["env"].get("CLAIMSENSE_DOCS_BUCKET")
    if not bucket:
        sys.exit("the door has no CLAIMSENSE_DOCS_BUCKET: nothing to drill")
    if not LASTGOOD.exists() or json.loads(LASTGOOD.read_text())["env"].get("CLAIMSENSE_DOCS_BUCKET") != bucket:
        LASTGOOD.write_text(json.dumps(cfg))
    os.chmod(LASTGOOD, 0o600)
    mark("preflight", f"preflight: alarm {state}; last-good door config saved (image {cfg['image'].rsplit(':', 1)[-1]})")
    canary = Canary(door)
    canary.start()
    while not canary.streak(True, 4):
        time.sleep(2)
        if len(canary.rows) > 12:
            canary.stop = True
            sys.exit(f"canary not green before the drill: {canary.rows[-4:]}")
    mark("baseline", "canary green: 4/4 door routes 200 (alice, real Cognito token)")
    # 3 inject
    bad = dict(cfg["env"], CLAIMSENSE_DOCS_BUCKET=f"{bucket}-staging")
    mark("inject", "INJECT: release a config change: CLAIMSENSE_DOCS_BUCKET -> '<bucket>-staging' (wrong bucket)")
    set_env(bad)
    mark("released", "bad config live on the door (Lambda updated)")
    # 4 impact: one real claim during the incident
    imp = claim()
    T["impact"] = now()
    note(f"user impact: alice runs CLM-2024-1800 -> outcome {imp.get('outcome')!r}, decided_by {imp.get('decided_by')!r}, "
         f"error {imp.get('error')!r}")
    # 5 detect: whichever comes first; keep watching the alarm for up to 6 min after T0
    while True:
        if "canary_detect" not in T and (t := canary.streak(False, 3)):
            T["canary_detect"] = t
            note(f"DETECTED by the canary: 3 failed door calls in a row "
                 f"(last: {canary.rows[-1][1]} -> {canary.rows[-1][2]})")
        s, ts = alarm_state()
        if s == "ALARM" and "alarm" not in T:
            T["alarm"] = ts
            note(f"DETECTED by the alarm: {ALARM} -> ALARM (SNS email sent)")
        waited = (now() - T["inject"]).total_seconds()
        if "alarm" in T or (waited > 360 and "canary_detect" in T):
            break
        time.sleep(10)
    if "alarm" not in T:
        note(f"the alarm stayed {alarm_state()[0]} for {int(waited)} s after the bad release: it did NOT see this incident")
    # 6 roll back
    mark("rollback_start", "ROLLBACK: restore the last-good door config (runbook: Roll back a release)")
    rollback(json.loads(LASTGOOD.read_text()))
    mark("rollback_done", "rollback live (Lambda updated)")
    # 7 verify
    while not (t := canary.streak(True, 5)):
        time.sleep(3)
    T["canary_green"] = t
    note("canary green again: 5 door calls in a row 200")
    ok1, l1 = check("evals/deployed_route_check.py")
    note(f"M3 deployed route check: {l1}")
    ok2, l2 = check("evals/s3_doc_store_check.py", "--deployed")
    note(f"M3 S3 document-store check: {l2}")
    rec = claim()
    note(f"alice runs CLM-2024-1800 again -> outcome {rec.get('outcome')!r}, net payable {rec.get('net_payable')!r}, "
         f"decided_by {rec.get('decided_by')!r}")
    verified = ok1 and ok2 and rec.get("outcome") == "approve" and rec.get("net_payable") == 2700
    mark("verified", f"VERIFIED RECOVERY: {'yes' if verified else 'NO'}")
    deadline = time.time() + 420
    while time.time() < deadline and alarm_state()[0] == "ALARM":
        time.sleep(15)
    note(f"alarm state after recovery: {alarm_state()[0]}")
    canary.stop = True
    time.sleep(6)
    # outputs
    fails = [r for r in canary.rows if r[2] != 200]
    first_fail = fails[0][0] if fails else None
    detect = min([t for k, t in T.items() if k in ("canary_detect", "alarm")], default=None)
    secs = lambda a, b: round((b - a).total_seconds()) if a and b else None
    summary = {
        "label": label, "date": T["inject"].strftime("%Y-%m-%d"), "fault": "door config: CLAIMSENSE_DOCS_BUCKET -> wrong bucket",
        "times_utc": {k: v.isoformat() for k, v in T.items()},
        "first_failed_call": first_fail.isoformat() if first_fail else None,
        "time_to_detect_s": secs(T["inject"], detect), "detected_by": "alarm" if detect and detect == T.get("alarm") else "canary",
        "alarm_fired": "alarm" in T, "time_to_rollback_s": secs(T["inject"], T["rollback_done"]),
        "time_to_verified_recovery_s": secs(T["inject"], T["verified"]), "verified": verified,
        "impact_claim": imp, "recovered_claim": rec,
        "canary": {"calls": len(canary.rows), "failed": len(fails),
                   "failed_statuses": sorted({str(r[2]) for r in fails})},
    }
    out = ROOT / "M4" / "drill" / "runs"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{label}.json").write_text(json.dumps(summary, indent=1) + "\n")
    m = lambda s: re.sub(r"\b\d{12}\b", "<acct>", s)
    text = [f"# incident-{label} — incident drill on the deployed system (M4 step 5)",
            f"# command: python M4/drill/incident_drill.py run --label {label}",
            f"# fault: {summary['fault']} · door {door}", "",
            "TIMELINE (UTC)", *log, "",
            f"time to detect:            {summary['time_to_detect_s']} s (by the {summary['detected_by']}; alarm fired: {summary['alarm_fired']})",
            f"time to rollback:          {summary['time_to_rollback_s']} s",
            f"time to verified recovery: {summary['time_to_verified_recovery_s']} s",
            f"canary: {len(canary.rows)} calls, {len(fails)} failed ({', '.join(summary['canary']['failed_statuses']) or 'none'})",
            f"user impact during the incident: {json.dumps(imp)}",
            "", f"RESULT: {'PASS — recovered and verified' if verified else 'FAIL — recovery not verified'}"]
    (ROOT / "M4" / "evidence" / f"incident-{label}.txt").write_text(m("\n".join(text)) + "\n")
    subprocess.run([sys.executable, str(ROOT / "M4/ops/dashboard_snapshot.py"), "--hours", "1",
                    "--name", f"incident-{label}-dashboard.png"], check=False)
    print(f"\nwrote M4/drill/runs/{label}.json and M4/evidence/incident-{label}.txt")
    return 0 if verified else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "rollback"])
    ap.add_argument("--label", default="drill-1")
    a = ap.parse_args()
    if a.cmd == "rollback":
        rollback()
        print("door config restored to the last-good")
    else:
        try:
            sys.exit(run(a.label))
        except BaseException:
            if LASTGOOD.exists() and lambda_config()["env"] != json.loads(LASTGOOD.read_text())["env"]:
                print("drill interrupted: restoring the last-good door config", flush=True)
                rollback()
            raise
