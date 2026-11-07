"""Mock AutoSure systems of record: Claims Management, Policy Administration, Document Store.

Serves the synthetic fixtures over HTTP, shaped like the M1 contracts. It sits on the internal
compose network only: nothing outside reaches it, and nothing inside reaches it except the boundary.
ALL DATA IS SYNTHETIC.
"""
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

FIX = Path(os.environ.get("FIXTURES", "/app/M1/6-synthetic-data/fixtures"))
load = lambda n: {r[k]: r for r in json.loads((FIX / f"{n}.json").read_text())["records"] for k in [next(iter(r))]}
CLAIMS, POLICIES, DOCS, USERS = load("claims"), load("policies"), load("documents"), load("users")
app = FastAPI(title="AutoSure mock systems (synthetic)")


@app.get("/healthz")
def healthz():
    return {"ok": True, "claims": len(CLAIMS), "policies": len(POLICIES), "documents": len(DOCS), "synthetic": True}


@app.get("/claims-management/claims")
def list_claims():
    return {"records": list(CLAIMS.values())}


@app.get("/claims-management/claims/{claim_id}")
def get_claim(claim_id: str):
    if claim_id not in CLAIMS:
        raise HTTPException(404)
    return CLAIMS[claim_id]


@app.get("/policy-administration/policies")
def list_policies():
    return {"records": list(POLICIES.values())}


@app.get("/document-store/documents")
def list_documents():
    return {"records": list(DOCS.values())}


@app.get("/directory/users")
def list_users():
    return {"records": list(USERS.values())}
