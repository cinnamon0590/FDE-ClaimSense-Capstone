"""Contract tests: the reference boundary must satisfy every rule in contracts.md.

    python3 test_contracts.py -v        (stdlib only; run from M1/5-system-contracts)

M3's real service (API Gateway + Lambda + Cognito) must pass these same tests.
"""
import json
import sys
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from jsonschema_lite import validate  # noqa: E402
import reference_boundary as rb  # noqa: E402

S = {p.stem.split(".")[0]: json.loads(p.read_text()) for p in (HERE / "schemas").glob("*.json")}
DATA = {p.stem.split(".")[0]: json.loads(p.read_text()) for p in (HERE.parent / "6-synthetic-data" / "schemas").glob("*.json")}


def ok(value, contract, name):
    """Validate value against $defs/name in a contract schema; returns the error list."""
    doc = S[contract]
    return validate(value, {"$ref": f"#/$defs/{name}"} | {"$defs": doc["$defs"]}, root=doc)


ALICE = {"user_id": "alice", "groups": ["adjuster"]}
BOB = {"user_id": "bob", "groups": ["senior-adjuster"]}
DAVE = {"user_id": "dave", "groups": ["customer-service"]}
AGENT = {"user_id": "agent:decision-draft", "groups": ["adjuster"]}


def card(claim_id="CLM-2024-1800", outcome="approve", net=2700):
    return {"claim_id": claim_id, "outcome": outcome,
            "reasoning": "Collision inside the policy term; damage consistent with the police report.",
            "citations": [{"source_id": "CLS-COL-001"}, {"source_id": "CLS-DED-002"}],
            "computed": {"loss_in_policy_term": True, "net_payable": net, "repair_to_acv_ratio": 0.13,
                         "over_authority_limit": (net or 0) > 25_000},
            "judgment": {"coverage_finding": "covered", "fraud_signals": [], "injury_exposure": False},
            "verdict_source": "model", "guardrails_fired": [], "adjuster_confirmation_required": True,
            "model": {"name": "gpt-4o", "prompt_version": "decision-draft@0.1"}}


class SchemaTests(unittest.TestCase):
    def test_decision_card_example_is_valid(self):
        self.assertEqual(ok(card(), "common", "DecisionCard"), [])

    def test_decision_card_cannot_waive_adjuster_confirmation(self):
        bad = card(); bad["adjuster_confirmation_required"] = False
        self.assertTrue(ok(bad, "common", "DecisionCard"))

    def test_get_claim_response_matches_claim_data_shape(self):
        resp = rb.Boundary().get_claim(ALICE, "CLM-2024-1800")
        self.assertEqual(validate(resp, DATA["claim"]), [])

    def test_get_policy_response_matches_policy_data_shape(self):
        resp = rb.Boundary().get_policy(ALICE, "POL-AU-10418")
        self.assertEqual(validate(resp, DATA["policy"]), [])

    def test_list_documents_response_is_valid(self):
        resp = rb.Boundary().list_documents(ALICE, "CLM-2024-1800")
        self.assertEqual(ok(resp, "document-store", "ListDocumentsResponse"), [])

    def test_every_audit_record_is_valid(self):
        b = rb.Boundary()
        b.get_claim(ALICE, "CLM-2024-1800"); b.get_claim(DAVE, "CLM-2024-1873")
        b.post_recommendation(ALICE, {"claim_id": "CLM-2024-1800", "idempotency_key": str(uuid.uuid4()), "decision_card": card()})
        for rec in b.audit:
            self.assertEqual(ok(rec, "common", "AuditRecord"), [], rec)


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.b = rb.Boundary()
        self.req = {"claim_id": "CLM-2024-1800", "idempotency_key": str(uuid.uuid4()), "decision_card": card()}

    def test_first_write_returns_a_draft_receipt(self):
        r = self.b.post_recommendation(ALICE, self.req)
        self.assertEqual(ok(r, "claims-management", "RecommendationReceipt"), [])
        self.assertEqual(r["status"], "draft_pending_confirmation")
        self.assertFalse(r["idempotent_replay"])

    def test_same_key_same_payload_replays_the_original(self):
        first = self.b.post_recommendation(ALICE, self.req)
        again = self.b.post_recommendation(ALICE, self.req)
        self.assertEqual(again["recommendation_id"], first["recommendation_id"])
        self.assertTrue(again["idempotent_replay"])
        self.assertEqual(len(self.b.recommendations), 1)              # one write, not two
        self.assertEqual(self.b.audit[-1]["decision"], "replay")

    def test_same_key_different_payload_is_a_conflict(self):
        self.b.post_recommendation(ALICE, self.req)
        changed = dict(self.req, decision_card=card(outcome="deny", net=None))
        r = self.b.post_recommendation(ALICE, changed)
        self.assertEqual(r["error"]["code"], "idempotency_conflict")
        self.assertEqual(ok(r, "common", "Error"), [])
        self.assertEqual(len(self.b.recommendations), 1)

    def test_new_key_creates_a_new_version(self):
        self.b.post_recommendation(ALICE, self.req)
        r2 = self.b.post_recommendation(ALICE, dict(self.req, idempotency_key=str(uuid.uuid4())))
        self.assertEqual(r2["version"], 2)


