"""Reference implementation of the ClaimSense data-boundary contract (in-memory, stdlib only).

This is the executable specification for the three client-system contracts. M3 builds the real
service (API Gateway + Lambda, Cognito JWT) and must pass the same tests (test_contracts.py).
It runs on the M1 synthetic fixtures.

Rules it implements (see contracts.md):
  * Entitlement is checked IN CODE before any data is returned, and before any agent sees it.
  * Missing and unentitled records return the SAME error (anti-enumeration).
  * Every call writes an append-only audit record: allow, deny, replay or error.
  * Writes require an Idempotency-Key. Same key + same payload → the original receipt
    (idempotent_replay = true, no second write). Same key + different payload → 409-style conflict.
  * Recommendations are always drafts. Only a human adjuster can confirm or override; an agent
    service identity calling confirm_recommendation is refused.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "6-synthetic-data" / "fixtures"
HUMAN_CONFIRMERS = {"adjuster", "senior-adjuster"}
AGENT_SERVICE_PREFIX = "agent:"           # agent service identities, e.g. "agent:decision-draft"
AUTHORITY_LIMIT = 25_000


def _now():
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Boundary:
    def __init__(self):
        load = lambda n: json.loads((FIXTURES / f"{n}.json").read_text())["records"]
        self.claims = {c["claim_id"]: c for c in load("claims")}
        self.policies = {p["policy_id"]: p for p in load("policies")}
        self.documents = {d["doc_id"]: d for d in load("documents")}
        self.users = {u["user_id"]: u for u in load("users")}
        self.audit = []                      # append-only
        self.recommendations = {}            # recommendation_id -> record
        self._idem = {}                      # (caller, operation, key) -> (fingerprint, response)

    # ── helpers ──────────────────────────────────────────────────────────────────────────────
    def _audit(self, caller, action, resource, decision, reason="", on_behalf_of_agent=None):
        rec = {"ts": _now(), "request_id": str(uuid.uuid4()), "user_id": caller["user_id"],
               "groups": list(caller["groups"]), "on_behalf_of_agent": on_behalf_of_agent,
               "action": action, "resource": resource, "decision": decision, "reason": reason}
        self.audit.append(rec)
        return rec["request_id"]

    @staticmethod
    def _error(code, message, request_id, retry_after_s=None):
        err = {"code": code, "message": message, "request_id": request_id}
        if retry_after_s:
            err["retry_after_s"] = retry_after_s
        return {"error": err}

    def entitled(self, caller, claim):
        g = set(caller["groups"])
        if "senior-adjuster" in g:
            return True
        if "adjuster" in g:
            return claim["assigned_group"] == "adjuster"
        if "fraud-investigator" in g:
            return claim["assigned_group"] == "fraud-investigator"
        if "total-loss-appraiser" in g:
            return claim["assigned_group"] == "total-loss-appraiser"
        return False                         # customer-service and unknown groups: no claim files

    # ── claims management ────────────────────────────────────────────────────────────────────
    def get_claim(self, caller, claim_id, agent=None):
        claim = self.claims.get(claim_id)
        if claim is None or not self.entitled(caller, claim):
            reason = "not_found" if claim is None else "not_entitled"
            rid = self._audit(caller, "get_claim", claim_id, "deny", reason, agent)
            # identical message for both cases: the reason lives only in the audit log
            return self._error("not_found_or_forbidden", "No claim is available for this request.", rid)
        self._audit(caller, "get_claim", claim_id, "allow", on_behalf_of_agent=agent)
        return dict(claim)

    def post_recommendation(self, caller, request, agent="decision-draft"):
        claim_id, key = request["claim_id"], request["idempotency_key"]
        claim = self.claims.get(claim_id)
        if claim is None or not self.entitled(caller, claim):
            rid = self._audit(caller, "post_recommendation", claim_id, "deny", "not_found_or_not_entitled", agent)
            return self._error("not_found_or_forbidden", "No claim is available for this request.", rid)
        slot = (caller["user_id"], "post_recommendation", key)
        fp = _fingerprint({"claim_id": claim_id, "decision_card": request["decision_card"]})
        if slot in self._idem:
            prev_fp, prev_resp = self._idem[slot]
            if prev_fp != fp:
                rid = self._audit(caller, "post_recommendation", claim_id, "error", "idempotency_conflict", agent)
                return self._error("idempotency_conflict", "This Idempotency-Key was used with a different payload.", rid)
            self._audit(caller, "post_recommendation", claim_id, "replay", "same key, same payload", agent)
            return dict(prev_resp, idempotent_replay=True)
        version = 1 + sum(1 for r in self.recommendations.values() if r["claim_id"] == claim_id)
        rec_id = "REC-" + hashlib.sha256(f"{claim_id}|{key}".encode()).hexdigest()[:12]
        receipt = {"recommendation_id": rec_id, "claim_id": claim_id, "version": version,
                   "status": "draft_pending_confirmation", "idempotent_replay": False, "created_at": _now()}
        self.recommendations[rec_id] = {"claim_id": claim_id, "card": request["decision_card"], "confirmation": None}
        self._idem[slot] = (fp, receipt)
        self._audit(caller, "post_recommendation", claim_id, "allow", f"draft v{version}", agent)
        return dict(receipt)

    def confirm_recommendation(self, caller, request):
        rid_key = request["recommendation_id"]
        if caller["user_id"].startswith(AGENT_SERVICE_PREFIX) or not (set(caller["groups"]) & HUMAN_CONFIRMERS):
            rid = self._audit(caller, "confirm_recommendation", rid_key, "deny", "confirmation is human-only")
            return self._error("human_confirmation_required", "Only a licensed adjuster can confirm an outcome.", rid)
        rec = self.recommendations.get(rid_key)
        if rec is None or not self.entitled(caller, self.claims[rec["claim_id"]]):
            rid = self._audit(caller, "confirm_recommendation", rid_key, "deny", "not_found_or_not_entitled")
            return self._error("not_found_or_forbidden", "No recommendation is available for this request.", rid)
        if request["action"] == "override" and not request.get("override_reason"):
            rid = self._audit(caller, "confirm_recommendation", rid_key, "error", "override without reason")
            return self._error("invalid_request", "An override needs an override_reason.", rid)
        net = rec["card"].get("computed", {}).get("net_payable") or 0
        outcome = request.get("final_outcome") or rec["card"]["outcome"]
        if outcome == "approve" and net > AUTHORITY_LIMIT and "senior-adjuster" not in caller["groups"]:
            rid = self._audit(caller, "confirm_recommendation", rid_key, "deny", "above authority limit")
            return self._error("not_found_or_forbidden", "This outcome needs senior-adjuster sign-off.", rid)
        slot = (caller["user_id"], "confirm_recommendation", request["idempotency_key"])
        fp = _fingerprint(request)
        if slot in self._idem:
            prev_fp, prev = self._idem[slot]
            if prev_fp != fp:
                rid = self._audit(caller, "confirm_recommendation", rid_key, "error", "idempotency_conflict")
                return self._error("idempotency_conflict", "This Idempotency-Key was used with a different payload.", rid)
            self._audit(caller, "confirm_recommendation", rid_key, "replay")
            return dict(prev, idempotent_replay=True)
        receipt = {"recommendation_id": rid_key, "claim_id": rec["claim_id"], "action": request["action"],
                   "final_outcome": outcome, "confirmed_by": caller["user_id"], "idempotent_replay": False,
                   "confirmed_at": _now()}
        rec["confirmation"] = receipt
        self._idem[slot] = (fp, receipt)
        self._audit(caller, "confirm_recommendation", rid_key, "allow", request["action"])
        return dict(receipt)

    # ── policy administration ────────────────────────────────────────────────────────────────
    def get_policy(self, caller, policy_id, agent=None):
        pol = self.policies.get(policy_id)
        claim_ok = pol and any(c["policy_id"] == policy_id and self.entitled(caller, c) for c in self.claims.values())
        if not claim_ok:
            rid = self._audit(caller, "get_policy", policy_id, "deny", "not_found_or_not_entitled", agent)
            return self._error("not_found_or_forbidden", "No policy is available for this request.", rid)
        self._audit(caller, "get_policy", policy_id, "allow", on_behalf_of_agent=agent)
        return dict(pol)

    # ── document store ───────────────────────────────────────────────────────────────────────
    def list_documents(self, caller, claim_id, agent=None):
        claim = self.claims.get(claim_id)
        if claim is None or not self.entitled(caller, claim):
            rid = self._audit(caller, "list_documents", claim_id, "deny", "not_found_or_not_entitled", agent)
            return self._error("not_found_or_forbidden", "No claim is available for this request.", rid)
        self._audit(caller, "list_documents", claim_id, "allow", on_behalf_of_agent=agent)
        return {"claim_id": claim_id, "documents": [
            {k: self.documents[d][k] for k in ("doc_id", "doc_type", "title", "received_date", "sha256")}
            for d in claim["document_ids"]]}


RETRYABLE = {"rate_limited", "upstream_unavailable"}


def retry_plan(error, attempt):
    """Client retry policy: only retry transient errors, honour retry_after_s, max 3 attempts."""
    code = error["error"]["code"]
    if code not in RETRYABLE or attempt >= 3:
        return None
    return error["error"].get("retry_after_s") or 0.2 * (2 ** attempt)   # 0.2s, 0.4s, 0.8s
