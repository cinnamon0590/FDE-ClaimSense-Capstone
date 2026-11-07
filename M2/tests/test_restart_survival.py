"""D-027: state survives a restart. A crashed claim resumes from its checkpoints without re-running (or
re-paying for) finished agents, and the boundary keeps drafts, idempotency records and the audit trail."""
import importlib.util
import uuid
from pathlib import Path

import pytest

from claimsense.boundary_client import LocalBoundary
from claimsense.pipeline import Pipeline, run_claim, run_sync

M2 = Path(__file__).resolve().parents[1]


class Crash(BaseException):
    """Stands in for a killed process: not an Exception, so nothing in the pipeline can catch it."""


def _agents_started(result):
    return [e["name"] for e in result["events"] if e["kind"] == "agent_start"]


def test_a_claim_killed_mid_run_resumes_in_a_new_process_without_repaying(tmp_path):
    run_id = f"CLM-2024-1800:{uuid.uuid4().hex[:8]}"

    def die_after_coverage(ev):
        if ev["kind"] == "checkpoint_saved" and ev["name"] == "coverage":
            raise Crash()
    with pytest.raises(Crash):
        run_sync(Pipeline(brain="replay").run("CLM-2024-1800", "alice", run_id=run_id, on_event=die_after_coverage))

    fresh = Pipeline(brain="replay")                      # new objects, same state directory = a restarted service
    assert fresh.checkpoints.has(run_id)
    r = run_sync(fresh.run("CLM-2024-1800", "alice", run_id=run_id, resume=True))
    restored = [e["name"] for e in r["events"] if e["kind"] == "checkpoint"]
    assert restored == ["Document Intake restored from checkpoint", "Coverage Check restored from checkpoint"]
    assert "Document Intake" not in _agents_started(r) and "Coverage Check" not in _agents_started(r)
    assert {u["agent"] for u in r["usage"]} >= {"Claim Assessment", "Decision Draft"}
    assert not {"Document Intake", "Coverage Check"} & {u["agent"] for u in r["usage"]}       # not paid twice
    assert r["decided_by"] == "agents" and r["response"]["outcome"] == "approve"
    assert r["retrieved_clause_ids"]                                 # retrieval state came back with Coverage


def test_boundary_drafts_idempotency_and_confirmations_survive_a_restart(tmp_path):
    db = tmp_path / "boundary.db"
    card = run_claim("CLM-2024-1800", "alice", brain="replay")["response"]
    before = LocalBoundary(db)
    draft = before.recommend("alice", "CLM-2024-1800", card, "write-key-1")
    rid = draft["recommendation_id"]

    after = LocalBoundary(db)                              # the boundary restarts
    assert rid in after.recommendations
    again = after.recommend("alice", "CLM-2024-1800", card, "write-key-1")
    assert again["idempotent_replay"] and again["recommendation_id"] == rid          # no duplicate draft
    confirm = {"recommendation_id": rid, "action": "confirm", "idempotency_key": "confirm-key-1"}
    assert after.confirm("alice", confirm)["confirmed_by"] == "alice"

    third = LocalBoundary(db)                              # and restarts again
    assert third.recommendations[rid]["confirmation"]["confirmed_by"] == "alice"
    assert third.confirm("alice", confirm)["idempotent_replay"] is True               # same key: replay
    second = dict(confirm, idempotency_key="confirm-key-2", action="override", override_reason="changed my mind")
    assert third.confirm("alice", second)["error"]["code"] == "already_confirmed"   # new key: decided once only


