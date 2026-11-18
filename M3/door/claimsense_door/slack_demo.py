"""On-call paging through the door: RBAC + every failure mode, offline (the checklist's PROBLEM -> HANDLED evidence).

    python -m claimsense_door.slack_demo            # mock Slack, all scenarios, exit 0 only if all are handled
    python -m claimsense_door.slack_demo --real     # one real page via M3/.slack.env (bot token or webhook)
"""
import sys

from .clients import InProcess
from .proofs import _client
from .slack import MockSlack, SlackNotifier, transport_from_env


def fresh(fault=None):
    tc, _ = _client()
    c = InProcess(ticketing=tc)
    c.b.slack = SlackNotifier(c.b, MockSlack(fault), "mock", sleep=lambda s: None)
    return c


def page(c, user="alice", key="page-1800-0001", claim="CLM-2024-1800"):
    _, r = c.call(user, "notify_oncall", {"claim_id": claim, "reason": "Impact side contradicts the narrative.",
                                          "idempotency_key": key}, agent="agent:decision-draft")
    return r["structuredContent"]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--real" in argv:
        t, mode = transport_from_env()
        if mode == "mock":
            raise SystemExit("--real needs SLACK_BOT_TOKEN + SLACK_CHANNEL_ID or SLACK_WEBHOOK_URL (M3/.slack.env)")
        c = fresh()
        c.b.slack = SlackNotifier(c.b, t, mode)
        print("REAL page:", page(c))
        return 0
    rows, ok = [], True

    def scenario(name, problem, out, handled, cond):
        nonlocal ok
        ok &= bool(cond)
        rows.append((name, problem, handled if cond else f"NOT HANDLED: {out}"))
        print(f"▶ {name}\n    {out}")

    c = fresh()
    scenario("happy", "a normal page", page(c), "posted to Slack, audit row written",
             page.__name__ and c.b.slack.t.posted and c.audit()[-1]["decision"] == "allow")
    c = fresh()
    out = page(c, user="carol")
    scenario("rbac", "a fraud investigator pages for a claim that isn't hers", out,
             "denied at the door + deny row audited; Slack never called",
             out.get("error", {}).get("code") == "not_found_or_forbidden" and not c.b.slack.t.calls)
    c = fresh("rate_limit")
    out = page(c)
    scenario("rate_limit", "Slack returns 429", out, "backoff + retry -> delivered_via=slack",
             out.get("delivered_via") == "slack" and any("429" in x for x in c.b.slack.log))
    c = fresh("expired_webhook")
    out = page(c)
    scenario("expired_webhook", "the webhook/token was rotated (404)", out,
             f"graceful fallback -> SIU ticket {out.get('ticket_id')} (escalation never lost)",
             out.get("delivered_via") == "fallback" and (out.get("ticket_id") or "").startswith("SIU-"))
    c = fresh("timeout")
    outs = [page(c, key=f"page-timeout-{i:04d}") for i in range(3)]
    scenario("timeout", "Slack hangs, three pages in a row", outs[-1],
             "breaker opened after 2 failures; the 3rd call short-circuited to the fallback",
             outs[-1].get("reason") == "circuit_open" and c.b.slack.t.calls == 2)
    c = fresh()
    first, again = page(c, key="dup-00000001"), page(c, key="dup-00000001")
    scenario("duplicate", "the agent retries the whole step", again, "deduped=True: on-call paged once, not twice",
             again.get("deduped") and len(c.b.slack.t.posted) == 1)
    c = fresh("schema_drift")
    out = page(c)
    scenario("schema_drift", "Slack answers 200 in a changed shape", out,
             "defensive parse: still delivered, flagged for review, no crash",
             out.get("delivered_via") == "slack" and out.get("flagged") is True)
    card = MockSlack()
    SlackNotifier(fresh().b, card).card("CLM-2024-1800", "reason", "alice")
    c = fresh()
    page(c)
    posted = str(c.b.slack.t.posted[0])
    claim = c.b.claims["CLM-2024-1800"]
    leak = [v for v in (claim.get("claimant_name"), str(claim.get("repair_estimate")), claim.get("policy_id")) if v and v in posted]
    scenario("no_data_in_slack", "could the card leak claim data into Slack?", {"card_fields": "id, reason, link"},
             "the card carries the claim id, the reason and a link; no name, amount or policy",
             not leak)
    print("\n" + "-" * 74 + "\n  SUMMARY: every failure mode handled deterministically, in the door\n" + "-" * 74)
    for name, problem, handled in rows:
        print(f"  PROBLEM: {problem:<52} -> HANDLED: {handled}")
    print(f"\nSLACK THROUGH THE DOOR: {'PASS' if ok else 'FAIL'} ({len(rows)} scenarios)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
