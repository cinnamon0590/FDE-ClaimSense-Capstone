"""HO-20 (held-out set, D-052): a UK passport number and a UK mobile in the FNOL reached the model unmasked, because
G3 only knew US formats. The decision was right, the guardrail didn't fire. This pins the fix on the real claim file."""
import json

from claimsense._m1 import FIXTURES, guardrails as G


def test_ho20_claim_file_is_masked_before_the_model_sees_it():
    docs = [d for d in json.loads((FIXTURES / "documents.json").read_text())["records"]
            if d["claim_id"] == "CLM-2026-3020"]
    fnol = next(d for d in docs if d["doc_type"] == "fnol_form")
    raw = json.dumps(fnol)
    assert "533380742" in raw and "07700 900461" in raw          # the fixture really carries them
    masked = G.mask_pii(raw)
    assert "533380742" not in masked and "07700 900461" not in masked
    assert "[ID_NUMBER]" in masked and "[PHONE]" in masked
