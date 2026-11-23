"""The ClaimSense operations dashboard and alarm on CloudWatch (M4 deliverable 3, D-048).

    ALARM_EMAIL=you@example.com python M4/ops/observability.py apply     # ~$0 (3 dashboards free; 10 alarms free)
    python M4/ops/observability.py destroy

Creates, idempotently:
  * dashboard `ClaimSense-Operations`: call volume, error rate, p50/p95 latency (door requests and whole claims),
    eval pass rate, cost per claim, refusals, fallbacks and holds, with the SLO lines from M0;
  * alarm `ClaimSense-door-error-rate`: the door's server-error rate above 5% in 2 of 3 one-minute periods (no traffic
    is "not breaching"), notifying SNS topic `claimsense-alerts`;
  * the topic, and an email subscription for ALARM_EMAIL (AWS emails a confirmation link; click it once).
Metrics come from the EMF lines the services print (claimsense/metrics.py): no agent, no extra permission.
The email address is read from the environment and never written to the repo.
"""
import json
import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")


def api_id():
    """The door's API Gateway id (from the deploy record), for the EDGE metrics: AWS/ApiGateway 5xx and Count see
    what the app's own EMF can't, e.g. a door that crashes at start-up (incident-drill-1, D-050)."""
    from pathlib import Path
    url = json.loads((Path.home() / ".claimsense" / "deploy.json").read_text())["door_url"]
    return url.split("//", 1)[1].split(".", 1)[0]
NS, DASH, ALARM, TOPIC = "ClaimSense", "ClaimSense-Operations", "ClaimSense-door-error-rate", "claimsense-alerts"
SLO = {"eval_pass_pct": 90, "claim_p95_ms": 90_000, "door_error_pct": 5}   # M0 SC-1 gate floor, SC-2, ops alarm


def m(name, service, stat="Sum", **kw):
    return [NS, name, "Service", service, {"stat": stat, **kw}]


def widget(x, y, w, h, title, metrics, *, annotations=None, yaxis=None, view="timeSeries", stat="Sum"):
    props = {"title": title, "region": REGION, "view": view, "period": 60, "stat": stat, "metrics": metrics}
    if annotations:
        props["annotations"] = {"horizontal": annotations}
    if yaxis:
        props["yAxis"] = {"left": yaxis}
    return {"type": "metric", "x": x, "y": y, "width": w, "height": h, "properties": props}


def dashboard(alarm_arn):
    text = ("## ClaimSense · operations\n"
            "**SLOs (from the M0 success criteria):** eval pass rate ≥ **90%** with **0 adversarial failures** (SC-1, "
            "SC-5: the deploy gate) · claim p95 latency < **90 s** (SC-2) · door server-error rate < **5%** (the alarm). "
            "Runbook: `M4/RUNBOOK.md`. Metrics: `claimsense/metrics.py` (EMF).")
    return {"widgets": [
        {"type": "text", "x": 0, "y": 0, "width": 24, "height": 2, "properties": {"markdown": text}},
        widget(0, 2, 8, 6, "Call volume (requests per minute)",
               [m("Requests", "door", label="door"), m("Requests", "orchestrator", label="orchestrator"),
                m("ClaimRuns", "orchestrator", label="claims decided")]),
        widget(8, 2, 8, 6, "Error rate (% of requests with a 5xx)",
               [[{"expression": "100*FILL(e1,0)/FILL(r1,1)", "label": "door error % (app)", "id": "er1"}],
                [{"expression": "100*FILL(ge,0)/FILL(gr,1)", "label": "door error % (edge: API Gateway)", "id": "erg"}],
                ["AWS/ApiGateway", "5xx", "ApiId", api_id(), {"id": "ge", "visible": False}],
                ["AWS/ApiGateway", "Count", "ApiId", api_id(), {"id": "gr", "visible": False}],
                [NS, "ServerErrors", "Service", "door", {"id": "e1", "visible": False}],
                [NS, "Requests", "Service", "door", {"id": "r1", "visible": False}],
                [{"expression": "100*FILL(e2,0)/FILL(r2,1)", "label": "orchestrator error %", "id": "er2"}],
                [NS, "ServerErrors", "Service", "orchestrator", {"id": "e2", "visible": False}],
                [NS, "Requests", "Service", "orchestrator", {"id": "r2", "visible": False}]],
               annotations=[{"label": "alarm 5%", "value": SLO["door_error_pct"], "color": "#d62728"}],
               yaxis={"min": 0, "max": 100}),
        {"type": "alarm", "x": 16, "y": 2, "width": 8, "height": 6,
         "properties": {"title": "Alarm", "alarms": [alarm_arn]}},
        widget(0, 8, 8, 6, "Door latency (ms): p50 · p95",
               [m("LatencyMs", "door", "p50", label="p50"), m("LatencyMs", "door", "p95", label="p95")], stat="p95"),
        widget(8, 8, 8, 6, "Claim latency (ms): p50 · p95 (SLO < 90 s)",
               [m("ClaimLatencyMs", "orchestrator", "p50", label="p50"),
                m("ClaimLatencyMs", "orchestrator", "p95", label="p95")],
               annotations=[{"label": "SLO 90 s (SC-2)", "value": SLO["claim_p95_ms"]}], stat="p95"),
        widget(16, 8, 8, 6, "Eval pass rate (%), continuous sample (SLO ≥ 90%)",
               [m("EvalPassRate", "eval", "Average", label="pass rate")],
               annotations=[{"label": "SLO 90% (SC-1)", "value": SLO["eval_pass_pct"]}], yaxis={"min": 0, "max": 100},
               stat="Average"),
        widget(0, 14, 8, 6, "Cost per claim (USD)", [m("CostUSD", "orchestrator", "Average", label="avg $ per claim")],
               stat="Average"),
        widget(8, 14, 8, 6, "Refusals (401/403): access control at work",
               [m("Refusals", "door", label="door"), m("Refusals", "orchestrator", label="orchestrator")]),
        widget(16, 14, 8, 6, "Held for a person: fallbacks · guardrail holds",
               [m("Fallbacks", "orchestrator", label="fallbacks"), m("GuardrailHolds", "orchestrator", label="holds")]),
    ]}


