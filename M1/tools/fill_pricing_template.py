"""Fill the course's Pricing_Model_Template.docx from pricing.py (numbers are computed, never typed).

    python fill_pricing_template.py /path/to/Pricing_Model_Template.docx ../3-pricing-model.docx

Requires python-docx. Reuses the template-editing helpers from fill_sow_template.py, and imports the
estimate and prices from pricing.py so the worksheet can never disagree with the calculator.
"""
import copy
import sys

import docx
from docx.shared import Pt

import pricing as pm
from fill_sow_template import fill_table, set_col_widths, set_label_value, set_text

rows, lo, ex, hi = pm.estimate(pm.MILESTONES)
overhead = sum(pm.FIXED_OVERHEAD.values())
cost = ex * pm.BLENDED_DAY_RATE + overhead
cost_lo, cost_hi = lo * pm.BLENDED_DAY_RATE + overhead, hi * pm.BLENDED_DAY_RATE + overhead
tm, fx, oc, rec = pm.price_tm_cap(cost), pm.price_fixed(cost), pm.price_outcome(cost), pm.price_floor_plus_bonus(cost)
_, _, _, hi_pess = pm.estimate(pm.MILESTONES, dict(pm.RISK_BUFFER, access_politics=2.20))
m = pm.money
access = next(r for r in rows if r[0].risk_class == "access_politics")
team = ex / (pm.ENGAGEMENT_WEEKS * pm.WORKING_DAYS_PER_WEEK)
rpe = rec["expected"] / ex * pm.DAYS_PER_YEAR

ESTIMATE = [(r[0].name, r[0].size, f"{pm.TSHIRT[r[0].size][0]}–{pm.TSHIRT[r[0].size][1]}", f"{r[4]:.2f} ({r[0].risk_class})",
             f"{r[1]} / {r[2]:g} / {r[3]:.1f}") for r in rows]
ESTIMATE.append(("TOTAL (FDE-days)", "", "", "", f"{lo:g} / {ex:g} / {hi:.1f}"))

ACCESS = (f"The controls review & cloud access line is sized {access[0].size} ({access[1]}–{pm.TSHIRT[access[0].size][1]} days) "
          f"and carries the biggest buffer, {pm.RISK_BUFFER['access_politics']}×, so its high case is {access[3]:.1f} days "
          f"({m(access[3] * pm.BLENDED_DAY_RATE)}). It runs in parallel with the build because the architecture starts on synthetic "
          f"data, so a slow review delays M3, not M2. If the review is worse than feared (2.2×), the high case rises by "
          f"{m((hi_pess - hi) * pm.BLENDED_DAY_RATE)}. Data access is the long pole at a regulated insurer, so it is priced, not hoped for.")

WHEN = ["AutoSure can't yet say how many claims or criteria; we'd bill hours up to a cap",
        "Discovery was strong (charter, 20 labelled cases, measured baseline), so scope is well defined",
        "The result is clean and countable: acceptance criteria run by AutoSure's own CI"]

PRICES = [
    ("T&M with a cap", f"{m(tm['expected'])} (cap {m(tm['high'])})", f"cost × 1.35 markup = {tm['margin']*100:.1f}% margin; client bears overrun up to the cap"),
    ("Fixed price", m(fx['expected']), f"{fx['margin']*100:.0f}% margin; a 25% overrun cuts it to {fx['overrun_margin']*100:.1f}%"),
    ("Outcome-based", f"{m(oc['low'])} floor + up to {m(rec['pool'])}", f"thin floor (5% margin); expected {m(oc['expected'])} at {pm.EXPECTED_CRITERIA_MET}/4 criteria met"),
    ("Fixed floor + capped bonus", f"{m(rec['floor'])} + up to {m(rec['pool'])}", f"RECOMMENDED: expected {m(rec['expected'])} ({rec['margin']*100:.1f}% margin), max {m(rec['high'])}"),
]

RATIONALE = (f"A fixed floor of {m(rec['floor'])} gives Procurement the ceiling it needs and covers cost plus a 20% margin while "
             f"access politics resolve. The capped bonus ($9,000 for each of acceptance criteria 1–4 met at the Week 5 run, max "
             f"{m(rec['pool'])}) aligns us with the Claims Director's outcome. Who counts: AutoSure's own CI runs the eval suite on the "
             f"submitted commit; latency comes from CloudWatch and confirmations from the claims system, never the agent's own report. "
             f"Criterion 5 (zero harm) is a gate, never a bonus.")

MARGIN = (f"Price − cost = {m(rec['expected'])} − {m(cost)} = {m(rec['expected'] - cost)} expected margin "
          f"({rec['margin']*100:.1f}%; the floor alone clears expected cost by {m(rec['floor'] - cost)}). The access buffer sits in the "
          f"high case ({m(cost_hi)}), which is {m(cost_hi - rec['floor'])} above the floor; change control and milestone payments "
          f"(30/40/30) protect that tail. Revenue per engineer: {m(rec['expected'])} ÷ {ex:g} days × {pm.DAYS_PER_YEAR} ≈ "
          f"{m(rpe)}/yr, inside the $0.6–1.0M band. The pilot clears cost + buffer + margin, so no scope cut is needed.")

