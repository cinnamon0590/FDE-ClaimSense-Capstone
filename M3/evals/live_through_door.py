"""The LIVE gate through the governed door: all 40 cases on the pinned live models (gpt-4o-mini-2024-07-18 +
gpt-4o-2024-08-06), with EVERY agent data access an MCP tool call on the door, made with a delegated OBO token, and
the Policy KB served by the door's BM25 search. Same gate as M2 (D-035): overall >= 90%, adversarial 100%, every case
decided by the model (never the rule-engine fallback). The cost is summed from the runs and appended to the spend
ledger. Approved by Susan (2026-11-18, about $0.70).

    cd M3 && docker compose down -v && MOCK_BRAIN=0 docker compose up -d --wait && python evals/live_through_door.py
"""
import json
import sys
import time

import httpx

from _common import M3, ORCH, ROOT, Report, tokens

sys.path[:0] = [str(ROOT / "M2")]
from claimsense._m1 import score  # noqa: E402
from claimsense.cases import all_cases  # noqa: E402


def main():
    R = Report(15, "live-gate-through-the-door", "the live 40-case gate with every agent data access through /mcp (OBO)")
    health = httpx.get(f"{ORCH}/healthz").json()
    R.say(f"orchestrator: brain={health['brain']} · models={health['models']} · retrieval={health['retrieval']} · "
          "data: MCP door (/mcp) with RFC 8693 delegated tokens", "")
    if health["brain"] != "live":
        R.check("the orchestrator is on the LIVE brain", False, health["brain"])
        return R.finish("python evals/live_through_door.py")
    tok = tokens()
    cases, passed, adv_total, adv_pass, not_model, cost, lat = all_cases(), 0, 0, 0, [], 0.0, []
    for c in cases:
        t0 = time.time()
        r = httpx.post(f"{ORCH}/claims/{c['claim']['claim_id']}/recommend", json={},
                       headers={"Authorization": f"Bearer {tok(c['requesting_user']['id'])}"}, timeout=300).json()
        lat.append(time.time() - t0)
        resp = dict(r["response"])
        if "citations" in resp:
            resp["citations"] = [x["source_id"] for x in resp["citations"]]
            resp["returns_claim_data"] = True
        why = score.fail_reason(c, resp)
        model = r.get("decided_by") != "fallback" and resp.get("verdict_source") == "model"
        if not model:
            not_model.append(c["case_id"])
        cost += float(r.get("cost_usd") or 0)
        passed += why is None
        if c["category"] == "adversarial":
            adv_total += 1
            adv_pass += why is None
        got = resp.get("outcome", "?") + (f"→{resp['route_to']}" if resp.get("route_to") else "")
        R.say(f"  {'PASS' if why is None else 'FAIL'}  {c['case_id']}  {c['category']:<11} {got:<32} "
              f"{r.get('decided_by'):<16} engine={'model' if model else 'rule-engine'}" + (f"  ({why})" if why else ""))
    lat.sort()
    R.say("", f"pass rate: {passed}/{len(cases)} = {passed / len(cases):.0%} · adversarial {adv_pass}/{adv_total} · "
              f"model-decided {len(cases) - len(not_model)}/{len(cases)}",
          f"cost: ${cost:.4f} total · ${cost / len(cases):.5f} per claim · p95 latency {lat[int(0.95 * len(lat)) - 1]:.1f}s")
    R.check("overall >= 90% (the M2 gate, never lowered)", passed / len(cases) >= 0.90)
    R.check("adversarial = 100%", adv_pass == adv_total)
    R.check("every case decided by the model (no rule-engine fallback)", not not_model, ", ".join(not_model))
    ledger = ROOT / "M2" / "evals" / "spend-ledger.jsonl"
    with ledger.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "suite": "m3-live-through-door", "cases": len(cases),
                            "brain": "live", "provider": "openai", "cost_usd": round(cost, 4)}) + "\n")
    total = sum(json.loads(x)["cost_usd"] for x in ledger.read_text().splitlines() if x.strip())
    (ROOT / "SPEND.txt").write_text(f"{total:.2f}\n")
    R.say(f"spend ledger updated: cumulative ${total:.2f} (SPEND.txt)")
    return R.finish("python evals/live_through_door.py")


if __name__ == "__main__":
    sys.exit(main())
