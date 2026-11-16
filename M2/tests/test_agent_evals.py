"""Per-agent evals (D-031): labels are derived (never hand-edited or model-derived), the scorer catches a wrong
agent output, and no agent regresses below its ratchet floor."""
import copy
import importlib
import json
import sys
from pathlib import Path

M2 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(M2 / "evals"))
import agent_evals as AE  # noqa: E402


def test_committed_labels_equal_a_fresh_derivation(tmp_path, monkeypatch):
    import derive_agent_labels as D
    committed = json.loads((M2 / "evals" / "agent-labels.json").read_text())
    monkeypatch.setattr(D, "HERE", tmp_path)
    D.main()
    fresh = json.loads((tmp_path / "agent-labels.json").read_text())
    assert fresh["labels"] == committed["labels"]            # labels change only through the derivation rules


def _run_all():
    from claimsense.cases import all_cases
    from claimsense.pipeline import Pipeline, run_sync
    pipe = Pipeline(brain="replay")
    return {c["case_id"]: run_sync(pipe.run(c["claim"]["claim_id"], c["requesting_user"]["id"])) for c in all_cases()}


def test_no_agent_regresses_below_its_floor():
    labels = json.loads(AE.LABELS.read_text())["labels"]
    stats, _ = AE.score(_run_all(), labels)
    for agent, st in stats.items():
        assert st["all_ok"] / st["cases"] >= AE.FLOOR[agent] - 1e-9, f"{agent} regressed below its floor"


def test_the_scorer_catches_a_wrong_agent_output():
    labels = json.loads(AE.LABELS.read_text())["labels"]
    results = _run_all()
    bad = copy.deepcopy(results)
    for ev in bad["CS-001"]["events"]:
        if ev["kind"] == "agent_end" and ev["name"] == "Coverage Check":
            ev["output"]["coverage_finding"] = "not_covered"          # the agent gets coverage wrong
    good_stats, _ = AE.score(results, labels)
    bad_stats, misses = AE.score(bad, labels)
    assert bad_stats["Coverage Check"]["all_ok"] == good_stats["Coverage Check"]["all_ok"] - 1
    assert ("CS-001", "Coverage Check", "coverage_finding", "covered", "not_covered") in misses
