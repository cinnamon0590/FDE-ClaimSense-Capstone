"""Stretch (W15 demo 3): the SAME Coverage Check agent on a second harness, Strands Agents.

What doesn't change: the instructions (COVERAGE), the typed output (CoverageResult), the retrieval
function and its provenance quarantine (G2), and the citation rule (cited ⊆ retrieved, G5).
What changes: ~15 lines of harness glue. That's the portability argument for keeping guardrails and
business rules in plain code instead of inside one framework.

    MOCK_BRAIN=0 python M2/stretch/strands_coverage.py CLM-2024-3412     # needs OPENAI_API_KEY
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claimsense import config  # noqa: E402
from claimsense.agents_def import COVERAGE  # noqa: E402
from claimsense.boundary_client import LocalBoundary  # noqa: E402
from claimsense.deterministic import compute, coverage_questions, missing_documents, verified_facts  # noqa: E402
from claimsense.models import CoverageResult  # noqa: E402
from claimsense.retrieval import get_index, search_with_provenance  # noqa: E402


def run(claim_id, user="alice"):
    from strands import Agent, tool
    from strands.models.openai import OpenAIModel

    b = LocalBoundary()
    claim = b.claim(user, claim_id, "agent:coverage-check")
    if "error" in claim:
        return {"refused": claim["error"]["code"]}
    policy = b.policy(user, claim["policy_id"], "agent:coverage-check")
    index, retrieved, quarantined = get_index(), set(), []

    @tool
    def search_clauses(query: str) -> str:
        """Search the AutoSure policy wording. Returns clauses with clause_id, title and text. Cite only these IDs.

        Args:
            query: plain-language description of the coverage question.
        """
        kept, dropped = search_with_provenance(index, query, k=3)       # same G2 quarantine
        retrieved.update(k["clause_id"] for k in kept)
        quarantined.extend(d["clause_id"] for d in dropped)
        return json.dumps([{k: c[k] for k in ("clause_id", "title", "text")} for c in kept])

    # structured_output_model on the agent = run the tool loop first, then return the typed result.
    # (agent.structured_output() alone skips the tools: tried first, and it invented clause IDs that G5 caught.)
    agent = Agent(model=OpenAIModel(model_id=config.MODEL_SMART, params={"temperature": 0}),
                  system_prompt=COVERAGE, tools=[search_clauses], structured_output_model=CoverageResult,
                  callback_handler=None)
    computed = compute(claim, policy)
    docs = [b.document(user, d, "agent:coverage-check") for d in claim["document_ids"]]
    missing = missing_documents(claim["loss_type"], [d["doc_type"] for d in docs if "error" not in d])
    payload = {"claim_id": claim_id, "verified_facts": verified_facts(claim, policy, computed, missing),
               "coverage_questions": coverage_questions(claim, policy, computed, missing), "computed": computed,
               "policy": {k: policy[k] for k in ("coverages", "deductible", "term_start", "term_end", "status_field", "renewal")},
               "intake": {"loss_type": claim["loss_type"], "injury_indicated": claim["injury_reported"]}}
    result = agent(json.dumps(payload))
    out: CoverageResult = result.structured_output
    not_retrieved = [c for c in out.cited_clause_ids if c not in retrieved]     # same G5 rule
    return {"harness": "strands-agents", "model": config.MODEL_SMART, "coverage": out.model_dump(),
            "retrieved": sorted(retrieved), "quarantined": quarantined,
            "citation_check": "PASS" if not not_retrieved else f"TRIPPED: {not_retrieved}"}


if __name__ == "__main__":
    if config.MOCK_BRAIN:
        sys.exit("Strands port runs live only: set OPENAI_API_KEY and MOCK_BRAIN=0 in M2/.env")
    claims = sys.argv[1:] or ["CLM-2024-1800", "CLM-2024-3412", "CLM-2024-3518"]
    results = {c: run(c) for c in claims}
    text = json.dumps(results, indent=1)
    print(text)
    (Path(__file__).resolve().parents[1] / "evidence" / "strands-port.json").write_text(text + "\n")
