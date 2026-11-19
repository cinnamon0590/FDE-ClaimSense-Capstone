"""OBO with a real IdP doing the exchange ITSELF (Architect tier, D-041): Keycloak's RFC 8693 standard token exchange,
the exchanged token's scope driving the door's _authorize. Needs `python keycloak/setup.py up` first ($0, local).

  1  alice signs in at Keycloak (console client)        -> a token for the ORCHESTRATOR, not usable at the door
  2  the orchestrator exchanges it AT KEYCLOAK            -> 5 min, aud = the door, azp = orchestrator, scope = asked
  3  the exchanged token calls get_claim on the door      -> allowed; audit names alice AND the agent
  4  ... calls get_policy (alice is granted it; the token does not carry it) -> refused by the TOKEN's scope, audited
  5  asking Keycloak for confirm_recommendation           -> refused at the IdP (invalid_scope): never delegable
  6  alice's sign-in token presented to the door directly  -> 401 (not exchanged for the door)
  7  carol's exchanged token, alice's claim               -> the identical not-found-or-forbidden denial (entitlement)
  8  dave's exchanged token asks for policy search        -> Keycloak issues it; the door's grants still refuse it
  9  a tampered exchanged token (scope widened)            -> 401, signature fails
 10  no client secret / wrong secret                      -> Keycloak refuses the exchange (unauthorized_client)

    python evals/keycloak_obo_check.py
"""
import base64
import json
import os
import sys
from pathlib import Path

import httpx
import jwt

from _common import DOOR, Report, tokens

KC = os.environ.get("KEYCLOAK_URL", "http://localhost:8180").rstrip("/")
TOKEN_URL = f"{KC}/realms/claimsense/protocol/openid-connect/token"
GT = "urn:ietf:params:oauth:grant-type:token-exchange"
AT = "urn:ietf:params:oauth:token-type:access_token"
CREDS = json.loads((Path.home() / ".claimsense" / "keycloak.json").read_text())
CLAIM = "CLM-2024-1800"
SHOW = ("iss", "aud", "azp", "preferred_username", "groups", "scope")


def signin(user):
    r = httpx.post(TOKEN_URL, data={"client_id": "claimsense-console", "grant_type": "password", "username": user,
                                    "password": CREDS["users"][user]["password"], "scope": "openid"})
    r.raise_for_status()
    return r.json()["access_token"]


def exchange(subject, scope, secret=None):
    return httpx.post(TOKEN_URL, data={"client_id": "claimsense-orchestrator",
                                       "client_secret": CREDS["orchestrator_secret"] if secret is None else secret,
                                       "grant_type": GT, "subject_token": subject, "subject_token_type": AT,
                                       "requested_token_type": AT, "audience": "claimsense-door", "scope": scope})


def claims(tok):
    c = jwt.decode(tok, options={"verify_signature": False})
    return {k: c[k] for k in SHOW if k in c} | {"lifetime_s": c["exp"] - c["iat"]}


def mcp(token, name, args, n=[0]):
    n[0] += 1
    r = httpx.post(f"{DOOR}/mcp", headers={"Authorization": f"Bearer {token}"}, timeout=30,
                   json={"jsonrpc": "2.0", "id": n[0], "method": "tools/call",
                         "params": {"name": name, "arguments": args}})
    return r.status_code, (r.json().get("result") if r.status_code == 200 else None)


def audit_row(rid):
    bob = tokens()("bob")
    rows = httpx.get(f"{DOOR}/audit", params={"limit": 1000}, headers={"Authorization": f"Bearer {bob}"}).json()["rows"]
    return next((r for r in rows if r["request_id"] == rid), None)


def last_allow(user, action, resource):
    bob = tokens()("bob")
    rows = httpx.get(f"{DOOR}/audit", params={"limit": 1000}, headers={"Authorization": f"Bearer {bob}"}).json()["rows"]
    hits = [r for r in rows if r.get("user_id") == user and r["action"] == action and r["resource"] == resource
            and r["decision"] == "allow"]
    return hits[-1] if hits else None


def brief(r):
    return json.dumps({k: r.get(k) for k in ("acting_identity", "scope", "on_behalf_of_agent", "action", "resource",
                                             "decision", "reason", "via")}) if r else "MISSING"


