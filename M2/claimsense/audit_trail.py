"""The one append-only audit trail (M3, D-036). Every service that accepts a call writes here: the data boundary,
the MCP door, the webhook receiver and the orchestrator's own entry points. That covers refusals made before any
agent runs, so "every call, granted or denied" really is every call.

One JSON object per line, appended under an exclusive lock, never rewritten. Each row carries the deliverable's
three fields (user, action, resource) plus the decision, the reason, the channel (`via`) and a request id. Locally
the file lives on the shared /state volume; on AWS the same rows go to the DynamoDB audit table M1 provisioned
(D-015), selected by CLAIMSENSE_AUDIT_TABLE, AND each row is echoed as one `AUDIT {json}` line to stdout, which
Lambda ships to CloudWatch Logs (D-042: "open CloudWatch Logs and confirm every call logs user, action, resource").
DynamoDB stays the system of record; the log line is the operator's view. CLAIMSENSE_AUDIT_STDOUT=1 turns the echo on
anywhere (e.g. `docker compose logs`), =0 turns it off.
"""
import contextvars
import fcntl
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config

# which door the current call came through: "rest" (console / REST API), "mcp" (agents), "webhook", "orchestrator"
VIA: contextvars.ContextVar = contextvars.ContextVar("claimsense_audit_via", default="rest")
REQUIRED = ("ts", "request_id", "user_id", "action", "resource", "decision")


def audit_path():
    return Path(os.environ.get("AUDIT_LOG", str(config.STATE_DIR / "audit.jsonl")))


def row(user_id, groups, action, resource, decision, reason="", on_behalf_of_agent=None, via=None, **extra):
    # acting_identity / scope: the W16 checklist's names for the same facts (who acted, under which scope), kept
    # beside user_id / groups so both vocabularies read the trail directly
    return {"ts": datetime.now(timezone.utc).isoformat(), "request_id": str(uuid.uuid4()), "user_id": user_id,
            "groups": list(groups or []), "acting_identity": user_id, "scope": list(groups or []),
            "on_behalf_of_agent": on_behalf_of_agent, "action": action,
            "resource": resource, "decision": decision, "reason": reason, "via": via or VIA.get(), **extra}


def append(rec, path=None):
    """Append one audit row atomically (exclusive lock, one write). Returns the row's request_id."""
    table = os.environ.get("CLAIMSENSE_AUDIT_TABLE")
    if table:                                                        # AWS: the append-only DynamoDB table (D-015)
        _put_dynamodb(table, rec)
    else:
        p = Path(path or audit_path())
        p.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(rec, default=str) + "\n").encode()
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, line)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    if _echo(table):                                                 # CloudWatch Logs on Lambda (D-042)
        sys.stdout.write("AUDIT " + json.dumps(rec, default=str, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    return rec["request_id"]


def _echo(table):
    flag = os.environ.get("CLAIMSENSE_AUDIT_STDOUT", "")
    return flag == "1" or (bool(table) and flag != "0")


def record(user_id, groups, action, resource, decision, reason="", **kw):
    return append(row(user_id, groups, action, resource, decision, reason, **kw))


def read(limit=None, path=None):
    """Rows in write order (the newest last)."""
    if (table := os.environ.get("CLAIMSENSE_AUDIT_TABLE")):
        rows = _scan_dynamodb(table)
    else:
        p = Path(path or audit_path())
        rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.exists() else []
    return rows[-limit:] if limit else rows


def _put_dynamodb(table, rec):
    import boto3
    item = {k: {"S": json.dumps(v) if isinstance(v, (list, dict)) else str(v if v is not None else "")}
            for k, v in rec.items()}
    # M1's table (provision.sh): pk `resource`, sk `ts_request` = "<ts>#<request_id>". Append-only: a key is written
    # once, never overwritten (conditional put).
    item["resource"] = {"S": str(rec.get("resource") or "-")}
    item["ts_request"] = {"S": f"{rec['ts']}#{rec['request_id']}"}
    boto3.client("dynamodb").put_item(TableName=table, Item=item,
                                      ConditionExpression="attribute_not_exists(ts_request)")


def _scan_dynamodb(table):
    import boto3
    out, kw = [], {"TableName": table}
    client = boto3.client("dynamodb")
    while True:
        page = client.scan(**kw)
        for it in page["Items"]:
            r = {k: v["S"] for k, v in it.items() if k != "ts_request"}
            r["groups"] = json.loads(r.get("groups") or "[]")
            r["scope"] = json.loads(r.get("scope") or "[]")
            r["on_behalf_of_agent"] = r.get("on_behalf_of_agent") or None
            out.append(r)
        if "LastEvaluatedKey" not in page:
            break
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return sorted(out, key=lambda r: r.get("ts", ""))
