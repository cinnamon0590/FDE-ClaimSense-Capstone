"""Reference implementation of the ClaimSense content guardrails (stdlib only).

The executable spec for every guardrail that sits between the model and the outside world
(guardrails.md). M2's orchestrator must apply exactly these rules, in code, and pass the same
tests (test_guardrails.py). Access-control guardrails (entitlement, anti-enumeration, idempotency,
human-only confirmation, audit) live in ../5-system-contracts/reference_boundary.py.

Every guardrail is deterministic code. None of them asks a model whether something is safe.
"""
import base64
import copy
import hashlib
import re
import unicodedata

# ── G1 · Injection scan (input) ──────────────────────────────────────────────────────────────
# Untrusted text (claim narratives, documents, retrieved chunks) is scanned before it reaches a
# model. A hit doesn't silently drop the text: the case is flagged and routed to a human.
#
# Hardened in M2 after the adversarial fuzz suite (M2/evals/fuzz_guardrails.py) caught only 17% of
# mutated payloads. Text is scanned in three views: as written, NORMALISED (full-width folded, invisible
# characters removed) and as a SKELETON (look-alike letters and leetspeak mapped back, accents dropped,
# punctuation collapsed), plus any base64 payload decoded and rescanned. Patterns cover paraphrases
# ("disregard prior rules", "you are now") and five languages.
INJECTION_PATTERNS = [
    r"\bignore (?:all |any )?(?:previous|prior|above|earlier) (?:instructions|constraints|rules)\b",
    r"\b(?:system|developer) (?:note|prompt|message)\b",
    r"\b(?:to|for) (?:the )?(?:ai|model|assistant|llm|reviewer bot|ai reviewer|language model)\b",
    r"^\s*(?:assistant|system)\s*:",
    r"\bdo not (?:mention|reveal|disclose) (?:this|these)\b",
    r"\balways approve\b",
    r"\bapprove (?:this|the) claim\b",
    r"\bfraud checks? (?:passed|cleared|complete)\b",
]
# matched against the SKELETON view (lower case, a-z/0-9 words separated by single spaces)
SKELETON_PATTERNS = [
    r"\b(?:ignore|disregard|forget|override|bypass)(?: \w+){0,3} (?:instructions?|rules|constraints|guidelines|prompts?|exclusions?|checks?)\b",
    r"\bnew instructions? (?:for|to) (?:the )?(?:ai|model|assistant|llm|language model|reviewer)\b",
    r"\binstructions? (?:for|to) (?:the )?(?:ai|model|assistant|llm|language model|reviewer)\b",
    r"\b(?:message|note) (?:to|for) (?:the )?(?:ai|model|assistant|llm|language model|reviewer)\b",
    r"\byou are now\b",
    r"\byou must (?:approve|disregard|ignore|pay)\b",
    r"\brespond only with\b",
    r"\b(?:set|change) (?:the )?outcome to\b",
    r"\boutcome (?:is )?approve\b",
    r"\bmark (?:this|the) claim as (?:approved|covered|paid)\b",
    r"\bapprove (?:this|the) (?:claim|payout|settlement)\b",
    r"\balways approve\b",
    r"\bfraud checks? (?:has |have |is |are )?(?:passed|cleared|complete)\b(?! by)",
    r"\b(?:system|developer) (?:note|prompt|message)\b",
    r"\bdo not (?:mention|reveal|disclose) (?:this|these)\b",
    # directives aimed at the reviewer rather than facts about the claim (layer added after held-out set v1)
    r"\b(?:attention|hey|dear)\b(?: \w+){0,2} (?:automated|ai|system|bot|assistant|model|claimsense|reviewer)\b",
    r"\b(?:pretend|act as if|act as though|imagine) (?:you|that|the)\b",
    r"\b(?:discard|disregard|forget) (?:everything|all|what) (?:you|that|i)\b",
    r"\b(?:previous|prior|earlier|above) (?:guidance|instructions|rules|context|prompt) (?:no longer|does not|doesn t|do not|don t) appl",
    r"\b(?:admin|administrator|root|developer|system) (?:override|mode|access)\b",
    r"\b(?:classification|verdict|outcome) (?:is |should be |must be )?approve",
    r"\btreat (?:this|the) claim as (?:covered|approved|valid|genuine|paid)\b",
    r"\bsign (?:this|it) off as\b",
    r"\bjust approve\b",
    r"\bignore (?:what|the) (?:policy|exclusions?|rules?|clauses?)\b",
    r"\breturn (?:the )?json\b",
    # the same attack in Spanish, French, German, Italian, Portuguese (accents dropped in the skeleton)
    r"\b(?:ignora|ignorez|ignoriere|ignorar|ignore)\b(?: \w+){0,3} (?:instrucciones|instructions|anweisungen|istruzioni|instrucoes)\b",
    r"\b(?:aprueba|approuvez|genehmige|approva|aprove)\b(?: \w+){0,2} (?:reclamacion|sinistre|schaden|sinistro)\b",
]
_INJ = [re.compile(p, re.I | re.M) for p in INJECTION_PATTERNS]
_SKEL = [re.compile(p) for p in SKELETON_PATTERNS]

