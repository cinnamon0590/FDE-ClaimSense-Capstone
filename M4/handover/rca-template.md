# RCA template (one page) and the incident archive

Write one for every SEV-1 or SEV-2, and for any incident over 15 minutes. One page, written in 2 days, blameless,
with numbers. Copy the block below into `M4/drill/RCA-<date>-<slug>.md`.

```markdown
# RCA · <date> · <what users experienced, in one line>

**Severity:** SEV-n · **Type:** real | staged drill · **Owner:** <name> · **Status:** open | closed

| | |
|---|---|
| Detected by | <alarm / canary / continuous eval / a user>. Did the alarm fire? If not, why not? |
| User-facing impact | <who, what they saw, for how long, how many claims>. Any wrong decision or data exposed? |
| **Time to verified recovery** | <first failure> → <the moment a check proved it fixed>, in minutes and seconds |

## Timeline (UTC; from the audit trail, logs and alarm history, not from memory)
- hh:mm:ss · <event>

## Root cause and contributing factors
The trigger; why it wasn't caught earlier (each check that missed it); what made it worse.
**What went well:** <fail-closed held? rollback fast?>

## Action items
| # | Action | Where | Proof it's done |
|---|---|---|---|

**New eval case it spawned:** <id, file>. It must fail on the pre-fix code and pass now.
```

**Rules:**
- **"Verified recovery" means a check passed,** not that someone thinks it's fixed: the door smoke, the deployed
  route check, a real claim deciding correctly.
- **Every RCA adds a case** that fails on the old code.
- **The timeline comes from the audit trail.** DynamoDB `claimsense-audit` and the `AUDIT` lines in
  `/aws/lambda/claimsense-door` carry user, action, resource and decision for every call.

## Incident archive
| Date | RCA | Type | What happened | Time to verified recovery | Case it spawned |
|---|---|---|---|---|---|
| 2026-11-23 | [The door lost its document store after a bad config release](../drill/RCA-2026-11-23.md) | staged drill (×2) | a console config change pointed the door at the wrong bucket; the alarm was blind (drill 1), then fired at +2 min 22 s (drill 2) | 481 s → **279 s** | IC-001 (`M2/tests/test_incident_door_down.py`) |
| 2026-11-23 | [First deployed claim runs ended with no card](../drill/RCA-2026-11-23-2-mcp-gateway.md) | **real** | the gateway rejected the agents' delegated token on `/mcp`; found by the client | **31 min 38 s** | `[RCA-2]` in `M3/evals/deployed_route_check.py` |
| 2026-11-23 | Held-out HO-20 (no RCA: no outage) | real defect | international PII reached the model unmasked | n/a (fixed before any real file) | `M2/tests/test_holdout_ho20_pii.py` |