def main():
    R = Report(19, "keycloak-obo-exchange", "OBO with a real IdP: Keycloak performs the RFC 8693 exchange; its scope "
                                            "drives _authorize")
    meta = httpx.get(f"{DOOR}/.well-known/oauth-protected-resource").json()
    R.say(f"Keycloak realm: {KC}/realms/claimsense (quay.io/keycloak/keycloak:26.2.5, standard token exchange)",
          f"door's protected-resource metadata lists it: {meta['authorization_servers']}", "")
    R.check("the door advertises Keycloak as an authorization server (RFC 9728)",
            f"{KC}/realms/claimsense" in meta["authorization_servers"])

    s = signin("alice")
    R.say("1  alice signs in at Keycloak (console client). Sign-in token claims:", f"     {claims(s)}")
    R.check("the sign-in token is addressed to the orchestrator, not the door",
            "claimsense-door" not in (jwt.decode(s, options={"verify_signature": False})["aud"]))

    r = exchange(s, "get_claim search_policy_clauses")
    x = r.json().get("access_token", "")
    c = claims(x) if x else r.json()
    R.say("2  the orchestrator exchanges it AT KEYCLOAK (grant_type token-exchange, audience claimsense-door,",
          "   scope 'get_claim search_policy_clauses'). Exchanged token claims (signature not shown):", f"     {c}")
    R.check("Keycloak issued the exchanged token (HTTP 200, issued_token_type access_token)",
            r.status_code == 200 and r.json().get("issued_token_type") == AT, f"HTTP {r.status_code}")
    R.check("exchanged token: aud = the door only, azp = the orchestrator, user and groups kept, 5-minute life",
            c.get("aud") == "claimsense-door" and c.get("azp") == "claimsense-orchestrator"
            and c.get("preferred_username") == "alice" and c.get("groups") == ["adjuster"] and c["lifetime_s"] <= 300)

    st, out = mcp(x, "get_claim", {"claim_id": CLAIM})
    row = last_allow("alice", "get_claim", CLAIM)
    R.say("3  get_claim with the exchanged token:", f"     HTTP {st} isError={out and out['isError']}",
          f"     audit: {brief(row)}")
    R.check("allowed, and the audit row names alice AND the agent that exchanged",
            st == 200 and not out["isError"] and row and row["on_behalf_of_agent"] == "agent:claimsense-orchestrator")

    st, out = mcp(x, "get_policy", {"policy_id": "POL-AU-10418"})
    err = (out or {}).get("structuredContent", {}).get("error", {})
    row = audit_row(err.get("request_id"))
    R.say("4  get_policy with the same token (alice IS granted get_policy; the exchanged scope does not carry it):",
          f"     HTTP {st} error={err.get('code')}", f"     audit: {brief(row)}")
    R.check("refused by the exchanged token's scope, and the refusal is audited",
            out and out["isError"] and row and row["decision"] == "deny"
            and row["reason"] == "outside the delegated token's scope")

    r = exchange(s, "get_claim confirm_recommendation")
    R.say("5  asking Keycloak for confirm_recommendation:", f"     HTTP {r.status_code} {r.json()}")
    R.check("refused at the IdP: confirming is never delegable (no such scope in the realm)",
            r.status_code == 400 and r.json().get("error") == "invalid_scope")

    st, _ = mcp(s, "get_claim", {"claim_id": CLAIM})
    R.say("6  alice's raw sign-in token presented to the door:", f"     HTTP {st}")
    R.check("401: a token not exchanged for the door is refused", st == 401)

    xc = exchange(signin("carol"), "get_claim").json()["access_token"]
    st, out = mcp(xc, "get_claim", {"claim_id": CLAIM})
    err = (out or {}).get("structuredContent", {}).get("error", {})
    st2, out2 = mcp(xc, "get_claim", {"claim_id": "CLM-2099-0001"})
    err2 = (out2 or {}).get("structuredContent", {}).get("error", {})
    R.say("7  carol (fraud-investigator) exchanges for get_claim and asks for alice's claim:",
          f"     {err.get('code')}: {err.get('message')}  ·  a claim that does not exist: {err2.get('code')}: "
          f"{err2.get('message')}", f"     audit: {brief(audit_row(err.get('request_id')))}")
    R.check("the exchanged scope does not widen entitlement: identical denial for 'not yours' and 'missing'",
            err.get("code") == "not_found_or_forbidden"
            and (err.get("code"), err.get("message")) == (err2.get("code"), err2.get("message")))

    r = exchange(signin("dave"), "search_policy_clauses")
    xd = r.json().get("access_token", "")
    st, out = mcp(xd, "search_policy_clauses", {"query": "windscreen deductible"})
    err = (out or {}).get("structuredContent", {}).get("error", {})
    R.say("8  dave (customer-service) gets an exchanged token for search_policy_clauses from Keycloak:",
          f"     Keycloak HTTP {r.status_code}; door: {err.get('code')}",
          f"     audit: {brief(audit_row(err.get('request_id')))}")
    R.check("the IdP's scope is necessary, not sufficient: the door's grants (deny-by-default) still refuse dave",
            r.status_code == 200 and err.get("code") == "not_found_or_forbidden")

    h, p, sig = x.split(".")
    body = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
    body["scope"] += " get_policy list_documents"
    forged = ".".join([h, base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("="), sig])
    st, _ = mcp(forged, "get_policy", {"policy_id": "POL-AU-10418"})
    R.say("9  the exchanged token with its scope widened by hand (signature kept):", f"     HTTP {st}")
    R.check("401: the signature no longer verifies", st == 401)

    r1, r2 = exchange(s, "get_claim", secret=""), exchange(s, "get_claim", secret="guessed-secret")
    R.say("10 exchange without / with a wrong orchestrator secret:",
          f"     HTTP {r1.status_code} {r1.json().get('error')} · HTTP {r2.status_code} {r2.json().get('error')}")
    R.check("Keycloak refuses: only the authenticated orchestrator may exchange", r1.status_code in (400, 401)
            and r2.status_code in (400, 401))
    return R.finish("python evals/keycloak_obo_check.py   (after: python keycloak/setup.py up)")


if __name__ == "__main__":
    sys.exit(main())