ASSUMPTIONS = [
    f"Blended rate {m(pm.BLENDED_DAY_RATE)}/FDE-day (course illustrative rate); {ex:g} expected days over {pm.ENGAGEMENT_WEEKS} weeks ≈ {team:.1f} FDE-equivalents.",
    "Fixed overhead " + m(overhead) + ": " + "; ".join(f"{k.split(' (')[0]} {m(v)}" for k, v in pm.FIXED_OVERHEAD.items()) + ".",
    f"Planning assumption: {pm.EXPECTED_CRITERIA_MET} of 4 bonus criteria met (one may slip in a 5-week pilot).",
    f"Phase 2 option (after Security clears real data): {m(pm.PHASE2_FEE_PER_CONFIRMED_DECISION)} per adjuster-confirmed first decision within the SLA, "
    f"capped at {m(pm.PHASE2_MONTHLY_CAP)}/month; ≈ {m(pm.PHASE2_CLAIMS_PER_DAY * 21 * pm.PHASE2_CONFIRMED_SHARE * pm.PHASE2_FEE_PER_CONFIRMED_DECISION)}/month "
    f"at {pm.PHASE2_CLAIMS_PER_DAY} claims/day (A) × {pm.PHASE2_CONFIRMED_SHARE:.0%} confirmed; counted in the claims system, reconciled with the audit log.",
    "All figures are regenerated by M1/tools/pricing.py; change an assumption there and re-run.",
]


def main(template, out):
    d = docx.Document(template)
    P = d.paragraphs
    set_text(P[0], "Pricing-Model Worksheet — ClaimSense AI × AutoSure Insurance (pilot)")
    set_text(P[1], "Cost first, then the price; the price has to clear the cost. Every number below is computed by M1/tools/pricing.py.")
    by_start = lambda s: next(p for p in d.paragraphs if p.text.startswith(s))

    def nxt(heading):
        ps = d.paragraphs
        i = next(k for k, p in enumerate(ps) if p._element is by_start(heading)._element)
        return ps[i + 1]

    set_label_value(by_start("Blended day-rate:"), "Blended day-rate:",
                    f"{m(pm.BLENDED_DAY_RATE)} per FDE-day (≈ {team:.1f} FDE-equivalents over {pm.ENGAGEMENT_WEEKS} weeks)")
    set_label_value(by_start("Estimated cost"), "Estimated cost (low / expected / high):",
                    f"{m(cost_lo)} / {m(cost)} / {m(cost_hi)}  (labour + {m(overhead)} fixed overhead)")
    set_text(nxt("2. Access-politics buffer"), ACCESS)
    set_label_value(by_start("Chosen model:"), "Chosen model:", "fixed floor + capped acceptance bonus")
    ps = d.paragraphs
    set_text(ps[next(k for k, p in enumerate(ps) if p.text.startswith("Chosen model:")) + 1], RATIONALE)
    margin_p = by_start("Price − cost − access buffer")
    body_src = margin_p._element            # capture before its text is replaced
    set_text(margin_p, MARGIN)

    T = d.tables
    fill_table(T[0], ESTIMATE, size=9.5)
    for r, w in zip(T[1].rows[1:], WHEN):
        set_text(r.cells[3].paragraphs[0], w)
    fill_table(T[2], PRICES, size=9.5)
    set_col_widths(T[0], [3.0, 0.7, 0.8, 1.35, 1.15])
    set_col_widths(T[2], [1.75, 1.95, 3.2])

    # 7. Assumptions & Phase 2 option — appended in the template's own heading/body formatting
    heading_src = by_start("6. Margin check")._element
    h = copy.deepcopy(heading_src)
    body_src.addnext(h)
    hp = next(p for p in d.paragraphs if p._element is h)
    set_text(hp, "7. Assumptions & Phase 2 option")
    last = h
    for a in ASSUMPTIONS:
        b = copy.deepcopy(body_src)
        last.addnext(b)
        bp = next(p for p in d.paragraphs if p._element is b)
        set_text(bp, "• " + a)
        last = b

    for p in d.paragraphs:                     # filled content upright (template italicises placeholders)
        if not any(r.font.size and r.font.size.pt >= 13 for r in p.runs):
            for r in p.runs:
                r.italic = False
    for p in list(d.paragraphs):
        if not p.text.strip():
            p._element.getparent().remove(p._element)
    leftovers = [p.text for p in d.paragraphs if "[" in p.text and "]" in p.text]
    leftovers += [c.text for t in d.tables for r in t.rows for c in r.cells if "[" in c.text]
    assert not leftovers, f"unfilled placeholders remain: {leftovers}"
    d.core_properties.title = "Pricing model — ClaimSense AI × AutoSure Insurance"
    d.core_properties.author = "Susan Wellington"
    d.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
