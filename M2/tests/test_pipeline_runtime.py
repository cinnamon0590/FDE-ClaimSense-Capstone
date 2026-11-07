"""Sessions/checkpoints, tracing, cost, and the boundary audit trail."""
import asyncio

from claimsense.boundary_client import LocalBoundary
from claimsense.pipeline import Pipeline, run_claim


def test_resume_from_checkpoint_skips_completed_agents():
    pipe = Pipeline(brain="replay")
    first = asyncio.run(pipe.run("CLM-2024-1800", "alice", run_id="r1"))
    again = asyncio.run(pipe.run("CLM-2024-1800", "alice", run_id="r1", resume=True))
    assert len([e for e in again["events"] if e["kind"] == "checkpoint"]) == 4 + pipe.wants_second_opinion("CLM-2024-1800")
    assert again["response"]["outcome"] == first["response"]["outcome"] == "approve"
    assert again["cost_usd"] == 0                                                # nothing paid twice


def test_trace_written_for_every_run():
    from claimsense import config
    r = run_claim("CLM-2024-1800", "alice", brain="replay")
    f = config.STATE_DIR / "traces" / f"{r['trace_id']}.jsonl"
    text = f.read_text()
    for kind in ('"type": "agent"', '"type": "function"', '"type": "guardrail"', '"type": "generation"'):
        assert kind in text, kind


def test_every_agent_call_is_audited_on_behalf_of_an_agent():
    b = LocalBoundary()
    run_claim("CLM-2024-1800", "alice", brain="replay", boundary=b)
    rows = [a for a in b.audit if a["resource"] in ("CLM-2024-1800", "POL-AU-10418") or a["action"] == "get_document"]
    assert rows and all(a["user_id"] == "alice" and a["on_behalf_of_agent"] for a in rows)
    assert {a["decision"] for a in rows} == {"allow"}


def test_cost_and_latency_are_reported_per_claim():
    r = run_claim("CLM-2024-1800", "alice", brain="replay")
    agents = [u for u in r["usage"] if u["agent"] != "G1b injection classifier"]          # G1b is metered too
    assert [u["agent"] for u in agents][:4] == ["Document Intake", "Coverage Check", "Claim Assessment", "Decision Draft"]
    assert agents[0]["model"].startswith("replay:gpt-4o-mini") and agents[1]["model"].startswith("replay:gpt-4o")
    assert r["cost_usd"] > 0 and r["latency_s"] < 90


def test_a_run_that_dies_part_way_never_damages_a_good_replay(replay_copy):
    """Regression (2026-11-07): an out-of-credits run overwrote replays with partial recordings."""
    import json
    before = replay_copy.path("CLM-2024-1800").read_text()
    replay_copy.start_recording("CLM-2024-1800")
    replay_copy.save_turn("CLM-2024-1800", "intake", {"tool_calls": [{"name": "get_claim_file", "arguments": "{}"}]}, "gpt-4o-mini")
    assert replay_copy.commit_recording("CLM-2024-1800") is False            # incomplete: refused
    assert replay_copy.path("CLM-2024-1800").read_text() == before
    full = json.loads(before)
    replay_copy.start_recording("CLM-2024-1800")
    for agent, rec in full["agents"].items():
        for t in rec["turns"]:
            replay_copy.save_turn("CLM-2024-1800", agent, t, rec["model"])
    assert replay_copy.commit_recording("CLM-2024-1800", "test") is True
    assert json.loads(replay_copy.path("CLM-2024-1800").read_text())["source"] == "recorded"


def test_outage_gives_labelled_fallback_without_false_guardrail_flags(monkeypatch):
    from claimsense import brains
    async def outage(*a, **kw):
        raise RuntimeError("429 no credits")
    monkeypatch.setattr(brains.ReplayModel, "get_response", outage)
    r = run_claim("CLM-2024-2822", "alice", brain="replay")                 # lapsed policy (CS-003)
    card = r["response"]
    assert r["decided_by"] == "fallback" and card["verdict_source"] == "deterministic_fallback"
    assert card["outcome"] == "deny" and "uncited_claim_blocked" not in card["guardrails_fired"]


def test_back_to_back_runs_share_one_event_loop():
    """Regression (2026-11-07 release gate): a fresh asyncio.run() per run left the OpenAI client's pooled
    connections on a closed loop, so the next run's first claims fell back ("Event loop is closed")."""
    import asyncio
    from claimsense.pipeline import run_sync

    async def which():
        return asyncio.get_running_loop()
    assert run_sync(which()) is run_sync(which())
