# M1 Deliverable 5: Typed contracts for the three client systems

**Engagement:** ClaimSense AI · AutoSure Insurance (motor) · **FDE:** Susan Wellington · **Date:** 2026-11-05

Agents never call a client system directly. Every call goes through **one data boundary**
(MCP server on API Gateway + Lambda, Cognito JWT). The boundary checks entitlement in code,
returns only what the caller may see, and writes an audit record for every call. The contracts
below are what crosses that boundary.

**Source of truth:** JSON Schema (draft 2020-12) in [`schemas/`](schemas/). There's a typed
Python mirror in [`contracts.py`](contracts.py), and an executable spec, the in-memory
[`reference_boundary.py`](reference_boundary.py), proven by
[`test_contracts.py`](test_contracts.py) (17 tests). M3's production service must pass the same tests.

| Schema file | Defines |
|---|---|
| [`common.schema.json`](schemas/common.schema.json) | `Error` envelope, `AuditRecord`, `DecisionCard` (the model's typed output) |
| [`claims-management.contract.json`](schemas/claims-management.contract.json) | claim reads, recommendation write, human confirmation write |
| [`policy-administration.contract.json`](schemas/policy-administration.contract.json) | policy read, clause search (retrieval) |
| [`document-store.contract.json`](schemas/document-store.contract.json) | document list and read |
| [`../6-synthetic-data/schemas/`](../6-synthetic-data/schemas/) | the `Claim`, `Policy` and `Document` records the reads return |

---

## Rules that apply to every operation

| Rule | Contract |
|---|---|
| **Authentication** | `Authorization: Bearer <Cognito JWT>`. No token or an invalid one → `unauthenticated`. The boundary derives `user_id` and `groups` from the token, never from the request body. |
| **Entitlement (in code, before any agent)** | `adjuster` → claims in the adjuster queue · `senior-adjuster` → all first-pass claims · `fraud-investigator` / `total-loss-appraiser` → claims routed to them · `customer-service` → no claim files. |
| **Anti-enumeration** | A missing record and an unentitled record return the **same** error: `not_found_or_forbidden`, with the same message. The real reason is recorded only in the audit log. |
| **Audit** | Every call appends an `AuditRecord` `{ts, request_id, user_id, groups, on_behalf_of_agent, action, resource, decision, reason}`. `decision` ∈ `allow / deny / replay / error`; denials are always logged. The log is append-only: no role can edit or delete it. |
| **Error envelope** | `{"error": {"code", "message", "request_id", "retry_after_s"?}}`. A raw stack trace or a bare 500 never reaches the caller. |
| **Untrusted content** | Claim narratives and document text are marked `trust: "untrusted"`. Document reads include an `injection_scan`. Retrieval drops any chunk whose hash isn't in the clause manifest (`quarantined` count). |
| **Data minimisation** | Responses carry only the fields in the schema (`additionalProperties: false`). `claimant_name` is PII-class: masked in logs and traces. |

## Claims management system

| Operation (MCP tool / REST) | Request | Response | Errors | Notes |
|---|---|---|---|---|
| `get_claim` · `GET /claims/{claim_id}` | `GetClaimRequest {claim_id}` | `Claim` record | `not_found_or_forbidden`, `unauthenticated` | Read. Naturally idempotent. |
| `get_claim_history` · `GET /claimants/{id}/claims?limit=` | `{claimant_id, limit ≤ 20}` | `ClaimHistoryResponse` | as above | Prior losses for the fraud and frequency read. |
| `post_recommendation` · `POST /claims/{claim_id}/recommendations` | `{claim_id, idempotency_key, decision_card}` | `RecommendationReceipt` with `status: "draft_pending_confirmation"` | `not_found_or_forbidden`, `idempotency_conflict`, `invalid_request` | **Write. Idempotent (rules below).** Always a draft; a new key creates version n+1. |
| `confirm_recommendation` · `POST /recommendations/{id}/confirmation` | `{recommendation_id, action: confirm/override, final_outcome?, override_reason?, idempotency_key}` | `ConfirmationReceipt` | `human_confirmation_required`, `invalid_request`, `not_found_or_forbidden`, `idempotency_conflict` | **Write, human-only.** An agent service identity is refused. An override needs a reason. Approving above $25,000 net needs `senior-adjuster`. |

## Policy administration system

| Operation | Request | Response | Errors | Notes |
|---|---|---|---|---|
| `get_policy` · `GET /policies/{policy_id}` | `{policy_id}` | `Policy` record | `not_found_or_forbidden` | Allowed only if the caller is entitled to a claim on that policy. Feeds the **deterministic** date and money checks; `status_field` is never used to decide coverage. |
| `search_clauses` · `GET /clauses/search?q=&loss_type=&top_k=` | `{query, loss_type?, top_k 1–8}` | `SearchClausesResponse {hits[], quarantined}` | `invalid_request`, `rate_limited` | Retrieval over the clause corpus (OpenSearch). Each hit carries `clause_id` and `manifest_sha256`. The agents may cite only clause IDs returned here. |

## Document store

| Operation | Request | Response | Errors | Notes |
|---|---|---|---|---|
| `list_documents` · `GET /claims/{claim_id}/documents` | `{claim_id}` | `ListDocumentsResponse` (metadata and hashes only) | `not_found_or_forbidden` | Lets Document Intake spot missing documents (e.g. no police report on a theft). |
| `get_document` · `GET /documents/{doc_id}` | `{doc_id}` | `GetDocumentResponse {content_text, trust: "untrusted", injection_scan}` | `not_found_or_forbidden` | Text is wrapped as data, never instructions, before it reaches a model. |

The document store and policy administration are **read-only** in the pilot. The only writes in
the whole system are the two claims-management writes above.

---

## Idempotency rules (all write operations)

1. **Key required.** Every write carries an `Idempotency-Key` (UUID v4). A write without one is `invalid_request`.
2. **Scope.** A key is unique per *(caller, operation, key)*, so two users can't collide.
3. **Same key + same payload → replay.** The boundary fingerprints the payload (SHA-256 of
   canonical JSON) and returns the **original** response with `idempotent_replay: true`. There's
   no second write and no new version, and the audit row says `replay`.
4. **Same key + different payload → `idempotency_conflict`** (HTTP 409). Nothing is written.
5. **New key → new version.** The same claim with a new key creates recommendation `version` n+1.
   Drafts are never overwritten.
6. **Retention.** Keys and their responses are kept 30 days (longer than any retry window).
7. **Concurrency.** Two simultaneous requests with the same key: one writes and the other
   receives the replay (conditional write on the key in the backing store, a DynamoDB condition
   expression in M3).
8. **Confirmation writes** follow rules 1–7 and also require a human `adjuster` or
   `senior-adjuster` identity.

### Example: a network retry made harmless

```text
POST /claims/CLM-2024-1800/recommendations   Idempotency-Key: 6f1c…   → 201
{"recommendation_id": "REC-3b9e0c27a41d", "claim_id": "CLM-2024-1800", "version": 1,
 "status": "draft_pending_confirmation", "idempotent_replay": false, "created_at": "2026-11-05T15:02:11Z"}

POST /claims/CLM-2024-1800/recommendations   Idempotency-Key: 6f1c…   (same body, client retried) → 200
{"recommendation_id": "REC-3b9e0c27a41d", ..., "version": 1, "idempotent_replay": true}

POST /claims/CLM-2024-1800/recommendations   Idempotency-Key: 6f1c…   (DIFFERENT body) → 409
{"error": {"code": "idempotency_conflict", "message": "This Idempotency-Key was used with a different payload.", "request_id": "…"}}
```

## Retry policy (client side)

Retry **only** `rate_limited` and `upstream_unavailable`, at most 3 attempts. Honour
`retry_after_s` if it's given; otherwise back off exponentially (0.2 s, 0.4 s, 0.8 s). Never retry
other 4xx errors. Because writes are idempotent, a retried write can't create a duplicate.

## The model's output contract: `DecisionCard`

The Decision Draft agent returns a typed `DecisionCard` (in M2, the OpenAI Agents SDK
`output_type` with strict structured output). Its structure enforces the code/model boundary:

- `computed` is filled by **deterministic code**: whether the loss is in the policy term, net
  payable, the repair-to-ACV ratio and the authority-limit flag.
- `judgment` is filled by the **model**: the coverage finding, fraud signals, injury exposure and
  missing documents. Each item must be backed by an entry in `citations` (a `CLS-…` clause or a
  `DOC-…` document).
- `verdict_source` is `model` or `deterministic_fallback`, so a rule-table verdict can always be
  told apart from a model verdict.
- `adjuster_confirmation_required` is the constant `true`. The schema rejects any card that
  tries to waive it (tested).

## Verify

```bash
cd M1/5-system-contracts
python3 test_contracts.py -v          # 17 tests: schemas, idempotency, access, audit, retry
```
