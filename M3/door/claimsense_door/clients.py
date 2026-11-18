"""Two ways to call the door for the proofs: in-process (offline, $0, no containers) or over HTTP (the running stack
or the deployed API). Both speak MCP; both return (request_record, response) so the evidence can show the exact
request and response (D-4), with the bearer token redacted."""
import json
import os
import tempfile
from pathlib import Path

REDACTED = "Bearer <redacted JWT>"


class InProcess:
    """A fresh GrantedBoundary on the synthetic fixtures, its own temp audit trail and state."""

    def __init__(self, ticketing=None):
        tmp = Path(tempfile.mkdtemp(prefix="claimsense-door-"))
        os.environ["AUDIT_LOG"] = str(tmp / "audit.jsonl")
        from claimsense import audit_trail
        from .door import GrantedBoundary
        from .mcp import McpDoor
        audit_trail.VIA.set("mcp")
        self.b = GrantedBoundary(state_path=tmp / "door.db", ticketing=ticketing)
        self.door, self.mode, self.n = McpDoor(self.b), "in-process (offline, synthetic fixtures)", 0

    def call(self, user, tool, args, agent="agent:document-intake"):
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": "tools/call", "params": {"name": tool, "arguments": args}}
        req = {"transport": "in-process MCP", "acting_user": user, "on_behalf_of_agent": agent, "body": msg}
        res = self.door.handle(msg, user, agent)["result"]
        return req, res

    def audit(self, request_id=None):
        from claimsense import audit_trail
        rows = audit_trail.read()
        return [r for r in rows if r["request_id"] == request_id] if request_id else rows


class Http:
    """The running door: POST {base}/mcp with each user's real token (dev issuer locally, Cognito on AWS)."""

    def __init__(self, base, token_for, admin_user="bob"):
        import httpx
        self.base, self.token_for, self.admin = base.rstrip("/"), token_for, admin_user
        self.http, self.mode, self.n = httpx.Client(timeout=30), f"HTTP {self.base}/mcp", 0

    def call(self, user, tool, args, agent="agent:document-intake"):
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": "tools/call", "params": {"name": tool, "arguments": args}}
        headers = {"Authorization": f"Bearer {self.token_for(user)}", "Content-Type": "application/json",
                   "MCP-Protocol-Version": "2025-06-18", "X-On-Behalf-Of-Agent": agent}
        r = self.http.post(f"{self.base}/mcp", content=json.dumps(msg), headers=headers)
        req = {"method": "POST", "url": f"{self.base}/mcp",
               "headers": dict(headers, Authorization=REDACTED), "body": msg}
        body = r.json()
        res = body.get("result") or {"isError": True, "structuredContent": body.get("error"), "http_status": r.status_code}
        res["http_status"] = r.status_code
        return req, res

    def audit(self, request_id=None):
        r = self.http.get(f"{self.base}/audit", params={"limit": 1000},
                          headers={"Authorization": f"Bearer {self.token_for(self.admin)}"})
        rows = r.json().get("rows", [])
        return [x for x in rows if x["request_id"] == request_id] if request_id else rows


def dev_tokens(base):
    """Token minting via the local dev issuer (CLAIMSENSE_DEV_ISSUER=1 sandbox only; Cognito on AWS)."""
    import httpx
    cache = {}

    def token_for(user):
        if user not in cache:
            r = httpx.post(f"{base.rstrip('/')}/dev/token", json={"user_id": user}, timeout=10)
            r.raise_for_status()
            cache[user] = r.json()["token"]
        return cache[user]
    return token_for
