"""The ONE door to client data (M1 D-003). Agents' tools call this and nothing else.

Two transports behind one interface:
  * LocalBoundary: the M1 reference boundary in-process (tests, CI, the mock brain)
  * HttpBoundary:  the `boundary` container over HTTP (docker compose; M3 replaces it with
                   API Gateway + Lambda + Cognito JWT, with the same routes and the same rules)
Entitlement, anti-enumeration, audit and idempotency are enforced by the boundary, in code,
before any data reaches an agent.
"""
import contextvars
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
        self.assignments = PersistentDict(state_path, "assignments")      # claim_id -> group, after a hand-off
        for claim_id, group in self.assignments.items():
            if claim_id in self.claims:
                self.claims[claim_id]["assigned_group"] = group

    # ── routing hand-off (D-030): a confirmed route moves the claim into that specialist group's queue ─────
    HANDOFF_GROUPS = {"fraud-investigator", "total-loss-appraiser", "injury-specialist", "senior-adjuster"}

    def _hand_off(self, caller, rec, request):
        """After a HUMAN confirms (or overrides to) route/flag_review, reassign the claim to the target group, so
        the specialist can open it and the first-pass adjuster no longer can (least privilege). Audited."""
        card = rec["card"]
        outcome = request.get("final_outcome") or card.get("outcome")
        target = request.get("route_to") or card.get("route_to")
        if outcome not in ("route", "flag_review") or target not in self.HANDOFF_GROUPS:
            return None
        claim = self.claims[rec["claim_id"]]
        before = claim["assigned_group"]
        if before == target:
            return None
        claim["assigned_group"] = target
        if hasattr(self, "assignments"):
            self.assignments[rec["claim_id"]] = target
        self._audit(caller, "reassign_claim", rec["claim_id"], "allow", f"{before} -> {target} (confirmed {outcome})")
        return {"claim_id": rec["claim_id"], "from": before, "to": target}

    def post_recommendation(self, caller, request, agent="decision-draft"):
        receipt = super().post_recommendation(caller, request, agent)
        rid = receipt.get("recommendation_id")
        if rid in self.recommendations and not receipt.get("idempotent_replay"):
            # queue metadata, so the adjuster queue can list drafts without re-deriving them
            self.recommendations[rid].update(version=receipt["version"], created_at=receipt["created_at"],
                                             drafted_for=caller["user_id"], agent=agent)
            if isinstance(self.recommendations, PersistentDict):
                self.recommendations.save(rid)
        return receipt

    # ── the adjuster queue (W15: "a recommendation in her ops team's own queue") ──────────────────────
    def list_pending(self, caller):
        """Undecided drafts on claims the caller is entitled to, newest first. Audited like any read."""
        rows = []
        for rid, rec in self.recommendations.items():
            claim = self.claims.get(rec["claim_id"])
            if rec.get("confirmation") or claim is None or not self.entitled(caller, claim):
                continue
            card = rec["card"]
            rows.append({"recommendation_id": rid, "claim_id": rec["claim_id"], "version": rec.get("version"),
                         "created_at": rec.get("created_at"), "outcome": card.get("outcome"),
                         "route_to": card.get("route_to"), "net_payable": card.get("computed", {}).get("net_payable"),
                         "verdict_source": card.get("verdict_source"), "guardrails_fired": card.get("guardrails_fired", [])})
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        self._audit(caller, "list_pending_recommendations", "queue", "allow", f"{len(rows)} drafts")
        return {"pending": rows}

    def latest_draft(self, caller, claim_id, agent=None):
        """The newest draft for one claim (any status), entitlement first, same error for missing/forbidden."""
        claim = self.claims.get(claim_id)
        if claim is None or not self.entitled(caller, claim):
            rid = self._audit(caller, "get_latest_draft", claim_id, "deny", "not_found_or_not_entitled", agent)
            return self._error("not_found_or_forbidden", "No draft is available for this request.", rid)
        mine = [(rid, r) for rid, r in self.recommendations.items() if r["claim_id"] == claim_id]
        if not mine:
            rid = self._audit(caller, "get_latest_draft", claim_id, "deny", "no_draft", agent)
            return self._error("not_found_or_forbidden", "No draft is available for this request.", rid)
        rid, rec = max(mine, key=lambda x: (x[1].get("version") or 0, x[1].get("created_at") or ""))
        self._audit(caller, "get_latest_draft", claim_id, "allow", on_behalf_of_agent=agent)
        return {"recommendation_id": rid, "version": rec.get("version"), "card": rec["card"],
                "status": "decided" if rec.get("confirmation") else "draft_pending_confirmation",
                "confirmation": rec.get("confirmation")}

    # uniform client API for the queue
    def pending(self, user_id):
        return self.list_pending(self.caller(user_id))

    def draft(self, user_id, claim_id, agent=None):
        return self.latest_draft(self.caller(user_id), claim_id, agent)

    def confirm_recommendation(self, caller, request):
        rid = request.get("recommendation_id")
        rec = self.recommendations.get(rid)
        slot = (caller["user_id"], "confirm_recommendation", request.get("idempotency_key"))
        if slot in self._idem and self._idem[slot][0] == ref._fingerprint(request):
            # the decider's own resubmit replays the receipt, even after the hand-off moved the claim away from them
            self._audit(caller, "confirm_recommendation", rid, "replay", "same key, same payload")
            return dict(self._idem[slot][1], idempotent_replay=True)
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
        if "error" not in out and not out.get("idempotent_replay") and rid in self.recommendations:
            if (moved := self._hand_off(caller, self.recommendations[rid], request)):
                out = dict(out, handed_off=moved)
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


