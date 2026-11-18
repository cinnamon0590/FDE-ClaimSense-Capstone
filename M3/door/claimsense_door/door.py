"""The ClaimSense governed door (M3, D-036): the one place an agent, the console or another system reaches client data.

The W16 lab's anatomy, applied to AutoSure's four systems of record:

  1. Identity       who is acting: the verified token's user and the DIRECTORY's groups (never a tool argument)
  2. _authorize     two deterministic gates, in order: the ACTION gate (explicit grants, deny-by-default) and the
                    RECORD gate (the M1 entitlement rule: which claims a group may see). The audit row is written
                    BEFORE a denial is returned; missing and forbidden records get the identical answer.
  3. typed tools    get_claim · get_policy · list_documents · get_document (Claims, Policy Admin, Document Store),
                    search_policy_clauses (Policy & Coverage KB), post_recommendation (idempotent draft),
                    create_escalation_ticket / get_escalation (the 4th backend: SIU escalation ticketing)
  4. AuditLog       every call, allowed, denied, replayed or failed, one append-only row (claimsense.audit_trail)

The model is never asked whether a user may see something. A prompt injection can change what the model asks
for; it cannot change what these gates return.
"""
import hashlib
import hmac
import json
import os
import time

from claimsense import audit_trail
from claimsense.boundary_client import LocalBoundary, PersistentDict

from .grants import granted
from .obo import TOKEN_ACTOR, TOKEN_SCOPE
from .ticketing import TicketingClient, TicketingUnavailable

# denial text per action: identical for "no grant", "not entitled" and "does not exist" (anti-enumeration)
DENIED = {"get_claim": "No claim is available for this request.",
          "list_documents": "No claim is available for this request.",
          "post_recommendation": "No claim is available for this request.",
          "create_escalation_ticket": "No claim is available for this request.",
          "get_escalation": "No claim is available for this request.",
          "get_policy": "No policy is available for this request.",
          "get_document": "No document is available for this request.",
          "get_latest_draft": "No draft is available for this request.",
          "list_pending_recommendations": "No queue is available for this request.",
          "search_policy_clauses": "No policy wording is available for this request.",
          "read_audit": "No audit view is available for this request.",
          "confirm_recommendation": "No recommendation is available for this request."}
WEBHOOK_TOLERANCE_S = 300
SERVICE_TICKETING = {"user_id": "system:ticketing", "groups": []}


