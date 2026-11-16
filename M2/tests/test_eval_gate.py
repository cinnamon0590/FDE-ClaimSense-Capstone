"""Deliverable 4: the eval gate passes on the healthy pipeline and BLOCKS when a guardrail breaks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import run_evals  # noqa: E402


def test_gate_passes_on_the_healthy_pipeline(tmp_path):
    assert run_evals.main(["--brain", "replay", "--out", str(tmp_path / "r.txt")]) == 0


def test_gate_blocks_when_the_injection_guardrail_is_removed(tmp_path, monkeypatch):
    from claimsense._m1 import guardrails
    monkeypatch.setattr(guardrails, "scan_injection", lambda text: [])        # a "harmless refactor"
    assert run_evals.main(["--brain", "replay", "--out", str(tmp_path / "r.txt")]) == 1
    assert "DEPLOY GATE: BLOCKED" in (tmp_path / "r.txt").read_text()


def test_gate_blocks_when_the_model_is_down(tmp_path, monkeypatch):
    from claimsense import brains
    async def outage(*a, **kw):
        raise TimeoutError("model provider unavailable")
    monkeypatch.setattr(brains.ReplayModel, "get_response", outage)
    assert run_evals.main(["--brain", "replay", "--suite", "smoke", "--out", str(tmp_path / "r.txt")]) == 1   # fallback never counts
    assert "fallback share" in (tmp_path / "r.txt").read_text()


# ── the CI brief's gate rules (D-035) ───────────────────────────────────────────────────────────────────────
def test_with_llm_required_a_missing_key_turns_the_gate_red(tmp_path, monkeypatch):
    monkeypatch.setattr(run_evals, "LLM_REQUIRED", True)
    from claimsense import config
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    assert run_evals.main(["--out", str(tmp_path / "r.txt")]) == 1                # default = live, the real gate
    assert "no OPENAI_API_KEY" in (tmp_path / "r.txt").read_text()


def test_with_llm_required_the_replay_brain_cannot_pass_the_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(run_evals, "LLM_REQUIRED", True)
    assert run_evals.main(["--brain", "replay", "--out", str(tmp_path / "r.txt")]) == 1
    assert "replay brain cannot satisfy the gate" in (tmp_path / "r.txt").read_text()


def test_eval_threshold_101_blocks_even_when_every_case_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_THRESHOLD", "101")
    assert run_evals.main(["--brain", "replay", "--suite", "smoke", "--out", str(tmp_path / "r.txt")]) == 1
    text = (tmp_path / "r.txt").read_text()
    assert "pass rate: 100% (20/20)" in text and "DEPLOY GATE: BLOCKED" in text


def test_the_threshold_can_never_be_lowered_below_the_floor(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_THRESHOLD", "50")
    assert run_evals.main(["--brain", "replay", "--out", str(tmp_path / "r.txt")]) == 1
    assert "below its 90% floor: refused" in (tmp_path / "r.txt").read_text()


def test_a_crashed_case_is_a_failed_case_named_in_the_report(tmp_path, monkeypatch):
    from claimsense.pipeline import Pipeline
    real = Pipeline.run

    async def flaky(self, claim_id, user_id, **kw):
        if claim_id == "CLM-2024-1800":
            raise RuntimeError("simulated crash")
        return await real(self, claim_id, user_id, **kw)
    monkeypatch.setattr(Pipeline, "run", flaky)
    assert run_evals.main(["--brain", "replay", "--suite", "smoke", "--out", str(tmp_path / "r.txt")]) == 1
    text = (tmp_path / "r.txt").read_text()
    assert "FAIL  CS-001" in text and "CRASHED: RuntimeError: simulated crash" in text and "CRASHED: CS-001" in text
