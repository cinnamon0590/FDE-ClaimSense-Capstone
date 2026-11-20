"""The document store on AWS: S3 (M3, D-044; the Learning UI Viewer's "aws s3 sync ./data/policies/ s3://...").

When CLAIMSENSE_DOCS_BUCKET is set (the deployed door), the Policy & Coverage KB corpus, the policy records and the
claim documents are read from the M1 bucket (private, SSE-S3, versioned) instead of the copies baked into the image:

    policies/clauses.json      the policy clause corpus the KB search indexes
    policies/policies.json     the policy records (Policy Administration)
    documents/documents.json   the synthetic claim documents (Document Store)

`M3/cloud/sync_docs.sh` puts them there. What S3 can NOT change: the clause manifest (the signed-off hashes) always
comes from the image, so a clause edited in the bucket fails G2 and is quarantined, never cited. Unset (local stack,
tests, CI): returns None and callers use the fixtures, exactly as before. All data is synthetic.
"""
import json
import os

BUCKET_ENV = "CLAIMSENSE_DOCS_BUCKET"
KEYS = {"clauses": "policies/clauses.json", "policies": "policies/policies.json",
        "documents": "documents/documents.json"}
_cache = {}


def bucket():
    return os.environ.get(BUCKET_ENV) or None


def source():
    return "s3" if bucket() else "image"


def load(name):
    """The named object from the bucket, parsed; None when no bucket is configured. A configured bucket that can't be
    read raises (fail closed: the door never quietly serves a different corpus than the one it was pointed at)."""
    if not bucket():
        return None
    if name not in _cache:
        import boto3
        body = boto3.client("s3").get_object(Bucket=bucket(), Key=KEYS[name])["Body"].read()
        _cache[name] = json.loads(body)
    return _cache[name]