class GrantedBoundary(LocalBoundary):
    """M2's boundary (entitlement, anti-enumeration, idempotency, human-only confirm, hand-offs) behind an explicit
    grant gate, writing the shared audit trail. Used by the REST routes, the MCP door and the webhook receiver."""

    def __init__(self, state_path=None, ticketing=None, clause_index=None):
        self.escalations, self.webhook_events = {}, {}          # persist() swaps in SQLite-backed dicts
        super().__init__(state_path)
        self.ticketing = ticketing
        self._clause_index = clause_index

    def persist(self, state_path):
        super().persist(state_path)
        self.escalations = PersistentDict(state_path, "escalations")
        self.webhook_events = PersistentDict(state_path, "webhook_events")

    # ── audit: one shared, append-only trail (in-memory copy kept for the reference contract tests) ─────────────
    def _audit(self, caller, action, resource, decision, reason="", on_behalf_of_agent=None):
        # a delegated (OBO) token names its agent in `act`; that beats any self-declared agent header
        rec = audit_trail.row(caller["user_id"], caller.get("groups"), action, resource, decision, reason,
                              on_behalf_of_agent=TOKEN_ACTOR.get() or on_behalf_of_agent)
        self.audit.append(rec)
        audit_trail.append(rec)
        return rec["request_id"]

    # ── gate 1: the action grant (deny-by-default). Gate 2 (entitlement) is the inherited M1 rule. ─────────────
    def _authorize(self, caller, action, resource, agent=None):
        """None when the action is granted; otherwise the audited denial (written BEFORE it is returned)."""
        scope = TOKEN_SCOPE.get()                    # a delegated token narrows further: grants AND token scope
        if granted(caller, action) and (scope is None or action in scope):
            return None
        reason = "no_grant" if not granted(caller, action) else "outside the delegated token's scope"
        rid = self._audit(caller, action, resource, "deny", reason, agent)
        return self._error("not_found_or_forbidden", DENIED.get(action, "This request is not available."), rid)

    # ── the uniform client API, every method gated ───────────────────────────────────────────────────────────
    def claim(self, user_id, claim_id, agent=None):
        c = self.caller(user_id)
        return self._authorize(c, "get_claim", claim_id, agent) or self.get_claim(c, claim_id, agent)

    def policy(self, user_id, policy_id, agent=None):
        c = self.caller(user_id)
        return self._authorize(c, "get_policy", policy_id, agent) or self.get_policy(c, policy_id, agent)

    def documents_for(self, user_id, claim_id, agent=None):
        c = self.caller(user_id)
        return self._authorize(c, "list_documents", claim_id, agent) or self.list_documents(c, claim_id, agent)

    def document(self, user_id, doc_id, agent=None):
        c = self.caller(user_id)
        return self._authorize(c, "get_document", doc_id, agent) or self.get_document(c, doc_id, agent)

    def recommend(self, user_id, claim_id, card, idempotency_key, agent="agent:decision-draft"):
        c = self.caller(user_id)
        return self._authorize(c, "post_recommendation", claim_id, agent) or \
            super().recommend(user_id, claim_id, card, idempotency_key, agent)

    def draft(self, user_id, claim_id, agent=None):
        c = self.caller(user_id)
        return self._authorize(c, "get_latest_draft", claim_id, agent) or self.latest_draft(c, claim_id, agent)

    def pending(self, user_id):
        c = self.caller(user_id)
        return self._authorize(c, "list_pending_recommendations", "queue") or self.list_pending(c)

    def confirm(self, user_id, request, agent=None):
        if agent:   # an agent identity holds no confirm grant: confirmation is human-only (same code as M1)
            caller = {"user_id": agent, "groups": []}
            rid = self._audit(caller, "confirm_recommendation", request.get("recommendation_id"), "deny",
                              "no_grant: confirmation is human-only")
            return self._error("human_confirmation_required", "Only a licensed adjuster can confirm an outcome.", rid)
        c = self.caller(user_id)
        return self._authorize(c, "confirm_recommendation", request.get("recommendation_id")) or \
            self.confirm_recommendation(c, request)

    def audit_rows(self, user_id, limit=50, claim_id=None):
        c = self.caller(user_id)
        if (denied := self._authorize(c, "read_audit", "audit")):
            return denied
        rows = audit_trail.read()
        if claim_id:
            rows = [r for r in rows if r.get("resource") == claim_id or claim_id in str(r.get("resource"))]
        self._audit(c, "read_audit", claim_id or "audit", "allow", f"{min(limit, len(rows))} rows")
        return {"rows": rows[-limit:]}

    # ── Policy & Coverage KB through the door (read-only, unscoped by claim, still granted + audited) ──────────
    @property
    def clause_index(self):
        if self._clause_index is None:
            from claimsense import config
            from claimsense.retrieval import get_index
            self._clause_index = get_index(None if config.OPENSEARCH_URL else "lexical")
        return self._clause_index

    def search_clauses(self, user_id, query, k=3, agent=None):
        c = self.caller(user_id)
        if (denied := self._authorize(c, "search_policy_clauses", f"policy-kb?q={query[:80]}", agent)):
            return denied
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            rid = self._audit(c, "search_policy_clauses", "policy-kb", "error", "invalid_request", agent)
            return self._error("invalid_request", "query must be 1 to 500 characters.", rid)
        from claimsense.retrieval import search_with_provenance
        kept, dropped = search_with_provenance(self.clause_index, query, k=max(1, min(int(k), 5)))
        self._audit(c, "search_policy_clauses", f"policy-kb?q={query[:80]}", "allow",
                    f"{len(kept)} kept, {len(dropped)} quarantined (G2)", agent)
        strip = lambda ch: {k2: v for k2, v in ch.items() if k2 not in ("vector", "embedding")}
        return {"backend": self.clause_index.backend, "clauses": [strip(ch) for ch in kept],
                "quarantined": [d["clause_id"] for d in dropped]}

    # ── the 4th backend: SIU / escalation ticketing (idempotent write, retry/backoff, breaker, never lost) ──────
    def escalate(self, user_id, claim_id, reason, idempotency_key, priority="normal", agent=None):
        c = self.caller(user_id)
        if (denied := self._authorize(c, "create_escalation_ticket", claim_id, agent)):
            return denied
        claim = self.claims.get(claim_id)
        if claim is None or not self.entitled(c, claim):
            rid = self._audit(c, "create_escalation_ticket", claim_id, "deny", "not_found_or_not_entitled", agent)
            return self._error("not_found_or_forbidden", DENIED["create_escalation_ticket"], rid)
        if not idempotency_key or not isinstance(reason, str) or not reason.strip() or priority not in ("normal", "high"):
            rid = self._audit(c, "create_escalation_ticket", claim_id, "error", "invalid_request", agent)
            return self._error("invalid_request", "An escalation needs a reason, a priority (normal|high) and an "
                                                  "idempotency key.", rid)
        if self.ticketing is None:
            rid = self._audit(c, "create_escalation_ticket", claim_id, "error", "ticketing not configured", agent)
            return self._error("upstream_unavailable", "Escalation ticketing is not configured.", rid)
        # the ticket carries a link and a reason, never claim data: the specialist opens the claim through the door
        payload = {"claim_id": claim_id, "reason": reason.strip()[:500], "priority": priority,
                   "requested_by": c["user_id"], "requested_group": (c["groups"] or ["-"])[0]}
        try:
            ticket = self.ticketing.create(payload, idempotency_key)
        except TicketingUnavailable as e:
            # never lose an escalation: park it in the outbox and say so (structured, retryable)
            self.escalations[claim_id] = {"claim_id": claim_id, "status": "pending_delivery", "seq": 0,
                                          "outbox": {"payload": payload, "idempotency_key": idempotency_key},
                                          "updated_at": time.time(), "detail": str(e)}
            rid = self._audit(c, "create_escalation_ticket", claim_id, "error", f"ticketing unavailable: {e}", agent)
            return self._error("upstream_unavailable", "Ticketing is unavailable; the escalation is queued and will "
                                                       "be delivered.", rid, retry_after_s=30)
        prev = self.escalations.get(claim_id) or {}
        replay = prev.get("ticket_id") == ticket["ticket_id"]
        self.escalations[claim_id] = {"claim_id": claim_id, "ticket_id": ticket["ticket_id"],
                                      "status": prev.get("status") if replay else ticket["status"],
                                      "seq": prev.get("seq", ticket.get("seq", 0)) if replay else ticket.get("seq", 0),
                                      "updated_at": time.time(), "history": prev.get("history", []) if replay else []}
        self._audit(c, "create_escalation_ticket", claim_id, "replay" if (replay or ticket.get("idempotent_replay"))
                    else "allow", ticket["ticket_id"], agent)
        return {"ticket_id": ticket["ticket_id"], "claim_id": claim_id, "status": self.escalations[claim_id]["status"],
                "idempotent_replay": bool(replay or ticket.get("idempotent_replay"))}

    def escalation(self, user_id, claim_id, agent=None):
        c = self.caller(user_id)
        if (denied := self._authorize(c, "get_escalation", claim_id, agent)):
            return denied
        claim, esc = self.claims.get(claim_id), self.escalations.get(claim_id)
        if claim is None or not self.entitled(c, claim) or esc is None:
            rid = self._audit(c, "get_escalation", claim_id, "deny", "not_found_or_not_entitled_or_none", agent)
            return self._error("not_found_or_forbidden", DENIED["get_escalation"], rid)
        self._audit(c, "get_escalation", claim_id, "allow", esc.get("status", ""), agent)
        return {k: esc.get(k) for k in ("claim_id", "ticket_id", "status", "seq", "updated_at", "history")}

    def flush_outbox(self):
        """Retry escalations parked while ticketing was down (called on each webhook and on health checks)."""
        for claim_id, esc in list(self.escalations.items()):
            ob = esc.get("outbox")
            if not ob or self.ticketing is None:
                continue
            try:
                t = self.ticketing.create(ob["payload"], ob["idempotency_key"])
            except TicketingUnavailable:
                return
            self.escalations[claim_id] = {"claim_id": claim_id, "ticket_id": t["ticket_id"], "status": t["status"],
                                          "seq": t.get("seq", 0), "updated_at": time.time(), "history": []}
            self._audit({"user_id": ob["payload"]["requested_by"], "groups": []}, "create_escalation_ticket",
                        claim_id, "allow", f"{t['ticket_id']} (delivered from outbox)")

    # ── webhook-driven updates: the ticketing system PUSHES status changes (stretch, D-038) ────────────────────
    def apply_ticket_event(self, event):
        """Called only AFTER the signature and timestamp are verified. Idempotent (event_id) and order-safe (seq)."""
        caller = SERVICE_TICKETING
        if (denied := self._authorize(caller, "ticket_webhook", event.get("claim_id", "-"))):
            return denied, 403
        eid, claim_id = event.get("event_id"), event.get("claim_id")
        if eid in self.webhook_events:
            self._audit(caller, "ticket_webhook", claim_id, "replay", f"duplicate delivery {eid}")
            return {"ok": True, "deduped": True}, 200
        self.webhook_events[eid] = {"received_at": time.time(), "seq": event.get("seq")}
        esc = self.escalations.get(claim_id)
        if claim_id not in self.claims or esc is None or esc.get("ticket_id") != event.get("ticket_id"):
            self._audit(caller, "ticket_webhook", claim_id, "deny", "unknown claim or ticket")
            return {"ok": False, "error": "unknown_ticket"}, 404
        if int(event.get("seq", 0)) <= int(esc.get("seq", 0)):
            self._audit(caller, "ticket_webhook", claim_id, "replay",
                        f"out-of-order seq {event.get('seq')} <= {esc.get('seq')}: ignored")
            return {"ok": True, "ignored": "stale_seq"}, 200
        esc = dict(esc, status=event["status"], seq=int(event["seq"]), updated_at=time.time(),
                   history=(esc.get("history") or []) + [{"status": event["status"], "seq": int(event["seq"]),
                                                          "at": event.get("ts")}])
        self.escalations[claim_id] = esc
        self._audit(caller, "ticket_webhook", claim_id, "allow",
                    f"{event['ticket_id']} -> {event['status']} (seq {event['seq']})")
        return {"ok": True, "status": esc["status"]}, 200


