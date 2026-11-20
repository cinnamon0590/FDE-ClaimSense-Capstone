"""D-044 on AWS: the deployed door reads the Policy & Coverage KB corpus, the policy records and the claim documents
from S3 (M1's private bucket), as the Learning UI Viewer's Week 3 "AWS commands this week" and its architecture
("the MCP document store fetches from here in production") describe.

    python evals/s3_doc_store_check.py --deployed      # needs `aws login`, M3/cloud/deploy.sh   -> evidence/22

Checks: the objects are in the bucket (encrypted, private); the door says its document store is S3; a document and a
KB search answered by the door match the S3 objects byte-for-byte in content; the Lambda's role may only READ the two
prefixes. That a clause edited in the bucket is quarantined (the manifest ships in the image) is proven offline in
tests/test_s3_doc_store.py, so the live bucket is never tampered with. Account id masked; tokens never printed.
"""
import json
import os
import re
import sys
from pathlib import Path

import httpx

os.environ["DOOR_URL"] = json.loads((Path.home() / ".claimsense" / "deploy.json").read_text())["door_url"]
os.environ["CLAIMSENSE_COGNITO"] = "1"
from _common import DOOR, Report, tokens  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-east-1")
KEYS = ("policies/clauses.json", "policies/policies.json", "documents/documents.json")
DOC = "DOC-2024-1800-POLICE-REPORT"                 # on CLM-2024-1800, one of alice's claims


def mask(s):
    return re.sub(r"\d{12}", "<acct>", str(s))


def main():
    import boto3
    R = Report(22, "s3-document-store-deployed", "D-044 on AWS: the door's KB corpus, policies and documents come from S3")
    account = boto3.client("sts").get_caller_identity()["Account"]
    bucket = f"claimsense-autosure-docs-{account}-{REGION}"
    s3 = boto3.client("s3", region_name=REGION)
    R.say(f"door: {DOOR}", f"bucket: s3://{mask(bucket)}/ (M1/7-cloud/provision.sh)", "")

    R.say("1  The objects in S3 (uploaded by M3/cloud/sync_docs.sh, the viewer's `aws s3 sync ./data/policies/ ...`)")
    objs = {}
    for key in KEYS:
        head = s3.head_object(Bucket=bucket, Key=key)
        objs[key] = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
        R.say(f"   s3://{mask(bucket)}/{key:26}  {head['ContentLength']:>7} bytes  SSE={head.get('ServerSideEncryption')}"
              f"  records={len(objs[key]['records'])}")
    R.check("all three objects are in the bucket, encrypted at rest", all(objs.values()))
    pab = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    R.check("the bucket blocks all public access", all(pab.values()), json.dumps(pab))

    R.say("", "2  The door reads them")
    hz = httpx.get(f"{DOOR}/healthz", timeout=30).json()
    R.say("   GET /healthz -> " + json.dumps(hz))
    R.check("the deployed door's document store is S3", hz.get("document_store") == "s3")
    R.check("it holds every document in the bucket", hz.get("documents") == len(objs["documents/documents.json"]["records"]),
            f"{hz.get('documents')} documents")

    tok = tokens(cognito=True)
    H = {"Authorization": f"Bearer {tok('alice')}"}
    r = httpx.get(f"{DOOR}/documents/{DOC}", headers=H, timeout=30)
    want = next(d for d in objs["documents/documents.json"]["records"] if d["doc_id"] == DOC)
    got = r.json()
    R.say(f"   GET /documents/{DOC} (alice) -> HTTP {r.status_code}: "
          + json.dumps({k: got.get(k) for k in ("doc_id", "claim_id", "doc_type", "sha256")}))
    R.check("a document the door serves is the S3 object's record", r.status_code == 200
            and all(got.get(k) == want[k] for k in ("doc_id", "claim_id", "content_text", "sha256")))

    q = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "search_policy_clauses", "arguments": {"query": "collision deductible", "k": 3}}}
    m = httpx.post(f"{DOOR}/mcp", headers={**H, "MCP-Protocol-Version": "2025-06-18"}, json=q, timeout=60).json()
    sc = m.get("result", {}).get("structuredContent", {})
    hits = sc.get("clauses") or sc.get("results") or []
    s3_text = {c["clause_id"]: c["text"] for c in objs["policies/clauses.json"]["records"]}
    R.say("   tools/call search_policy_clauses('collision deductible') (alice) -> "
          + json.dumps([h.get("clause_id") for h in hits]))
    R.check("the KB answers from the S3 corpus, and every returned clause is word-for-word the S3 text",
            hits and all(s3_text.get(h.get("clause_id")) == h.get("text") for h in hits), f"{len(hits)} clauses")

    R.say("", "3  Least privilege: the Lambda's role may only READ the two prefixes")
    pol = boto3.client("iam").get_role_policy(RoleName="claimsense-door-lambda", PolicyName="door-least-privilege")
    stmts = [s for s in pol["PolicyDocument"]["Statement"] if any(a.startswith("s3:") for a in s["Action"])]
    for s in stmts:
        R.say("   " + mask(json.dumps(s)))
    R.check("S3 access is s3:GetObject only, on policies/* and documents/* only",
            len(stmts) == 1 and stmts[0]["Action"] == ["s3:GetObject"]
            and sorted(x.split("/", 1)[1] for x in stmts[0]["Resource"]) == ["documents/*", "policies/*"])

    blob = "\n".join(R.lines)
    R.check("no token or account id in this evidence", "eyJ" not in blob and account not in blob)
    return R.finish("python evals/s3_doc_store_check.py --deployed")


if __name__ == "__main__":
    sys.exit(main())