def apply():
    sns, cw = boto3.client("sns", region_name=REGION), boto3.client("cloudwatch", region_name=REGION)
    topic = sns.create_topic(Name=TOPIC, Tags=[{"Key": "Project", "Value": "ClaimSense"}])["TopicArn"]
    email = os.environ.get("ALARM_EMAIL")
    if email:
        subs = sns.list_subscriptions_by_topic(TopicArn=topic)["Subscriptions"]
        if not any(s["Endpoint"] == email for s in subs):
            sns.subscribe(TopicArn=topic, Protocol="email", Endpoint=email)
            print("email subscription requested: AWS sends a confirmation link to the address in ALARM_EMAIL")
        else:
            print("email subscription already exists")
    else:
        print("ALARM_EMAIL not set: the alarm is created; add a subscriber later")
    cw.put_metric_alarm(
        AlarmName=ALARM, AlarmDescription="Door server-error rate above 5% (2 of 3 one-minute periods). Runbook: "
        "M4/RUNBOOK.md, 'Door error rate alarm'. The worse of the app's own count (EMF) and the edge's (API Gateway), "
        "so a door that can't start still alarms (incident-drill-1, D-050).", ActionsEnabled=True, AlarmActions=[topic], OKActions=[topic],
        EvaluationPeriods=3, DatapointsToAlarm=2, Threshold=SLO["door_error_pct"],
        ComparisonOperator="GreaterThanThreshold", TreatMissingData="notBreaching",
        Metrics=[{"Id": "rate", "Expression": "MAX([100*FILL(e,0)/FILL(r,1), 100*FILL(ge,0)/FILL(gr,1)])",
                  "Label": "door error % (worse of app and edge)", "ReturnData": True},
                 {"Id": "ge", "ReturnData": False, "MetricStat": {"Metric": {"Namespace": "AWS/ApiGateway", "MetricName": "5xx",
                  "Dimensions": [{"Name": "ApiId", "Value": api_id()}]}, "Period": 60, "Stat": "Sum"}},
                 {"Id": "gr", "ReturnData": False, "MetricStat": {"Metric": {"Namespace": "AWS/ApiGateway", "MetricName": "Count",
                  "Dimensions": [{"Name": "ApiId", "Value": api_id()}]}, "Period": 60, "Stat": "Sum"}},
                 {"Id": "e", "ReturnData": False, "MetricStat": {"Metric": {"Namespace": NS, "MetricName": "ServerErrors",
                  "Dimensions": [{"Name": "Service", "Value": "door"}]}, "Period": 60, "Stat": "Sum"}},
                 {"Id": "r", "ReturnData": False, "MetricStat": {"Metric": {"Namespace": NS, "MetricName": "Requests",
                  "Dimensions": [{"Name": "Service", "Value": "door"}]}, "Period": 60, "Stat": "Sum"}}],
        Tags=[{"Key": "Project", "Value": "ClaimSense"}])
    arn = cw.describe_alarms(AlarmNames=[ALARM])["MetricAlarms"][0]["AlarmArn"]
    cw.put_dashboard(DashboardName=DASH, DashboardBody=json.dumps(dashboard(arn)))
    print(f"dashboard {DASH}: https://{REGION}.console.aws.amazon.com/cloudwatch/home?region={REGION}#dashboards/dashboard/{DASH}")
    print(f"alarm {ALARM}: door 5xx rate > {SLO['door_error_pct']}% (2 of 3 minutes) -> SNS {TOPIC}")


def destroy():
    cw, sns = boto3.client("cloudwatch", region_name=REGION), boto3.client("sns", region_name=REGION)
    cw.delete_dashboards(DashboardNames=[DASH])
    cw.delete_alarms(AlarmNames=[ALARM])
    for t in sns.list_topics()["Topics"]:
        if t["TopicArn"].endswith(":" + TOPIC):
            sns.delete_topic(TopicArn=t["TopicArn"])
    print("dashboard, alarm and topic removed")


if __name__ == "__main__":
    {"apply": apply, "destroy": destroy}[(sys.argv[1:] or ["apply"])[0]]()