# The adjuster's token for THIS request (set by the orchestrator per request; asyncio tasks inherit it), forwarded
# to the boundary so every agent data access is made as that adjuster, on behalf of a named agent (D-030).
CALLER_TOKEN: contextvars.ContextVar = contextvars.ContextVar("claimsense_caller_token", default=None)


class HttpBoundary:
    """Client for services/boundary. Identity is the caller's JWT (forwarded); X-User-Id is only honoured by a
    boundary started with CLAIMSENSE_ALLOW_HEADER_IDENTITY=1 (tests). M3 points this at API Gateway + Cognito."""

    def __init__(self, base_url):
        import httpx
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=15)

    @staticmethod
    def _headers(user_id, agent=None, **extra):
        h = {"X-User-Id": user_id} | extra
        if (token := CALLER_TOKEN.get()):
            h["Authorization"] = f"Bearer {token}"
        if agent:
            h["X-On-Behalf-Of-Agent"] = agent
        return h

    def _get(self, path, user_id, agent, **params):
        r = self.http.get(path, headers=self._headers(user_id, agent), params=params or None)
        try:
            body = r.json()
        except ValueError:
            body = {}
        if r.status_code >= 500 and not isinstance(body.get("error"), dict):   # the door is down (incident-drill-1)
            return {"error": {"code": "upstream_unavailable", "message": f"HTTP {r.status_code} from the door"}}
        return body

    def claim(self, user_id, claim_id, agent=None):
        return self._get(f"/claims/{claim_id}", user_id, agent)

    def policy(self, user_id, policy_id, agent=None):
        return self._get(f"/policies/{policy_id}", user_id, agent)

    def documents_for(self, user_id, claim_id, agent=None):
        return self._get(f"/claims/{claim_id}/documents", user_id, agent)

    def document(self, user_id, doc_id, agent=None):
        return self._get(f"/documents/{doc_id}", user_id, agent)

    def pending(self, user_id):
        return self._get("/recommendations", user_id, None, status="pending")

    def draft(self, user_id, claim_id, agent=None):
        return self._get(f"/claims/{claim_id}/recommendations/latest", user_id, agent)

    def recommend(self, user_id, claim_id, card, idempotency_key, agent="agent:decision-draft"):
        return self.http.post(f"/claims/{claim_id}/recommendations", json={"decision_card": card},
                              headers=self._headers(user_id, agent, **{"Idempotency-Key": idempotency_key})).json()

    def confirm(self, user_id, request, agent=None):
        return self.http.post(f"/recommendations/{request['recommendation_id']}/confirm", json=request,
                              headers=self._headers(user_id, agent,
                                                    **{"Idempotency-Key": request["idempotency_key"]})).json()


