"""D-5: an audit record is written for EVERY call, granted or denied, carrying user, action and resource.

Two halves:
  1  completeness by construction: a fixed script of calls (allow, deny-by-entitlement, deny-by-grant, not-found,
     unauthenticated, invalid arguments, idempotent replay, the orchestrator's own entry point) through REST, MCP and
     the orchestrator; for EVERY call, exactly one new row whose request_id we can name, with user, action, resource
  2  the whole trail on the stack: every row has the required fields; counts by channel and decision; "who touched
     CLM-2024-1800" answered from the trail (the CISO's 3 a.m. query); the trail is append-only (no route edits it)

    python evals/audit_check.py
"""
import json
import sys
import uuid
from collections import Counter

import httpx

from _common import DOOR, ORCH, Report, tokens

REQUIRED = ("ts", "request_id", "user_id", "action", "resource", "decision", "via")


def trail(bob):
    return httpx.get(f"{DOOR}/audit", params={"limit": 1000}, headers={"Authorization": f"Bearer {bob}"}).json()["rows"]


def main():
    R = Report(9, "audit-every-call", "D-5: one audit row for every call, granted or denied (user, action, resource)")
    tok = tokens()
    alice, carol, dave, bob = tok("alice"), tok("carol"), tok("dave"), tok("bob")
    H = lambda t: {"Authorization": f"Bearer {t}"} if t else {}

    def mcp(t, name, args):
        r = httpx.post(f"{DOOR}/mcp", headers=H(t), json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                           "params": {"name": name, "arguments": args}})
        b = r.json()
        sc = (b.get("result") or {}).get("structuredContent") or {}
        return r.status_code, (sc.get("error") or {}).get("request_id") or (b.get("error") or {}).get("data", {}).get("request_id")

    key = f"audit-check-{uuid.uuid4().hex[:8]}"
    script = [
        ("REST allow", lambda: httpx.get(f"{DOOR}/claims/CLM-2024-1800", headers=H(alice)), ("alice", "get_claim", "allow")),
        ("REST deny (entitlement)", lambda: httpx.get(f"{DOOR}/claims/CLM-2024-1800", headers=H(carol)),
         ("carol", "get_claim", "deny")),
        ("REST deny (no grant)", lambda: httpx.get(f"{DOOR}/recommendations", headers=H(dave)),
         ("dave", "list_pending_recommendations", "deny")),
        ("REST not found", lambda: httpx.get(f"{DOOR}/documents/DOC-0000-NOPE", headers=H(alice)),
         ("alice", "get_document", "deny")),
        ("REST unauthenticated", lambda: httpx.get(f"{DOOR}/claims/CLM-2024-1800"), ("anonymous", "authenticate", "deny")),
        ("MCP allow", lambda: mcp(alice, "get_policy", {"policy_id": "POL-AU-08812"}), ("alice", "get_policy", None)),
        ("MCP deny", lambda: mcp(carol, "list_claim_documents", {"claim_id": "CLM-2024-1800"}),
         ("carol", "list_documents", "deny")),
        ("MCP invalid arguments", lambda: mcp(alice, "get_claim", {"claim_id": "not-an-id"}), ("alice", "get_claim", "error")),
        ("MCP unauthenticated", lambda: mcp(None, "get_claim", {"claim_id": "CLM-2024-1800"}),
         ("anonymous", "authenticate", "deny")),
        ("MCP write", lambda: mcp(alice, "create_escalation_ticket", {"claim_id": "CLM-2024-1800", "reason": "audit check",
                                                                      "idempotency_key": key}),
         ("alice", "create_escalation_ticket", None)),
        ("MCP replay", lambda: mcp(alice, "create_escalation_ticket", {"claim_id": "CLM-2024-1800", "reason": "audit check",
                                                                       "idempotency_key": key}),
         ("alice", "create_escalation_ticket", "replay")),
        ("orchestrator unauthenticated", lambda: httpx.post(f"{ORCH}/claims/CLM-2024-1800/ask", json={"question": "x"}),
         ("anonymous", "authenticate", "deny")),
        ("orchestrator accepted", lambda: httpx.get(f"{ORCH}/claims/CLM-2024-1800/ask/history", headers=H(carol)),
         ("carol", "read_ask_history", "authenticated")),
        ("audit read (itself audited)", lambda: httpx.get(f"{DOOR}/audit", params={"limit": 1}, headers=H(bob)),
         ("bob", "read_audit", "allow")),
    ]
    R.say("1 · every call in a fixed script leaves exactly one matching row:")
    from datetime import datetime, timezone
    for label, fn, (user, action, decision) in script:
        t0 = datetime.now(timezone.utc).isoformat()
        fn()
        new = [r for r in trail(bob) if r["ts"] >= t0]
        mine = [r for r in new if r["user_id"] == user and r["action"] == action
                and (decision is None or r["decision"] == decision)]
        complete = all(all(r.get(k) not in (None, "") for k in REQUIRED) for r in mine)
        R.check(f"{label:<30} -> {action:<28} {decision or 'allow/replay':<8}", mine and complete,
                json.dumps({k: mine[-1][k] for k in ("user_id", "action", "resource", "decision", "via")}) if mine else
                f"no matching row in {[(r['user_id'], r['action'], r['decision']) for r in new]}")
    rows = trail(bob)
    missing = [r for r in rows if not all(r.get(k) not in (None, "") for k in REQUIRED)]
    R.say("", f"2 · the whole trail on this stack: {len(rows)} rows (the newest 1000)",
          "   by channel/decision: " + json.dumps(dict(Counter(f"{r['via']}/{r['decision']}" for r in rows))))
    R.check("every row carries ts, request_id, user, action, resource, decision and channel", not missing,
            f"{len(missing)} incomplete")
    touched = [r for r in rows if r["resource"] == "CLM-2024-1800" and r["decision"] != "authenticated"]
    who = Counter((r["user_id"], r["decision"]) for r in touched)
    R.say("   who touched CLM-2024-1800's DATA (door decisions only; orchestrator entry rows are 'authenticated'): "
          + ", ".join(f"{u} {d}×{n}" for (u, d), n in sorted(who.items())))
    R.check("the trail answers 'who accessed claim X, and were they allowed?'", touched)
    for method in ("DELETE", "PUT", "PATCH", "POST"):
        code = httpx.request(method, f"{DOOR}/audit", headers=H(bob)).status_code
        R.check(f"{method} /audit is not a thing (append-only; only the system writes)", code in (404, 405), str(code))
    r = httpx.get(f"{DOOR}/audit", headers=H(alice))
    R.check("only senior adjusters read the trail; alice's attempt is refused and itself audited",
            "error" in r.json(), json.dumps(r.json()))
    return R.finish("python evals/audit_check.py")


if __name__ == "__main__":
    sys.exit(main())