def verify_signature(secret: bytes, header: str | None, body: bytes, now=None, tolerance=WEBHOOK_TOLERANCE_S):
    """`X-Ticketing-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, f"{t}.{body}")>`.
    Returns None when valid, else the reason. Constant-time compare; a stale timestamp is refused (replay)."""
    if not header:
        return "missing signature"
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        ts = int(parts.get("t", ""))
    except ValueError:
        return "malformed signature"
    if abs((now or time.time()) - ts) > tolerance:
        return "timestamp outside the replay window"
    want = hmac.new(secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, parts.get("v1", "")):
        return "bad signature"
    return None


def sign(secret: bytes, body: bytes, ts=None):
    ts = int(ts or time.time())
    return f"t={ts},v1={hmac.new(secret, f'{ts}.'.encode() + body, hashlib.sha256).hexdigest()}"


def shared_secret(name, directory=None):
    """A per-deployment secret shared by two services WITHOUT living in the repo, an image, or compose: created once
    on the private secrets volume (0600, exclusive create) and read by both sides. CLAIMSENSE_SECRET_<NAME> (e.g.
    from Secrets Manager on AWS) overrides it."""
    env = os.environ.get(f"CLAIMSENSE_SECRET_{name.upper()}")
    if env:
        return env.encode()
    from pathlib import Path
    d = Path(directory or os.environ.get("CLAIMSENSE_SECRETS_DIR", "/secrets"))
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(os.urandom(32).hex())
    except FileExistsError:
        pass
    for _ in range(50):                      # the other side may be mid-write
        v = p.read_text().strip()
        if v:
            return v.encode()
        time.sleep(0.1)
    raise RuntimeError(f"shared secret {name} is empty")


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]
