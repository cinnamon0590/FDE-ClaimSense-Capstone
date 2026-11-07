"""Prove restart survival on the RUNNING containers (D-027): kill the orchestrator mid-claim, let Docker
restart it, resume by run_id; restart the boundary twice and show drafts, idempotency, confirmations and the
audit trail survive. $0 on the replay brain. Writes M2/evidence/restart-survival.txt.

    cd M2 && MOCK_BRAIN=1 docker compose -f docker-compose.yml -f restart-test.compose.yml up --build -d --wait
    python M2/evals/restart_survival.py
"""
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

M2 = Path(__file__).resolve().parents[1]
ORCH, BOUNDARY = "http://127.0.0.1:8003", "http://127.0.0.1:8002"
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "restart-test.compose.yml"]
CLAIM, USER = "CLM-2024-1800", "alice"


def sh(*args):
    return subprocess.run([*COMPOSE, *args], cwd=M2, check=True, capture_output=True, text=True).stdout.strip()


def restarts(service):
    cid = sh("ps", "-q", service)
    return int(subprocess.run(["docker", "inspect", "-f", "{{.RestartCount}}", cid], check=True,
                              capture_output=True, text=True).stdout.strip())


def wait_healthy(url, seconds=90):
    end = time.time() + seconds
    while time.time() < end:
        try:
            if httpx.get(f"{url}/healthz", timeout=2).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"{url} did not come back")


def main():
    out, ok = [f"ClaimSense restart-survival proof · {time.strftime('%Y-%m-%d %H:%M:%S')}"], True

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        out.append(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))

    health = httpx.get(f"{ORCH}/healthz").json()
    out += [f"orchestrator brain={health['brain']} · fault injection enabled for this test only", ""]
    run_id = f"{CLAIM}:restart-{uuid.uuid4().hex[:8]}"

    out.append("1 · Kill the orchestrator mid-claim (right after Coverage is checkpointed)")
    before = restarts("orchestrator")
    try:
        httpx.post(f"{ORCH}/claims/{CLAIM}/recommend", json={"user_id": USER, "run_id": run_id,
                                                             "crash_after_step": "coverage"}, timeout=60)
        died = False
    except httpx.HTTPError as e:
        died = True
        out.append(f"     request dropped: {type(e).__name__} (process exited)")
    check("orchestrator process died mid-claim", died)
    wait_healthy(ORCH)
    time.sleep(1)
    check("Docker restarted it (restart policy)", restarts("orchestrator") > before,
          f"RestartCount {before} -> {restarts('orchestrator')}")

    out += ["", "2 · Resume the same run_id on the restarted process"]
    r = httpx.post(f"{ORCH}/claims/{CLAIM}/recommend", json={"user_id": USER, "run_id": run_id}, timeout=120).json()
    restored = [e["name"].replace(" restored from checkpoint", "") for e in r["events"] if e["kind"] == "checkpoint"]
    started = [e["name"] for e in r["events"] if e["kind"] == "agent_start"]
    check("run resumed from checkpoints", r.get("resumed") is True)
    check("finished agents restored, not re-run", restored == ["Document Intake", "Coverage Check"],
          f"restored {restored}; ran {started}")
    check("no usage billed for restored agents",
          not {"Document Intake", "Coverage Check"} & {u["agent"] for u in r["usage"]})
    check("claim completed with a model verdict", r["decided_by"] == "agents" and r["response"]["outcome"] == "approve",
          f"{r['response']['outcome']} · verdict_source={r['response']['verdict_source']}")
    rec = r["receipt"]["recommendation_id"]
    out.append(f"     draft written back: {rec}")

    out += ["", "3 · Restart the boundary; replay the same run"]
    sh("restart", "boundary")
    wait_healthy(BOUNDARY)
    again = httpx.post(f"{ORCH}/claims/{CLAIM}/recommend", json={"user_id": USER, "run_id": run_id}, timeout=120).json()
    check("draft survived the boundary restart; no duplicate written",
          again["receipt"]["recommendation_id"] == rec and again["receipt"]["idempotent_replay"] is True,
          f"receipt {again['receipt']['recommendation_id']} idempotent_replay={again['receipt']['idempotent_replay']}")
    check("fully restored run costs nothing", again["cost_usd"] == 0, f"${again['cost_usd']}")

    out += ["", "4 · A human confirms; restart the boundary again; the decision holds exactly once"]
    key = uuid.uuid4().hex
    conf = httpx.post(f"{BOUNDARY}/recommendations/{rec}/confirm", json={"action": "confirm"},
                      headers={"X-User-Id": USER, "Idempotency-Key": key}).json()
    check("alice confirms", conf.get("confirmed_by") == USER)
    audit_before = len(httpx.get(f"{BOUNDARY}/audit?limit=100000", headers={"X-User-Id": "bob"}).json()["rows"])
    sh("restart", "boundary")
    wait_healthy(BOUNDARY)
    replay = httpx.post(f"{BOUNDARY}/recommendations/{rec}/confirm", json={"action": "confirm"},
                        headers={"X-User-Id": USER, "Idempotency-Key": key}).json()
    check("same key after restart replays the original receipt", replay.get("idempotent_replay") is True)
    second = httpx.post(f"{BOUNDARY}/recommendations/{rec}/confirm",
                        json={"action": "override", "final_outcome": "deny", "override_reason": "second try"},
                        headers={"X-User-Id": USER, "Idempotency-Key": uuid.uuid4().hex}).json()
    check("a second decision under a new key is refused", second.get("error", {}).get("code") == "already_confirmed")
    audit_after = len(httpx.get(f"{BOUNDARY}/audit?limit=100000", headers={"X-User-Id": "bob"}).json()["rows"])
    check("audit trail survived both restarts", audit_after >= audit_before, f"{audit_before} rows before, {audit_after} after")

    out += ["", f"RESTART SURVIVAL: {'PASS' if ok else 'FAIL'}"]
    text = "\n".join(out)
    print(text)
    (M2 / "evidence" / "restart-survival.txt").write_text(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