class AccessTests(unittest.TestCase):
    def test_missing_and_unentitled_look_identical(self):
        b = rb.Boundary()
        missing = b.get_claim(DAVE, "CLM-2099-0000")
        forbidden = b.get_claim(DAVE, "CLM-2024-1873")
        strip = lambda r: {k: v for k, v in r["error"].items() if k != "request_id"}
        self.assertEqual(strip(missing), strip(forbidden))
        self.assertEqual([a["decision"] for a in b.audit], ["deny", "deny"])   # both audited
        self.assertEqual([a["reason"] for a in b.audit], ["not_found", "not_entitled"])  # reason only in the log

    def test_unentitled_user_gets_no_claim_data(self):
        r = rb.Boundary().get_claim(DAVE, "CLM-2024-1873")
        self.assertEqual(set(r), {"error"})
        self.assertNotIn("BMW", json.dumps(r))

    def test_agent_identity_cannot_confirm(self):
        b = rb.Boundary()
        rec = b.post_recommendation(ALICE, {"claim_id": "CLM-2024-1800", "idempotency_key": str(uuid.uuid4()), "decision_card": card()})
        r = b.confirm_recommendation(AGENT, {"recommendation_id": rec["recommendation_id"], "action": "confirm",
                                             "idempotency_key": str(uuid.uuid4())})
        self.assertEqual(r["error"]["code"], "human_confirmation_required")

    def test_adjuster_confirms_and_override_needs_a_reason(self):
        b = rb.Boundary()
        rec = b.post_recommendation(ALICE, {"claim_id": "CLM-2024-1800", "idempotency_key": str(uuid.uuid4()), "decision_card": card()})
        bad = b.confirm_recommendation(ALICE, {"recommendation_id": rec["recommendation_id"], "action": "override",
                                               "final_outcome": "flag_review", "idempotency_key": str(uuid.uuid4())})
        self.assertEqual(bad["error"]["code"], "invalid_request")
        good = b.confirm_recommendation(ALICE, {"recommendation_id": rec["recommendation_id"], "action": "confirm",
                                                "idempotency_key": str(uuid.uuid4())})
        self.assertEqual(ok(good, "claims-management", "ConfirmationReceipt"), [])
        self.assertEqual(good["confirmed_by"], "alice")

    def test_above_authority_limit_needs_a_senior_adjuster(self):
        b = rb.Boundary()
        big = card("CLM-2024-2019", "approve", 27_400)
        rec = b.post_recommendation(ALICE, {"claim_id": "CLM-2024-2019", "idempotency_key": str(uuid.uuid4()), "decision_card": big})
        req = {"recommendation_id": rec["recommendation_id"], "action": "confirm", "idempotency_key": str(uuid.uuid4())}
        self.assertIn("error", b.confirm_recommendation(ALICE, req))
        self.assertEqual(b.confirm_recommendation(BOB, dict(req, idempotency_key=str(uuid.uuid4())))["confirmed_by"], "bob")

    def test_every_call_is_audited(self):
        b = rb.Boundary()
        b.get_claim(ALICE, "CLM-2024-1800"); b.get_claim(DAVE, "CLM-2024-1800"); b.list_documents(ALICE, "CLM-2024-1800")
        self.assertEqual(len(b.audit), 3)


class RetryTests(unittest.TestCase):
    def test_only_transient_errors_are_retried(self):
        rl = {"error": {"code": "rate_limited", "message": "slow down", "request_id": str(uuid.uuid4()), "retry_after_s": 2}}
        self.assertEqual(rb.retry_plan(rl, 0), 2)
        self.assertEqual(rb.retry_plan({"error": dict(rl["error"], code="upstream_unavailable", retry_after_s=None)}, 1), 0.4)
        self.assertIsNone(rb.retry_plan({"error": dict(rl["error"], code="not_found_or_forbidden")}, 0))
        self.assertIsNone(rb.retry_plan(rl, 3))                       # max 3 attempts


if __name__ == "__main__":
    unittest.main()
