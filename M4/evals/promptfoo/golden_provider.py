"""Promptfoo provider (grader #2's agreement runner): run ONE golden case through the real ClaimSense pipeline and
return "PASS" or "FAIL: <reason>", scored by the same M0 scorer as the gate.

Brain: replay by default ($0, recorded live outputs: the same verdicts the gate scores), `CLAIMSENSE_BRAIN=live`
for a live run. Promptfoo calls `call_api(prompt, options, context)`; the case id arrives as `vars.case_id`.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "M2"), str(ROOT / "M2" / "evals")]
os.environ.setdefault("CLAIMSENSE_LLM_REQUIRED", "false")

_cases = None


def _case(cid):
    global _cases
    if _cases is None:
        from claimsense.cases import all_cases
        _cases = {c["case_id"]: c for c in all_cases()}
    return _cases[cid]


def run_case(cid, brain=None):
    from claimsense.pipeline import run_claim
    from claimsense._m1 import score
    from run_evals import for_scoring
    c = _case(cid)
    res = run_claim(c["claim"]["claim_id"], c["requesting_user"]["id"], brain=brain or os.environ.get("CLAIMSENSE_BRAIN", "replay"))
    why = (score.fail_reason(c, for_scoring(res)) or score.evidence_fail(c, for_scoring(res)))
    return res, why


def call_api(prompt, options, context):
    cid = (context.get("vars") or {}).get("case_id") or prompt.strip()
    try:
        res, why = run_case(cid)
    except Exception as e:                                  # a crash is a failed case, never a skipped one
        return {"output": f"FAIL: crashed: {type(e).__name__}: {e}"[:300]}
    return {"output": "PASS" if why is None else f"FAIL: {why}",
            "metadata": {"decided_by": res.get("decided_by"), "outcome": (res.get("response") or {}).get("outcome")}}


def card_api(prompt, options, context):
    """For the rubric grader: return the decision card (JSON) the pipeline drafts for the case, LIVE models."""
    cid = (context.get("vars") or {}).get("case_id") or prompt.strip()
    res, _ = run_case(cid, brain=os.environ.get("CLAIMSENSE_BRAIN", "live"))
    card = res.get("response") or {}
    keep = {k: card.get(k) for k in ("outcome", "route_to", "reasoning", "citations", "computed", "judgment",
                                     "verdict_source", "guardrails_fired", "adjuster_confirmation_required",
                                     "returns_claim_data", "error")}
    return {"output": json.dumps({k: v for k, v in keep.items() if v is not None}, ensure_ascii=False)}
