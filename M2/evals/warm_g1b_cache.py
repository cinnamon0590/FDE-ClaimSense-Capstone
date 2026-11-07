"""Fill evals/g1b-cache.json with G1b verdicts for every eval case's untrusted text (live, ~$0.01), so the
replay brain and CI can apply G1b at $0.  python M2/evals/warm_g1b_cache.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claimsense.boundary_client import LocalBoundary, AGENT_IDS  # noqa: E402
from claimsense.cases import all_cases  # noqa: E402
from claimsense.injection_classifier import InjectionClassifier  # noqa: E402
from claimsense.tools import RunCtx, claim_packet, screen_packet  # noqa: E402


async def main():
    clf, b = InjectionClassifier("live"), LocalBoundary()
    for c in all_cases():
        cid, user = c["claim"]["claim_id"], c["requesting_user"]["id"]
        ctx = RunCtx(boundary=b, user_id=user, claim_id=cid, index=None, classifier=clf)
        claim = b.claim(user, cid, AGENT_IDS["intake"])
        if "error" in claim:
            continue                                 # refused at the boundary: no text ever reaches a model
        ctx.claim = claim
        await screen_packet(ctx, claim_packet(ctx))
        print(f"{c['case_id']} {c['category']:<11} {[cat for cat, _ in ctx.g1b] or '-'}")
    clf.save()


if __name__ == "__main__":
    asyncio.run(main())
