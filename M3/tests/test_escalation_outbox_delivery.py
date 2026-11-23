"""M4 runbook test found that a queued escalation was never delivered: nothing called flush_outbox. Now the health
check, escalation reads and new escalations deliver it, in the background (never blocking on ticketing)."""
import time

from claimsense_door.ticketing import TicketingUnavailable


class FlakyTicketing:
    def __init__(self):
        self.up, self.created = False, []

    def create(self, payload, key):
        if not self.up:
            raise TicketingUnavailable("down")
        self.created.append(key)
        return {"ticket_id": f"SIU-{len(self.created)}", "status": "open", "seq": 1}


def test_queued_escalation_is_delivered_once_ticketing_recovers(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    from claimsense_door.door import GrantedBoundary
    b = GrantedBoundary(None)
    b.escalations, b.webhook_events, b.recommendations, b._idem = {}, {}, {}, {}
    b.ticketing = FlakyTicketing()
    r = b.escalate("bob", "CLM-2025-1084", "manual: timeline inconsistent", "k-1")
    assert r["error"]["code"] == "upstream_unavailable" and b.queued() == 1
    b.ticketing.up = True
    b.flush_outbox_in_background()                      # what the health check does
    for _ in range(50):
        if not b.queued():
            break
        time.sleep(0.02)
    assert b.queued() == 0 and b.escalations["CLM-2025-1084"]["ticket_id"] == "SIU-1"
    assert b.ticketing.created == ["k-1"]               # delivered once, with the original idempotency key
