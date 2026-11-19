# M3 · Integrated and access-controlled (W16 · brief Milestone 4)

**The governed door.** Every route to AutoSure's data now goes through one MCP server (synthetic data only). The door
enforces explicit grants and per-user entitlement in code, before any agent runs, and writes an append-only audit row
for every call.

## M3

Scope is enforced in **code, in the door**, in two deterministic gates that run before any data moves.
1. **The action gate:** `grants.json` says what each role may do. It is **deny-by-default**: an unknown role, an
   undeclared action or a typo is refused.
2. **The record gate:** M1's `entitled()` rule says which claims that role may see. It checks the claim's
   `assigned_group`, and a confirmed hand-off moves the claim between groups.

The gate writes the audit row first, then returns the denial. "Does not exist" and "not yours" give an identical
answer, so nobody can probe which claims exist.

It is **not in the prompt** because a prompt is advice to a model, and a model can be talked out of its
instructions: a poisoned document can make it *ask* for anything. The door ignores what the model wants. It looks
only at the verified token's user and the directory's groups. Identity is never a tool argument, so the model cannot
present someone else's badge.

## The five graded deliverables, and where each is proven

| # | Deliverable | Evidence (`evidence/`) |
|---|---|---|
| D-1 | **Data access boundary deployed and callable** | **AWS:** API Gateway (Cognito JWT authorizer) → Lambda → the door, with the audit trail in DynamoDB. [`13-deployed-two-user-test.txt`](evidence/13-deployed-two-user-test.txt) and [`14-deployed-route-auth.txt`](evidence/14-deployed-route-auth.txt). **Local:** the M3 stack (`docker compose up`; the door at `:8002`, REST + `/mcp`) |
| D-2 | **Authorisation on every route; no valid token = refused** | [`05-route-auth-every-route.txt`](evidence/05-route-auth-every-route.txt): 21 HTTP routes + 10 MCP tools × 6 bad credentials = **186/186 refused (401)**, 186 audit rows. **On AWS: 150/150** refused, every one in the edge access log ([14](evidence/14-deployed-route-auth.txt)). Tokens are verified in middleware *before routing*, so no route can answer with a 422 first. The unit test `test_every_route_is_listed…` **fails the build on any unmapped route** |
| D-3 | **Access control in code, before any agent** | [`06-access-control-before-agents.txt`](evidence/06-access-control-before-agents.txt): an entitled run starts 13 agent events; carol's and dave's refusals start **zero** agents, make zero model calls and cost $0. No authorisation phrase appears in any prompt |
| D-4 | **Two-user test: both requests + both responses, same claim** | [`02`](evidence/02-two-user-test-offline.txt) (offline) and [`04-two-user-test-stack.txt`](evidence/04-two-user-test-stack.txt) (over HTTP): the full requests (token redacted), the full responses, the matching allow and deny audit rows, `RESULT: PASS — scope holds` |
| D-5 | **An audit record for every call (user, action, resource)** | [`09-audit-every-call.txt`](evidence/09-audit-every-call.txt): 14 kinds of call (allow, deny by grant, deny by entitlement, not-found, unauthenticated, invalid, write, replay, orchestrator entry, audit read) each leave exactly one complete row. The trail is append-only: there is no write route, and DELETE/PUT/PATCH/POST all return 405 |

**The grader's one-liner:** `python -m claimsense_door.two_analyst_test ; echo $?` → `0`, with the PASS line and both
audit rows (run from `M3/door` with `PYTHONPATH=../../M2:.`, or use `make two-user`). The grader's `pytest -q` from the
repo root runs M0 to M3 in one process: **163 passed** (evidence 12), and CI runs exactly that command.

## The graded checklist (`milestone-M3-integration.md`): every tier

