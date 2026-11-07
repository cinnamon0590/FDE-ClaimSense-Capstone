"""The eval set: the 20 M0 cases plus the M2 additions (M2/evals/cases-m2.json)."""
import json
from pathlib import Path

from ._m1 import M0_CASES

M2_CASES = Path(__file__).resolve().parents[1] / "evals" / "cases-m2.json"


def all_cases():
    cases = json.loads(M0_CASES.read_text())["cases"]
    if M2_CASES.exists():
        cases += json.loads(M2_CASES.read_text())["cases"]
    return cases
