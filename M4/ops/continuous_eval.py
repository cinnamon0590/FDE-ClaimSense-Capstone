"""Continuous evaluation (W17 notebook §7b; Builder tier, D-048): re-grade a random sample of golden cases against the
LIVE system on a schedule, publish the pass rate to CloudWatch, and fail (exit 1) when it drops below the SLO.

    python M4/ops/continuous_eval.py                 # 10 random cases, live models, publishes EvalPassRate
    python M4/ops/continuous_eval.py --sample 25 --no-publish
    # as a schedule: cron `0 7 * * *` on an ops box, or a GitHub Actions `schedule:` trigger with the same command

The sample always includes at least one adversarial case (zero tolerance applies here too: one adversarial
failure fails the run whatever the rate). Cost: ~$0.024 per case (10 cases ≈ $0.25).
"""
import argparse
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "M2"), str(ROOT / "M2" / "evals")]
os.environ.setdefault("MOCK_BRAIN", "0")
os.environ.setdefault("CLAIMSENSE_LLM_REQUIRED", "true")

SLO_PCT = 90


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=10)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args(argv)
    from claimsense.cases import all_cases
    from claimsense.pipeline import run_claim
    from claimsense._m1 import score
    from claimsense import metrics
    from run_evals import for_scoring

    cases = all_cases()
    rng = random.Random(a.seed if a.seed is not None else int(time.time()))
    adv = [c for c in cases if c["category"] == "adversarial"]
    sample = [rng.choice(adv)] + rng.sample([c for c in cases], max(0, a.sample - 1))
    rows, adv_fail = [], []
    for c in sample:
        res = run_claim(c["claim"]["claim_id"], c["requesting_user"]["id"], brain="live")
        why = (score.fail_reason(c, for_scoring(res)) or score.evidence_fail(c, for_scoring(res)))
        rows.append((c["case_id"], why))
        if why and c["category"] == "adversarial":
            adv_fail.append(c["case_id"])
    passed = sum(1 for _, w in rows if w is None)
    rate = round(100 * passed / len(rows), 1)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"continuous eval · {stamp} · {len(rows)} live cases (seed {a.seed}) · pass {passed}/{len(rows)} = {rate}%")
    for cid, why in rows:
        print(f"  {'PASS' if why is None else 'FAIL'}  {cid}" + (f"  ({why})" if why else ""))
    if not a.no_publish:
        import boto3
        boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-east-1")).put_metric_data(
            Namespace="ClaimSense", MetricData=[{"MetricName": "EvalPassRate", "Value": rate, "Unit": "Percent",
                                                 "Dimensions": [{"Name": "Service", "Value": "eval"}]}])
        print("published ClaimSense/EvalPassRate (Service=eval) to CloudWatch")
    metrics.emit("eval", EvalPassRate=rate)
    ok = rate >= SLO_PCT and not adv_fail
    print(f"VERDICT: {'within SLO' if ok else 'BELOW SLO: page the on-call (runbook: Eval pass rate below SLO)'}"
          + (f" · adversarial failures: {adv_fail}" if adv_fail else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
