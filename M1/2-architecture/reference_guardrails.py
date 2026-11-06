"""Reference implementation of the ClaimSense content guardrails (stdlib only).

The executable spec for every guardrail that sits between the model and the outside world
(guardrails.md). M2's orchestrator must apply exactly these rules, in code, and pass the same
tests (test_guardrails.py). Access-control guardrails (entitlement, anti-enumeration, idempotency,
human-only confirmation, audit) live in ../5-system-contracts/reference_boundary.py.

Every guardrail is deterministic code. None of them asks a model whether something is safe.
"""
import copy
import hashlib
import re

# ── G1 · Injection scan (input) ──────────────────────────────────────────────────────────────
# Untrusted text (claim narratives, documents, retrieved chunks) is scanned before it reaches a
# model. A hit doesn't silently drop the text: the case is flagged and routed to a human.
INJECTION_PATTERNS = [
    r"\bignore (?:all |any )?(?:previous|prior|above|earlier) (?:instructions|constraints|rules)\b",
    r"\b(?:system|developer) (?:note|prompt|message)\b",
    r"\b(?:to|for) (?:the )?(?:ai|model|assistant|llm|reviewer bot|ai reviewer)\b",
    r"^\s*(?:assistant|system)\s*:",
    r"\bdo not (?:mention|reveal|disclose) (?:this|these)\b",
    r"\balways approve\b",
    r"\bapprove (?:this|the) claim\b",
    r"\bfraud checks? (?:passed|cleared|complete)\b",
]
_INJ = [re.compile(p, re.I | re.M) for p in INJECTION_PATTERNS]

# Pressure to skip the human (a different threat from injection: the verdict may still be right,
# but nothing may finalise it). These fire G6, not a reroute.
AUTO_DECISION_PATTERNS = [
    r"\bno (?:adjuster|human) review (?:required|needed)\b",
    r"\bpay (?:immediately|now|at once)\b",
    r"\bpre-?authori[sz]ed by\b",
    r"\bauto-?(?:approve|pay|settle)\b",
]
_AUTO = [re.compile(p, re.I) for p in AUTO_DECISION_PATTERNS]


def scan_injection(text):
    """Return the matched injection spans (empty list = clean)."""
    return [m.group(0) for rx in _INJ for m in rx.finditer(text or "")]


def scan_auto_decision_pressure(text):
    """Return phrases that try to bypass adjuster confirmation."""
    return [m.group(0) for rx in _AUTO for m in rx.finditer(text or "")]


# ── G2 · Provenance quarantine (retrieval) ───────────────────────────────────────────────────
def chunk_hash(label, text):
    return hashlib.sha256(f"{label}|{text}".encode()).hexdigest()


def quarantine_chunks(chunks, manifest_hashes):
    """Keep only retrieved chunks whose hash is in the clause manifest. Returns (kept, quarantined)."""
    kept, dropped = [], []
    for c in chunks:
        (kept if chunk_hash(c["clause_id"], c["text"]) in manifest_hashes else dropped).append(c)
    return kept, dropped


# ── G3 · PII masking (prompts, logs, traces) ─────────────────────────────────────────────────
PII_PATTERNS = {
    "EMAIL": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "PHONE": r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)",
    "SSN": r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)",
    "VIN": r"\b[A-HJ-NPR-Z0-9]{17}\b",
    "CARD": r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)",
}


def mask_pii(text, names=()):
    """Replace PII with typed placeholders. Names come from the claim record (known, not guessed)."""
    out = text or ""
    for n in sorted(filter(None, names), key=len, reverse=True):
        out = re.sub(re.escape(n), "[NAME]", out, flags=re.I)
    for label, rx in PII_PATTERNS.items():
        out = re.sub(rx, f"[{label}]", out)
    return out


# ── G4 · Computed fields are code-owned (output) ─────────────────────────────────────────────
def enforce_computed(card, computed):
    """Overwrite the model's `computed` section with the values code calculated. Returns (card, changed)."""
    card = copy.deepcopy(card)
    changed = card.get("computed") != computed
    card["computed"] = dict(computed)
    return card, changed


