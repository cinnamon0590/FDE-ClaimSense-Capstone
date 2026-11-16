"""The full 40-case eval THROUGH the running containers (D-033): console-facing API -> orchestrator -> boundary
-> mock systems, with retrieval served by the OpenSearch RAG store. Proves the containerised stack reaches the same
decisions as the in-process gate. $0 on the replay brain. Run it BEFORE evals/rbac_check.py (its hand-offs move
some claims out of the first-pass adjuster's reach). Writes M2/evidence/container-eval.txt; exit 1 on any miss.
"""
import os
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
from _auth import auth  # noqa: E402
from claimsense._m1 import score  # noqa: E402
from claimsense.cases import all_cases  # noqa: E402

ORCH = os.environ.get("ORCHESTRATOR_URL", "http://localhost:8003")


def main():
    rag = httpx.get(f"{ORCH}/healthz").json().get("rag_store", {})
    lines, misses = [f"ClaimSense 40-case eval through the containers · {time.strftime('%Y-%m-%d %H:%M:%S')}",
                     f"retrieval: {rag.get('backend')} ({rag.get('indexed_chunks')} documents) · identity: signed tokens", ""], []
    for c in all_cases():
        r = httpx.post(f"{ORCH}/claims/{c['claim']['claim_id']}/recommend", json={},
                       headers=auth(c["requesting_user"]["id"]), timeout=180).json()
        resp = dict(r["response"])
        if "citations" in resp:
            resp["citations"] = [x["source_id"] for x in resp["citations"]]
            resp["returns_claim_data"] = True
        why = score.fail_reason(c, resp)
        got = resp.get("outcome", "?") + (f"→{resp['route_to']}" if resp.get("route_to") else "")
        lines.append(f"  {'PASS' if why is None else 'FAIL'}  {c['case_id']}  {got:<34} {r.get('decided_by')}"
                     + (f"  ({why})" if why else ""))
        if why:
            misses.append(c["case_id"])
    lines += ["", f"{40 - len(misses)}/40 through the containers", f"CONTAINER EVAL: {'PASS' if not misses else 'FAIL'}"]
    text = "\n".join(lines)
    print(text)
    try:
        (HERE.parent / "evidence" / "container-eval.txt").write_text(text + "\n")
    except OSError:
        pass                                   # run inside a sealed container: the caller captures stdout instead
    return 0 if not misses else 1


if __name__ == "__main__":
    sys.exit(main())
