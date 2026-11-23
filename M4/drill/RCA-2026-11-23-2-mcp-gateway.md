# RCA-2 · 2026-11-23 · First deployed claim runs ended with no card: the gateway blocked the agents' token

**Severity:** SEV-2. Every claim on the newly deployed console failed. No wrong decision was made and no data was
exposed.
**Type:** a **real incident** (not staged), found by the client's first hands-on test of the deployed frontend.
**Owner:** Susan Wellington. **Status:** closed, all action items done.
**Companion to:** the staged drill in [RCA-2026-11-23.md](RCA-2026-11-23.md).

| | |
|---|---|
| Detected by | **the client**, in the browser ("both outcomes are the same, they just say done and nothing happens"). The alarm could not see it: the gateway refused with 401s, so the door saw no requests and no 5xx |
| User-facing impact | about 32 min: 4 claim runs (alice ×1, carol ×3) showed "done" and no card |
| **Time to verified recovery** | **31 min 38 s**, from the first failed run (01:59:50) to the client's verified run (02:31:28: alice approve $2,700, then carol refused at 02:32:08) |

## Timeline (UTC, from the DynamoDB audit trail and `/claimsense/frontend` logs)
- **01:23** · The frontend (console + orchestrator on ECS) went live. Its HTTPS, health and CloudFront-only checks
  passed. No claim had been run through it yet.
- **01:34–01:36** · First clicks happened before sign-in, so the orchestrator answered 401. The console **crashed**
  on that answer (`KeyError: 'kind'`). This was contributing issue A.
- **01:48** · Two sign-ins were refused because the passcode was mis-copied: its alphabet had look-alike characters
  (I/l/1, O/0) and punctuation. This was contributing issue B. A console fix and a new passcode alphabet were
  deployed.
- **01:58:18** · alice signed in through real Cognito.
- **01:59:50** · alice ran CLM-2024-1800. The run was accepted and the delegated token issued, but **no `mcp` audit
  row** appeared. The run ended with `KeyError: 'result'`.
- **02:00–02:01** · carol tried the same three times, with the same result.
- **~02:02** · The client reported the problem.
- **Diagnosis:** the incident was reproduced locally against the AWS door. `POST /mcp` answered **401
  `{"message":"Unauthorized"}`** from API Gateway, not from the door:
  - with alice's Cognito token: 200;
  - with the door's own delegated (OBO) token: 401.
- **Fix:**
  - `POST /mcp` became a route the **door** verifies itself. The door already refuses and audits none, forged and
    expired tokens before routing. Re-proved: no token 401, forged 401, delegated 200.
  - The orchestrator now turns a non-JSON-RPC refusal into a structured error.
  - The door and frontend were redeployed. The M3 route, Week 4 viewer and S3 checks passed on AWS.
- **02:31:12–02:31:28** · alice: 4 agents, the door returned the documents and clauses, the draft was posted,
  **approve $2,700**.
- **02:32:06** · carol: `get_claim` **deny** (not_entitled), no claim data. The client: "It WORKED!!!"

## Root cause
**An integration gap between two things that were each tested alone.**
- M3 proved the gateway's Cognito authorizer (every route, 150 bad credentials) and proved the door's token exchange
  (it *issues* a narrowed delegated token).
- No deployed check ever **used** that delegated token on `/mcp` through the gateway. In M3 the agents ran locally,
  against the local door, where there is no gateway.
- The gateway's authorizer only knows Cognito's signing keys, so it rejected the door's own tokens.

**Contributing:**
- the console crashed on a non-200 stream (A);
- the passcode was hard to copy (B);
- the orchestrator swallowed the gateway's non-JSON-RPC body (so "done" with no card, not an error).

**What went well:**
- it **failed closed**: no decision, no data, no spend;
- the audit trail showed exactly where the calls stopped (token exchange allowed, no `mcp` row);
- the fix needed no code change to the door's own checks.

## Action items (all done)
| # | Action | Where | Proof |
|---|---|---|---|
| 1 | `/mcp` verified by the door, not the Cognito authorizer | `M3/cloud/deploy.sh` (D-049) | no token 401 · forged 401 · delegated 200 on AWS |
| 2 | Gateway refusals become structured errors; console shows refusals, never crashes; Run disabled until signed in | `boundary_client.py`, console | the client's re-test |
| 3 | Passcode with no look-alike characters; pasted quotes and spaces forgiven | `frontend.py`, orchestrator | `M2/tests/test_demo_signin.py` |
| 4 | **New eval case:** the deployed route check **uses** the delegated token on `/mcp` and must get the claim back | `M3/evals/deployed_route_check.py` `[RCA-2]` | PASS now. It would have failed before the fix (401 from the gateway) |
| 5 | **Prevention:** the post-deploy smoke runs the agents' path too (token exchange, then `/mcp` `get_claim`), so a door release that breaks it rolls itself back | `M4/ops/door_smoke.py` | 5/5 PASS on the live door |

**Lesson for the handover:** prove the path the system actually takes in production (here: agent → gateway →
door with a delegated token), not only each hop on its own. Both RCAs end in the same place: the smoke test now
exercises what a real user and a real agent do.
