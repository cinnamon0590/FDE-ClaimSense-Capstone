# M1 Deliverable 6: Synthetic data shapes (claims, policies, documents)

**Engagement:** ClaimSense AI · AutoSure Insurance (motor) · **Date:** 2026-11-05

> **All data is synthetic.** Names, VINs and IDs are generated, and no record describes a real
> person or vehicle (brief constraint #3). Every fixture file carries `"synthetic": true`, and the
> validator fails if it's missing.

## Design: one source of truth

The fixtures are **generated from the M0 eval cases** ([`../../M0/evals/cases.json`](../../M0/evals/cases.json))
by [`generate_fixtures.py`](generate_fixtures.py). The data the system runs on and the tests that grade
it can't drift apart, and [`validate_data.py`](validate_data.py) proves it by checking every case
against the fixtures field by field. Generation is deterministic: re-running produces byte-identical files.

| Shape | Schema | Fixtures | Records | System of record |
|---|---|---|---|---|
| **Claim** | [`claim.schema.json`](schemas/claim.schema.json) | [`claims.json`](fixtures/claims.json) | 19 | Claims management |
| **Policy** | [`policy.schema.json`](schemas/policy.schema.json) | [`policies.json`](fixtures/policies.json) | 19 | Policy administration |
| **Document** | [`document.schema.json`](schemas/document.schema.json) | [`documents.json`](fixtures/documents.json) | 67 | Document store (FNOL forms in claims management) |
| Clause *(extra)* | [`clause.schema.json`](schemas/clause.schema.json) | [`clauses.json`](fixtures/clauses.json) | 12 | Policy administration (wording corpus for retrieval) |
| User *(extra)* | [`user.schema.json`](schemas/user.schema.json) | [`users.json`](fixtures/users.json) | 5 | Identity provider (Cognito groups, M3) |

There are 19 claims for 20 cases because CS-019 deliberately reuses CS-008's claim, to test that
an unentitled user is refused.

## Claim (claims management)

| Field | Type | Notes |
|---|---|---|
| `claim_id` | `CLM-YYYY-NNNN` | primary key |
| `policy_id` | `POL-AU-NNNNN` | → Policy |
| `claimant_id` / `claimant_name` | `CUS-XXXXXX` / string | name is **PII-class**: masked in logs and traces |
| `loss_type` | collision · glass · hail · theft · vandalism | |
| `incident_date`, `incident_time`, `reported_date` | date / `HH:MM` or null / date | the date check is deterministic code |
| `narrative` | string | claimant free text, **untrusted** |
| `vehicle` | {year, make, model, colour?, vin} | synthetic 17-character VIN (no I/O/Q) |
| `acv`, `repair_estimate` | integer USD | money is whole dollars, computed in code |
| `injury_reported` | boolean | |
| `fraud_risk_score` | 0–1 | legacy score: an input, **never** the decision |
| `status` | first_pass_pending → recommendation_drafted → confirmed / overridden / routed | |
| `assigned_group` | adjuster · senior-adjuster · fraud-investigator · total-loss-appraiser · injury-specialist | drives entitlement |
| `document_ids` | [DOC-…] | → Document |

## Policy (policy administration)

| Field | Type | Notes |
|---|---|---|
| `policy_id`, `holder_id` | `POL-AU-NNNNN`, `CUS-XXXXXX` | holder = claimant (checked) |
| `coverages` | [liability · collision · comprehensive] | liability-only policies are a coverage gap (CS-002) |
| `deductible` | integer USD | net payable = gross − deductible (code) |
| `limits` | {physical_damage: actual_cash_value, liability_per_occurrence} | |
| `use_class` | private · commercial | the rideshare exclusion (CS-013) |
| `term_start`, `term_end`, `term_end_rule` | dates, rule text | cover ends 23:59 on `term_end` |
| `status_field` | Active · Pending renewal · Expired · Lapsed | **can be stale**; never used to decide coverage (CS-003, CS-014) |
| `renewal` | {submitted, processed} | an unprocessed renewal is ambiguous (CS-009) |

## Document (document store)

| Field | Type | Notes |
|---|---|---|
| `doc_id` | `DOC-YYYY-NNNN-TYPE` | |
| `claim_id` | → Claim | |
| `doc_type` | 13 types (fnol_form, police_report, repair_estimate, repair_invoice, glass_invoice, photos, medical_note, er_discharge_summary, driver_statement, tow_receipt, third_party_note, authorisation_letter, renewal_confirmation_email) | |
| `source_system` | claims_management · document_store | |
| `received_date` | date | an invoice dated *before* the loss is a fraud signal (CS-015) |
| `content_text` | string | **untrusted**: carries the planted injection for CS-016 |
| `metadata` | {image_count, exif_dates} | photo dates that contradict the narrative (CS-015) |
| `trust` | constant `untrusted` | |
| `sha256` | hex | integrity |

## Clause corpus *(extra: needed for cited retrieval in M2)*

Twelve citable clauses (`CLS-COL-001` … `CLS-LIA-012`), each with a `manifest_sha256`. That hash is
the provenance rule: a retrieved chunk whose hash isn't in the manifest is quarantined before model
context. The corpus also records the planted `"CLS-PER-006 (updated)"` injection used by CS-020, and
the validator proves it is **not** in the manifest.

## Verify

```bash
cd M1/6-synthetic-data
python3 -I generate_fixtures.py     # regenerate (byte-identical)
python3 -I validate_data.py         # schemas + referential integrity + M0-case consistency + provenance
```
