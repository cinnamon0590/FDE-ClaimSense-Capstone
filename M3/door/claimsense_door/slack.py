"""Page the on-call senior adjuster in Slack, THROUGH the governed door (M3 Builder: a real external integration).

`notify_oncall` is a typed MCP tool like every other: the action grant and the claim's entitlement are checked in code
first (a denied escalation never reaches Slack), and every attempt writes an audit row. The card carries the claim id,
the reason and a button back into the ClaimSense console. It NEVER carries claim data: Slack gets the page; the
console (behind login and the same door) holds the record.

Real integrations fail, so the door handles the failures, never the model (the W16 Slack lesson, five patterns):
  429 rate limit         -> backoff + retry, honouring Retry-After
  404 expired webhook    -> graceful fallback: an SIU escalation ticket (the escalation is never lost)
  timeout                -> a circuit breaker opens after 2 consecutive failures; later calls short-circuit to fallback
  duplicate              -> idempotency key: on-call is paged once, never twice
  schema drift           -> defensive parse: delivered, flagged, not crashed

Transports, chosen from the environment (secrets live only in M3/.slack.env, gitignored, which Susan fills herself):
  SLACK_BOT_TOKEN + SLACK_CHANNEL_ID -> chat.postMessage as the app · SLACK_WEBHOOK_URL -> incoming webhook ·
  neither -> an offline mock (deterministic), used by the proofs and CI.
"""
import json
import os
import time
import urllib.error
import urllib.request

CONSOLE = os.environ.get("CLAIMSENSE_CONSOLE_URL", "http://localhost:8510").rstrip("/")


class SlackError(Exception):
    def __init__(self, code, detail="", retry_after=None):
        super().__init__(f"{code}: {detail}")
        self.code, self.retry_after = code, retry_after


class MockSlack:
    """Offline Slack with injectable faults (the lab's simulations)."""

    def __init__(self, fault=None):
        self.fault, self.calls, self.posted = fault, 0, []

    def post(self, payload):
        self.calls += 1
        if self.fault == "rate_limit" and self.calls == 1:
            raise SlackError("rate_limited", "HTTP 429", retry_after=1)
        if self.fault == "expired_webhook":
            raise SlackError("invalid_token", "HTTP 404")
        if self.fault == "timeout":
            raise SlackError("timeout", "no response")
        self.posted.append(payload)
        if self.fault == "schema_drift":
            return {"status": "accepted", "ts": "1720000000.1"}           # 200, but not Slack's documented shape
        return {"ok": True, "ts": f"17000000{self.calls:02d}.0001"}


class WebhookSlack:
    def __init__(self, url):
        self.url = url

    def post(self, payload):
        return _http(self.url, payload, {})


class BotSlack:
    def __init__(self, token, channel):
        self.token, self.channel = token, channel

    def post(self, payload):
        return _http("https://slack.com/api/chat.postMessage", dict(payload, channel=self.channel),
                     {"Authorization": f"Bearer {self.token}"})


