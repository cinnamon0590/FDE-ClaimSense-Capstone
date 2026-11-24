"""The ADV-* index (M4/evals/adversarial-index.json) names every adversarial golden case exactly once, so the
W17 checklist's ADV-* view can't drift from the cases the gate actually runs."""
import json
from pathlib import Path

from claimsense.cases import all_cases

ROOT = Path(__file__).resolve().parents[2]


def test_every_adversarial_case_has_exactly_one_adv_id():
    idx = json.loads((ROOT / "M4/evals/adversarial-index.json").read_text())["cases"]
    adv = sorted(c["case_id"] for c in all_cases() if c["category"] == "adversarial")
    assert sorted(r["case_id"] for r in idx) == adv
    assert len({r["adv_id"] for r in idx}) == len(idx) == 45
    assert {r["family"] for r in idx} >= {"prompt_injection", "cross_record_leakage", "forced_auto_decision"}
