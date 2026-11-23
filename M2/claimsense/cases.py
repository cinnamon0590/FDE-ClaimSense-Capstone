"""The eval set: the 20 M0 cases, the M2 additions (M2/evals/cases-m2.json) and the M4 additions
(M4/evals/cases-m4.json): 150 cases."""
import json
from pathlib import Path

from ._m1 import M0_CASES

M2_CASES = Path(__file__).resolve().parents[1] / "evals" / "cases-m2.json"
M4_CASES = Path(__file__).resolve().parents[2] / "M4" / "evals" / "cases-m4.json"


def all_cases():
    cases = json.loads(M0_CASES.read_text())["cases"]
    for extra in (M2_CASES, M4_CASES):
        if extra.exists():
            cases += json.loads(extra.read_text())["cases"]
    return cases
