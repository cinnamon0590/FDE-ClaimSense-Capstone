# Escalation map

Two kinds of escalation: a **claim** that needs a person (every day, by design), and the **system** that needs a
person (incidents). Roles come from the M0 RACI.

## Claims: where each first decision goes
| The card says | Goes to | Who acts | How |
|---|---|---|---|
| **APPROVE / DENY** | the adjuster who opened it | **confirms or overrides** (an override needs a reason) | console: Confirm as drafted / Override |
| **FLAG_REVIEW → senior adjuster** (ambiguous cover, over the $25K authority limit, missing documents, theft without a police report) | the senior adjusters' queue | Senior Adjuster / Team Lead | console queue tab |
| **ROUTE → fraud investigator** | SIU (carol's group) | fraud investigator | the claim is handed off: only SIU and senior adjusters can open it |
| **ROUTE → injury specialist / total-loss appraiser** | that specialist group | specialist | same hand-off |
| **Guardrail hold** (injection, unsure model, two drafts disagree) | senior adjuster | Senior Adjuster | the card says why; the raw text is never shown to the model |
| **A person suspects fraud the co-pilot didn't flag** | SIU | any adjuster entitled to the claim | **🚩 Escalate to SIU (manual)** or `M4/ops/escalate.py` ([runbook §3](../RUNBOOK.md#3--escalate-a-flagged-claim-manually)) |
| **Unavailable** ("claim systems unavailable, nothing decided") | nobody: retry shortly | the adjuster | if it persists over 10 minutes, it's a SEV-2 below |

## System: severities and who owns them
| Severity | Examples | Detected by | First responder | Then | Target |
|---|---|---|---|---|---|
| **SEV-1** | wrong data returned to a user; an agent decision that bypassed confirmation; a secret exposed | audit review, a user report, `door_smoke` | on-call engineer: **stop the frontend** (`rollback.py` to the last good, or `frontend.py destroy`) | **Security / Compliance** (hard veto owner) within 1 hour; Claims Director the same day | contain < 1 h; RCA in 2 days |
| **SEV-2** | no claim can be processed (door down, gateway, model provider) | **the alarm** (SNS email), the continuous eval, users | on-call engineer → [runbook §5](../RUNBOOK.md#5--door-error-rate-alarm) (roll back first) | IT / Cloud if it's AWS-side; Claims Director if over 1 hour | verified recovery < 30 min (drill: 4 min 39 s) |
| **SEV-3** | eval pass below SLO; hold spike; cost spike; one adversarial failure in the daily sample | continuous eval, dashboard, monthly review | claims-ops lead → [runbook §6](../RUNBOOK.md#6--eval-pass-rate-below-slo) | Senior Adjuster (labels); engineer (model/prompt) | within the week |
| **SEV-4** | a user can't sign in; a single odd card | a user | the adjuster's team lead | [runbook §1](../RUNBOOK.md#1--add-or-remove-a-user) | same day |

**Paging path:** CloudWatch alarm `ClaimSense-door-error-rate` → SNS `claimsense-alerts` → the on-call email list
(add yours on day 1). There is no Slack page on AWS yet. The door's `notify_oncall` tool exists and is tested
locally; connect it to AutoSure's Slack through the door when ready.

**Who decides go / no-go after a SEV-1:** the Claims Director (Accountable for go-live), with Security /
Compliance able to block.
