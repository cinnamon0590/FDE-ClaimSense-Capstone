"""Strict typed outputs (Pydantic). Each agent's `output_type` is one of these, so the SDK asks the
model for strict JSON Schema output and rejects anything that doesn't parse.

`DecisionCard` mirrors the M1 contract (M1/5-system-contracts/schemas/common.schema.json#/$defs/DecisionCard);
`tests/test_models.py` proves every card validates against that schema.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Outcome = Literal["approve", "flag_review", "route", "deny"]
RouteTo = Literal["senior-adjuster", "fraud-investigator", "total-loss-appraiser", "injury-specialist"]
CoverageFinding = Literal["covered", "not_covered", "ambiguous"]
GuardrailName = Literal["injection_detected", "poisoned_chunk_quarantined", "auto_decision_blocked",
                        "uncited_claim_blocked", "pii_masked", "cross_record_blocked"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Agent outputs (model judgment) ───────────────────────────────────────────────────────────
class IntakeResult(Strict):
    """Document Intake: what is on file and what the documents say. Facts, not decisions."""
    claim_id: str
    loss_type: str
    documents_on_file: list[str] = Field(description="doc_type of every document received")
    missing_documents: list[str] = Field(description="required document types not on file")
    injury_indicated: bool
    commercial_use_indicated: bool = Field(description="any sign the vehicle carried people or goods for pay")
    inconsistencies: list[str] = Field(description="factual contradictions between documents, dates or vehicle")
    summary: str


class CoverageResult(Strict):
    """Coverage Check: grounded in clauses retrieved by search_clauses, and only those."""
    claim_id: str
    coverage_finding: CoverageFinding
    basis: str
    cited_clause_ids: list[str] = Field(description="only clause IDs returned by search_clauses")
    exclusion_or_condition: str | None


class AssessmentResult(Strict):
    """Claim Assessment: risk signals and the specialist (if any) the claim needs."""
    claim_id: str
    fraud_signals: list[str]
    fraud_suspected: bool
    total_loss: bool
    injury_exposure: bool
    recommended_route: RouteTo | None
    rationale: str


class Citation(Strict):
    source_id: str = Field(pattern=r"^(CLS-[A-Z]{2,4}-\d{3}|DOC-\d{4}-\d{4}-[A-Z-]+)$")
    quote: str


class DecisionDraft(Strict):
    """Decision Draft: the recommendation an adjuster will confirm or override."""
    claim_id: str
    outcome: Outcome
    route_to: RouteTo | None
    reasoning: str
    citations: list[Citation]


# ── The card (contract) ──────────────────────────────────────────────────────────────────────
class Computed(Strict):
    """DETERMINISTIC CODE ONLY: never produced by the model (guardrail G4 overwrites it)."""
    loss_in_policy_term: bool
    net_payable: int | None
    repair_to_acv_ratio: float
    over_authority_limit: bool


class Judgment(Strict):
    coverage_finding: CoverageFinding
    fraud_signals: list[str]
    injury_exposure: bool
    missing_documents: list[str]


class ModelInfo(Strict):
    name: str
    prompt_version: str


class DecisionCard(Strict):
    claim_id: str = Field(pattern=r"^CLM-\d{4}-\d{4}$")
    outcome: Outcome
    route_to: RouteTo | None = None
    reasoning: str = Field(min_length=20)
    citations: list[Citation]
    computed: Computed
    judgment: Judgment
    verdict_source: Literal["model", "deterministic_fallback"]
    guardrails_fired: list[GuardrailName]
    adjuster_confirmation_required: Literal[True]
    model: ModelInfo

    def contract_dict(self):
        """The card exactly as the M1 schema defines it (route_to omitted when there's none)."""
        d = self.model_dump()
        if d.get("route_to") is None:
            d.pop("route_to", None)
        return d
