"""The adjuster queue (D-028): drafts land in the ops team's own queue, entitlement-filtered and audited."""
from claimsense.boundary_client import LocalBoundary
from claimsense.pipeline import run_claim


def _draft(b, claim_id, user="alice", key=None):
    card = run_claim(claim_id, user, brain="replay")["response"]
    return b.recommend(user, claim_id, card, key or f"k-{claim_id}")


def test_pending_drafts_appear_in_the_queue_newest_first_and_leave_it_once_decided(tmp_path):
    b = LocalBoundary(tmp_path / "boundary.db")
    first = _draft(b, "CLM-2024-1800")
    second = _draft(b, "CLM-2024-3104")
    queue = b.pending("alice")["pending"]
    assert [q["recommendation_id"] for q in queue] == [second["recommendation_id"], first["recommendation_id"]]
    assert queue[1]["outcome"] == "approve" and queue[1]["net_payable"] == 2700 and queue[1]["version"] == 1
    b.confirm("alice", {"recommendation_id": first["recommendation_id"], "action": "confirm", "idempotency_key": "c1"})
    assert [q["recommendation_id"] for q in b.pending("alice")["pending"]] == [second["recommendation_id"]]
    assert LocalBoundary(tmp_path / "boundary.db").pending("alice")["pending"][0]["version"] == 1   # survives restart
    assert b.audit[-1]["action"] == "list_pending_recommendations"


def test_the_queue_only_shows_claims_the_caller_is_entitled_to():
    b = LocalBoundary()
    _draft(b, "CLM-2024-1800")
    assert b.pending("dave")["pending"] == []                         # customer service sees no drafts
    assert b.draft("dave", "CLM-2024-1800")["error"]["code"] == "not_found_or_forbidden"
    latest = b.draft("alice", "CLM-2024-1800")
    assert latest["status"] == "draft_pending_confirmation" and latest["card"]["outcome"] == "approve"


def test_drafts_saved_before_queue_metadata_still_list(tmp_path):
    """Regression (browser check 2026-11-07): drafts on the /state volume from before D-028 have no
    created_at/version; the queue must still list them, oldest last."""
    b = LocalBoundary(tmp_path / "boundary.db")
    rec = _draft(b, "CLM-2024-1800")
    legacy = dict(b.recommendations[rec["recommendation_id"]])
    for k in ("created_at", "version", "drafted_for", "agent"):
        legacy.pop(k, None)
    b.recommendations[rec["recommendation_id"]] = legacy
    row = LocalBoundary(tmp_path / "boundary.db").pending("alice")["pending"][0]
    assert row["created_at"] is None and row["version"] is None and row["outcome"] == "approve"
