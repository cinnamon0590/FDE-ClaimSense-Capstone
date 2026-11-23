"""Operational metrics (M4, D-048): one CloudWatch Embedded Metric Format (EMF) line per request and per claim run.

CloudWatch turns each `{"_aws": {...}, ...}` JSON line a Lambda (or App Runner service) prints into metrics, with no
agent and no extra permission. Namespace `ClaimSense`, one dimension `Service` (door | orchestrator):

    Requests, ServerErrors, Refusals, LatencyMs         every HTTP request (error rate = ServerErrors / Requests)
    ClaimRuns, ClaimErrors, ClaimLatencyMs, CostUSD,     every claim the pipeline decides
    Fallbacks, GuardrailHolds
    EvalPassRate                                         the continuous-eval sample (M4/ops/continuous_eval.py)

On by default where CloudWatch reads stdout (Lambda); `CLAIMSENSE_METRICS=1` turns EMF on anywhere, `=0` off, and
`=cloudwatch` sends the same values with PutMetricData from a background thread (ECS, where the awslogs driver
doesn't extract EMF). Lines also go to `$CLAIMSENSE_STATE/metrics.jsonl` when CLAIMSENSE_METRICS_FILE is set, for the local
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
    if flag in ("0", "1", "cloudwatch"):
        return flag in ("1", "cloudwatch")
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
    if os.environ.get("CLAIMSENSE_METRICS") == "cloudwatch":       # ECS (awslogs doesn't extract EMF): direct API
        _put_async(service, {k: values[k] for k in names})
        return
    if enabled():
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    path = os.environ.get("CLAIMSENSE_METRICS_FILE")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")


def _put_async(service, values):
    import threading

    def put():
        try:
            import boto3
            boto3.client("cloudwatch").put_metric_data(Namespace=NAMESPACE, MetricData=[
                {"MetricName": k, "Value": float(v), "Unit": UNITS[k],
                 "Dimensions": [{"Name": "Service", "Value": service}]} for k, v in values.items()])
        except Exception:                                        # metrics must never break a request
            pass
    threading.Thread(target=put, daemon=True).start()


def request(service, status, started):
    emit(service, Requests=1, ServerErrors=int(status >= 500), Refusals=int(status in (401, 403)),
         LatencyMs=round((time.time() - started) * 1000, 1))


def claim_run(result):
    decided = result.get("decided_by")
    emit("orchestrator", ClaimRuns=1, ClaimErrors=int(decided in ("fallback", "unavailable")),
         ClaimLatencyMs=round(result.get("latency_s", 0) * 1000, 1), CostUSD=round(result.get("cost_usd", 0), 6),
         Fallbacks=int(decided == "fallback"), GuardrailHolds=int(decided in ("guardrail_hold", "consistency_hold")))
