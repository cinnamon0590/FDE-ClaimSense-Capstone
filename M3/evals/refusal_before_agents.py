"""D-3: access control runs in deterministic code BEFORE any agent is invoked (never a prompt).

On the running stack: an entitled adjuster's run (the baseline: agents run, MCP tool calls happen) versus three
refusals that must start ZERO agents, make ZERO model calls, cost $0, return no claim data, and leave deny rows:
  * carol (fraud-investigator) asks for a first-pass adjuster's claim      -> refused by the RECORD gate
  * dave  (customer-service) asks for the same claim                       -> refused by the ACTION gate (no grant)
  * nobody (no token)                                                       -> refused before the route runs (401)
Also: the access rule is not in any prompt. The agents' instructions are scanned for authorisation logic.

    python evals/refusal_before_agents.py
"""
import json
import sys

import httpx

from _common import ORCH, ROOT, Report, tokens

AGENT_EVENTS = {"agent", "handoff", "tool", "agent_start", "agent_end", "llm", "model"}


def run(claim, token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.post(f"{ORCH}/claims/{claim}/recommend", json={}, headers=h, timeout=300)


def summary(r):
    if r.status_code != 200:
        return {"http": r.status_code, "body": r.json()}
    j = r.json()
    ev = j.get("events", [])
    return {"http": 200, "outcome": j["response"].get("outcome"), "decided_by": j.get("decided_by"),
            "returns_claim_data": j["response"].get("returns_claim_data", "citations" in j["response"]),
            "agent_events": [e["kind"] + ":" + str(e.get("name")) for e in ev if e["kind"] in AGENT_EVENTS],
            "model_calls": len(j.get("usage", [])), "cost_usd": j.get("cost_usd"),
            "event_kinds": sorted({e["kind"] for e in ev})}


def main():
    R = Report(6, "access-control-before-agents", "D-3: access control in code, executed before any agent runs")
    tok = tokens()
    claim = "CLM-2024-1800"
    base = summary(run(claim, tok("alice")))
    R.say("baseline (alice, adjuster, entitled): " + json.dumps({k: base[k] for k in ("outcome", "decided_by",
                                                                                     "model_calls")}))
    R.check("the entitled run does start the agents (so the counter below is meaningful)",
            base["agent_events"] or base["model_calls"] or base["decided_by"] == "agents",
            f"{len(base['agent_events'])} agent/tool events")
    for who in ("carol", "dave"):
        s = summary(run(claim, tok(who)))
        R.say("", f"{who}: " + json.dumps(s))
        R.check(f"{who}: refused, no claim data, decided_by=boundary_refusal",
                s.get("outcome") == "refused" and s.get("returns_claim_data") is False
                and s.get("decided_by") == "boundary_refusal")
        R.check(f"{who}: ZERO agents started, ZERO model calls, $0", not s["agent_events"] and s["model_calls"] == 0
                and not s["cost_usd"], f"event kinds: {s['event_kinds']}")
    s = summary(run(claim))
    R.say("", "no token: " + json.dumps(s))
    R.check("no token: 401 before the route runs", s.get("http") == 401)
    rows = httpx.get(f"{ORCH.replace('8003', '8002')}/audit", params={"limit": 1000, "claim_id": claim},
                     headers={"Authorization": f"Bearer {tok('bob')}"}).json()["rows"]
    allrows = httpx.get(f"{ORCH.replace('8003', '8002')}/audit", params={"limit": 1000},
                        headers={"Authorization": f"Bearer {tok('bob')}"}).json()["rows"]
    for who, gate in (("carol", "not_entitled"), ("dave", "no_grant")):
        # carol: her delegated token works, the RECORD gate refuses the claim; dave: no grants, so the OBO exchange
        # itself is refused (no delegable scope) and the agents never even get a token
        d = [r for r in rows + allrows if r["user_id"] == who and r["decision"] == "deny"]
        R.check(f"{who}'s refusal is in the audit trail (reason={gate})", any(r["reason"].startswith(gate) for r in d),
                json.dumps({k: d[-1][k] for k in ("user_id", "action", "resource", "decision", "reason", "via")})
                if d else "none")
    prompts = (ROOT / "M2" / "claimsense" / "agents_def.py").read_text().lower()
    leaks = [w for w in ("entitled", "assigned_group", "senior-adjuster may", "only show", "not allowed to see")
             if w in prompts]
    R.check("no authorisation rule lives in an agent prompt (the gate is code: grants.json + entitled())",
            not leaks, f"authorisation phrases found in agents_def.py: {leaks or 'none'}")
    return R.finish("python evals/refusal_before_agents.py")


if __name__ == "__main__":
    sys.exit(main())
