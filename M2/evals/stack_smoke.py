"""Smoke-test the RUNNING stack (docker compose up): one claim per outcome, end to end through
console-facing APIs -> orchestrator -> boundary -> mock systems, plus a refusal and a human confirm.

    python M2/evals/stack_smoke.py            # writes M2/evidence/stack-smoke.txt
"""
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

ORCH, BOUNDARY = "http://localhost:8003", "http://localhost:8002"
RUNS = [("CS-001", "CLM-2024-1800", "alice", "approve"), ("CS-002", "CLM-2024-3104", "alice", "deny"),
        ("CS-004", "CLM-2024-1946", "alice", "route"), ("CS-009", "CLM-2024-3412", "alice", "flag_review"),
        ("CS-016", "CLM-2024-3602", "alice", "flag_review"), ("CS-019", "CLM-2024-1873", "dave", "refused")]


def main():
    out = [f"ClaimSense stack smoke · {time.strftime('%Y-%m-%d %H:%M:%S')}",
           f"orchestrator: {json.dumps(httpx.get(f'{ORCH}/healthz').json())}",
           f"boundary:     {json.dumps(httpx.get(f'{BOUNDARY}/healthz').json())}", ""]
    ok = True
    receipts = {}
    for case_id, claim, user, want in RUNS:
        r = httpx.post(f"{ORCH}/claims/{claim}/recommend", json={"user_id": user}, timeout=180).json()
        card = r["response"]
        got = card["outcome"]
        ok &= got == want
        rec = r.get("receipt") or {}
        receipts[claim] = rec.get("recommendation_id")
        out.append(f"{'PASS' if got == want else 'FAIL'}  {case_id} {claim} as {user:<6} -> {got:<12}"
                   f"{('→' + card['route_to']) if card.get('route_to') else '':<24} decided_by={r['decided_by']:<16}"
                   f" source={card.get('verdict_source')} guardrails={card.get('guardrails_fired', [])}"
                   f" draft={rec.get('recommendation_id', '-')} {r['latency_s']}s")
    # a human confirms the approval; the agent identity may not
    rid = receipts["CLM-2024-1800"]
    agent = httpx.post(f"{BOUNDARY}/recommendations/{rid}/confirm", json={"action": "confirm"},
                       headers={"X-User-Id": "agent:decision-draft", "Idempotency-Key": uuid.uuid4().hex}).json()
    human = httpx.post(f"{BOUNDARY}/recommendations/{rid}/confirm", json={"action": "confirm"},
                       headers={"X-User-Id": "alice", "Idempotency-Key": uuid.uuid4().hex}).json()
    ok &= agent.get("error", {}).get("code") == "human_confirmation_required" and human.get("confirmed_by") == "alice"
    out += ["", f"agent tries to confirm {rid}: {agent.get('error', {}).get('code')}",
            f"alice confirms {rid}: final_outcome={human.get('final_outcome')} confirmed_by={human.get('confirmed_by')}"]
    audit = httpx.get(f"{BOUNDARY}/audit?limit=400", headers={"X-User-Id": "bob"}).json()["rows"]
    denies = [a for a in audit if a["decision"] == "deny"]
    out += [f"audit rows: {len(audit)} (denials recorded: {len(denies)}; e.g. {denies[0]['action']} by "
            f"{denies[0]['user_id']} reason={denies[0]['reason']})" if denies else f"audit rows: {len(audit)}",
            "", f"STACK SMOKE: {'PASS' if ok else 'FAIL'}"]
    text = "\n".join(out)
    print(text)
    ev = Path(__file__).resolve().parents[1] / "evidence"
    ev.mkdir(exist_ok=True)
    (ev / "stack-smoke.txt").write_text(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
