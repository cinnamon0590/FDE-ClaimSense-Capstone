"""Prove the containerised stack is wired (W15 "Containerise" + "Set up local RAG", D-033).

"docker compose up --build from a fresh clone brings up the whole stack, and I can prove the agent, the mock
claims API and the RAG store talk to each other." Against the RUNNING stack ($0, replay brain):
  * agent ↔ RAG store   the orchestrator reports OpenSearch with the corpus indexed; a claim's search_clauses
                         calls are answered by OpenSearch and the card cites what it returned
  * boundary ↔ mock API  the boundary serves claims it loaded from the mock systems, which are unreachable from
                         the host (internal network only)
  * guardrails hold      the planted, unprovenanced chunk comes back FROM OpenSearch and G2 quarantines it
  * AgentCore contract   GET /ping and POST /invocations answer
  * containers           every service runs as a non-root user and its image's own HEALTHCHECK is healthy

    cd M2 && MOCK_BRAIN=1 docker compose up --build -d --wait && python evals/wiring_check.py
Writes M2/evidence/container-wiring.txt; exit 1 on any failure.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _auth import BOUNDARY, auth  # noqa: E402

ORCH = "http://localhost:8003"
M2 = Path(__file__).resolve().parents[1]
SERVICES = ["opensearch", "mock-systems", "boundary", "orchestrator", "console"]


def compose(*args):
    return subprocess.run(["docker", "compose", *args], cwd=M2, capture_output=True, text=True).stdout.strip()


def inspect(service, fmt):
    cid = compose("ps", "-q", service)
    return subprocess.run(["docker", "inspect", "-f", fmt, cid], capture_output=True, text=True).stdout.strip() if cid else ""


def run(claim, user="alice"):
    return httpx.post(f"{ORCH}/claims/{claim}/recommend", json={}, headers=auth(user), timeout=180).json()


def main(build_seconds=None):
    out, ok = [f"ClaimSense container wiring proof · {time.strftime('%Y-%m-%d %H:%M:%S')}"], True
    if build_seconds is not None:
        out.append(f"fresh clone -> `docker compose up --build` healthy in {build_seconds:.0f} s "
                   f"(target < 300 s: {'PASS' if build_seconds < 300 else 'OVER'})")
    out.append("")

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        out.append(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))

    h = httpx.get(f"{ORCH}/healthz").json()
    rag = h.get("rag_store", {})
    out.append("Agent ↔ RAG store (OpenSearch)")
    check("orchestrator uses the OpenSearch RAG store", rag.get("backend", "").startswith("opensearch"),
          f"{rag.get('backend')} at {rag.get('url')}")
    check("policy corpus indexed (12 clauses + 1 planted unprovenanced chunk)", rag.get("indexed_chunks") == 13,
          f"{rag.get('indexed_chunks')} documents")
    r = run("CLM-2024-1800")
    searches = [e for e in r["events"] if e["kind"] == "tool" and e["name"] == "search_clauses"]
    retrieved = {cid for e in searches for cid in e.get("retrieved", [])}
    cited = {c["source_id"] for c in r["response"].get("citations", [])}
    check("search_clauses answered by OpenSearch", searches and all(e.get("backend", "").startswith("opensearch")
                                                                     for e in searches),
          f"{len(searches)} searches -> {sorted(retrieved)}")
    check("the card cites only what OpenSearch returned", cited and cited <= retrieved,
          f"{r['response']['outcome']} citing {sorted(cited)}")
    poisoned = run("CLM-2024-3701")                         # CS-020: a poisoned chunk competes in retrieval
    q = [d for e in poisoned["events"] if e["kind"] == "tool" and e["name"] == "search_clauses"
         for d in e.get("quarantined", [])]
    check("G2 quarantines the planted chunk returned by OpenSearch", q and
          "poisoned_chunk_quarantined" in poisoned["response"].get("guardrails_fired", []), f"quarantined {q}")

    out += ["", "Boundary ↔ mock claims API"]
    bh = httpx.get(f"{BOUNDARY}/healthz").json()
    n_fix = len(json.loads((M2.parent / "M1" / "6-synthetic-data" / "fixtures" / "claims.json").read_text())["records"])
    check("boundary loaded the claims from the mock systems", bh.get("claims") == n_fix,
          f"{bh.get('claims')} claims, {n_fix} in the fixtures")
    claim = httpx.get(f"{BOUNDARY}/claims/CLM-2024-1800", headers=auth("alice")).json()
    check("a claim read flows mock systems -> boundary (token-checked)", claim.get("claim_id") == "CLM-2024-1800")
    try:
        httpx.get("http://localhost:8001/healthz", timeout=2)
        exposed = True
    except httpx.HTTPError:
        exposed = False
    check("mock systems unreachable from the host (internal network only)", not exposed)

    out += ["", "AgentCore Runtime HTTP contract (same image)"]
    check("GET /ping", httpx.get(f"{ORCH}/ping").json().get("status") == "Healthy")
    inv = httpx.post(f"{ORCH}/invocations", json={"claim_id": "CLM-2024-1800"}, timeout=180,
                     headers=auth("alice", **{"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "wiring-proof"})).json()
    check("POST /invocations runs the pipeline; the session id becomes the run id",
          inv.get("run_id") == "CLM-2024-1800:wiring-proof" and inv["response"]["outcome"] == "approve",
          f"run {inv.get('run_id')} · resumed={inv.get('resumed')}")

    out += ["", "Containers: non-root, own HEALTHCHECK healthy"]
    for svc in SERVICES:
        user = inspect(svc, "{{.Config.User}}")
        # a container restarted moments ago (CI's restart-survival step) is legitimately "starting": wait for its
        # own HEALTHCHECK to settle, up to 60 s, then judge it
        for _ in range(60):
            health = inspect(svc, "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}")
            if health != "starting":
                break
            time.sleep(1)
        nonroot = svc == "opensearch" or user not in ("", "root", "0")
        if svc == "opensearch":                                 # the upstream image runs as its own 'opensearch' user
            uid = subprocess.run(["docker", "exec", compose("ps", "-q", svc), "id", "-u"], capture_output=True,
                                 text=True).stdout.strip()
            nonroot = uid not in ("", "0")
            user = f"uid {uid}"
        check(f"{svc:<13} user={user or 'root'} · health={health}", nonroot and health == "healthy")

    out += ["", f"CONTAINER WIRING: {'PASS' if ok else 'FAIL'}"]
    text = "\n".join(out)
    print(text)
    Path(os.environ.get("EVIDENCE_DIR", M2 / "evidence"), "container-wiring.txt").write_text(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else None
    sys.exit(main(secs))
