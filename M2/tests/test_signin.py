"""Per-user sign-in for the deployed console (D-056, replacing the D-049 demo passcode + user picker): each person
signs in with THEIR OWN Cognito username and password; nothing picks an identity for them. Cognito is stubbed."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

M2 = Path(__file__).resolve().parents[1]
PASSWORDS = {"alice": "Alice-pw-1!", "carol": "Carol-pw-2!"}


def _load(monkeypatch, on=True):
    monkeypatch.setenv("CLAIMSENSE_SIGNIN_POOL_ID", "pool" if on else "")
    monkeypatch.setenv("CLAIMSENSE_SIGNIN_CLIENT_ID", "client" if on else "")
    spec = importlib.util.spec_from_file_location(f"orch_signin_{on}", M2 / "services" / "orchestrator" / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    return app


@pytest.fixture()
def signin(monkeypatch):
    app = _load(monkeypatch)
    calls = []

    class NotAuthorizedException(Exception):
        pass

    class Cognito:
        def admin_initiate_auth(self, **kw):
            calls.append(kw)
            u, pw = kw["AuthParameters"]["USERNAME"], kw["AuthParameters"]["PASSWORD"]
            if PASSWORDS.get(u) != pw:
                raise NotAuthorizedException("Incorrect username or password.")
            return {"AuthenticationResult": {"IdToken": f"cognito-id-token-for-{u}"}}
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name, **k: Cognito()))
    rows = []
    monkeypatch.setattr(app.audit_trail, "record", lambda *a, **k: rows.append(a) or "rid")
    from fastapi.testclient import TestClient
    return TestClient(app.app), calls, rows


def test_off_unless_configured(monkeypatch):
    from fastapi.testclient import TestClient
    app = _load(monkeypatch, on=False)
    assert TestClient(app.app).post("/signin", json={"username": "alice", "password": "x"}).status_code == 404


def test_your_own_password_gives_your_own_token_and_your_directory_group(signin):
    c, calls, rows = signin
    r = c.post("/signin", json={"username": "Carol ", "password": PASSWORDS["carol"]})
    assert r.status_code == 200 and r.json()["token"] == "cognito-id-token-for-carol"
    assert r.json()["groups"] == ["fraud-investigator"]             # from the directory, never from the request
    assert calls[0]["AuthParameters"] == {"USERNAME": "carol", "PASSWORD": PASSWORDS["carol"]}
    assert rows[-1][2:5] == ("signin", "carol", "allow")


def test_a_signed_in_user_cannot_become_someone_else(signin):
    """The picker is gone: the only way to get carol's token is carol's password. alice's password for carol fails."""
    c, calls, rows = signin
    r = c.post("/signin", json={"username": "carol", "password": PASSWORDS["alice"]})
    assert r.status_code == 401 and "token" not in r.json()
    assert rows[-1][2:5] == ("signin", "carol", "deny")


@pytest.mark.parametrize("body", [{"username": "alice", "password": "wrong"}, {"username": "alice"},
                                  {"username": "", "password": "x"}, {}, {"username": "mallory", "password": "x"}])
def test_refusals_say_the_same_thing_and_leave_an_audit_row(signin, body):
    c, calls, rows = signin
    r = c.post("/signin", json=body)
    assert r.status_code == 401 and "token" not in r.json()
    assert r.json()["error"]["message"] == "Sign-in refused: check your username and password."
    assert rows[-1][4] == "deny"


def test_unknown_user_never_reaches_cognito(signin):
    c, calls, rows = signin
    c.post("/signin", json={"username": "mallory", "password": "x"})
    assert calls == []


def test_password_never_written_to_the_audit_trail(signin):
    c, calls, rows = signin
    c.post("/signin", json={"username": "alice", "password": "Sup3r-secret-guess!"})
    c.post("/signin", json={"username": "alice", "password": PASSWORDS["alice"]})
    assert not any("Sup3r-secret-guess!" in str(r) or PASSWORDS["alice"] in str(r) for r in rows)


def test_brute_force_brake_per_username(signin):
    c, calls, rows = signin
    for _ in range(5):
        c.post("/signin", json={"username": "alice", "password": "nope"})
    r = c.post("/signin", json={"username": "alice", "password": PASSWORDS["alice"]})
    assert r.status_code == 429
    assert c.post("/signin", json={"username": "carol", "password": PASSWORDS["carol"]}).status_code == 200