| Tier | Item | ClaimSense |
|---|---|---|
| Floor | One governed door; the agent reaches *every* backend through it | `CLAIMSENSE_MCP_URL` → the orchestrator's `McpBoundary`. Every agent data access is an MCP `tools/call` (evidence 10: all 40 eval cases through `/mcp`; evidence 15: the live gate). No agent module imports a backend; M2's in-process boundary remains only for M2's own offline unit tests, selected when no door URL is set |
| Floor | Typed tools + structured errors | 10 tools with JSON-Schema inputs (pattern, length, `additionalProperties: false`). Errors are dicts: `not_found_or_forbidden`, `invalid_request`, `upstream_unavailable` + `retry_after_s`. Never a raw 500 |
| Floor | Idempotent writes | `create_recommendation` and `create_escalation_ticket` require a key; the replay **returns the original**, marked `idempotent_replay` (evidence 03 proof 2, 07 step 2) |
| Floor | Retry with backoff against a flaky backend | The ticketing system 503s every first attempt (the lab's `FlakyLegacyCore`, as a real container): `attempt 1: HTTP 503 -> backoff 0.05s` · `delivered on attempt 2` (evidence 03 proof 3, 07 step 1) |
| Floor | `_authorize` writes the audit row for allow AND deny, then **raises** | `GrantedBoundary._authorize` writes the deny row, then raises `AccessDenied` (a `PermissionError` carrying the structured error); the tool layer (`_gate`) turns it into the dict the caller sees, never a raw exception. The allow row is written once per call by the record gate (M1 `entitled()`). Tests: `test_authorize_raises_on_deny_after_writing_the_audit_row`, `test_denial_audit_row_is_written_before…` |
| Floor | Two-analyst test, runnable, exit 0/1 | `python -m claimsense_door.two_analyst_test` |
| Floor | Append-only audit, complete, `search_policy` audited | Every row carries the checklist's `{acting_identity, scope, action, resource, decision}` (plus `user_id`, `groups`, `reason`, `via`, `request_id`, `on_behalf_of_agent`), on every tool including the unscoped KB search (evidence 09 checks every row) |
| Floor | README section "M3" | Above |
| Builder | Jailbreak demonstration | Evidence 03 proof 6: the "model" asks for a handed-off claim and the gate refuses it with a deny row; a smuggled `user_id` argument is rejected |
| Builder | **Deny-by-default** with a grants table + a test | `door/claimsense_door/grants.json` + proof 5 + `test_nothing_is_granted_without_an_explicit_grant` |
| Builder | **Webhook or third backend** (we did both) | **A 4th system of record**, SIU escalation ticketing (its own container). **Webhook-driven updates**: HMAC-signed, 5-minute replay window, deduped by `event_id`, ordered by `seq` (evidence 07) |
| Builder | Live-platform bridge (*adapted*) | The checklist's version targets the Meridian `/api/v1`, which ClaimSense doesn't have. Our analogue: the two-user test and the route check against the **deployed AWS door** with real Cognito tokens, audit in DynamoDB (evidence 13, 14). Not counted toward the tier; four other Builder items are |
| Builder | **A real external integration (Slack)** | `notify_oncall`: on-call paging as a scoped, audited door tool. Handles a 429 (backoff), an expired webhook (fallback to an SIU ticket), a timeout (breaker), a duplicate (idempotent dedupe) and schema drift (defensive parse). The card carries a link, never claim data. The PROBLEM → HANDLED summary is [evidence 17](evidence/17-oncall-slack-through-the-door.txt). **A live page was delivered to Susan's private `#claimsense-oncall` through the door over MCP** ([evidence 18](evidence/18-slack-live-page.txt), [screenshot](evidence/18-slack-live-page.png)); the retry was deduped, and carol was refused before Slack |
| Architect | **AgentCore Gateway plan** | [`agentcore_gateway/README.md`](agentcore_gateway/README.md) (one page), `gateway_setup.py plan` (evidence 11), and **applied live** (evidence 16): AWS refuses caller-token pass-through for OpenAPI and MCP-server targets, so the hand-built door stays the enforcement point. Destroyed after |
| Architect | **OBO with a real IdP** (*partial on a strict reading*) | RFC 8693 token exchange at the door's own `POST /oauth/token`: a real Cognito ID token in (verified against Cognito's JWKS, evidence 14), a 5-minute delegated token out, with `act` = the agent and scope = request ∩ grants (never confirm or audit). **The token's scope drives `_authorize`** (`tests/test_obo.py`). Cognito has no RFC 8693 endpoint, so the exchange runs at the door, not at the IdP. Not needed for the tier: the other two Architect items are complete |
| Architect | **Injection containment test** | Evidence 03 proof 9: the planted unprovenanced chunk is quarantined at the door (G2), **and** a poisoned "fetch claim CLM-2024-1873" is refused at the gate |

**Six attacks on the door** (the W16 activity, evidence 03 proof 10):
- out-of-scope read: STOPPED, by scope;
- replayed write: STOPPED, by idempotency;
- ID probing: STOPPED, by identical denials;
- injected instruction: PARTLY, by quarantine with scope as the net;
- borrowed token: not stopped at the door. The **audit** attributes every action to the token's owner, and tokens
  expire;
- flood of retries: STOPPED, by backoff and the circuit breaker.

## Architecture

