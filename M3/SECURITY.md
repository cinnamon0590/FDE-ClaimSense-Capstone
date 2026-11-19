# SECURITY: the trust boundary (M3)

## Where each control lives

| Crossing | Control | Enforced by | Can a prompt injection beat it? |
|---|---|---|---|
| browser/client → any route | bearer token verified **before routing** (401 + audit) | door and orchestrator middleware; API Gateway JWT authorizer on AWS | no |
| orchestrator → agents | RFC 8693 exchange: a 5-minute delegated token, narrowed scope, `act` = the agent | `/oauth/token` | no |
| agent → data | **action gate** (`grants.json`, deny-by-default) → **record gate** (`entitled()`) | the door (`GrantedBoundary._authorize`) | no |
| agent → model context | G1/G1b injection screening, PII masking, G2 provenance quarantine (at the door for KB search) | M2 guardrails | partly (in-scope bad *behavior* is W17's job) |
| draft → decision | human-only confirm, the $25K authority limit, numbers re-derived by code | the door (M1 rules) | no |
| ticketing → door | HMAC-SHA256 signature, 5-minute window, `event_id` dedupe, `seq` order; one grant | `/webhooks/ticketing` | no |
| everything | an append-only audit row per call (user, action, resource, decision, reason, channel) | `claimsense/audit_trail.py` | no |

## Secrets
None are in the repo, an image, compose, or the logs. Where each one lives:
- **Dev issuer and OBO signing keys:** generated on the state volume (0600).
- **Ticketing API credential and webhook key:** on a private secrets volume (0600, exclusive create).
- **AWS:** Cognito holds identities; the synthetic users' passwords exist only in `~/.claimsense/` on the deployer's
  machine.
- **Evidence files:** tokens are redacted (`Bearer <redacted JWT>`).

## Known limits (honest)
- **A borrowed token is not stopped at the door.** The audit attributes every action to the token's owner, tokens
  expire (1 h ID, 5 min delegated), and revoking the user cuts them all off.
- **An injected instruction that stays *in scope*** (for example, "state this deadline confidently") passes every
  access gate. Gates govern access, not behavior. That's W17: evals, output guardrails and the incident drill.
- **The deployed function runs with reserved concurrency 1** (state in `/tmp`). DynamoDB-backed state is M4 work.
