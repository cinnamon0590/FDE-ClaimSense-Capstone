"""Keycloak as the IdP that performs the on-behalf-of exchange itself (RFC 8693 standard token exchange, D-041).

    python keycloak/setup.py up      # from M3/: start the stack + Keycloak, build the `claimsense` realm ($0, local)
    python keycloak/setup.py down    # stop Keycloak, put the door back to its plain configuration

The realm mirrors the synthetic directory (M1 users.json): alice, bob, carol, dave, eve in their groups.
  claimsense-console       public client; the adjuster signs in here (direct grant, synthetic sandbox only).
                           Its access tokens name the orchestrator as an audience, so the orchestrator may exchange them.
  claimsense-orchestrator  confidential client with STANDARD TOKEN EXCHANGE enabled: the agents' runtime. It may ask
                           for any of the door's delegable actions as OPTIONAL scopes; nothing else (no confirm, no
                           audit read: those scopes do not exist in the realm, so asking for one is refused at the IdP).
  claimsense-door          the audience of exchanged tokens (the resource server; no login flows).

Throwaway credentials (admin, client secret, one password per synthetic user) are generated here and kept in
~/.claimsense/keycloak.json (0600, outside the repo). They are never printed.
"""
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
M3 = HERE.parent
ROOT = M3.parent
KC = "http://localhost:8180"
REALM = "claimsense"
CREDS = Path.home() / ".claimsense" / "keycloak.json"
COMPOSE = ["docker", "compose", "-f", str(M3 / "docker-compose.yml"), "-f", str(HERE / "docker-compose.keycloak.yml")]
sys.path[:0] = [str(M3 / "door"), str(ROOT / "M2")]
from claimsense_door.obo import AGENT_SCOPE  # noqa: E402

ACTIONS = AGENT_SCOPE.split()                      # the delegable actions; never confirm / read_audit / ticket_webhook


def creds():
    if CREDS.exists():
        return json.loads(CREDS.read_text())
    users = json.loads((ROOT / "M1" / "6-synthetic-data" / "fixtures" / "users.json").read_text())["records"]
    c = {"admin_password": secrets.token_urlsafe(24), "orchestrator_secret": secrets.token_urlsafe(32),
         "users": {u["user_id"]: {"password": secrets.token_urlsafe(18), "groups": u["groups"]} for u in users}}
    CREDS.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(CREDS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(c, f)
    return c


def http(method, url, token=None, body=None, form=None):
    headers = {}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def wait_ready(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if http("GET", f"{KC}/realms/master")[0] == 200:
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(3)
    raise SystemExit("Keycloak did not become ready")


def build_realm(c):
    st, tok = http("POST", f"{KC}/realms/master/protocol/openid-connect/token",
                   form={"client_id": "admin-cli", "grant_type": "password", "username": "claimsense-admin",
                         "password": c["admin_password"]})
    assert st == 200, f"admin login failed ({st})"
    t = tok["access_token"]
    A = f"{KC}/admin/realms/{REALM}"
    http("DELETE", A, t)                                                  # idempotent: rebuild from scratch
    st, _ = http("POST", f"{KC}/admin/realms", t, {"realm": REALM, "enabled": True, "accessTokenLifespan": 300})
    assert st == 201, f"realm create failed ({st})"

    def scope(name, mappers=()):
        st, _ = http("POST", f"{A}/client-scopes", t, {
            "name": name, "protocol": "openid-connect", "protocolMappers": list(mappers),
            "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"}})
        assert st == 201, (name, st)

    def audience(client_id):
        return {"name": f"aud-{client_id}", "protocol": "openid-connect", "protocolMapper": "oidc-audience-mapper",
                "config": {"included.client.audience": client_id, "access.token.claim": "true",
                           "id.token.claim": "false", "introspection.token.claim": "true"}}

    def client(rep):
        st, _ = http("POST", f"{A}/clients", t, rep)
        assert st == 201, (rep["clientId"], st)
        return http("GET", f"{A}/clients?clientId={rep['clientId']}", t)[1][0]["id"]

    door = client({"clientId": "claimsense-door", "publicClient": False, "standardFlowEnabled": False,
                   "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False, "bearerOnly": True})
    orch = client({"clientId": "claimsense-orchestrator", "publicClient": False,
                   "clientAuthenticatorType": "client-secret", "secret": c["orchestrator_secret"],
                   "standardFlowEnabled": False, "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
                   "attributes": {"standard.token.exchange.enabled": "true"}})
    console = client({"clientId": "claimsense-console", "publicClient": True, "standardFlowEnabled": False,
                      "directAccessGrantsEnabled": True})
    del door

    scope("claimsense-groups", [{"name": "groups", "protocol": "openid-connect",
                                 "protocolMapper": "oidc-group-membership-mapper",
                                 "config": {"claim.name": "groups", "full.path": "false", "access.token.claim": "true",
                                            "id.token.claim": "true", "userinfo.token.claim": "false"}}])
    scope("aud-claimsense-orchestrator", [audience("claimsense-orchestrator")])
    scope("aud-claimsense-door", [audience("claimsense-door")])
    for a in ACTIONS:
        scope(a)
    ids = {s["name"]: s["id"] for s in http("GET", f"{A}/client-scopes", t)[1]}
    for cid, defaults, optional in ((console, ["claimsense-groups", "aud-claimsense-orchestrator"], []),
                                    (orch, ["claimsense-groups", "aud-claimsense-door"], ACTIONS)):
        for n in defaults:
            assert http("PUT", f"{A}/clients/{cid}/default-client-scopes/{ids[n]}", t)[0] == 204, n
        for n in optional:
            assert http("PUT", f"{A}/clients/{cid}/optional-client-scopes/{ids[n]}", t)[0] == 204, n

    for g in sorted({g for u in c["users"].values() for g in u["groups"]}):
        assert http("POST", f"{A}/groups", t, {"name": g})[0] == 201, g
    for name, u in c["users"].items():
        st, _ = http("POST", f"{A}/users", t, {
            "username": name, "enabled": True, "email": f"{name}@autosure.example", "emailVerified": True,
            "firstName": name.capitalize(), "lastName": "Synthetic", "groups": [f"/{g}" for g in u["groups"]],
            "credentials": [{"type": "password", "value": u["password"], "temporary": False}]})
        assert st == 201, (name, st)
    print(f"realm `{REALM}` built: {len(c['users'])} synthetic users, clients console / orchestrator (standard "
          f"token exchange ON) / door, {len(ACTIONS)} delegable action scopes")


def main():
    cmd = (sys.argv[1:] or ["up"])[0]
    if cmd == "down":
        subprocess.run(COMPOSE + ["stop", "keycloak"], check=False)
        subprocess.run(COMPOSE + ["rm", "-f", "keycloak"], check=False)
        subprocess.run(["docker", "compose", "-f", str(M3 / "docker-compose.yml"), "up", "-d", "--wait",
                        "boundary"], check=True, env=dict(os.environ, MOCK_BRAIN=os.environ.get("MOCK_BRAIN", "1")))
        return
    c = creds()
    env = dict(os.environ, KC_BOOTSTRAP_ADMIN_PASSWORD=c["admin_password"],
               MOCK_BRAIN=os.environ.get("MOCK_BRAIN", "1"))
    subprocess.run(COMPOSE + ["up", "-d", "--wait"], check=True, env=env, stdout=subprocess.DEVNULL)
    wait_ready()
    build_realm(c)


if __name__ == "__main__":
    main()
