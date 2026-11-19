# Evidence index (M3)

Every file starts with a header (what, when, command) and holds the verbatim output. Produced on a fresh
`docker compose down -v && up` stack, in CI order (the RBAC hand-offs last). CI re-runs all of it (`m3-door`).

| # | File | What it proves | Status |
|---|---|---|---|
| 01 | [`01-mcp-selftest.txt`](01-mcp-selftest.txt) | The MCP protocol: initialize → list → call → dedupe → deny → enumerate, smuggled identity refused | ✅ PASS |
| 02 | [`02-two-user-test-offline.txt`](02-two-user-test-offline.txt) | D-4 two-user test in-process: both requests, both responses, matching audit rows | ✅ PASS |
| 03 | [`03-door-proofs-offline.txt`](03-door-proofs-offline.txt) | 11 proofs: the lab's 4, deny-by-default, jailbreak, webhooks, 4th backend, injection containment, six attacks, audit traps | ✅ PASS |
| 04 | [`04-two-user-test-stack.txt`](04-two-user-test-stack.txt) | D-4 over HTTP on the running stack (dev-issuer RS256 tokens) | ✅ PASS |
| 05 | [`05-route-auth-every-route.txt`](05-route-auth-every-route.txt) | D-2: 21 routes + 10 MCP tools × 6 bad credentials = 186/186 refused, 186 audit rows; token exchange refusals | ✅ PASS |
| 06 | [`06-access-control-before-agents.txt`](06-access-control-before-agents.txt) | D-3: refusals start zero agents, zero model calls, $0; no authorisation in any prompt | ✅ PASS |
| 07 | [`07-ticketing-backend-and-webhooks.txt`](07-ticketing-backend-and-webhooks.txt) | Stretch: 4th backend through the door + signed, deduped, ordered webhooks | ✅ PASS |
| 08 | [`08-mcp-interop-official-client.txt`](08-mcp-interop-official-client.txt) | The official Agents SDK MCP client connects, lists, calls; scope holds; no token cannot initialize | ✅ PASS |
| 09 | [`09-audit-every-call.txt`](09-audit-every-call.txt) | D-5: 14 kinds of call each leave one complete row; append-only; who touched a claim | ✅ PASS |
| 10 | [`10-m2-suites-through-the-door.txt`](10-m2-suites-through-the-door.txt) | M2's smoke, 40/40 container eval and RBAC hand-offs with every agent access via /mcp | ✅ PASS |
| 11 | [`11-agentcore-gateway-plan.txt`](11-agentcore-gateway-plan.txt) | Architect: the managed twin's plan ($0) | ✅ PASS |
| 12 | [`12-unit-tests.txt`](12-unit-tests.txt) | pytest: a bare `pytest -q` from the repo root, as the grader runs it (M0 to M3 in one process): 163 passed; M3 alone 32 | ✅ PASS |
| 13 | [`13-deployed-two-user-test.txt`](13-deployed-two-user-test.txt) | D-1 + D-4 on AWS: API Gateway (Cognito JWT) → Lambda → the door, with real Cognito tokens and the DynamoDB audit | ✅ PASS |
| 14 | [`14-deployed-route-auth.txt`](14-deployed-route-auth.txt) | D-2 on AWS: 150/150 bad credentials refused, all recorded at the edge; OBO exchange on the real IdP | ✅ PASS |
| 15 | [`15-live-gate-through-the-door.txt`](15-live-gate-through-the-door.txt) | the live 40-case gate through /mcp with delegated tokens: 40/40, 11/11 adversarial, all model-decided, $0.68 | ✅ PASS |
| 16 | [`16-agentcore-gateway-apply.txt`](16-agentcore-gateway-apply.txt) | Architect: Gateway applied live; AWS refuses JWT pass-through for OpenAPI and MCP-server targets → hand-built door stays; destroyed | ✅ answered |
| 17 | [`17-oncall-slack-through-the-door.txt`](17-oncall-slack-through-the-door.txt) | Builder: Slack on-call through the door, 8 scenarios PROBLEM → HANDLED | ✅ PASS |
| 18 | [`18-slack-live-page.txt`](18-slack-live-page.txt) | Builder: a REAL page in Susan's private #claimsense-oncall, through the door over MCP; the retry deduped; carol refused before Slack. Screenshot of the card: [`18-slack-live-page.png`](18-slack-live-page.png) (cropped to the message) | ✅ PASS |
| 19 | [`19-keycloak-obo-exchange.txt`](19-keycloak-obo-exchange.txt) | Architect, literal: **Keycloak performs the RFC 8693 exchange**; the exchanged token's scope drives `_authorize`; non-delegable scopes refused at the IdP; the door's grants and entitlement still hold (13/13) | ✅ PASS |
