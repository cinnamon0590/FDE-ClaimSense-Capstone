"""Load the executable specs from M0/M1 by file path (their folders aren't Python packages).

M2 doesn't copy the guardrail, boundary or scoring rules. It imports the same reference modules
that M1's tests prove, so the production pipeline and the spec can't drift apart.
"""
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAIMSENSE_ROOT") or Path(__file__).resolve().parents[2])


def _load(name, rel):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


guardrails = _load("cs_reference_guardrails", "M1/2-architecture/reference_guardrails.py")
boundary = _load("cs_reference_boundary", "M1/5-system-contracts/reference_boundary.py")
score = _load("cs_score", "M0/evals/score.py")
jsonschema_lite = _load("cs_jsonschema_lite", "M1/tools/jsonschema_lite.py")

FIXTURES = ROOT / "M1" / "6-synthetic-data" / "fixtures"
SCHEMAS = ROOT / "M1" / "5-system-contracts" / "schemas"
M0_CASES = ROOT / "M0" / "evals" / "cases.json"
