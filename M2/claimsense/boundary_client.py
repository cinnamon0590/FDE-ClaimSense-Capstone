"""The ONE door to client data (M1 D-003). Agents' tools call this and nothing else.

Two transports behind one interface:
  * LocalBoundary: the M1 reference boundary in-process (tests, CI, the mock brain)
  * HttpBoundary:  the `boundary` container over HTTP (docker compose; M3 replaces it with
                   API Gateway + Lambda + Cognito JWT, with the same routes and the same rules)
Entitlement, anti-enumeration, audit and idempotency are enforced by the boundary, in code,
before any data reaches an agent.
"""
import json

from ._m1 import FIXTURES, boundary as ref

AGENT_IDS = {"intake": "agent:document-intake", "coverage": "agent:coverage-check",
             "assessment": "agent:claim-assessment", "decision": "agent:decision-draft"}


def users():
    return {u["user_id"]: u for u in json.loads((FIXTURES / "users.json").read_text())["records"]}


class LocalBoundary(ref.Boundary):
    """Reference boundary plus document reads (the Document Store contract's GET /documents/{id})."""

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
        return self.post_recommendation(self.caller(user_id), {"claim_id": claim_id, "decision_card": card,
                                                               "idempotency_key": idempotency_key}, agent)

    def confirm(self, user_id, request):
        return self.confirm_recommendation(self.caller(user_id), request)


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

    def confirm(self, user_id, request):
        return self.http.post(f"/recommendations/{request['recommendation_id']}/confirm", json=request,
                              headers={"X-User-Id": user_id, "Idempotency-Key": request["idempotency_key"]}).json()


def make_boundary(url=""):
    return HttpBoundary(url) if url else LocalBoundary()
