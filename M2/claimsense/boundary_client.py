"""The ONE door to client data (M1 D-003). Agents' tools call this and nothing else.

Two transports behind one interface:
  * LocalBoundary: the M1 reference boundary in-process (tests, CI, the mock brain)
  * HttpBoundary:  the `boundary` container over HTTP (docker compose; M3 replaces it with
                   API Gateway + Lambda + Cognito JWT, with the same routes and the same rules)
Entitlement, anti-enumeration, audit and idempotency are enforced by the boundary, in code,
before any data reaches an agent.
"""
import json
import sqlite3
from pathlib import Path

from ._m1 import FIXTURES, SCHEMAS, boundary as ref, jsonschema_lite
from .deterministic import compute

_COMMON = json.loads((SCHEMAS / "common.schema.json").read_text())

AGENT_IDS = {"intake": "agent:document-intake", "coverage": "agent:coverage-check",
             "assessment": "agent:claim-assessment", "decision": "agent:decision-draft"}


def users():
    return {u["user_id"]: u for u in json.loads((FIXTURES / "users.json").read_text())["records"]}


class PersistentDict(dict):
    """A dict that writes through to SQLite, so the boundary's drafts and idempotency records survive a
    restart (D-027). Local twin of the DynamoDB tables M1 provisioned (claimsense-idempotency) for M3."""

    def __init__(self, path, table, encode_key=str, decode_key=str):
        super().__init__()
        self.path, self.table, self._ek = Path(path), table, encode_key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(f"CREATE TABLE IF NOT EXISTS {table} (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
            for k, v in db.execute(f"SELECT k, v FROM {table}"):
                super().__setitem__(decode_key(k), _untuple(json.loads(v)))

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.save(key)

    def save(self, key):
        """Re-persist a value that was mutated in place."""
        with sqlite3.connect(self.path) as db:
            db.execute(f"INSERT OR REPLACE INTO {self.table} VALUES (?, ?)", (self._ek(key), json.dumps(self[key])))


def _untuple(v):
    # idempotency values are (fingerprint, response) tuples; JSON brings them back as lists
    return tuple(v) if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], dict) else v


