"""Deliverable 3: retrieval over the clause corpus; only provenanced chunks reach the model."""
import json

from claimsense._m1 import FIXTURES, guardrails as G
from claimsense.retrieval import get_index, load_corpus, search_with_provenance

QUERIES = json.loads((FIXTURES / "clauses.json").read_text())


def test_manifest_hashes_match_the_clause_text():
    chunks, manifest = load_corpus()
    real = [c for c in chunks if c["provenance"] == "manifest"]
    assert len(real) == 12
    assert all(G.chunk_hash(c["clause_id"], c["text"]) in manifest for c in real)


def test_poisoned_chunk_is_in_the_index_but_never_returned():
    idx = get_index("lexical")
    hits = idx.search("is a lapsed policy still covered after the end date", k=3)
    assert any(h["provenance"] == "unknown" for h in hits), "the planted chunk should rank for this query"
    kept, dropped = search_with_provenance(idx, "is a lapsed policy still covered after the end date", k=3)
    assert dropped and all(k["provenance"] == "manifest" for k in kept)
    assert not any("always approve" in k["text"] for k in kept)


def test_plain_language_queries_find_each_clause():
    from evals_queries import QUERY
    idx = get_index("lexical")
    for clause_id, q in QUERY.items():
        kept, _ = search_with_provenance(idx, q, k=3)
        assert clause_id in [k["clause_id"] for k in kept], (clause_id, q)