# Pressure to skip the human (a different threat from injection: the verdict may still be right,
# but nothing may finalise it). These fire G6, not a reroute.
AUTO_DECISION_PATTERNS = [
    r"\bno (?:adjuster|human) review (?:required|needed)\b",
    r"\bpay (?:immediately|now|at once)\b",
    r"\bpre-?authori[sz]ed by\b",
    r"\bauto-?(?:approve|pay|settle)\b",
]
_AUTO = [re.compile(p, re.I) for p in AUTO_DECISION_PATTERNS]

_CONFUSABLES = str.maketrans({  # Cyrillic and Greek letters that look Latin
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "ո": "n", "ν": "v", "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k",
    "τ": "t", "ρ": "p", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "Х": "X", "І": "I", "Ѕ": "S"})
_LEET = str.maketrans({"4": "a", "3": "e", "1": "i", "0": "o", "5": "s", "7": "t", "@": "a", "$": "s"})
_B64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def normalise(text):
    """Fold compatibility forms (full-width letters) and strip invisible format characters
    (zero-width space/joiners, word joiner, BOM, soft hyphen). Meaning-preserving."""
    t = unicodedata.normalize("NFKC", text or "")
    return "".join(ch for ch in t if unicodedata.category(ch) != "Cf")


def skeleton(text):
    """A matching-only view: look-alikes and leetspeak mapped to letters, accents dropped, every run
    of non-alphanumerics collapsed to one space, lower case. Never shown to anyone."""
    t = normalise(text).translate(_CONFUSABLES)
    t = "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))
    t = t.lower().translate(_LEET)
    return " ".join(re.findall(r"[a-z0-9]+", t))


def _decoded_payloads(text):
    for tok in _B64.findall(text):
        try:
            raw = base64.b64decode(tok + "=" * (-len(tok) % 4), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if sum(ch.isprintable() or ch.isspace() for ch in raw) >= 0.9 * len(raw):
            yield raw


def scan_injection(text, _depth=0):
    """Return the matched injection spans (empty list = clean). Spans found in the normalised or skeleton
    view are reported as found there (the raw text may not contain them byte-for-byte)."""
    raw = text or ""
    hits = [m.group(0) for rx in _INJ for m in rx.finditer(raw)]
    norm = normalise(raw)
    if not hits and norm != raw:
        hits = [m.group(0) for rx in _INJ for m in rx.finditer(norm)]
    if not hits:
        sk = skeleton(raw)
        hits = [m.group(0) for rx in _SKEL for m in rx.finditer(sk)]
    if not hits and _depth == 0:
        for payload in _decoded_payloads(norm):
            hits += [f"base64: {h}" for h in scan_injection(payload, _depth=1)]
    return hits


def scan_auto_decision_pressure(text):
    """Return phrases that try to bypass adjuster confirmation."""
    return [m.group(0) for rx in _AUTO for m in rx.finditer(normalise(text))]


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
    "VIN": r"(?i)\b(?=[A-HJ-NPR-Z]*\d)(?=\d*[A-HJ-NPR-Z])[A-HJ-NPR-Z0-9]{17}\b",   # any case; letters AND digits
    "CARD": r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)",
}


def mask_pii(text, names=()):
    """Replace PII with typed placeholders. Names come from the claim record (known, not guessed).
    Text is normalised first, so zero-width characters or full-width digits can't hide a value."""
    out = normalise(text)
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
        # never echo the injected text itself into the card (it would re-deliver the payload);
        # the spans stay in the audit trail for the adjuster to inspect
        reasons = ([f"{len(hits)} instruction-like passage(s) found in untrusted claim text"] if hits else []) + bad_cites
        card["reasoning"] = (card.get("reasoning", "") + " [GUARDRAIL] Routed to a senior adjuster: "
                             + "; ".join(reasons))[:2000]
    card["guardrails_fired"] = sorted(set(card.get("guardrails_fired", []) + fired))
    return card, card["guardrails_fired"]
