"""Operational metrics (M4, D-048): one CloudWatch Embedded Metric Format (EMF) line per request and per claim run.

CloudWatch turns each `{"_aws": {...}, ...}` JSON line a Lambda (or App Runner service) prints into metrics, with no
agent and no extra permission. Namespace `ClaimSense`, one dimension `Service` (door | orchestrator):

    Requests, ServerErrors, Refusals, LatencyMs         every HTTP request (error rate = ServerErrors / Requests)
    ClaimRuns, ClaimErrors, ClaimLatencyMs, CostUSD,     every claim the pipeline decides
    Fallbacks, GuardrailHolds
    EvalPassRate                                         the continuous-eval sample (M4/ops/continuous_eval.py)

On by default where CloudWatch reads stdout (Lambda, App Runner); `CLAIMSENSE_METRICS=1` turns it on anywhere,
`=0` off. Lines also go to `$CLAIMSENSE_STATE/metrics.jsonl` when CLAIMSENSE_METRICS_FILE is set, for the local
dashboard twin. Values are counts, milliseconds and dollars only: never a token, user id or claim content.
"""
import json
import os
import sys
import time

NAMESPACE = "ClaimSense"
UNITS = {"Requests": "Count", "ServerErrors": "Count", "Refusals": "Count", "LatencyMs": "Milliseconds",
         "ClaimRuns": "Count", "ClaimErrors": "Count", "ClaimLatencyMs": "Milliseconds", "CostUSD": "None",
         "Fallbacks": "Count", "GuardrailHolds": "Count", "EvalPassRate": "Percent"}


def enabled():
    flag = os.environ.get("CLAIMSENSE_METRICS", "")
    if flag in ("0", "1"):
        return flag == "1"
    return bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("CLAIMSENSE_ON_APPRUNNER"))


def emit(service, **values):
    """Print one EMF line (and append it to the local metrics file, if configured)."""
    if not (enabled() or os.environ.get("CLAIMSENSE_METRICS_FILE")):
        return
    names = [k for k in values if k in UNITS]
    line = {"_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
        "Namespace": NAMESPACE, "Dimensions": [["Service"]],
        "Metrics": [{"Name": k, "Unit": UNITS[k]} for k in names]}]},
        "Service": service, **{k: values[k] for k in names}}
    text = json.dumps(line, separators=(",", ":"))
    if enabled():
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    path = os.environ.get("CLAIMSENSE_METRICS_FILE")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")


def request(service, status, started):
    emit(service, Requests=1, ServerErrors=int(status >= 500), Refusals=int(status in (401, 403)),
         LatencyMs=round((time.time() - started) * 1000, 1))


def claim_run(result):
    decided = result.get("decided_by")
    emit("orchestrator", ClaimRuns=1, ClaimErrors=int(decided == "fallback"),
         ClaimLatencyMs=round(result.get("latency_s", 0) * 1000, 1), CostUSD=round(result.get("cost_usd", 0), 6),
         Fallbacks=int(decided == "fallback"), GuardrailHolds=int(decided in ("guardrail_hold", "consistency_hold")))
