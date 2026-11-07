"""D-025: a second, independent Decision Draft; if the two disagree, a senior adjuster decides."""
import copy

from claimsense import config
from claimsense.pipeline import Pipeline, run_claim, schema_errors


def _with_second_opinion(store, claim_id, outcome=None, route_to="keep"):
    def add(d):
        check = copy.deepcopy(d["agents"]["decision"])
        final = check["turns"][-1]["final"]
        if outcome:
            final = dict(final) if isinstance(final, dict) else __import__("json").loads(final)
            final["outcome"] = outcome
            if route_to != "keep":
                final["route_to"] = route_to
            check["turns"][-1]["final"] = final
        d["agents"]["decision_check"] = check
    store.edit(claim_id, add)
    store._cache.clear()


def test_agreeing_drafts_keep_the_model_verdict(replay_copy):
    _with_second_opinion(replay_copy, "CLM-2024-1800")                      # CS-001, approve
    r = run_claim("CLM-2024-1800", "alice", brain="replay", store=replay_copy)
    assert r["decided_by"] == "agents" and r["response"]["outcome"] == "approve"
    assert "Decision Draft · second opinion" in [u["agent"] for u in r["usage"]]   # metered like any agent
    assert any(e["kind"] == "consistency" and e["agree"] for e in r["events"])


def test_disagreeing_drafts_go_to_a_senior_adjuster(replay_copy):
    _with_second_opinion(replay_copy, "CLM-2024-1800", outcome="deny", route_to=None)
    r = run_claim("CLM-2024-1800", "alice", brain="replay", store=replay_copy)
    card = r["response"]
    assert r["decided_by"] == "consistency_hold"
    assert (card["outcome"], card["route_to"]) == ("flag_review", "senior-adjuster")
    assert "model_disagreement" in card["guardrails_fired"] and card["verdict_source"] == "model"
    assert "approve vs deny" in card["reasoning"] and not schema_errors(card)


def test_a_second_opinion_runs_only_when_switched_on(monkeypatch):
    assert Pipeline(brain="replay").wants_second_opinion("CLM-2024-1800") in (True, False)   # replay: if recorded
    p = Pipeline.__new__(Pipeline)
    p.brain = "live"
    monkeypatch.setattr(config, "CONSISTENCY_CHECK", False)
    assert p.wants_second_opinion("CLM-2024-1800") is False
    monkeypatch.setattr(config, "CONSISTENCY_CHECK", True)
    assert p.wants_second_opinion("CLM-2024-1800") is True
