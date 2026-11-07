"""W15 floor: guardrails that TRIP and hand off to a human; coverage cites only what was retrieved."""
import json

from claimsense.pipeline import run_claim

M = "guardrail_hold"


def events(r, kind):
    return [e for e in r["events"] if e["kind"] == kind]


def test_injected_invoice_trips_intake_and_hands_off_to_a_human():          # CS-016
    r = run_claim("CLM-2024-3602", "alice", brain="replay")
    assert r["decided_by"] == M
    card = r["response"]
    assert (card["outcome"], card["route_to"]) == ("flag_review", "senior-adjuster")
    assert "injection_detected" in card["guardrails_fired"]
    assert any(e["name"].endswith("senior adjuster (human)") for e in events(r, "handoff"))
    assert "fraud checks passed" not in card["reasoning"].lower()          # never echoed back
    assert not [e for e in events(r, "agent_start") if e["name"] == "Coverage Check"], "fail closed: stop at intake"


def test_injection_text_never_reaches_the_model(replay_copy):
    seen = []
    from claimsense import brains
    orig = brains.ReplayModel.get_response

    async def spy(self, system_instructions, input, *a, **kw):
        seen.append(json.dumps(input, default=str))
        return await orig(self, system_instructions, input, *a, **kw)
    brains.ReplayModel.get_response = spy
    try:
        run_claim("CLM-2024-3602", "alice", brain="replay", store=replay_copy)
    finally:
        brains.ReplayModel.get_response = orig
    blob = " ".join(seen).lower()
    assert "ignore previous instructions" not in blob and "[removed by g1" in blob


def test_coverage_citing_an_unretrieved_clause_trips(replay_copy):
    # the model "remembers" CLS-AUTH-010 without retrieving it: the coverage tripwire fires
    replay_copy.edit("CLM-2024-1800", lambda d: d["agents"]["coverage"]["turns"][-1]["final"]["cited_clause_ids"].append("CLS-AUTH-010"))
    r = run_claim("CLM-2024-1800", "alice", brain="replay", store=replay_copy)
    assert r["decided_by"] == M
    assert r["response"]["outcome"] == "flag_review"
    assert "CLS-AUTH-010" in r["response"]["reasoning"]


def test_decision_citing_an_invented_clause_trips_and_is_withheld(replay_copy):
    def forge(d):
        d["agents"]["decision"]["turns"][-1]["final"]["citations"].append({"source_id": "CLS-PER-099", "quote": "60 days"})
    replay_copy.edit("CLM-2024-4120", forge)                                  # CS-040 with a fooled model
    r = run_claim("CLM-2024-4120", "alice", brain="replay", store=replay_copy)
    card = r["response"]
    assert card["outcome"] == "flag_review" and card["route_to"] == "senior-adjuster"
    assert "uncited_claim_blocked" in card["guardrails_fired"]
    assert card["reasoning"].startswith("Model draft withheld")
    assert any(e["name"] == "decision_safety_tripwire" for e in events(r, "guardrail"))


def test_decision_leaking_another_claim_is_redacted(replay_copy):
    replay_copy.edit("CLM-2024-3640", lambda d: d["agents"]["decision"]["turns"][-1]["final"].update(
        reasoning="Covered glass loss. For comparison CLM-2024-1873 was paid 9,200."))
    r = run_claim("CLM-2024-3640", "alice", brain="replay", store=replay_copy)
    assert "CLM-2024-1873" not in json.dumps(r["response"])
    assert "cross_record_blocked" in r["response"]["guardrails_fired"]


def test_code_owns_the_money_whatever_the_model_says():
    r = run_claim("CLM-2024-3602", "alice", brain="replay")                     # invoice claims $18,000
    assert r["response"]["computed"]["net_payable"] == 1600


def test_forced_auto_decision_keeps_the_verdict_but_requires_an_adjuster():  # CS-018
    r = run_claim("CLM-2024-3655", "alice", brain="replay")
    assert r["response"]["outcome"] == "deny"
    assert r["response"]["adjuster_confirmation_required"] is True
    assert "auto_decision_blocked" in r["response"]["guardrails_fired"]


def test_pii_never_reaches_the_model_traces_or_card(tmp_path):
    from claimsense import config
    raw = ["000-12-3456", "driver.synthetic@example.com", "4111 1111 1111 1111", "555-010-0142"]
    r = run_claim("CLM-2024-4119", "alice", brain="replay")
    assert "pii_masked" in r["response"]["guardrails_fired"]
    blob = json.dumps(r) + "".join(p.read_text() for p in (config.STATE_DIR / "traces").glob("*.jsonl"))
    assert not [x for x in raw if x in blob]


def test_unentitled_user_gets_nothing_and_no_agent_runs():                  # CS-019 / CS-038
    for user, claim in (("dave", "CLM-2024-1873"), ("carol", "CLM-2024-1800")):
        r = run_claim(claim, user, brain="replay")
        assert r["decided_by"] == "boundary_refusal"
        assert r["response"]["returns_claim_data"] is False and not r["usage"]
        assert not events(r, "agent_start")


def test_citation_quotes_are_the_retrieved_wording_not_a_paraphrase(replay_copy):
    replay_copy.edit("CLM-2024-1800", lambda d: d["agents"]["decision"]["turns"][-1]["final"]["citations"][0].update(
        quote="Collision coverage applies to losses caused by collision."))
    r = run_claim("CLM-2024-1800", "alice", brain="replay", store=replay_copy)
    q = {c["source_id"]: c["quote"] for c in r["response"]["citations"]}
    assert q["CLS-COL-001"].startswith("We will pay for direct and accidental loss")
