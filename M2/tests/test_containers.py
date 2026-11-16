"""D-033: the RAG store as a service (OpenSearch backend) and the AgentCore HTTP contract, tested without Docker.
The real containers are proven by evals/wiring_check.py (CI stack-smoke job) and scripts/fresh-clone-proof.sh."""
import importlib.util
import json
from pathlib import Path

import httpx

from claimsense.retrieval import OpenSearchIndex, load_corpus, search_with_provenance

M2 = Path(__file__).resolve().parents[1]


class FakeOpenSearch:
    """Just enough of OpenSearch's REST API: mapping/_meta, create, bulk, count and a keyword search."""

    def __init__(self):
        self.mapping, self.docs, self.creates = None, {}, 0

    def __call__(self, req: httpx.Request):
        path, m = req.url.path, req.method
        if path.endswith("/_mapping"):
            return httpx.Response(200, json={"claimsense-clauses": {"mappings": self.mapping}}) if self.mapping \
                else httpx.Response(404, json={})
        if m == "DELETE":
            self.mapping, self.docs = None, {}
            return httpx.Response(200, json={})
        if m == "PUT":
            self.mapping, self.creates = json.loads(req.content)["mappings"], self.creates + 1
            return httpx.Response(200, json={})
        if path == "/_bulk":
            lines = req.content.decode().strip().split("\n")
            for meta, doc in zip(lines[::2], lines[1::2]):
                self.docs[json.loads(meta)["index"]["_id"]] = json.loads(doc)
            return httpx.Response(200, json={"errors": False})
        if path.endswith("/_count"):
            return httpx.Response(200, json={"count": len(self.docs)})
        if path.endswith("/_search"):
            q = json.loads(req.content)["query"]["multi_match"]["query"].lower().split()
            scored = sorted(((sum(w in (d["title"] + " " + d["text"]).lower() for w in q), i)
                             for i, d in self.docs.items()), reverse=True)
            return httpx.Response(200, json={"hits": {"hits": [{"_id": i, "_score": s} for s, i in scored[:3] if s]}})
        return httpx.Response(404, json={})


def test_the_corpus_is_indexed_once_and_searched_through_opensearch():
    chunks, manifest = load_corpus()
    fake = FakeOpenSearch()
    idx = OpenSearchIndex(chunks, "http://opensearch:9200", transport=httpx.MockTransport(fake))
    assert idx.backend == "opensearch-bm25" and idx.count() == len(chunks) == 13
    hits = idx.search("windscreen glass replacement")
    assert hits and hits[0]["clause_id"] and "score" in hits[0]
    OpenSearchIndex(chunks, "http://opensearch:9200", transport=httpx.MockTransport(fake))   # a restart
    assert fake.creates == 1                                    # same corpus hash: not rebuilt


def test_g2_still_quarantines_the_planted_chunk_when_it_comes_from_opensearch():
    chunks, manifest = load_corpus()
    idx = OpenSearchIndex(chunks, "http://opensearch:9200", transport=httpx.MockTransport(FakeOpenSearch()))
    idx.manifest = manifest
    planted = next(c for c in chunks if c["provenance"] == "unknown")
    kept, dropped = search_with_provenance(idx, " ".join(planted["text"].split()[:12]), k=3)
    assert any(d["text"] == planted["text"] for d in dropped)
    assert all(k["text"] != planted["text"] for k in kept)


def _orch():
    spec = importlib.util.spec_from_file_location("orch_c", M2 / "services" / "orchestrator" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_orchestrator_speaks_the_agentcore_runtime_contract():
    from fastapi.testclient import TestClient
    c = TestClient(_orch().app)
    assert c.get("/ping").json()["status"] == "Healthy"
    r = c.post("/invocations", json={"claim_id": "CLM-2024-1800", "user_id": "alice"},
               headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "sess-9"}).json()
    assert r["run_id"] == "CLM-2024-1800:sess-9" and r["response"]["outcome"] == "approve"
    again = c.post("/invocations", json={"claim_id": "CLM-2024-1800", "user_id": "alice"},
                   headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "sess-9"}).json()
    assert again["resumed"] is True and again["cost_usd"] == 0              # same session -> resumed