```
 console (adjuster, Cognito/dev ID token) ──REST──┐
                                                  ▼
 orchestrator ── token exchange (RFC 8693) ──▶ ┌─────────────── THE DOOR (boundary service) ───────────────┐
   4 agents (OpenAI Agents SDK)                │ authenticate in middleware (before routing) → 401 + audit  │
   McpBoundary ──── MCP /mcp (delegated) ────▶ │ _authorize: grants.json (ACTION) → entitled() (RECORD)     │
                                               │ typed tools · idempotency · retry/backoff · breaker        │
 ticketing ── signed webhook ────────────────▶ │ append-only audit row on EVERY call (shared trail)         │
                                               └──┬──────────┬──────────┬───────────────┬───────────────────┘
                                                  ▼          ▼          ▼               ▼
                                          Claims Mgmt  Policy Admin  Document Store  Policy & Coverage KB  SIU Ticketing
                                          (mock systems of record, internal network)   (OpenSearch)        (4th, flaky)
```

The **tool names** map from the lab's bank to the insurer:
- `lookup_dispute` → `get_claim`;
- `fetch_transactions` → `list_claim_documents` / `get_document`;
- `create_ticket` → `create_escalation_ticket` (plus `create_recommendation`);
- `search_policy` → `search_policy_clauses`.

**Defense in depth** (class notebook §6). There are three layers:
1. The agent prompt: advisory only.
2. The door's gates: enforced in code.
3. The data-layer filter: the boundary only ever returns rows the caller is entitled to, even if a caller skips the
   grant gate. This is ClaimSense's equivalent of row-level security.

**Tenancy:** AutoSure is the single tenant. Scope (role) is not tenancy (whose rows exist at all); a second insurer
would add a tenant wall below the role gate (W16 notebook §5.5).

## The scope matrix (W16 activity, applied to this insurer)

| Role ↓ / action → | claim, policy, documents | KB search | draft | confirm | escalate | read audit |
|---|---|---|---|---|---|---|
| adjuster (first pass) | R (assigned group) | R | W | **W (human-only)** | W | – |
| senior-adjuster | R (all) | R | W | W | W | **R (read-only)** |
| fraud-investigator / total-loss-appraiser | R (after a hand-off) | R | W | – | W | – |
| customer-service | **–** (trap 1: never reads fraud scores) | – | – | – | – | – |
| system:ticketing | – | – | – | – | – | – (only `ticket_webhook`) |

**Trap 2:** no human role writes the audit trail; only the system does.

## Run it

```bash
cd M3
make test        # 31 M3 tests + the offline two-user test + every door proof + the MCP self-test ($0, no containers)
make up          # the M3 stack: door, ticketing, mock systems, OpenSearch, orchestrator, console
make proofs      # every running-stack check (writes evidence/04..10)
make down
```

Connect any MCP client: `claude mcp add claimsense -- env CLAIMSENSE_ACTING_TOKEN=<an adjuster's token> python -m
claimsense_door.stdio`, or point any streamable-HTTP MCP client at `http://localhost:8002/mcp` with a bearer token.

## Deployment

`cloud/deploy.sh` deploys the door as a Lambda container image behind an API Gateway HTTP API. The API's **Cognito JWT
authorizer** guards every route except health, the key and metadata documents, the token exchange and the HMAC-signed
webhook. The door verifies the token again, in code.
- **Reused from M1:** the Cognito pool (5 groups) and the `claimsense-audit` DynamoDB table.
- **Users:** five synthetic users with random passwords, stored only in `~/.claimsense/` (0600).
- **Cost:** about $0 within the free tiers. `cloud/teardown.sh` removes everything.
- **Proof:** `two_analyst_test --url <door> --cognito` and `evals/route_auth_check.py` against the URL.
- **Known limit (documented):** the function runs with reserved concurrency 1, keeping drafts and idempotency in
  `/tmp`. DynamoDB-backed state is an M4 hardening item.

## Assumptions and limits

- **AWS:** deployed 2026-11-18. The Lambda runs unreserved, because the account's concurrency quota (10) can't
  reserve 1. Drafts and idempotency live in `/tmp` on the single warm instance; DynamoDB-backed state is the M4
  hardening item. Edge refusals are in the API Gateway access log, door decisions in the DynamoDB audit table.
- **Policy KB search at the door** is BM25, so the door never holds a model key. The **live 40-case gate through the
  door passed 40/40** (evidence 15, $0.68), so the retrieval change cost no accuracy.
- **AgentCore Gateway** was applied live and destroyed. AWS doesn't yet pass the caller's token through to OpenAPI or
  MCP-server targets (evidence 16), so the hand-built door stays the enforcement point.
- **The OBO IdP** is Cognito (real) for the subject token; the RFC 8693 exchange itself runs at the door, because
  Cognito has none. An IdP that performs the exchange natively (Keycloak, Okta) would close that gap; its JWKS plugs
  into `Verifier` unchanged.
