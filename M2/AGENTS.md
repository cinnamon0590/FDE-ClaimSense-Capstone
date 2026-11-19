# ClaimSense agents, in Agent Script terms

> This file describes the **product's AI agents** (what they do, what they may touch, what code decides for them).
> It is not a set of instructions for coding assistants.

ClaimSense's agents run on the **OpenAI Agents SDK** in Python, not on Salesforce Agentforce. This page maps them to
the conventions of [Salesforce Agent Script](https://developer.salesforce.com/docs/ai/agentforce/guide/agent-script.html)
(blocks, deterministic logic `->` vs prompt text `|`, variables, tools, transitions, escalation, running user) so the
whole design can be read in one place. Everything below links to the code that enforces it. All data is synthetic.

## The agent (`config` / `system` / `access`)

| Agent Script | ClaimSense |
|---|---|
| `config.developer_name`, `description`, `role` | **ClaimSense**: an AutoSure motor-claims co-pilot that drafts ONE recommendation per claim for a licensed adjuster, who always confirms or overrides it. |
| `agent_version` | `PROMPT_VERSION` = `m2-v9` ([`claimsense/__init__.py`](claimsense/__init__.py)), stamped on every run and replay file. |
| `access.default_agent_user` (the agent runs as a user whose permissions decide data access) | **Every call runs as the signed-in adjuster**, never a shared agent account. Each agent has its own identity for the audit (`agent:document-intake`, `agent:coverage-check`, `agent:claim-assessment`, `agent:decision-draft`, `agent:ask-claimsense`), and in M3 it carries a 5-minute delegated token (RFC 8693: Keycloak locally, the door's own exchange on AWS). The governed door ([`../M3/door`](../M3/door)) enforces that adjuster's **grants** (`grants.json`, deny-by-default) and **entitlement**, and audits every call. |
| `system` messages (welcome / error) | The console's messages; the fail-closed answer `FAIL_CLOSED` in [`claimsense/assistant.py`](claimsense/assistant.py). |
| `runtime.groundedness` / `citation` | Code-owned guardrails G1–G7 ([`claimsense/guardrails.py`](claimsense/guardrails.py), M1 spec): a cited clause must have been retrieved in this run; quotes come from the retrieved text, never a paraphrase. |

## Variables (state held by code, not by model memory)

`RunCtx` ([`claimsense/tools.py`](claimsense/tools.py)) carries the run's state: `user_id`, `claim_id`, the claim and
policy as returned by the door, `documents`, `retrieved_clause_ids` and `retrieved_chunks`, `quarantined` chunks, PII
and injection flags. Code computes the rest **before** any agent reasons ([`claimsense/deterministic.py`](claimsense/deterministic.py)):

| Variable | Set by | Meaning |
|---|---|---|
| `computed` | `compute()` | net payable, deductible, repair-to-ACV ratio, authority limit, policy-term check. **The only money an agent may mention.** |
| `missing` | `missing_documents()` | the required-document checklist per loss type |
| `verified_facts` | `verified_facts()` | statements code has established; every prompt says to treat them as true |
| `coverage_questions` | `coverage_questions()` | what Coverage must look up |

## Flow of control (`start_agent`, transitions)

There is **no LLM router**. ClaimSense processes one claim, not an open conversation, so the order is fixed in code
([`claimsense/pipeline.py`](claimsense/pipeline.py), decision D-011). In Agent Script terms, `start_agent` does only
deterministic work and every transition is a fixed `@utils.transition to`, never a tool the model may choose:

```
start_agent (code)   -> the door: entitlement for this adjuster        refused? stop: no agent runs, $0, audited
  -> Document Intake -> compute(), missing_documents(), verified_facts()   (code overrides the model's checklist)
  -> Coverage Check
  -> Claim Assessment -> code re-applies the fraud rule and route_priority() to the model's flags
  -> Decision Draft  [-> a second, independent Decision Draft when the consistency check is on]
  -> code: guardrails G1-G7, the M1 schema  -> a draft card for the adjuster (never final, never paid)
```

Transitions are one-way. Each agent sees only the structured outputs of the steps before it, never another agent's prompt.

## The agents (`subagent` blocks)

Each agent has a strict typed output (`output_type`), `temperature=0`, and only the tools it needs, with
`tool_choice="required"` when it has any ([`claimsense/agents_def.py`](claimsense/agents_def.py)).

### Document Intake (`agent:document-intake`, fast model)
- **description:** report the claim file's facts only; no coverage decision.
- **actions (tools):** `get_claim_file` only, called exactly once. The claim id is bound by code (`with`), never chosen by the model.
- **`->` logic (code):** the door checks entitlement first; the claim file is sanitised (PII masked, other claims' ids masked, injection screened) before the model sees it; afterwards code **overwrites** `missing_documents` with the rule table whenever they differ (logged as `code_override`).
- **`|` prompt:** list documents on file, injury and commercial-use indicators, material inconsistencies (quoting dates), a two-sentence summary.
- **output:** `IntakeResult`. **Guardrails:** `untrusted_input_scan` (input), `intake_injection_tripwire` (output).

### Coverage Check (`agent:coverage-check`, smart model)
- **description:** decide whether the policy covers this loss, grounded only in retrieved clauses.
- **actions (tools):** `search_clauses` only (up to six searches), through the door's `search_policy_clauses` (granted, audited, provenance-checked: unprovenanced chunks are quarantined).
- **`->` logic (code):** supplies `verified_facts`, `computed` and `coverage_questions`; the dates and money are never recomputed by the model.
- **`|` prompt:** search once per coverage question; cite the clause that decides the outcome; `covered` / `not_covered` / `ambiguous`.
- **output:** `CoverageResult`. **Guardrail:** `coverage_citation_tripwire` (a cited id must have been retrieved).

### Claim Assessment (`agent:claim-assessment`, fast model)
- **description:** assess fraud, total loss and injury, and name the specialist route.
- **actions (tools):** none.
- **`->` logic (code):** after the model answers, code sets `fraud_suspected` (score >= 0.7 or any inconsistency), `total_loss` (ratio >= 1.0) and the route by `route_priority()` (fraud, then injury, then total loss), overriding the model where a rule decides.
- **`|` prompt:** the same rules in words, so the model's reasoning agrees with the code.
- **output:** `AssessmentResult`.

### Decision Draft (`agent:decision-draft`, smart model)
- **description:** draft ONE recommendation for the adjuster.
- **actions (tools):** none; it works only from the earlier steps' outputs.
- **`|` prompt:** the five ordered rules (deny / flag_review / route / flag_review / approve) and the citation and money rules.
- **`->` logic (code):** optional second opinion (`decision_check`, the same prompt run independently): if the two drafts disagree, the claim goes to a senior adjuster.
- **output:** `DecisionDraft`. **Guardrail:** `decision_safety_tripwire` (only `computed.net_payable`, no other claim's id, never "final" or "paid").

### Ask ClaimSense (`agent:ask-claimsense`) and the Coverage specialist ([`claimsense/assistant.py`](claimsense/assistant.py))
- **description:** the adjuster's follow-up chat about ONE drafted claim. It explains; it never decides.
- **actions (tools):** `get_draft`, `get_claim_file`. **The one model-chosen transition:** a handoff to the **Coverage specialist** (`transfer_to_coverage_specialist`, i.e. a subagent offered as a tool), which may only call `search_clauses`.
- **`->` logic (code):** entitlement is checked on every turn; the conversation is an SDK session on the `/state` volume.
- **guardrail:** an answer citing a clause nobody retrieved, or naming another claim, is withheld and replaced by `FAIL_CLOSED`.

## Escalation (`@utils.escalate`)

Code, never the model, hands a claim to a person ("senior adjuster (human)" events in [`claimsense/pipeline.py`](claimsense/pipeline.py)):
- an input or output guardrail trips: the run stops and a hold card is issued (`guardrail_hold`);
- the Decision Draft disagrees with itself (`consistency_hold`);
- the model fails, the budget cap is hit, or the output is malformed: a code-built `fallback_card` from the rule table (`fallback`);
- the draft itself routes to a specialist or flags review (ambiguous coverage, over the authority limit, missing documents).

M3 adds escalation **through the door**: an SIU ticket (`create_escalation_ticket`) and an on-call Slack page
(`notify_oncall`), each granted, idempotent and audited.

## Never delegated to any agent

Confirming a recommendation, reading the audit trail and receiving system webhooks are not tools of any agent and
cannot be put in a delegated token (`NEVER_DELEGATED` in [`../M3/door/claimsense_door/obo.py`](../M3/door/claimsense_door/obo.py)).
A human adjuster confirms.

## Versioning and tests

- **Release gate:** 40 labelled cases ([`evals/cases-m2.json`](evals/cases-m2.json)) must pass with **live** models at >= 90%; CI runs it on every merge to `main` and pushes the tested image ([`../.github/workflows/eval-gate.yml`](../.github/workflows/eval-gate.yml)).
- **Per-agent evals** against signed-off labels ([`evals/agent_evals.py`](evals/agent_evals.py), [`evals/agent-labels.json`](evals/agent-labels.json)); guardrail fuzzing ([`evals/fuzz_guardrails.py`](evals/fuzz_guardrails.py)).
- **Replay brain:** recorded model outputs per `PROMPT_VERSION`, so CI tests every agent path at $0.
- **Access:** the two-user test and the route checks ([`../M3/evidence`](../M3/evidence)).

**Keep this file in sync** whenever an agent, a tool, a prompt rule or a deterministic override changes.
