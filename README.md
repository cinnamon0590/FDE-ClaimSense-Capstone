# ClaimSense AI: FDE capstone

A claims-adjudication co-pilot for a motor insurer. Given a claim, it returns a first decision
(approve / flag for review / route to a specialist / deny), the reasoning, and citations to the
evidence. It refuses users who aren't entitled to the claim.
**A licensed adjuster confirms every outcome.**

Fixed constraints (from the client brief):
1. Identity, access control, policy dates and money are deterministic code, never a model.
2. Judgment is delegated to a model and is always cited.
3. Synthetic data only.

Stack standard: OpenAI Agents SDK · searchable policy-clause corpus · own authenticated service ·
containers · CI with an evaluation gate · AWS · Python 3.12+.

## Milestones

Folders are numbered by course week (M0 = W13 … M4 = W17). The client brief numbers the same
stages Milestone 1–5, which are capstone Weeks 1–5. CI (`.github/workflows/eval-gate.yml`) validates
the eval suite on every push from M0, and from M2 it gates the build.

| Folder | Course week | Brief milestone | Theme | Status |
|---|---|---|---|---|
| [`M0/`](M0/README.md) | W13 | Milestone 1 | Discovery & scoping: charter, RACI, success criteria, DECISIONS, 20 eval cases | Done |
| [`M1/`](M1/README.md) | W14 | Milestone 2 | SoW, pricing, architecture, risk register, system contracts, data shapes, cloud account | Done |
| [`M2/`](M2/README.md) | W15 | Milestone 3 | Four agents on the OpenAI Agents SDK, cited retrieval, containers (one command), CI eval gate that blocks the image push | Done |
| [`M3/`](M3/README.md) | W16 | Milestone 4 | The governed MCP door: deny-by-default grants + entitlement before any agent, auth on every route, two-user test, append-only audit; 4th backend + webhooks; RFC 8693 OBO | Done |
| [`M4/`](M4/README.md) | W17 | Milestone 5 | 150-case eval suite (150/150 live ×3, adversarial 45/45), second grader, dashboard and alarm, **deployed console: https://d2jfndltae6j40.cloudfront.net**, incident drill + RCA; next: runbook, handover | In progress |

**The agents, in one place:** [`M2/AGENTS.md`](M2/AGENTS.md) describes every ClaimSense agent in
[Salesforce Agent Script](https://developer.salesforce.com/docs/ai/agentforce/guide/agent-script.html) terms: what
code decides (`->`) versus what the model reasons (`|`), the tools each agent may use, the fixed flow of control,
escalation to humans, and the adjuster each call runs as.

## Working locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # python-docx (Word templates only)
```

Almost everything (validators, scorer, tests, pricing, fixtures) is standard-library Python and runs
with any Python 3.10+ for $0. CI runs every check on Python 3.12 (the brief's minimum) and 3.14 (the project venv).

Final submission (end of W17) is graded out of 100: framing 15 · design 15 · working system 25 ·
trust boundary 20 · evidence & handover 25.
