"""Ask ClaimSense (D-028): handoff, SQLiteSession and run_streamed fire in the product, under the same guardrails."""
import importlib.util
import json
from pathlib import Path

import pytest

from claimsense import assistant as A
from claimsense.pipeline import Pipeline, run_sync

M2 = Path(__file__).resolve().parents[1]


@pytest.fixture
def drafted():
    pipe = Pipeline(brain="replay")
    card = run_sync(pipe.run("CLM-2024-1800", "alice"))["response"]
    pipe.boundary.recommend("alice", "CLM-2024-1800", card, "write-1")
    return pipe, A.Assistant("replay", pipe.boundary, pipe.index, pipe.classifier)


def _ask(asst, q, user="alice"):
    events = []
    return run_sync(asst.ask("CLM-2024-1800", user, q, on_event=events.append)), events


def test_a_question_about_the_draft_is_answered_from_the_boundary_with_code_numbers(drafted):
    _, asst = drafted
    r, events = _ask(asst, "What did ClaimSense recommend and why?")
    assert r["agents"] == ["Ask ClaimSense"] and not r["guardrail_tripped"]
    assert "APPROVE" in r["answer"] and "$2,700" in r["answer"]                      # the code-computed number
    assert ("tool", "get_draft") in [(e["kind"], e.get("name")) for e in events]    # streamed as it happened


def test_a_policy_question_is_handed_off_to_the_coverage_specialist(drafted):
    _, asst = drafted
    r, events = _ask(asst, "Does the policy cover collision damage?")
    kinds = [(e["kind"], e.get("name")) for e in events]
    assert ("handoff", "Ask ClaimSense -> Coverage specialist") in kinds                # the SDK handoff primitive
    assert ("agent", "Coverage specialist") in kinds and ("tool", "search_clauses") in kinds
    cited = set(A.CLAUSE_RX.findall(r["answer"]))
    assert cited and not r["guardrail_tripped"]


def test_the_conversation_is_an_sdk_session_that_survives_a_restart(drafted):
    pipe, asst = drafted
    _ask(asst, "What did ClaimSense recommend and why?")
    _ask(asst, "Does the policy cover collision damage?")
    restarted = A.Assistant("replay", pipe.boundary, pipe.index, pipe.classifier)    # new process, same /state
    history = run_sync(restarted.history("CLM-2024-1800", "alice"))
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert run_sync(restarted.history("CLM-2024-1800", "bob")) == []                 # one session per adjuster


def test_an_answer_citing_an_unretrieved_clause_is_withheld_and_never_remembered(drafted, monkeypatch):
    _, asst = drafted
    real = A.ScriptedAssistantModel.get_response

    async def invents(self, *a, **kw):
        if self.role == "coverage":
            return self._say("Per [CLS-THF-008] you are fully covered.")             # nothing was retrieved
        return await real(self, *a, **kw)
    monkeypatch.setattr(A.ScriptedAssistantModel, "get_response", invents)
    r, events = _ask(asst, "Does the policy cover theft?")
    assert r["guardrail_tripped"] and r["answer"] == A.FAIL_CLOSED
    assert any(e["kind"] == "guardrail" for e in events)
    history = run_sync(asst.history("CLM-2024-1800", "alice"))
    assert history[-1]["text"] == A.FAIL_CLOSED and "CLS-THF-008" not in json.dumps(history)


def test_an_unentitled_user_gets_nothing(drafted):
    _, asst = drafted
    r, events = _ask(asst, "What did ClaimSense recommend?", user="dave")
    assert r["refused"] and r["answer"] is None and events == [{"kind": "refusal", "code": "not_found_or_forbidden"}]


def test_the_api_streams_the_answer_and_serves_the_history():
    from fastapi.testclient import TestClient
    spec = importlib.util.spec_from_file_location("orch_ask", M2 / "services" / "orchestrator" / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    c = TestClient(app.app)
    c.post("/claims/CLM-2024-1800/recommend", json={"user_id": "alice"})            # writes the draft back
    lines = c.post("/claims/CLM-2024-1800/ask", json={"user_id": "alice",
                                                       "question": "Does the policy cover collision damage?"}).text
    events = [json.loads(x) for x in lines.splitlines()]
    assert events[-1]["kind"] == "answer" and any(e["kind"] == "handoff" for e in events)
    hist = c.get("/claims/CLM-2024-1800/ask/history", params={"user_id": "alice"}).json()
    assert [m["role"] for m in hist["messages"]][-2:] == ["user", "assistant"]
    assert c.get("/claims/CLM-2024-1800/ask/history", params={"user_id": "dave"}).status_code == 404