class LocalBoundary(ref.Boundary):
    """Reference boundary plus document reads (the Document Store contract's GET /documents/{id}).
    With `state_path`, drafts and idempotency records persist in SQLite (restart-survivable, D-027)."""

    def __init__(self, state_path=None):
        super().__init__()
        if state_path:
            self.persist(state_path)

    def persist(self, state_path):
        self.recommendations = PersistentDict(state_path, "recommendations")
        self._idem = PersistentDict(state_path, "idempotency", encode_key=lambda k: json.dumps(list(k)),
                                    decode_key=lambda s: tuple(json.loads(s)))

    def confirm_recommendation(self, caller, request):
        rid = request.get("recommendation_id")
        rec = self.recommendations.get(rid)
        slot = (caller["user_id"], "confirm_recommendation", request.get("idempotency_key"))
        if rec and rec.get("confirmation") and slot not in self._idem and self.entitled(caller, self.claims[rec["claim_id"]]):
            # a draft is decided exactly once: a second confirm/override under a NEW key is a conflict, not an overwrite
            # (the same key still replays the original receipt, via the reference idempotency rule)
            done = rec["confirmation"]
            erid = self._audit(caller, "confirm_recommendation", rid, "error", "already_confirmed")
            return self._error("already_confirmed", f"This recommendation was already {done['action']}ed by "
                               f"{done['confirmed_by']} at {done['confirmed_at']}.", erid)
        out = super().confirm_recommendation(caller, request)
        if isinstance(self.recommendations, PersistentDict) and rid in self.recommendations:
            self.recommendations.save(rid)                 # the confirmation was written into the record in place
        return out

    def get_document(self, caller, doc_id, agent=None):
        doc = self.documents.get(doc_id)
        claim = self.claims.get(doc["claim_id"]) if doc else None
        if doc is None or not self.entitled(caller, claim):
            rid = self._audit(caller, "get_document", doc_id, "deny", "not_found_or_not_entitled", agent)
            return self._error("not_found_or_forbidden", "No document is available for this request.", rid)
        self._audit(caller, "get_document", doc_id, "allow", on_behalf_of_agent=agent)
        return dict(doc)

    def caller(self, user_id):
        u = self.users.get(user_id) or {"user_id": user_id, "groups": []}
        return {"user_id": u["user_id"], "groups": list(u["groups"])}

    # uniform client API (user_id in, dict out) shared with HttpBoundary
    def claim(self, user_id, claim_id, agent=None):
        return self.get_claim(self.caller(user_id), claim_id, agent)

    def policy(self, user_id, policy_id, agent=None):
        return self.get_policy(self.caller(user_id), policy_id, agent)

    def documents_for(self, user_id, claim_id, agent=None):
        return self.list_documents(self.caller(user_id), claim_id, agent)

    def document(self, user_id, doc_id, agent=None):
        return self.get_document(self.caller(user_id), doc_id, agent)

    def recommend(self, user_id, claim_id, card, idempotency_key, agent="agent:decision-draft"):
        caller = self.caller(user_id)
        claim = self.claims.get(claim_id)
        if claim is not None and self.entitled(caller, claim):
            # never trust the writer's numbers: the confirm step checks the $25K authority limit against
            # card.computed, so the boundary re-derives it in code (G4 at the door) and rejects any draft
            # that is not a valid DecisionCard for THIS claim
            card = dict(card, computed=compute(claim, self.policies[claim["policy_id"]]))
            errors = jsonschema_lite.validate(card, {"$ref": "#/$defs/DecisionCard", "$defs": _COMMON["$defs"]},
                                              root=_COMMON)
            if card.get("claim_id") != claim_id:
                errors.append("decision_card.claim_id does not match the claim in the path")
            if errors:
                rid = self._audit(caller, "post_recommendation", claim_id, "error", "invalid DecisionCard", agent)
                return self._error("invalid_request", "The draft is not a valid DecisionCard for this claim.", rid)
        return self.post_recommendation(caller, {"claim_id": claim_id, "decision_card": card,
                                                 "idempotency_key": idempotency_key}, agent)

    def confirm(self, user_id, request, agent=None):
        # confirmation is human-only: a request made by an agent is refused even when it acts for a
        # human who could confirm (the agent identity is the caller, so the M1 rule denies and audits it)
        caller = {"user_id": agent, "groups": []} if agent else self.caller(user_id)
        return self.confirm_recommendation(caller, request)


class HttpBoundary:
    """Client for services/boundary. Identity travels in headers today; M3 swaps in a Cognito JWT."""

    def __init__(self, base_url):
        import httpx
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=15)

    def _get(self, path, user_id, agent):
        h = {"X-User-Id": user_id}
        if agent:
            h["X-On-Behalf-Of-Agent"] = agent
        return self.http.get(path, headers=h).json()

    def claim(self, user_id, claim_id, agent=None):
        return self._get(f"/claims/{claim_id}", user_id, agent)

    def policy(self, user_id, policy_id, agent=None):
        return self._get(f"/policies/{policy_id}", user_id, agent)

    def documents_for(self, user_id, claim_id, agent=None):
        return self._get(f"/claims/{claim_id}/documents", user_id, agent)

    def document(self, user_id, doc_id, agent=None):
        return self._get(f"/documents/{doc_id}", user_id, agent)

    def recommend(self, user_id, claim_id, card, idempotency_key, agent="agent:decision-draft"):
        return self.http.post(f"/claims/{claim_id}/recommendations", json={"decision_card": card},
                              headers={"X-User-Id": user_id, "X-On-Behalf-Of-Agent": agent,
                                       "Idempotency-Key": idempotency_key}).json()

    def confirm(self, user_id, request, agent=None):
        headers = {"X-User-Id": user_id, "Idempotency-Key": request["idempotency_key"]}
        if agent:
            headers["X-On-Behalf-Of-Agent"] = agent
        return self.http.post(f"/recommendations/{request['recommendation_id']}/confirm", json=request,
                              headers=headers).json()


def make_boundary(url=""):
    return HttpBoundary(url) if url else LocalBoundary()
