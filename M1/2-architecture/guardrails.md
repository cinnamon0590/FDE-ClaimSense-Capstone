# Guardrail catalogue: ClaimSense AI × AutoSure

**Rule for every entry:** the trigger is checkable by code, the action is one of block / quarantine /
route to a human / overwrite, and the failure prevented is a concrete event, not a quality. *A rule in
the prompt is a suggestion; a rule in code is a control* (Week 14). No guardrail asks a model whether
something is safe.

**Status:** **Executable in M1** = implemented in a reference module and proven by tests now. M2 and M3
build the production versions against the same tests. **Live** = enforced in the AWS account today.

## 1. Content guardrails: between the model and the world
*Reference: [`reference_guardrails.py`](reference_guardrails.py) · proof: [`test_guardrails.py`](test_guardrails.py) (16 tests, graded with the M0 eval scorer)*

| ID | Guardrail | Trigger (code-checkable) | Action | Prevents | Eval case | Status |
|---|---|---|---|---|---|---|
| G1 | Injection scan | instruction-like patterns in untrusted text ("ignore previous instructions", "system note", "approve this claim", "fraud checks passed", role tags) | flag the case, route to senior adjuster, highlight the span | a planted instruction steering the decision | CS-016 | Executable in M1 |
| G2 | Provenance quarantine | a retrieved chunk whose hash isn't in the clause manifest | drop it before model context; count it (`quarantined`) | a poisoned or tampered clause changing coverage | CS-020 | Executable in M1 |
| G3 | PII masking | names from the claim record; email, phone, SSN, VIN, card patterns | replace with typed placeholders before prompts, logs and traces | personal data reaching the model provider or logs | (adds an `ADV` case in M2) | Executable in M1 |
| G4 | Code owns the numbers | every DecisionCard | overwrite `computed` (term check, net payable, repair÷ACV, $25K flag) with code's values | a wrong date or dollar figure, e.g. an injected $18,000 | CS-001, CS-003, CS-014 | Executable in M1 |
| G5 | Citation check | a cited clause not retrieved for this request; a cited document from another claim; approve or deny with no clause cited | route to senior adjuster (`uncited_claim_blocked`) | invented clause numbers; ungrounded coverage decisions | CS-002, CS-013 | Executable in M1 |
| G6 | Auto-decision block | `adjuster_confirmation_required ≠ true`, a final/paid status, or pressure phrases ("pay immediately", "no adjuster review", "pre-authorised by") | force confirmation, strip finality, **keep** a correct verdict | anything moving money without a licensed adjuster | CS-018 | Executable in M1 (also schema-enforced) |
| G7 | Cross-record block | another claim's ID in the output | redact it (never echoed back), route to senior adjuster | leaking another claimant's data | CS-017 | Executable in M1 |

## 2. Access guardrails: the data boundary
*Reference: [`../5-system-contracts/reference_boundary.py`](../5-system-contracts/reference_boundary.py) · proof: [`test_contracts.py`](../5-system-contracts/test_contracts.py) (17 tests)*

| ID | Guardrail | Trigger | Action | Prevents | Eval / test | Status |
|---|---|---|---|---|---|---|
| A1 | Authentication | missing or invalid Cognito JWT | `unauthenticated`; audit | anonymous access | M3 route tests | Live pool; enforced in M3 |
| A2 | Entitlement before any agent | caller's groups don't cover the claim | refusal, **zero claim data**; no agent invoked | an unentitled user reading a claim | CS-019 · `unentitled_user_gets_no_claim_data` | Executable in M1 |
| A3 | Anti-enumeration | missing or forbidden record | identical error for both; reason only in audit | probing IDs to learn which claims exist | `missing_and_unentitled_look_identical` | Executable in M1 |
| A4 | Audit every call | any call | append-only record incl. **denials** | silent access; unprovable behaviour | `every_call_is_audited` | Executable in M1; DynamoDB table live |
| A5 | Idempotent writes | repeated Idempotency-Key | replay the original; conflict on a different payload | duplicate recommendations from retries | `same_key_same_payload_replays` | Executable in M1; DynamoDB table live (30-day TTL) |
| A6 | Human-only confirmation | an agent identity calling confirm; an override without a reason; approval > $25K without a senior adjuster | refuse (`human_confirmation_required`) | the co-pilot deciding instead of recommending | `agent_identity_cannot_confirm` · `above_authority_limit…` | Executable in M1 |
| A7 | Data minimisation | any field outside the schema | rejected (`additionalProperties: false`) | over-collection of claim data | schema validation | Executable in M1 |

## 3. Data guardrails

| ID | Guardrail | Proof | Status |
|---|---|---|---|
| D1 | Synthetic data only; every fixture declares `synthetic: true` | `validate_data.py` fails if it's missing | Executable in M1 |
| D2 | Fixtures generated from the eval cases (no drift) | CI regenerates and fails on any diff | Executable in M1 (CI) |
| D3 | Clause provenance manifest | `validate_data.py` proves the planted chunk is **not** in the manifest | Executable in M1 |
| D4 | Untrusted content is labelled (`trust: "untrusted"`) | document schema `const` | Executable in M1 |

## 4. Release and process guardrails

| ID | Guardrail | Proof | Status |
|---|---|---|---|
| R1 | Deploy gate: overall ≥ 85% **and** adversarial 100% **and** model verdicts only (D-007) | M0 `score.py` + 9 harness tests | Executable; blocks image push from M2 |
| R2 | Fallback verdicts never count as model decisions | harness `fallback_verdict_never_counts` | Executable in M0 |
| R3 | Golden labels governed (Senior Adjuster owns; no silent relabelling) | success criteria §rules | Process |
| R4 | Change control before scope changes | SoW §10 | Contract |

## 5. Cloud guardrails, live in AWS today
*Evidence: [`../7-cloud/evidence/`](../7-cloud/evidence/)*

| Guardrail | Setting |
|---|---|
| No public data | S3 public access blocked (all 4 settings); bucket-owner-enforced |
| Encryption at rest | S3 SSE-S3, DynamoDB, ECR and Secrets Manager encrypted by default |
| Recoverable audit | DynamoDB point-in-time recovery on `claimsense-audit` |
| Supply chain | ECR scan on push; immutable image tags; keep last 10 |
| Secrets out of code | OpenAI key in Secrets Manager, read at runtime |
| Least privilege for people | root retired from daily use; IAM admin `FDE_PROJECT_ADMIN` with **MFA** and **no access keys** |
| Strong identity for users | Cognito: admin-created users only, 14-character passwords, TOTP MFA |
| Cost containment | $25/month budget with **verified** email alerts at 80% forecast and 100% actual |
| Inventory and teardown | everything tagged `Project=ClaimSense`; `ClaimSense-pilot` Resource Group; scripted teardown |
| Log hygiene | 30-day retention on all log groups |

## Still to come (planned, not yet built)

- **M2:** guardrails wired into the Agents SDK pipeline (`@input_guardrail` / `@output_guardrail`);
  a PII-leak adversarial eval case; GitHub OIDC role for CI.
- **M3:** production data boundary with JWT checks on every route, plus the two-user test with audit rows.
- **M4:** CloudWatch alarms on guardrail-fire rate and fallback share; an optional managed layer
  (e.g. Bedrock Guardrails) evaluated against these hand-rolled rules.
