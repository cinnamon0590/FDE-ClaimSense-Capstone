# Risk register, looked back on (M4)

The M1 register ([`../M1/4-risk-register.md`](../M1/4-risk-register.md)) was written in Week 2, before anything was
built. This page checks it against what actually happened in Weeks 3–5. For each risk: did it occur, did the
mitigation hold, and where is the evidence. The failures the register **didn't** anticipate are listed too: they're
the more useful half.

| Risk (M1) | Did it happen? | Did the mitigation hold? | Evidence |
|---|---|---|---|
| **R1** Security review or cloud permissions delay integration | **Partly, as friction:** expiring console sessions, a fresh account missing the ECS service-linked role (first frontend deploy failed), App Runner lacking WebSockets (switched to ECS + ALB + CloudFront) | **Yes.** Synthetic data meant no security review blocked anything; each blocker cost minutes, not weeks | D-049; `M4/cloud/frontend.py` creates the role |
| **R2** Ungrounded or poisoned citations | **Staged, never in production:** the planted chunk (CS-020), a clause edited in S3, 3 citation-forgery cases | **Yes:** quarantined at the door (G2) every time; citations ⊆ retrieved (G5) | M3 evidence 22; 150/150 live; corpus 2024.2 served `0 quarantined` |
| **R3** Model verdicts silently replaced by the fallback during an outage | **Yes, in a related form:** the door outage in the drill. Nothing was replaced by rules, but the adjuster was told "**refused**" | **Partly.** Fail-closed held; the label was wrong. Fixed: an outage is now `unavailable` (D-050) | `incident-drill-1.txt` → `incident-drill-2.txt`; IC-001 |
| **R4** Adjusters don't trust the drafts | **Not measurable on synthetic data.** Proxy: confirmable-as-written 100% on the 150 and 10/10 on the held-out set; the client's own hands-on test passed | Open: measure the real confirmation rate (SC-3) in the first month | "What to watch monthly" (handover) |
| **R5** Cross-record leakage | **Never:** 11 leakage cases + 1 held-out, all blocked; the two-user test passes on AWS | **Yes:** entitlement in code before any agent; other claim ids masked (G7) | M3 evidence 13, 21; HO-17 |
| **R6** Latency or cost overrun | **No:** p95 17 s (target < 90 s); $0.025 per claim; dev spend ≈ $70 across 5 weeks | **Yes:** small model on volume steps, pinned snapshots, replay brain in CI | `holdout-live.txt`; dashboard |
| **R7** Synthetic data doesn't reflect real claim files | **Yes:** the held-out set's HO-20 had a UK passport and mobile. The PII masker only knew US formats, so they reached the model unmasked | **Partly:** caught by the held-out set before any real file; fixed and pinned by tests (D-052) | `holdout-live.txt` (19/20); `holdout-ho20-postfix.txt` |
| **R8** Scope creep (auto-payment, letters, more systems) | **Only as attacks:** "pay now", "auto-settle" and "mark final" appear as forced-auto-decision cases | **Yes:** a person confirms every outcome; confirm can't be delegated to an agent | 10 + 1 held-out forced-auto-decision cases, all pass |

## What the register did not anticipate
| What happened | Found by | Now covered by |
|---|---|---|
| A configuration change made **outside the release path** took the door down; the **alarm was blind** to a door that can't start | the staged drill ([RCA-1](drill/RCA-2026-11-23.md)) | alarm on the edge 5xx too; post-deploy smoke with automatic rollback; "deploy.sh only" rule |
| **An integration gap:** the gateway rejected the agents' delegated token on `/mcp`; each hop had been tested alone | the client's first hands-on test ([RCA-2](drill/RCA-2026-11-23-2-mcp-gateway.md)) | the deployed route check and the smoke test now use the delegated token on `/mcp` |
| **An operations path that never ran:** escalations queued while ticketing was down were never delivered | testing the runbook (D-051) | delivery on health check, reads and new escalations; a regression test |
| **Tests hard-coding today's data** ("12 clauses") broke on the first corpus update | testing the runbook + CI (D-051) | counts derived from the corpus |

**Proposed additions to the register for the client's team:**
- **R9 · Production path not exercised end to end** (L3 × I4). Mitigation: post-deploy smoke as a real user *and* a
  real agent. Early warning: a deploy whose smoke is only `/healthz`.
- **R10 · Operations code that only runs during failures** (outbox, rollback, off-boarding) (L3 × I3). Mitigation:
  every runbook procedure is executed on a schedule (quarterly game day). Early warning: a procedure whose
  "Tested" line is older than a quarter.
