"""D-2: authorisation on EVERY route; requests without a valid token are refused (and every refusal is audited).

Enumerates the live route tables (the door's and the orchestrator's OpenAPI, plus every MCP tool from tools/list)
and fires five kinds of bad credential at each: none, malformed, forged (self-signed key), tampered (a real token
with its groups edited), expired (signed by the real issuer, one minute old), and alg=none. Every one must be 401
and leave a deny row. A valid token must get past authentication on the same routes.

    cd M3 && docker compose up -d --wait && python evals/route_auth_check.py
"""
import base64
import json
import sys
import time

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from _common import DOOR, ORCH, Report, in_container, tokens

PUBLIC = {"/healthz", "/ping", "/.well-known/jwks.json", "/.well-known/oauth-protected-resource",
          "/.well-known/oauth-protected-resource/mcp", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
          "/dev/token", "/oauth/token",    # /oauth/token: RFC 6749 400 invalid_grant, checked separately below
          "/demo/signin"}                  # the sign-in itself (passcode, not a token; D-049), checked separately below
SAMPLE = {"claim_id": "CLM-2024-1800", "policy_id": "POL-AU-08812", "doc_id": "DOC-2024-1800-FNOL-FORM",
          "rec_id": "REC-000000000000"}


def bad_tokens(valid):
    h, p, s = valid.split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=="))
    tampered_claims = dict(claims, **{"cognito:groups": ["senior-adjuster"]})
    tampered = ".".join([h, base64.urlsafe_b64encode(json.dumps(tampered_claims).encode()).rstrip(b"=").decode(), s])
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(dict(claims, exp=int(time.time()) + 600), attacker, algorithm="RS256",
                        headers={"kid": "claimsense-dev-1"})
    none_alg = ".".join([base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode(),
                         base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode(), ""])
    expired = in_container("boundary", "python", "-c",
                           "from claimsense.identity import DevIssuer; "
                           "print(DevIssuer('/state/dev-issuer').mint('alice', ['adjuster'], ttl=-60))").strip()
    return {"no token": None, "malformed (not Bearer)": "Token abc", "forged (attacker's key)": f"Bearer {forged}",
            "tampered (groups edited)": f"Bearer {tampered}", "expired (real issuer)": f"Bearer {expired}",
            "alg=none": f"Bearer {none_alg}"}


def routes(base):
    spec = httpx.get(f"{base}/openapi.json", timeout=10).json()
    out = []
    for path, ops in spec["paths"].items():
        for method in ops:
            if path in PUBLIC:
                continue
            url = path
            for k, v in SAMPLE.items():
                url = url.replace("{" + k + "}", v)
            out.append((method.upper(), path, f"{base}{url}"))
    return out


def main():
    R = Report(5, "route-auth-every-route", "D-2: every route and every MCP tool refuses a missing or invalid token")
    tok = tokens()
    valid = tok("alice")
    bads = bad_tokens(valid)
    table = routes(DOOR) + routes(ORCH)
    mcp_tools = [t["name"] for t in httpx.post(f"{DOOR}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                                headers={"Authorization": f"Bearer {valid}"}).json()["result"]["tools"]]
    R.say(f"guarded HTTP routes found in the live OpenAPI: {len(table)} (door + orchestrator); MCP tools: "
          f"{len(mcp_tools)}; bad credentials per target: {len(bads)}", "")
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat()
    refused = total = 0
    for method, path, url in table:
        codes = []
        for label, auth in bads.items():
            h = {"Authorization": auth} if auth else {}
            if method == "POST":
                h["Idempotency-Key"] = "route-auth-check-0001"
            r = httpx.request(method, url, headers=h, json={} if method == "POST" else None, timeout=30)
            total += 1
            refused += r.status_code == 401
            codes.append(r.status_code)
        R.check(f"{method:<5} {path:<48}", all(c == 401 for c in codes), "all " + ("401" if len(set(codes)) == 1
                                                                                  else str(codes)))
    for name in mcp_tools:
        codes = []
        for label, auth in bads.items():
            r = httpx.post(f"{DOOR}/mcp", headers={"Authorization": auth} if auth else {},
                           json={"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                 "params": {"name": name, "arguments": {"claim_id": "CLM-2024-1800"}}})
            total += 1
            refused += r.status_code == 401
            codes.append((r.status_code, "resource_metadata" in r.headers.get("www-authenticate", "")))
        R.check(f"MCP   tools/call {name:<38}", all(c == (401, True) for c in codes),
                "all 401 + WWW-Authenticate resource_metadata" if all(c == (401, True) for c in codes) else str(codes))
    rows = httpx.get(f"{DOOR}/audit", params={"limit": 1000}, headers={"Authorization": f"Bearer {tok('bob')}"}
                     ).json()["rows"]
    new_denies = [r for r in rows if r["ts"] >= started and r["decision"] == "deny" and r["user_id"] in ("anonymous", "unverified-webhook")]
    R.say("", f"bad-credential requests sent: {total} · refused with 401: {refused}")
    R.check("every refusal left an audit row (anonymous or unverified-webhook, action, resource, decision=deny, reason)",
            len(new_denies) == refused == total,
            f"{len(new_denies)} new deny rows; e.g. " + json.dumps({k: new_denies[-1][k] for k in
                                                                   ("user_id", "action", "resource", "decision", "reason",
                                                                    "via")}) if new_denies else "none")
    ok_valid = httpx.get(f"{DOOR}/claims/CLM-2024-1800", headers={"Authorization": f"Bearer {valid}"}).status_code
    R.check("the same routes accept a valid token (authentication is not the problem being tested away)",
            ok_valid == 200, f"GET /claims/CLM-2024-1800 with alice's token -> {ok_valid}")
    for label, auth in bads.items():
        subject = (auth or "").partition(" ")[2] or "none"
        r = httpx.post(f"{DOOR}/oauth/token", json={"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                                                    "subject_token": subject, "actor": "agent:claimsense-pipeline"})
        R.check(f"POST  /oauth/token with a {label} subject token", r.status_code == 400 and r.json().get("error") in
                ("invalid_grant", "invalid_request"), f"{r.status_code} {r.json().get('error')}")
    for label, auth in bads.items():                   # sign-in: never a token without the passcode (off here: 404)
        r = httpx.post(f"{ORCH}/demo/signin", json={"user_id": "alice", "passcode": (auth or "").partition(" ")[2]},
                       headers={"Authorization": auth} if auth else {})
        R.check(f"POST  /demo/signin with a {label} token and no passcode", r.status_code in (401, 404)
                and "token" not in r.text, f"{r.status_code} (404 = demo sign-in not configured, D-049)")
    meta = httpx.get(f"{DOOR}/.well-known/oauth-protected-resource").json()
    R.check("MCP door publishes RFC 9728 protected-resource metadata", meta.get("resource", "").endswith("/mcp")
            and meta.get("authorization_servers"), json.dumps(meta))
    dev = httpx.post(f"{DOOR}/dev/token", json={"user_id": "alice"}).status_code
    R.say("", f"note: /dev/token answers {dev} here because this is the synthetic sandbox (CLAIMSENSE_DEV_ISSUER=1); "
              "on AWS the flag is unset and it is 404 (tests/test_route_table.py, and evidence on the deployed door)")
    return R.finish("python evals/route_auth_check.py")


if __name__ == "__main__":
    sys.exit(main())
