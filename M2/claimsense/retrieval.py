"""Retrieval over the AutoSure policy-clause corpus.

One interface, `search(query, k) -> [chunk]`, three backends:
  * "embedding": OpenAI text-embedding-3-large vectors, cosine top-k (live; vectors cached on disk)
  * "lexical":   TF-IDF cosine in numpy (no key, $0; used by CI and the mock brain)
  * "opensearch": the AWS path (k-NN index); same interface, enabled in a later milestone

The index deliberately ALSO contains the planted, unprovenanced chunk from the fixtures
(`untrusted_index_injections`), like a compromised knowledge base would. Retrieval returns it if it
ranks; guardrail G2 (provenance quarantine) must drop it before any model sees it. Retrieval never
decides what is trustworthy: provenance does.
"""
import hashlib
import json
import math
import re
from collections import Counter

import numpy as np

from . import config
from ._m1 import FIXTURES, guardrails

STOP = set("a an the of to for and or in on at by is are be was were with any your our we you it its "
           "this that than from as not no all when only".split())


def _tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9$]+", text.lower()):
        if w in STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def load_corpus():
    src = json.loads((FIXTURES / "clauses.json").read_text())
    chunks = [{"clause_id": c["clause_id"], "title": c["title"], "section": c["section"], "text": c["text"],
               "applies_to": c["applies_to"], "provenance": "manifest"} for c in src["records"]]
    for inj in src.get("untrusted_index_injections", []):
        chunks.append({"clause_id": inj["chunk_label"].split()[0], "title": "", "section": "",
                       "text": inj["text"], "applies_to": ["*"], "provenance": "unknown"})
    manifest = {c["manifest_sha256"] for c in src["records"]}
    return chunks, manifest


class LexicalIndex:
    backend = "lexical"

    def __init__(self, chunks):
        self.chunks = chunks
        docs = [_tokens(f"{c['title']} {c['title']} {c['text']} {' '.join(c['applies_to'])}") for c in chunks]
        self.vocab = {w: i for i, w in enumerate(sorted({w for d in docs for w in d}))}
        df = Counter(w for d in docs for w in set(d))
        self.idf = np.array([math.log((1 + len(docs)) / (1 + df[w])) + 1 for w in self.vocab])
        self.m = np.vstack([self._vec(d) for d in docs])

    def _vec(self, toks):
        v = np.zeros(len(self.vocab))
        for w, n in Counter(toks).items():
            if w in self.vocab:
                v[self.vocab[w]] = n
        v *= self.idf
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def search(self, query, k=3):
        scores = self.m @ self._vec(_tokens(query))
        order = [i for i in np.argsort(-scores) if scores[i] > 0][:k]
        return [dict(self.chunks[i], score=round(float(scores[i]), 4)) for i in order]


class EmbeddingIndex:
    backend = "embedding"

    def __init__(self, chunks, model=None):
        from openai import OpenAI
        self.client, self.model, self.chunks = OpenAI(), model or config.EMBEDDING_MODEL, chunks
        texts = [f"{c['title']}. {c['text']}" for c in chunks]
        key = hashlib.sha256(json.dumps([self.model, texts]).encode()).hexdigest()[:16]
        cache = config.STATE_DIR / f"clauses-{key}.npy"
        if cache.exists():
            self.m = np.load(cache)
        else:
            self.m = self._embed(texts)
            config.STATE_DIR.mkdir(parents=True, exist_ok=True)
            np.save(cache, self.m)

    def _embed(self, texts):
        data = self.client.embeddings.create(model=self.model, input=texts).data
        m = np.array([d.embedding for d in data])
        return m / np.linalg.norm(m, axis=1, keepdims=True)

    def search(self, query, k=3):
        q = self._embed([query])[0]
        scores = self.m @ q
        order = list(np.argsort(-scores))[:k]
        return [dict(self.chunks[i], score=round(float(scores[i]), 4)) for i in order]


_INDEX = {}


def get_index(backend=None):
    """Embedding index when a key is configured and the brain is live; lexical otherwise."""
    # Bedrock runs stay inside AWS: no OpenAI embeddings, the local lexical index instead
    backend = backend or ("embedding" if not config.MOCK_BRAIN and config.MODEL_PROVIDER == "openai" else "lexical")
    if backend not in _INDEX:
        chunks, manifest = load_corpus()
        idx = EmbeddingIndex(chunks) if backend == "embedding" else LexicalIndex(chunks)
        idx.manifest = manifest
        _INDEX[backend] = idx
    return _INDEX[backend]


def with_all_versions(index, hits):
    """A clause ID can have several entries in a versioned knowledge base (e.g. an 'updated' wording).
    Return every entry that claims a retrieved clause ID, so provenance (not luck of ranking) decides which
    version reaches the model."""
    ids = {h["clause_id"] for h in hits}
    seen = {(h["clause_id"], h["text"]) for h in hits}
    extra = [dict(c, score=None) for c in index.chunks if c["clause_id"] in ids and (c["clause_id"], c["text"]) not in seen]
    return hits + extra


def search_with_provenance(index, query, k=3):
    """Retrieve, then apply G2: only chunks whose hash is in the clause manifest survive."""
    hits = with_all_versions(index, index.search(query, k))
    kept, dropped = guardrails.quarantine_chunks(hits, index.manifest)
    return kept, dropped