class McpBoundary(HttpBoundary):
    """M3 (D-036): the agents reach client data ONLY as MCP tools on the governed door (`POST /mcp`, JSON-RPC 2.0,
    spec 2025-06-18). Same interface as HttpBoundary, so the pipeline and the agents' tools do not change; the
    adjuster's verified token rides on every call, so the door enforces THAT adjuster's grants and entitlement.
    Human-only paths (the queue, confirm) stay on the REST door."""

    PROTOCOL = "2025-06-18"

    def __init__(self, base_url, mcp_url=None):
        super().__init__(base_url)
        self.mcp_url = mcp_url or f"{base_url.rstrip('/')}/mcp"
        self._n, self._ready = 0, False

    def _rpc(self, method, params, user_id, agent=None):
        self._n += 1
        h = self._headers(user_id, agent, **{"MCP-Protocol-Version": self.PROTOCOL})
        r = self.http.post(self.mcp_url, json={"jsonrpc": "2.0", "id": self._n, "method": method, "params": params},
                           headers=h)
        try:
            body = r.json()
        except ValueError:
            body = {}
        if "result" not in body and "error" not in body:     # e.g. a gateway refusal ({"message": "Unauthorized"})
            body = {"error": {"message": body.get("message") or f"HTTP {r.status_code} from the door"}}
        if "error" in body:                                  # transport refusal (401) or a JSON-RPC error
            data = body["error"].get("data") or {}
            code = ("unauthenticated" if r.status_code == 401 else "upstream_unavailable" if r.status_code >= 500
                    else "invalid_request")              # 5xx = the door is down, not a refusal (incident-drill-1)
            return {"error": {"code": code, "message": body["error"]["message"],
                              "request_id": data.get("request_id", "-")}}
        return body["result"]

    def _tool(self, name, args, user_id, agent=None):
        if not self._ready:                                  # MCP lifecycle: initialize once per client
            init = self._rpc("initialize", {"protocolVersion": self.PROTOCOL, "capabilities": {},
                                            "clientInfo": {"name": "claimsense-orchestrator", "version": "1"}},
                             user_id, agent)
            self._ready = "error" not in init
        res = self._rpc("tools/call", {"name": name, "arguments": args}, user_id, agent)
        if "error" in res and "content" not in res:
            return res
        return res.get("structuredContent") or json.loads(res["content"][0]["text"])

    def claim(self, user_id, claim_id, agent=None):
        return self._tool("get_claim", {"claim_id": claim_id}, user_id, agent)

    def policy(self, user_id, policy_id, agent=None):
        return self._tool("get_policy", {"policy_id": policy_id}, user_id, agent)

    def documents_for(self, user_id, claim_id, agent=None):
        return self._tool("list_claim_documents", {"claim_id": claim_id}, user_id, agent)

    def document(self, user_id, doc_id, agent=None):
        return self._tool("get_document", {"doc_id": doc_id}, user_id, agent)

    def search_clauses(self, user_id, query, k=3, agent=None):
        return self._tool("search_policy_clauses", {"query": query, "k": k}, user_id, agent)

    def draft(self, user_id, claim_id, agent=None):
        return self._tool("get_latest_draft", {"claim_id": claim_id}, user_id, agent)

    def recommend(self, user_id, claim_id, card, idempotency_key, agent="agent:decision-draft"):
        return self._tool("create_recommendation", {"claim_id": claim_id, "decision_card": card,
                                                    "idempotency_key": idempotency_key}, user_id, agent)

    def escalate(self, user_id, claim_id, reason, idempotency_key, priority="normal", agent=None):
        return self._tool("create_escalation_ticket", {"claim_id": claim_id, "reason": reason, "priority": priority,
                                                       "idempotency_key": idempotency_key}, user_id, agent)

    def escalation(self, user_id, claim_id, agent=None):
        return self._tool("get_escalation", {"claim_id": claim_id}, user_id, agent)


def make_boundary(url="", mcp_url=""):
    if mcp_url:
        return McpBoundary(url or mcp_url.rsplit("/mcp", 1)[0], mcp_url)
    return HttpBoundary(url) if url else LocalBoundary()
