# The managed door: AgentCore Gateway for ClaimSense (one-page decision)

**Question.** Should the hand-built MCP door (`../door/`) be replaced by Amazon Bedrock **AgentCore Gateway** (OpenAPI
→ MCP tools) plus **AgentCore Identity** (a credential vault)?

**Mapping:**

| Hand-built (M3) | Managed form | What moves | What must NOT move |
|---|---|---|---|
| `McpDoor` + 9 typed tools | Gateway + a target from `openapi.json` (each `operationId` → a tool) | tool wiring, the MCP transport | the grant gate, entitlement, anti-enumeration, audit |
| Cognito ID token, verified in the door | Gateway inbound **CUSTOM_JWT** authorizer (Cognito discovery URL + client id) | edge token validation | the door's own re-verification |
| RFC 8693 exchange (`/oauth/token`) | AgentCore Identity (token vault, outbound OAuth) | storing and refreshing credentials | the narrowing: request ∩ grants, never confirm or audit |
| append-only audit (DynamoDB) | OTel traces → CloudWatch | query tooling | the system-of-record trail itself |

**Target spec.** `openapi.json` exposes 4 read operations: `get_claim`, `list_claim_documents`, `get_document`,
`search_policy_clauses`. It has bearer security and the door's URL as the server. **Auth mode:** inbound CUSTOM_JWT
(the lab used AWS_IAM). Outbound uses the gateway role, with no stored credential.

**Why the lab's pattern doesn't fit us.** The lab's gateway signs callers in with IAM and injects ONE scoped API key
into every backend call, so the backend sees the bank's single badge. At AutoSure, scope is **per adjuster**. If
every call arrived under one credential, alice and carol would get the same answers, and the two-user test (this
milestone's acceptance criterion) would fail by construction. So:

1. **Read tools (the 4 above) may move to Gateway** only if the caller's own token reaches the door unchanged.
   Gateway validating it at the edge is good defense in depth; replacing it with a gateway credential is not
   acceptable. This must be verified against the AgentCore docs at `apply` time; until then they stay hand-built.
2. **Writes stay on the hand-built door:** `create_recommendation`, `create_escalation_ticket`, and confirm (which is
   never a tool). They carry idempotency keys, the M1 DecisionCard validation and the $25K authority check, and they
   need the delegated token's `act`/scope semantics.
3. **The webhook receiver stays hand-built.** Gateway is an inbound MCP surface, not a webhook endpoint.

**Recommendation:**
- **Pilot:** keep the hand-built door. It's about 600 legible lines that the CISO's team can read in one sitting
  (the W16 "procurement wants to see exactly what the door does" case).
- **Production at scale:** front the read tools with Gateway (edge JWT, managed transport, one place for every MCP
  client) **once** token pass-through is verified. Keep enforcement and audit in the door either way.

**Ladder** (`gateway_setup.py`, from the W16 lab):
- `plan` costs $0 and runs anywhere (evidence 11).
- `apply` → `invoke` → `destroy` need the deployed door, the Cognito ids and Susan's OK.
- `destroy` runs after every apply, so nothing burns while idle.
- The lab's READY-race fix is kept: the target is created only after the gateway reports READY.