def _orchestrator():
    spec = importlib.util.spec_from_file_location("orchestrator_app", M2 / "services" / "orchestrator" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_api_resumes_a_run_by_id_and_never_writes_a_duplicate_draft():
    from fastapi.testclient import TestClient
    app = _orchestrator()
    client = TestClient(app.app)
    first = client.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice"}).json()
    assert first["resumed"] is False and first["run_id"].startswith("CLM-2024-1800:")
    again = client.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice", "run_id": first["run_id"]}).json()
    assert again["resumed"] is True and again["cost_usd"] == 0 and not _agents_started(again)
    assert again["response"] == first["response"]
    assert again["receipt"]["recommendation_id"] == first["receipt"]["recommendation_id"]
    assert again["receipt"]["idempotent_replay"] is True


def test_fault_injection_is_off_unless_explicitly_enabled():
    app = _orchestrator()
    assert app.FAULT_INJECTION is False
    assert app._crash_hook(app.RunRequest(user_id="alice", crash_after_step="coverage")) is None


# ── console sessions: a refresh or reconnect joins the run in progress; it never starts a duplicate ──
def _slow_orchestrator(monkeypatch, delay=0.3):
    app = _orchestrator()
    calls = []
    real = app.PIPE.run

    async def slow_run(*a, **kw):
        calls.append(kw.get("run_id"))
        await __import__("asyncio").sleep(delay)          # keep the run in flight long enough to reconnect
        return await real(*a, **kw)
    monkeypatch.setattr(app.PIPE, "run", slow_run)
    return app, calls


def _client(app):
    import httpx
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://orchestrator")


def test_a_reconnect_joins_the_run_in_progress_and_nothing_runs_twice(monkeypatch):
    import asyncio
    app, calls = _slow_orchestrator(monkeypatch)
    run_id = f"CLM-2024-1800:{uuid.uuid4().hex[:8]}"

    async def go():
        async with _client(app) as c:
            first = asyncio.create_task(c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice", "run_id": run_id}))
            await asyncio.sleep(0.05)                       # the "refresh" arrives while the run is in flight
            second = await c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice", "run_id": run_id})
            return (await first).json(), second.json()
    a, b = run_sync(go())
    assert calls == [run_id]                                   # the pipeline ran once
    assert a["joined"] is False and b["joined"] is True
    assert a["response"] == b["response"] and a["receipt"] == b["receipt"]
    assert run_id not in app.INFLIGHT                          # cleaned up when the run finished


def test_a_joining_stream_gets_the_backlog_live_events_and_the_result(monkeypatch):
    import asyncio
    import json
    app, calls = _slow_orchestrator(monkeypatch)
    run_id = f"CLM-2024-1800:{uuid.uuid4().hex[:8]}"

    async def go():
        async with _client(app) as c:
            first = asyncio.create_task(c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice", "run_id": run_id}))
            await asyncio.sleep(0.05)
            r = await c.post("/claims/CLM-2024-1800/recommend/stream", json={"user_id": "alice", "run_id": run_id})
            await first
            return [json.loads(line) for line in r.text.splitlines()]
    events = run_sync(go())
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "joined" and kinds[1] == "run" and kinds[-1] == "result"
    assert "agent_start" in kinds and calls == [run_id]


def test_nobody_can_join_or_resume_someone_elses_run(monkeypatch):
    import asyncio
    app, _ = _slow_orchestrator(monkeypatch)
    run_id = f"CLM-2024-1800:{uuid.uuid4().hex[:8]}"

    async def go():
        async with _client(app) as c:
            alice = asyncio.create_task(c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice", "run_id": run_id}))
            await asyncio.sleep(0.05)
            bob = await c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "bob", "run_id": run_id})
            other_claim = await c.post("/claims/CLM-2024-3104/recommend", json={"user_id": "alice", "run_id": run_id})
            await alice
            return bob, other_claim
    bob, other_claim = run_sync(go())
    assert bob.status_code == 404 and bob.json()["error"]["code"] == "not_found_or_forbidden"
    assert "response" not in bob.json()                        # alice's result is never shared
    assert other_claim.status_code == 400                      # a run belongs to one claim


def test_a_closed_tab_does_not_cancel_the_run_and_a_reconnect_finds_it(monkeypatch):
    import asyncio
    app, calls = _slow_orchestrator(monkeypatch)
    run_id = f"CLM-2024-1800:{uuid.uuid4().hex[:8]}"

    async def go():
        async with _client(app) as c:
            tab = asyncio.create_task(c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice", "run_id": run_id}))
            await asyncio.sleep(0.05)
            tab.cancel()                                        # the adjuster closes the tab mid-run
            await asyncio.sleep(0.05)
            back = await c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice", "run_id": run_id})
            return back.json()
    r = run_sync(go())
    assert calls == [run_id] and r["joined"] is True and r["response"]["outcome"] == "approve"
