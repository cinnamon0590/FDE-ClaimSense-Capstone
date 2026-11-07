# M1: SoW, pricing & solution architecture (course Week 14)

> **Naming:** the ClaimSense brief calls this **"Milestone 2 — Statement of work, pricing and > architecture (Week 2)"**. This repo numbers milestones by course week: M0 = W13, **M1 = W14**,
> M2 = W15, M3 = W16, M4 = W17.

Goal: turn discovery into a contract, a price and a design detailed enough to build from, with the
boundary between deterministic code and model judgment made explicit.

## Deliverables: the union of every source

Where sources asked for different amounts, the larger requirement is delivered.

| # | Deliverable | Required by | Files | Beyond the requirement |
|---|---|---|---|---|
| 1 | **Statement of work, 2 pages:** scope, acceptance criteria, IP and data-handling terms, five-week timeline | M1 guidelines · brief M2 · class (criteria = M0 anchors, "Accepted when", a zero-harm line) · **SoW template** | [`1-statement-of-work.docx`](1-statement-of-work.docx) (course template, print-checked in Word at **2 pages**) · [`1-statement-of-work.md`](1-statement-of-work.md) | 8 acceptance criteria incl. the brief's own acceptance tests; each says who counts it |
| 2 | **Architecture diagram:** every data flow labelled, code/model boundary explicit | M1 guidelines · brief M2 · class (five layers, **stack matrix with flip condition**) | [`2-architecture/architecture.md`](2-architecture/architecture.md) · [`architecture.png`](2-architecture/architecture.png) / [`.svg`](2-architecture/architecture.svg) | 19 labelled flows, each mapped to a trust boundary, control and questionnaire item; deployment view; topology decision; what breaks first at scale |
| 3 | **Pricing model** with assumptions stated | M1 guidelines · brief M2 · class (rationale, **who counts the outcomes**) · **Pricing template** | [`3-pricing-model.docx`](3-pricing-model.docx) (course template) · [`3-pricing-model.md`](3-pricing-model.md) · calculator [`tools/pricing.py`](tools/pricing.py) | 4 models compared; sensitivity; margin and revenue-per-engineer checks; Phase 2 outcome option |
| 4 | **Risk register:** likelihood, impact, mitigation | M1 guidelines (5) · class notes (**≥ 6**, data access on top) | [`4-risk-register.md`](4-risk-register.md) | **8 risks**, owners, early warnings, proof per risk, heat map, re-plan triggers |
| 5 | **Typed contracts for all 3 systems** + idempotency rules for writes | M1 guidelines · brief M2 | [`5-system-contracts/contracts.md`](5-system-contracts/contracts.md) · [`schemas/`](5-system-contracts/schemas/) · [`contracts.py`](5-system-contracts/contracts.py) | **Executable spec:** reference boundary + **17 contract tests** (idempotent replay, conflict, human-only confirm, anti-enumeration, audit, retry) |
| 6 | **Synthetic data shapes** for claims, policies, documents | M1 guidelines · brief M2 | [`6-synthetic-data/data-shapes.md`](6-synthetic-data/data-shapes.md) · [`schemas/`](6-synthetic-data/schemas/) · [`fixtures/`](6-synthetic-data/fixtures/) | Fixtures **generated from the M0 eval cases** (one source of truth); clause corpus with provenance hashes; users; validator |
| 7 | **Cloud account provisioned**, resources evidenced | **brief M2** (not in the M1 guidelines) · class ("AWS sandbox confirmed") · Submission 1 | [`7-cloud/`](7-cloud/README.md) · [`evidence/inventory-2026-11-05.txt`](7-cloud/evidence/inventory-2026-11-05.txt) · [console screenshot](7-cloud/evidence/aws-console-resource-group-2026-11-05.png) | Idempotent provision, inventory and teardown scripts; every resource tagged; budget guardrail; account ID masked |

**Added Features / Extra Credit**
- [`2-architecture/guardrails.md`](2-architecture/guardrails.md): a catalogue of **every guardrail** (content, access, data, release, cloud), each with trigger, action, failure prevented and proof. The content guardrails (injection scan, provenance quarantine, PII masking, code-owned numbers, citation check, auto-decision block, cross-record block) are **executable now**: [`reference_guardrails.py`](2-architecture/reference_guardrails.py) with **16 tests** that drive them with the M0 adversarial cases and grade the output with the M0 eval scorer.
- [`security-questionnaire.md`](security-questionnaire.md) and [`.docx`](security-questionnaire.docx) (course template): all 15 vendor-security items answered, each with control, location and proof. This was the Week 14 class centrepiece.
- [`DECISIONS.md`](DECISIONS.md): nine new dated decisions (D-008 to D-016). D-001 to D-007 are in M0.
- [`tools/stack_matrix.py`](tools/stack_matrix.py) and [`tools/topology.py`](tools/topology.py): the class decision tools, re-scored for AutoSure. Outputs are in [`tools/output/`](tools/output/).
- The CI workflow now also validates the M1 data and runs the contract tests on every push.

## Headline numbers

| | |
|---|---|
| Expected cost | **$163,200** (84 FDE-days × $1,800 + $12,000 overhead; ≈ 3.4 FDE over 5 weeks) |
| Price | **$204,000 fixed floor + up to $36,000 acceptance bonus**; expected $231,000, 29.4% margin |
| Guardrails | 7 content + 7 access guardrails executable (16 + 17 tests); cloud guardrails live (MFA admin, encryption, budget alerts) |
| Top risk | **R1** Security / cloud-access delay (score 20), mitigated by synthetic data and early consultation |
| Stack | OpenAI Agents SDK + OpenAI API on AWS (4.65); flips to Bedrock if an external model provider is forbidden |
| Cloud | 9 tagged resources + budget + `ClaimSense-pilot` Resource Group live in us-east-1, at about $0.40/month while idle |

## Verify (project venv: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`)

```bash
cd M1/6-synthetic-data && python3 -I generate_fixtures.py && python3 -I validate_data.py
cd ../5-system-contracts && python3 test_contracts.py -v          # 17 tests
cd ../tools && python3 -I pricing.py && python3 -I stack_matrix.py && python3 -I topology.py
cd ../7-cloud && ./inventory.sh                                     # needs `aws login`
# Word documents (need python-docx) — template path is the course's Week 14 folder:
../../.venv/bin/python fill_sow_template.py <SoW_Template.docx> ../1-statement-of-work.docx
```

## Notes for the reviewer
- **All data is synthetic** (brief constraint #3). AutoSure Insurance is the instructor's worked-example client.
- Figures marked **(A)** are discovery assumptions; rule-table figures are measured (M0 baseline).
- **Follow-ups (owner actions):** none outstanding. Budget alerts are verified active; the CLI runs as the MFA-protected IAM admin `FDE_PROJECT_ADMIN`, not root.
