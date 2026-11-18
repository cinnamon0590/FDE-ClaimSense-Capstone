"""Client for the 4th backend, SIU / escalation ticketing (a ServiceNow-style system; mocked locally).

The integration contract from W16, enforced here so the agent never has to reason about it:
  * idempotency: every create carries an Idempotency-Key; a retry returns the ORIGINAL ticket
  * retry with exponential backoff on transient failures (503 / 429 / connection errors), honouring retry_after
  * a circuit breaker: after N consecutive failures, stop calling for a cool-off instead of hammering it
  * structured errors only: callers get TicketingUnavailable (-> upstream_unavailable), never a stack trace
"""
import time

import httpx


class TicketingUnavailable(Exception):
    pass


class TicketingClient:
    def __init__(self, base_url, token_fn, attempts=4, base_delay=0.05, breaker_threshold=3, cooloff_s=30,
                 sleep=time.sleep, http=None):
        self.base = base_url.rstrip("/")
        self.token_fn = token_fn                       # the service credential, read from the secrets volume
        self.attempts, self.base_delay = attempts, base_delay
        self.breaker_threshold, self.cooloff_s = breaker_threshold, cooloff_s
        self.sleep = sleep
        self.http = http or httpx.Client(timeout=5)
        self.failures, self.open_until = 0, 0.0
        self.log = []                                  # what happened, for the evidence (never sent to a model)

    def _note(self, msg):
        self.log.append(msg)

    def create(self, payload, idempotency_key):
        if time.time() < self.open_until:
            self._note("circuit open: short-circuit")
            raise TicketingUnavailable("circuit breaker open")
        delay = self.base_delay
        last = "no attempt"
        for attempt in range(1, self.attempts + 1):
            try:
                r = self.http.post(f"{self.base}/tickets", json=payload,
                                   headers={"Authorization": f"Bearer {self.token_fn().decode()}",
                                            "Idempotency-Key": idempotency_key})
            except httpx.HTTPError as e:
                last = f"{type(e).__name__}"
                retry_after = delay
            else:
                if r.status_code in (200, 201):
                    self.failures = 0
                    if attempt > 1:
                        self._note(f"delivered on attempt {attempt}")
                    return r.json()
                if r.status_code not in (429, 503):
                    self._fail()
                    raise TicketingUnavailable(f"ticketing refused: HTTP {r.status_code}")   # not retryable
                last = f"HTTP {r.status_code}"
                try:
                    retry_after = float(r.json().get("error", {}).get("retry_after_s") or delay)
                except ValueError:
                    retry_after = delay
            self._note(f"attempt {attempt}: {last} -> backoff {min(retry_after, delay):.2f}s")
            if attempt < self.attempts:
                self.sleep(min(retry_after, delay))
                delay *= 2
        self._fail()
        raise TicketingUnavailable(f"still failing after {self.attempts} attempts ({last})")

    def _fail(self):
        self.failures += 1
        if self.failures >= self.breaker_threshold:
            self.open_until = time.time() + self.cooloff_s
            self._note(f"circuit breaker OPEN for {self.cooloff_s}s after {self.failures} failures")
