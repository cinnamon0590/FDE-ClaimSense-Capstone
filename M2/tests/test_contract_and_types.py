"""Deliverable 1: strict typed outputs, and every card honours the M1 DecisionCard contract."""
import pytest
from agents import AgentOutputSchema

from claimsense.agents_def import SPECS, build_agents
from claimsense.cases import all_cases
from claimsense.models import AssessmentResult, CoverageResult, DecisionDraft, IntakeResult
from claimsense.pipeline import Pipeline, schema_errors, run_claim


@pytest.mark.parametrize("otype", [IntakeResult, CoverageResult, AssessmentResult, DecisionDraft])
def test_every_agent_output_is_a_strict_json_schema(otype):
    schema = AgentOutputSchema(otype)
    assert schema.is_strict_json_schema()
    assert schema.json_schema()["additionalProperties"] is False


def test_four_agents_with_model_routing():
    agents, _ = build_agents("replay")
    assert [a.name for a in agents.values()] == ["Document Intake", "Coverage Check", "Claim Assessment", "Decision Draft",
                                                 "Decision Draft · second opinion"]     # D-025: same agent, run twice
    assert agents["decision_check"].instructions == agents["decision"].instructions
    assert agents["decision_check"].output_type is agents["decision"].output_type
    assert {k: v[3] for k, v in SPECS.items()} == {"intake": "fast", "coverage": "smart", "assessment": "fast", "decision": "smart"}
    assert all(a.output_type is not None for a in agents.values())


def test_strict_parsing_rejects_a_malformed_model_output(replay_copy):
    # the model "answers" with an outcome outside the enum: the SDK refuses to parse it -> fallback, labelled
    replay_copy.edit("CLM-2024-1800", lambda d: d["agents"]["decision"]["turns"][-1]["final"].update(outcome="pay_now"))
    r = run_claim("CLM-2024-1800", "alice", brain="replay", store=replay_copy)
    assert r["decided_by"] == "fallback"
    assert r["response"]["verdict_source"] == "deterministic_fallback"


def test_every_case_yields_a_schema_valid_card():
    pipe = Pipeline(brain="replay")
    import asyncio
    for c in all_cases():
        r = asyncio.run(pipe.run(c["claim"]["claim_id"], c["requesting_user"]["id"]))
        if r["decided_by"] == "boundary_refusal":
            assert r["response"] == {"outcome": "refused", "returns_claim_data": False, "verdict_source": "model",
                                     "error": r["response"]["error"]}
            continue
        card = r["response"]
        assert schema_errors(card) == [], (c["case_id"], schema_errors(card))
        assert card["adjuster_confirmation_required"] is True
