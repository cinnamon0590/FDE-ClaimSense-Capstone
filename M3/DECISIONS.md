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
- **Deployed 2026-11-18** with Susan's OK (evidence 13 and 14).
  - The account's Lambda concurrency quota (10) can't reserve 1, so the function runs unreserved; sequential traffic
    stays on one warm instance.
  - Edge refusals are recorded in an API Gateway access log. Found while checking: an authorizer error containing
    quotes makes that log line invalid JSON, so it is counted by text, not by a JSON filter.
- **AgentCore Gateway applied live and destroyed (evidence 16).** AWS refuses caller-token pass-through for both
  OpenAPI and MCP-server targets, so a managed gateway would collapse every adjuster into one identity. The
  hand-built door stays the enforcement point.
- **Owner:** Susan Wellington.

## D-041 · 2026-11-18 · Architect, made literal: the IdP itself performs the on-behalf-of exchange (Keycloak)
- **Why:** D-039's exchange runs at the door, because Cognito has no RFC 8693 endpoint. The checklist asks for "an
  actual OAuth2 token exchange against any OIDC login system", so the exchange should happen **at the IdP**.
- **Decision:** an optional Keycloak 26.2.5 add-on (`M3/keycloak/`, local, $0) whose realm mirrors the synthetic
  directory. Keycloak's **standard token exchange** (RFC 8693) runs at Keycloak:
  - the adjuster signs in at the `claimsense-console` client; that token's audience is the orchestrator, not the door;
  - the `claimsense-orchestrator` client (confidential, exchange enabled) trades it for a 5-minute token with
    `aud` = `claimsense-door`, `azp` = the orchestrator, and `scope` = the action scopes it asked for;
  - only the 9 delegable actions exist as scopes, so asking for `confirm_recommendation` is refused **at the IdP**.
- **The door** (`obo.IdPExchange`) trusts such a token only if it is RS256-signed by the realm's JWKS, `iss` is the
  realm, `aud` is the door, `azp` is on the allow-list, and the user and groups still match the directory. Its scope,
  narrowed to delegable action names, sets `TOKEN_SCOPE`, so **the IdP-exchanged scope drives `_authorize`**. The
  door's grants still apply (the IdP's scope is necessary, not sufficient), and so does entitlement.
- **Secrets:** none in the repo or compose. Throwaway synthetic credentials live in `~/.claimsense/keycloak.json`
  (0600); the bootstrap admin password reaches Keycloak only through the environment of the `docker compose` call.
- **Evidence:** `evidence/19-keycloak-obo-exchange.txt` (13/13 live) and `tests/test_idp_exchange.py` (offline, in CI).
- **Not done:** Keycloak is not deployed to AWS (Cognito stays the AWS IdP; D-039's door-side exchange remains the
  path there).
- **Owner:** Susan Wellington.

## D-042 · 2026-11-19 · The Learning UI Viewer's Week 4 checks, made literal: assigned claims, REST 403, CloudWatch audit
- **Why:** the ClaimSense Learning UI Viewer's *Week 4 Integration* tab words three checks more strictly than our
  M3 did. (1) "RBAC enforces that adjusters only read their **assigned** claims", tested as "Alice requests a claim
  not assigned to her and receives 403; Bob (senior-adjuster) requests the same claim and receives 200 with full
  data". Our entitlement was by queue (`assigned_group`), and every claim was in the adjuster queue, so that test
  could not be run. (2) A refused REST read answered HTTP 200 with an error body, not 403. (3) "Open CloudWatch Logs
  and confirm every MCP call logs user ID, action and resource ID": our rows were in DynamoDB, not CloudWatch.
- **Decision:**
  - **Per-adjuster assignment.** Claims Management now records which adjuster owns each claim
    (`M1/6-synthetic-data/fixtures/claim_assignments.json`, served by the mock Claims Management system at
    `/claims-management/assignments`). M1's `entitled()` lets an adjuster read a claim only if it is in the adjuster
    queue **and** assigned to them; a senior adjuster still reads every claim; a claim with no owner is denied
    (deny-by-default). The assignment is kept **out of the claim record**, so the claim file every agent sees, and
    every eval case, replay and label, is byte-identical (the live gate needs no re-run).
  - **Two new synthetic claims**, `CLM-2024-5001` and `CLM-2024-5002`, in no eval suite, sit in bob's (the senior
    adjuster's) queue. Alice owns every other claim. They are generated by the same code as the rest
    (`source/senior_queue.json`).
  - **REST status codes.** The door's structured errors map to HTTP: `not_found_or_forbidden` and
    `human_confirmation_required` → 403, `invalid_request` → 400, `idempotency_conflict` / `already_confirmed` →
    409, `upstream_unavailable` → 503. A missing claim and a forbidden one are **both 403 with the same message**,
    so the status leaks nothing. `/mcp` is unchanged: a refused tool call stays a JSON-RPC result with `isError`,
    as the MCP spec requires.
  - **CloudWatch.** Every audit row is also written as one `AUDIT {json}` line to stdout. On Lambda that is
    CloudWatch Logs (`/aws/lambda/claimsense-door`, which the function's role already allowed). DynamoDB stays the
    append-only system of record. On by default when the DynamoDB trail is on; `CLAIMSENSE_AUDIT_STDOUT=1` turns it
    on locally (the compose door has it), `=0` turns it off. Rows hold IDs only: no token, no claimant name.
- **Evidence:** `evidence/20-viewer-week4-stack.txt` (local) and `evidence/21-viewer-week4-deployed.txt` (AWS,
  CloudWatch); `tests/test_week4_viewer.py` (offline, in CI); `python -m claimsense_door.two_analyst_test --viewer`.
- **Owner:** Susan Wellington.

## D-043 · 2026-11-19 · The Lambda ships as a container image, not a zip (the viewer says "zip Lambda")
- **Why:** the viewer's deploy step says "Zip Lambda, create the function, create HTTP API Gateway and wire the
  Cognito JWT authorizer". We deploy the same function, API and authorizer, but package it as a **container image**.
- **Decision:** keep the image.
  - It is the build CI tested, not a second packaging of the same code that nothing tested.
  - The door's dependencies (FastAPI, PyJWT, cryptography with native code) need a Linux build; an image pins that
    exactly, a zip would be built on a Mac.
  - The image runs the same ASGI app locally and on Lambda (Lambda Web Adapter), so the local proofs prove the
    deployed code.
- **What is identical to the viewer's step:** an HTTP API (API Gateway v2), a Cognito JWT authorizer on every
  protected route, and no valid token → 401 before the Lambda runs (evidence 14).
- **Owner:** Susan Wellington.