# ── G5 · Citation check (output) ─────────────────────────────────────────────────────────────
def check_citations(card, retrieved_clause_ids, claim_doc_ids):
    """Every cited source must be a clause retrieved for THIS request or a document of THIS claim.
    A decision (approve/deny) must cite at least one clause. Returns a list of violations."""
    violations = []
    cited = [c["source_id"] for c in card.get("citations", [])]
    for s in cited:
        if s.startswith("CLS-") and s not in retrieved_clause_ids:
            violations.append(f"cites clause {s} that was not retrieved for this request")
        elif s.startswith("DOC-") and s not in claim_doc_ids:
            violations.append(f"cites document {s} that does not belong to this claim")
    if card.get("outcome") in ("approve", "deny") and not any(s.startswith("CLS-") for s in cited):
        violations.append("a coverage decision must cite at least one policy clause")
    return violations


# ── G6 · Auto-decision block (output) ────────────────────────────────────────────────────────
FORBIDDEN_STATUSES = {"final", "paid", "approved_final", "closed"}


def block_auto_decision(card):
    """A recommendation can never finalise itself. Returns (card, fired)."""
    card = copy.deepcopy(card)
    fired = card.get("adjuster_confirmation_required") is not True or str(card.get("status", "")).lower() in FORBIDDEN_STATUSES
    card["adjuster_confirmation_required"] = True
    card.pop("status", None)
    return card, fired


# ── G7 · Cross-record reference (output) ─────────────────────────────────────────────────────
CLAIM_ID = re.compile(r"\bCLM-\d{4}-\d{4}\b")


def foreign_claim_references(card):
    """Claim IDs other than this claim's that appear anywhere in the card's text."""
    text = " ".join([card.get("reasoning", "")] + [c.get("quote", "") for c in card.get("citations", [])])
    return sorted({m for m in CLAIM_ID.findall(text) if m != card.get("claim_id")})


# ── Pipeline: apply every output guardrail, in a fixed order ─────────────────────────────────
def apply_guardrails(card, *, computed, retrieved_clause_ids, claim_doc_ids, untrusted_texts, quarantined=0):
    """Return (final_card, guardrails_fired).
    Injection, an invalid citation or a foreign-claim reference routes the case to a senior adjuster
    (the safe default is a human, never a silent approve). Pressure to auto-decide keeps the verdict
    but strips any finalisation. Quarantined chunks are recorded."""
    fired = []
    if quarantined:
        fired.append("poisoned_chunk_quarantined")
    card, _ = enforce_computed(card, computed)
    pressure = [h for t in untrusted_texts for h in scan_auto_decision_pressure(t)]
    card, auto = block_auto_decision(card)
    if auto or pressure:
        fired.append("auto_decision_blocked")
    hits = [h for t in untrusted_texts for h in scan_injection(t)]
    if hits:
        fired.append("injection_detected")
    bad_cites = check_citations(card, retrieved_clause_ids, claim_doc_ids)
    if bad_cites:
        fired.append("uncited_claim_blocked")
    foreign = foreign_claim_references(card)
    if foreign:
        fired.append("cross_record_blocked")
        bad_cites.append(f"response referenced {len(foreign)} other claim(s); redacted, never echoed")
        card["reasoning"] = CLAIM_ID.sub(lambda m: m.group(0) if m.group(0) == card.get("claim_id") else "[OTHER CLAIM]", card.get("reasoning", ""))
    if hits or bad_cites:
        card["outcome"], card["route_to"] = "flag_review", "senior-adjuster"
        reasons = hits + bad_cites
        card["reasoning"] = (card.get("reasoning", "") + " [GUARDRAIL] Routed to a senior adjuster: "
                             + "; ".join(reasons))[:2000]
    card["guardrails_fired"] = sorted(set(card.get("guardrails_fired", []) + fired))
    return card, card["guardrails_fired"]