def _http(url, payload, headers):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8", **headers})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode() or "{}"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SlackError("rate_limited", "HTTP 429", retry_after=int(e.headers.get("Retry-After", "1")))
        raise SlackError("invalid_token" if e.code in (403, 404) else "http_error", f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise SlackError("timeout", type(e).__name__)
    try:
        out = json.loads(body)
    except ValueError:
        out = {"raw": body}                                           # webhooks answer the text "ok"
    if out.get("ok") is False:
        raise SlackError(out.get("error", "slack_error"), "ok:false")
    return out if isinstance(out, dict) else {"raw": out}


def transport_from_env():
    if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_CHANNEL_ID"):
        return BotSlack(os.environ["SLACK_BOT_TOKEN"], os.environ["SLACK_CHANNEL_ID"]), "bot"
    if os.environ.get("SLACK_WEBHOOK_URL"):
        return WebhookSlack(os.environ["SLACK_WEBHOOK_URL"]), "webhook"
    return MockSlack(), "mock"


class SlackNotifier:
    def __init__(self, boundary, transport, mode="mock", breaker_threshold=2, sleep=time.sleep):
        self.b, self.t, self.mode, self.sleep = boundary, transport, mode, sleep
        self.threshold, self.failures, self.open = breaker_threshold, 0, False
        self.sent = {}                                                   # idempotency key -> prior result
        self.log = []

    def card(self, claim_id, reason, user):
        return {"text": f"Claim {claim_id}: human review needed",
                "blocks": [{"type": "header", "text": {"type": "plain_text", "text": f"Claim {claim_id}: review needed"}},
                           {"type": "section", "text": {"type": "mrkdwn", "text": f"*Why:* {reason[:300]}\n*Raised by:* {user}"}},
                           {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text",
                                                                                        "text": "Open in ClaimSense"},
                                                             "url": f"{CONSOLE}/?claim={claim_id}"}]},
                           {"type": "context", "elements": [{"type": "mrkdwn", "text":
                               "through the governed door · scoped + audited · the record lives in ClaimSense, not here"}]}]}

    def notify(self, user_id, claim_id, reason, idempotency_key, agent=None):
        b = self.b
        c = b.caller(user_id)
        if (denied := b._authorize(c, "notify_oncall", claim_id, agent)):
            return denied                                                  # Slack never called
        claim = b.claims.get(claim_id)
        if claim is None or not b.entitled(c, claim):
            rid = b._audit(c, "notify_oncall", claim_id, "deny", "not_found_or_not_entitled", agent)
            return b._error("not_found_or_forbidden", "No claim is available for this request.", rid)
        if not idempotency_key or not isinstance(reason, str) or not reason.strip():
            rid = b._audit(c, "notify_oncall", claim_id, "error", "invalid_request", agent)
            return b._error("invalid_request", "A page needs a reason and an idempotency key.", rid)
        if idempotency_key in self.sent:
            b._audit(c, "notify_oncall", claim_id, "replay", f"duplicate key {idempotency_key}: not re-posted", agent)
            return dict(self.sent[idempotency_key], deduped=True)
        result = self._deliver(c, claim_id, reason, idempotency_key, agent)
        self.sent[idempotency_key] = result
        b._audit(c, "notify_oncall", claim_id, "allow", f"delivered_via={result['delivered_via']}"
                 + (" (flagged: unexpected response shape)" if result.get("flagged") else ""), agent)
        return result

    def _deliver(self, c, claim_id, reason, key, agent):
        if self.open:
            self.log.append("circuit-breaker OPEN: skipping Slack, routing to the ticket fallback")
            return self._fallback(c, claim_id, reason, key, agent, "circuit_open")
        delay = 1
        for attempt in range(1, 4):
            try:
                resp = self.t.post(self.card(claim_id, reason, c["user_id"]))
            except SlackError as e:
                if e.code == "rate_limited" and attempt < 3:
                    wait = min(e.retry_after or delay, 5)
                    self.log.append(f"attempt {attempt}: 429 rate-limited -> backoff {wait}s, retrying")
                    self.sleep(wait)
                    delay *= 2
                    continue
                self.failures += 1
                self.log.append(f"attempt {attempt}: hard failure ({e}) -> not retryable")
                if self.failures >= self.threshold:
                    self.open = True
                    self.log.append(f"circuit-breaker TRIPPED after {self.failures} consecutive failures")
                return self._fallback(c, claim_id, reason, key, agent, e.code)
            self.failures = 0
            flagged = not (isinstance(resp, dict) and (resp.get("ok") is True or resp.get("raw") == "ok"))
            if flagged:
                self.log.append(f"defensive-parse: unexpected Slack response {json.dumps(resp)[:80]}; treated as "
                                "delivered, flagged for review")
            return {"delivered_via": "slack", "mode": self.mode, "claim_id": claim_id, "flagged": flagged}
        return self._fallback(c, claim_id, reason, key, agent, "rate_limited")

    def _fallback(self, c, claim_id, reason, key, agent, why):
        """Never lose the escalation: open an SIU ticket through the same door (idempotent on the same key)."""
        self.log.append("Slack undeliverable -> routing to the ticket fallback (escalation is never lost)")
        t = self.b.escalate(c["user_id"], claim_id, f"[on-call page failed: {why}] {reason}", f"slack-{key}",
                            "high", agent)
        return {"delivered_via": "fallback", "mode": self.mode, "claim_id": claim_id, "reason": why,
                "ticket_id": t.get("ticket_id"), "fallback_error": (t.get("error") or {}).get("code")}
