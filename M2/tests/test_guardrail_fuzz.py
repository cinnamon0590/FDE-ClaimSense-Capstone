"""The adversarial fuzz suite is a CI gate ($0): mutated attacks must be caught, benign claim text must not trip G1."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import fuzz_guardrails as F  # noqa: E402


def test_mutated_injections_and_pii_are_caught_with_no_false_positives():
    text, ok, det, pdet, fp = F.report()
    assert det >= F.DETECTION_BAR, text
    assert pdet >= F.DETECTION_BAR, text
    assert not fp, text
    assert ok


def test_g1b_cache_covers_every_eval_case_text():
    """CI applies G1b from cached verdicts; a missing verdict would silently weaken the replay gate."""
    from claimsense.boundary_client import AGENT_IDS, LocalBoundary
    from claimsense.cases import all_cases
    from claimsense.injection_classifier import InjectionClassifier
    from claimsense.pipeline import run_sync
    from claimsense.tools import RunCtx, claim_packet, screen_packet
    clf, b = InjectionClassifier("replay"), LocalBoundary()
    for c in all_cases():
        cid, user = c["claim"]["claim_id"], c["requesting_user"]["id"]
        claim = b.claim(user, cid, AGENT_IDS["intake"])
        if "error" in claim:
            continue
        ctx = RunCtx(boundary=b, user_id=user, claim_id=cid, index=None, classifier=clf, claim=claim)
        run_sync(screen_packet(ctx, claim_packet(ctx)))
    assert clf.misses == 0
