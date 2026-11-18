# DECISIONS (M3 · W16): integration and access control

Continues M2's log (D-017 to D-035). Each decision gives the date, the decision, why, the alternatives considered and
the owner.

## D-036 · 2026-11-18 · One governed door, spoken as MCP, built the way the W16 lab builds it
- **Context:**
  - The brief's Milestone 4 requires a boundary that is deployed, guards every route, controls access in code before
    any agent, has a recorded two-user test, and audits every call.
  - The course's graded M3 checklist and the W16 lab set the shape: `Identity` → `_authorize` (audit, then deny) →
    typed tools → `AuditLog`, plus idempotency, retry/backoff and structured errors.
- **Decision:** the M2 data boundary becomes the door, with two protocols and one set of rules:
  - REST for the console;
  - **MCP** (`POST /mcp`, JSON-RPC 2.0, spec 2025-06-18) for the agents.
  It is built like the lab's `meridian_slack_mcp.py`: stdlib JSON-RPC, every part visible, `--selftest`. The
  orchestrator's agents reach data only through `McpBoundary` (`CLAIMSENSE_MCP_URL`).
- **Identity:**
  - Over HTTP, from the verified bearer token. The door is an OAuth 2.1 resource server: `WWW-Authenticate` with
    RFC 9728 metadata.
  - Over stdio, from server-side configuration.
  - **Never from a tool argument**: every tool schema has `additionalProperties: false`.
- **Why not the official `mcp` SDK server:**
  - The lab teaches the protocol by hand, and procurement can read about 300 lines.
  - Interoperability is proven instead: the official SDK *client* (the Agents SDK's `MCPServerStreamableHttp`)
    connects, lists and calls (evidence 08).
- **Owner:** Susan Wellington (FDE).

## D-037 · 2026-11-18 · Deny-by-default grants in front of the M1 entitlement rule; one shared append-only audit trail
- **Decision:** two gates, both in code, both audited.
  - **ACTION gate:** `grants.json`, role → explicitly granted actions. No wildcard, no default-allow branch; unknown
    roles and undeclared actions are denied.
  - **RECORD gate:** M1's `entitled()` (assigned group; hand-offs move claims).
  Denials for "no grant", "not entitled" and "does not exist" are identical to the caller. The reason lives only in
  the audit row, which is written before the denial is returned.
- **One trail for every service** (`claimsense/audit_trail.py`):
  - **Writers:** the door (REST, MCP, the webhook, the token exchange) and the orchestrator's entry points.
  - **Format:** append-only JSONL under an exclusive lock locally; M1's DynamoDB table on AWS (conditional put,
    never overwritten).
  - **Orchestrator rows** use decision `authenticated`, not `allow`. Only the door decides what data is released,
    so "who was allowed claim X" is never muddied by entry rows.
- **Every route:** the token is verified in middleware **before routing**. Found by `route_auth_check`: FastAPI was
  validating request bodies first, so a no-token request with a bad body got a 422 (leaking the schema) instead of a
  401. A unit test fails the build if any route isn't listed in `ROUTE_ACTIONS`.
- **Alternative rejected:** an authorisation check per handler only. One forgotten route is the "Partial" band in the
  rubric.
- **Owner:** Susan Wellington.

## D-038 · 2026-11-18 · Stretch: a 4th system of record (SIU escalation ticketing) and webhook-driven updates
- **Decision:** a mock ServiceNow-style ticketing service (its own container) behind the same door, via the
  `create_escalation_ticket` / `get_escalation` tools.
- **It is flaky on purpose:** a structured 503 on every first attempt, so the retry and backoff run on every real
  escalation.
- **The door's client handles it with:**
  - idempotency keys;
  - exponential backoff honouring `retry_after`;
  - a circuit breaker (3 failures → 30 s open);
  - an outbox, so an escalation is never lost while ticketing is down.
- **Status changes are PUSHED** to `POST /webhooks/ticketing`:
  - HMAC-SHA256 over `t.body`, with a 5-minute replay window;
  - deduped by `event_id`;
  - ordered by `seq` (a late older event is ignored).
  - The ticketing system's identity holds exactly one grant, `ticket_webhook`; it cannot read a claim.
- **Secrets:** neither shared secret lives in the repo, an image or compose. Each is generated once on a private
  volume (0600, exclusive create) and read by both sides. On AWS, a `CLAIMSENSE_SECRET_*` value from Secrets Manager
  overrides it.
- **Owner:** Susan Wellington.

## D-039 · 2026-11-18 · Architect: on-behalf-of with a real IdP (RFC 8693 token exchange)
- **Decision:** the orchestrator exchanges the adjuster's IdP ID token (Cognito on AWS; the dev issuer locally) at
  `POST /oauth/token` for a **5-minute delegated token**:
  - `sub` = the adjuster;
  - `act.sub` = `agent:claimsense-pipeline`;
  - `scope` = the requested actions ∩ the adjuster's grants, **never** `confirm_recommendation`, `read_audit` or
    `ticket_webhook`;
  - `aud` = the door.
  The agents' MCP calls carry only this token. `_authorize` enforces grants **and** token scope, and the audit names
  the agent from the token, not from a header.
- **Behavior:** a user with no grants gets no token (`invalid_grant`, audited `no_grant`), so their agents never even
  reach the door. A delegated token stops working the moment the user's groups change.
- **Alternative:** AgentCore Identity's vault. Recorded in `agentcore_gateway/README.md`.
- **Owner:** Susan Wellington.

## D-040 · 2026-11-18 · Deployment: Lambda + API Gateway + Cognito; the AgentCore Gateway twin planned, not applied
- **Decision:** the door ships as a Lambda container image (Lambda Web Adapter) behind an API Gateway HTTP API.
  - A Cognito JWT authorizer guards `$default`.
  - The public routes are health, JWKS/metadata, the token exchange (authenticated by its subject token) and the
    HMAC webhook.
  - M1's Cognito pool and audit table are reused.
- **Known limit:** reserved concurrency 1 keeps drafts and idempotency consistent in `/tmp`. DynamoDB state is M4
  work.
- **Pending:** `deploy.sh`, and the Gateway `apply`, wait for Susan's `aws login` and an explicit OK. Expected cost is
  about $0, and `teardown.sh` is provided.
- **Owner:** Susan Wellington.
