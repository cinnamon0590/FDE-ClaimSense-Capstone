"""Typed Python mirror of the ClaimSense system contracts (stdlib typing only).

The JSON Schemas in schemas/ are the source of truth; these types let the M2 agent code and the
M3 boundary be type-checked against the same shapes. In M2 the DecisionCard becomes the
OpenAI Agents SDK `output_type` (strict structured output), so the model can only return this shape.
"""
from typing import List, Literal, Optional, TypedDict

Outcome = Literal["approve", "flag_review", "route", "deny"]
RouteTo = Literal["senior-adjuster", "fraud-investigator", "total-loss-appraiser", "injury-specialist"]
ErrorCode = Literal["unauthenticated", "not_found_or_forbidden", "invalid_request", "rate_limited",
                    "upstream_unavailable", "idempotency_conflict", "human_confirmation_required"]
Guardrail = Literal["injection_detected", "poisoned_chunk_quarantined", "auto_decision_blocked",
                    "uncited_claim_blocked", "pii_masked", "cross_record_blocked"]


# ── shared ──────────────────────────────────────────────────────────────────────────────────
class ErrorBody(TypedDict, total=False):
    code: ErrorCode              # required
    message: str                 # required
    request_id: str              # required (uuid)
    retry_after_s: int           # only for rate_limited / upstream_unavailable


class Error(TypedDict):
    error: ErrorBody


class AuditRecord(TypedDict):
    ts: str
    request_id: str
    user_id: str
    groups: List[str]
    on_behalf_of_agent: Optional[str]
    action: str
    resource: str
    decision: Literal["allow", "deny", "replay", "error"]
    reason: str


class Citation(TypedDict, total=False):
    source_id: str               # CLS-… clause or DOC-… document (required)
    quote: str


class Computed(TypedDict):       # DETERMINISTIC CODE ONLY
    loss_in_policy_term: bool
    net_payable: Optional[int]
    repair_to_acv_ratio: float
    over_authority_limit: bool


class Judgment(TypedDict, total=False):   # MODEL JUDGMENT, each item cited
    coverage_finding: Literal["covered", "not_covered", "ambiguous"]
    fraud_signals: List[str]
    injury_exposure: bool
    missing_documents: List[str]


class DecisionCard(TypedDict, total=False):
    claim_id: str
    outcome: Outcome
    route_to: RouteTo
    reasoning: str
    citations: List[Citation]
    computed: Computed
    judgment: Judgment
    verdict_source: Literal["model", "deterministic_fallback"]
    guardrails_fired: List[Guardrail]
    adjuster_confirmation_required: Literal[True]
    model: dict


# ── claims management ───────────────────────────────────────────────────────────────────────
class GetClaimRequest(TypedDict):
    claim_id: str


class PostRecommendationRequest(TypedDict):
    claim_id: str
    idempotency_key: str          # uuid v4, required on every write
    decision_card: DecisionCard


class RecommendationReceipt(TypedDict):
    recommendation_id: str
    claim_id: str
    version: int
    status: Literal["draft_pending_confirmation"]
    idempotent_replay: bool
    created_at: str


class ConfirmRecommendationRequest(TypedDict, total=False):   # HUMAN-ONLY
    recommendation_id: str
    action: Literal["confirm", "override"]
    final_outcome: Outcome
    override_reason: str          # required when action == "override"
    idempotency_key: str


class ConfirmationReceipt(TypedDict):
    recommendation_id: str
    claim_id: str
    action: Literal["confirm", "override"]
    final_outcome: Outcome
    confirmed_by: str
    idempotent_replay: bool
    confirmed_at: str


# ── policy administration ───────────────────────────────────────────────────────────────────
class SearchClausesRequest(TypedDict, total=False):
    query: str                    # required
    loss_type: Literal["collision", "glass", "hail", "theft", "vandalism"]
    top_k: int                    # 1..8


class ClauseHit(TypedDict):
    clause_id: str
    title: str
    text: str
    score: float
    manifest_sha256: str


class SearchClausesResponse(TypedDict):
    query: str
    hits: List[ClauseHit]
    quarantined: int              # chunks dropped for failing provenance


# ── document store ──────────────────────────────────────────────────────────────────────────
class DocumentMeta(TypedDict):
    doc_id: str
    doc_type: str
    title: str
    received_date: str
    sha256: str


class GetDocumentResponse(TypedDict, total=False):
    doc_id: str
    claim_id: str
    doc_type: str
    content_text: str             # UNTRUSTED
    metadata: dict
    trust: Literal["untrusted"]
    injection_scan: dict          # {"flagged": bool, "spans": [...]}
