"""Deliverable 4: the eval gate passes on the healthy pipeline and BLOCKS when a guardrail breaks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import run_evals  # noqa: E402


def test_gate_passes_on_the_healthy_pipeline(tmp_path):
    assert run_evals.main(["--out", str(tmp_path / "r.txt")]) == 0


def test_gate_blocks_when_the_injection_guardrail_is_removed(tmp_path, monkeypatch):
    from claimsense._m1 import guardrails
    monkeypatch.setattr(guardrails, "scan_injection", lambda text: [])        # a "harmless refactor"
    assert run_evals.main(["--out", str(tmp_path / "r.txt")]) == 1
    assert "DEPLOY GATE: BLOCKED" in (tmp_path / "r.txt").read_text()


def test_gate_blocks_when_the_model_is_down(tmp_path, monkeypatch):
    from claimsense import brains
    async def outage(*a, **kw):
        raise TimeoutError("model provider unavailable")
    monkeypatch.setattr(brains.ReplayModel, "get_response", outage)
    assert run_evals.main(["--suite", "smoke", "--out", str(tmp_path / "r.txt")]) == 1   # fallback never counts
    assert "fallback share" in (tmp_path / "r.txt").read_text()
