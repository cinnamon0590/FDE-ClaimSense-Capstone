# Artefact index: every engagement document, M0 to M4

Paths are from the repo root. "Evidence" folders hold the runs behind each claim. They are never edited by hand:
every file there was written by a command shown in its first lines.

## M0 · Discovery and scoping (Week 1)
| Artefact | Path | What it settles |
|---|---|---|
| Engagement charter | [`M0/1-engagement-charter.md`](../../M0/1-engagement-charter.md) | the problem, the three client systems and their integration points |
| Stakeholders and RACI | [`M0/2-stakeholders-raci.md`](../../M0/2-stakeholders-raci.md) | approver, reviewer, daily user, who can block rollout; cadence of contact |
| Success criteria | [`M0/3-success-criteria.md`](../../M0/3-success-criteria.md) | SC-1..SC-5 with the measured rule-table baseline; the origin of every SLO |
| Discovery notes, charter email | [`M0/discovery-notes.md`](../../M0/discovery-notes.md), [`M0/charter-confirmation-email.md`](../../M0/charter-confirmation-email.md) | what the client said, and what they confirmed |
| Seed eval set (20) | [`M0/evals/`](../../M0/evals/README.md) | the first golden cases and the scoring harness |
| Decisions D-001..D-007 | [`M0/DECISIONS.md`](../../M0/DECISIONS.md) | early architecture choices, with rejected alternatives |

## M1 · SoW, pricing and architecture (Week 2)
| Artefact | Path | What it settles |
|---|---|---|
| Statement of work | [`M1/1-statement-of-work.md`](../../M1/1-statement-of-work.md) (+ `.docx`) | scope, acceptance criteria, IP and data terms, timeline |
| Architecture (designed + **as built**) | [`M1/2-architecture/architecture.md`](../../M1/2-architecture/architecture.md) §10, [diagram](../../M1/2-architecture/architecture-as-built.png) | every data flow; the code/model boundary; design vs as built, row by row |
| Guardrails | [`M1/2-architecture/guardrails.md`](../../M1/2-architecture/guardrails.md) | G1–G8: what each catches, where it runs, what it prevents |
| Pricing model | [`M1/3-pricing-model.md`](../../M1/3-pricing-model.md) (+ `.docx`) | price, assumptions, who counts the outcomes |
| Risk register | [`M1/4-risk-register.md`](../../M1/4-risk-register.md) → [looked back on](../risk-retrospective.md) | 8 risks; what happened to each |
| System contracts | [`M1/5-system-contracts/contracts.md`](../../M1/5-system-contracts/contracts.md) | typed inputs and outputs for the 3 systems; idempotency for writes |
| Synthetic data | [`M1/6-synthetic-data/`](../../M1/6-synthetic-data/data-shapes.md) | shapes, generator, validator; the directory (`source/users.json`) and corpus (`source/clauses.json`) |
| Security questionnaire | [`M1/security-questionnaire.md`](../../M1/security-questionnaire.md) | the client's security answers |
| Cloud account | [`M1/7-cloud/`](../../M1/7-cloud/README.md) | the provisioned resources, tagged, with a budget alarm |
| Decisions D-008..D-016 | [`M1/DECISIONS.md`](../../M1/DECISIONS.md) | |

## M2 · Production agents (Week 3)
| Artefact | Path | What it settles |
|---|---|---|
| The pipeline | [`M2/README.md`](../../M2/README.md), [`M2/AGENTS.md`](../../M2/AGENTS.md) | 4 agents + Ask ClaimSense on the OpenAI Agents SDK, strict typed outputs, each agent's contract |
| CI eval gate | [`M2/CI-GATE.md`](../../M2/CI-GATE.md), [`.github/workflows/eval-gate.yml`](../../.github/workflows/eval-gate.yml) | a failing gate blocks the image push |
| Security model | [`M2/SECURITY.md`](../../M2/SECURITY.md) | identity, RBAC, data handling in the pipeline |
| Runbook (failure modes) | [`M2/RUNBOOK.md`](../../M2/RUNBOOK.md) | model outage, restarts, holds, cost, key rotation, model snapshots |
| Cost tables | [`M2/evals/cost-table-live.md`](../../M2/evals/cost-table-live.md) | tokens and $ per agent |
| Decisions D-017..D-035, D-045 | [`M2/DECISIONS.md`](../../M2/DECISIONS.md) | |

## M3 · Integration and access control (Week 4)
| Artefact | Path | What it settles |
|---|---|---|
| The governed door | [`M3/README.md`](../../M3/README.md) | MCP + REST, auth before routing, grants, entitlement, audit; deployed on AWS |
| Security and RBAC matrix | [`M3/SECURITY.md`](../../M3/SECURITY.md) | who can do what; how each route is guarded |
| Two-user test (offline, stack, AWS) | [`M3/evidence/`](../../M3/README.md) 02, 04, 13 | same claim, two users, two different answers, matching audit rows |
| OBO with a real IdP; Gateway plan | [`M3/keycloak/`](../../M3/keycloak/README.md), [`M3/agentcore_gateway/`](../../M3/agentcore_gateway/README.md) | delegated tokens; the managed-door decision |
| Decisions D-036..D-044 | [`M3/DECISIONS.md`](../../M3/DECISIONS.md) | |

## M4 · Evaluation, observability, reliability and handover (Week 5)
| Artefact | Path | What it settles |
|---|---|---|
| Overview and status | [`M4/README.md`](../README.md) | every M4 deliverable with its evidence |
| 150-case suite + gate | [`M4/evals/`](../evals/label-review.md), evidence `release-gate-live.txt` | the contract (see [eval-contract.md](eval-contract.md)) |
| Held-out set | [`M4/evals/holdout-label-review.md`](../evals/holdout-label-review.md), evidence `holdout-live.txt` | 19/20 on claims never tuned against |
| Second grader | [`M4/evals/promptfoo/`](../README.md#2--the-second-grader-promptfoo-d-047) | Promptfoo agreement + rubric; judge κ 0.95 |
| Dashboard, alarm, continuous eval | [`M4/ops/`](../README.md#3--observability-dashboard-alarm-continuous-eval-d-048) | the operating signals |
| Deployed frontend | [`M4/cloud/frontend.py`](../cloud/frontend.py) | console + orchestrator on ECS behind CloudFront |
| Incident drill + RCAs | [`M4/drill/`](rca-template.md#incident-archive) | a staged and a real incident, both recovered |
| Runbook | [`M4/RUNBOOK.md`](../RUNBOOK.md) | the six procedures, each executed |
| Decisions D-046..D-053 | [`M4/DECISIONS.md`](../DECISIONS.md) | |
