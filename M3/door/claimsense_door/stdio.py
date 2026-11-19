"""stdio transport for the ClaimSense MCP door (Claude Code, Claude Desktop, IDEs) + the protocol self-test.

    python -m claimsense_door.stdio --selftest       # initialize -> list -> call -> dedupe -> deny -> enumerate
    claude mcp add claimsense -- env CLAIMSENSE_ACTING_TOKEN=<adjuster's token> python -m claimsense_door.stdio

Identity is SERVER-side configuration, never a tool argument (the W16 discipline): the process acts as the user in
CLAIMSENSE_ACTING_TOKEN, a token verified against the issuer's JWKS (Cognito's, or the local dev issuer's) exactly
like the HTTP door. A model connected to this server cannot name another user. Logs go to stderr only; stdout is
the JSON-RPC channel.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

from .mcp import McpDoor


def _log(*a):
    print(*a, file=sys.stderr, flush=True)


def _acting_user(boundary):
    from claimsense.identity import DevIssuer, IdentityError, Verifier, resolve
    token = os.environ.get("CLAIMSENSE_ACTING_TOKEN", "")
    jwks_url = os.environ.get("CLAIMSENSE_JWKS_URL")
    verifier = Verifier(jwks_url=jwks_url) if jwks_url else Verifier(jwks=DevIssuer().jwks())
    try:
        return resolve(f"Bearer {token}" if token else None, None, verifier, boundary.users)
    except IdentityError as e:
        _log(f"claimsense-door: refusing to start: {e} (set CLAIMSENSE_ACTING_TOKEN)")
        raise SystemExit(2)


def serve(boundary=None):
    from claimsense import audit_trail
    from .door import GrantedBoundary
    boundary = boundary or GrantedBoundary()
    user = _acting_user(boundary)
    audit_trail.VIA.set("mcp-stdio")
    door = McpDoor(boundary)
    _log(f"claimsense-door (stdio) acting as {user}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = door.handle(msg, user, os.environ.get("CLAIMSENSE_ACTING_AGENT"))
        if out is not None:
            sys.stdout.write(json.dumps(out, default=str) + "\n")
            sys.stdout.flush()


class _MockTicketing:
    """In-process stand-in for the ticketing system (self-test only): idempotent by key."""

    def __init__(self):
        self.by_key, self.n = {}, 0

    def create(self, payload, key):
        if key in self.by_key:
            return dict(self.by_key[key], idempotent_replay=True)
        self.n += 1
        t = {"ticket_id": f"SIU-{9000 + self.n}", "claim_id": payload["claim_id"], "status": "open", "seq": 1}
        self.by_key[key] = t
        return dict(t)


def selftest():
    """Drive the full protocol in-process, as the lab's meridian_slack_mcp.py --selftest does."""
    tmp = Path(tempfile.mkdtemp(prefix="claimsense-door-selftest-"))
    os.environ["AUDIT_LOG"] = str(tmp / "audit.jsonl")
    from claimsense import audit_trail
    from .door import GrantedBoundary
    b = GrantedBoundary(state_path=tmp / "door.db", ticketing=_MockTicketing())
    door = McpDoor(b)
    audit_trail.VIA.set("mcp-selftest")
    ok, lines = True, []

    def call(n, user, name, args):
        r = door.handle({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                         "params": {"name": name, "arguments": args}}, user, "agent:selftest")
        return r["result"]["isError"], r["result"]["structuredContent"]

    init = door.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "selftest", "version": "0"}}},
        "alice")
    ok &= init["result"]["protocolVersion"] == "2025-06-18"
    lines.append(f"  initialize: ok (protocol {init['result']['protocolVersion']}, server "
                 f"{init['result']['serverInfo']['name']})")
    ok &= door.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, "alice") is None
    tools = [t["name"] for t in door.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, "alice")
             ["result"]["tools"]]
    ok &= len(tools) == 10
    lines.append(f"  tools/list: ok ({len(tools)} tools: {', '.join(tools)})")
    err, out = call(3, "alice", "get_claim", {"claim_id": "CLM-2024-1800"})
    ok &= not err and out.get("claim_id") == "CLM-2024-1800"
    lines.append(f"  tools/call #3 get_claim as alice (adjuster): isError={err} claim={out.get('claim_id')}")
    args = {"claim_id": "CLM-2024-1800", "reason": "Photos contradict the narrative; SIU review requested.",
            "priority": "high", "idempotency_key": "selftest-esc-0001"}
    err, first = call(4, "alice", "create_escalation_ticket", args)
    err2, replay = call(5, "alice", "create_escalation_ticket", args)
    ok &= not err and not err2 and first["ticket_id"] == replay["ticket_id"] and replay["idempotent_replay"]
    lines.append(f"  tools/call #4/#5 create_escalation_ticket twice, same key: ticket {first['ticket_id']} "
                 f"both times, replay marked={replay['idempotent_replay']}")
    err, denied = call(6, "carol", "get_claim", {"claim_id": "CLM-2024-1800"})
    row = [r for r in b.audit if r["request_id"] == denied["error"]["request_id"]][0]
    ok &= err and denied["error"]["code"] == "not_found_or_forbidden" and row["decision"] == "deny"
    lines.append(f"  tools/call #6 get_claim as carol (fraud-investigator, not her claim): isError={err} "
                 f"error={denied['error']['code']} audit_decision={row['decision']}")
    err, missing = call(7, "carol", "get_claim", {"claim_id": "CLM-2099-0001"})
    same = (missing["error"]["code"], missing["error"]["message"]) == (denied["error"]["code"],
                                                                         denied["error"]["message"])
    ok &= err and same
    lines.append(f"  tools/call #7 get_claim for a claim that does not exist: identical denial={same} (no enumeration)")
    err, nogrant = call(8, "dave", "search_policy_clauses", {"query": "windscreen deductible"})
    ok &= err and nogrant["error"]["code"] == "not_found_or_forbidden"
    lines.append(f"  tools/call #8 search_policy_clauses as dave (customer-service, no grant): isError={err} (deny-by-default)")
    err, bad = call(9, "alice", "get_claim", {"claim_id": "CLM-2024-1800", "user_id": "bob"})
    ok &= err and bad["error"]["code"] == "invalid_request"
    lines.append("  tools/call #9 get_claim with a smuggled user_id argument: isError=True (identity is never an "
                 "argument)")
    ok &= all({"user_id", "action", "resource", "decision"} <= r.keys() for r in audit_trail.read())
    lines.append(f"  audit: {len(audit_trail.read())} rows, every one with user, action, resource and decision")
    print("CLAIMSENSE MCP DOOR: selftest")
    print("\n".join(lines))
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        raise SystemExit(selftest())
    serve()
