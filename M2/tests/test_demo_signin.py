"""The deployed console's demo sign-in (M4, D-049): passcode-gated, Cognito-backed, audited, rate-limited, and off
unless configured. Cognito and Secrets Manager are stubbed; no AWS call is made."""
import hashlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

M2 = Path(__file__).resolve().parents[1]


def _load(monkeypatch, secret_id):
    monkeypatch.setenv("CLAIMSENSE_DEMO_SECRET_ID", secret_id)
    spec = importlib.util.spec_from_file_location(f"orch_demo_{secret_id or 'off'}", M2 / "services" / "orchestrator" / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    return app


@pytest.fixture()
def demo(monkeypatch):
    app = _load(monkeypatch, "claimsense/demo-signin")
    app._demo_cache["v"] = {"passcode_sha256": hashlib.sha256(b"right-code").hexdigest(), "pool_id": "pool",
                            "client_id": "client", "users": {"alice": "pw-a", "carol": "pw-c"}}
    calls = []

    class Cognito:
        def admin_initiate_auth(self, **kw):
            calls.append(kw)
            return {"AuthenticationResult": {"IdToken": f"cognito-id-token-for-{kw['AuthParameters']['USERNAME']}"}}
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name, **k: Cognito()))
    from fastapi.testclient import TestClient
    return TestClient(app.app), app, calls


def test_off_unless_configured(monkeypatch):
    from fastapi.testclient import TestClient
    app = _load(monkeypatch, "")
    assert TestClient(app.app).post("/demo/signin", json={"user_id": "alice", "passcode": "x"}).status_code == 404


def test_right_passcode_returns_a_real_cognito_token_for_that_user(demo):
    c, app, calls = demo
    r = c.post("/demo/signin", json={"user_id": "carol", "passcode": "right-code"})
    assert r.status_code == 200 and r.json()["token"] == "cognito-id-token-for-carol"
    assert r.json()["groups"] == ["fraud-investigator"]             # from the directory, never from the request
    assert calls[0]["AuthFlow"] == "ADMIN_USER_PASSWORD_AUTH" and calls[0]["AuthParameters"]["PASSWORD"] == "pw-c"


@pytest.mark.parametrize("body", [{"user_id": "alice", "passcode": "wrong"}, {"user_id": "mallory", "passcode": "right-code"},
                                  {"user_id": "alice"}, {}])
def test_wrong_passcode_or_unknown_user_is_refused_and_no_cognito_call(demo, body):
    c, app, calls = demo
    r = c.post("/demo/signin", json=body)
    assert r.status_code == 401 and "token" not in r.json() and calls == []


def test_brute_force_brake(demo):
    c, app, calls = demo
    for _ in range(10):
        c.post("/demo/signin", json={"user_id": "alice", "passcode": "nope"})
    r = c.post("/demo/signin", json={"user_id": "alice", "passcode": "right-code"})
    assert r.status_code == 429 and calls == []
