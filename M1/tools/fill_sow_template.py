"""Fill the course's SoW_Template.docx with the ClaimSense × AutoSure statement of work.

    python fill_sow_template.py /path/to/SoW_Template.docx ../1-statement-of-work.docx

Requires python-docx. Edits the template IN PLACE: same fonts, sizes and table styles. Bracketed
placeholders are replaced; table rows are cloned from the template's own rows. The blank
template is course material and isn't committed; pass its path.
Content mirrors 1-statement-of-work.md.
"""
import copy
import sys

import docx
from docx.shared import Pt

TITLE = "Statement of Work — ClaimSense AI × AutoSure Insurance (pilot)"
HEADER = {
    "Vendor:": "ClaimSense AI delivery team — FDE: Susan Wellington",
    "Client:": "AutoSure Insurance — motor claims",
    "Engagement:": "Claims-adjudication co-pilot — five-week pilot (synthetic data only)",
    "Version / Date:": "v1.0 / 2026-11-05",
}
BACKGROUND = ("Every motor claim's first pass is done by one adjuster acting as the integration layer between claims "
              "management, policy administration and the document store. A first decision takes about 3.2 hours, adjusters "
              "disagree on about 18% of files, and fraud referral fires on a score threshold. "
              "On our 20-case seed suite the current rule table is right 25% of the time and catches 0 of 2 fraud files. "
              "Objective: a first pass in minutes, not hours, with the reasoning written down and a licensed adjuster "
              "accountable for every outcome.")
SCOPE = [
    ("Charter, RACI, success criteria, decision log, 20 eval cases", "Discovery & scoping", "M0 · Week 1"),
    ("SoW, architecture, pricing, risk register, typed contracts, synthetic data, cloud account", "Design", "M1 · Week 2"),
    ("Four agents (Intake, Coverage, Assessment, Decision Draft), cited retrieval, containers, CI eval gate", "Build", "M2 · Week 3"),
    ("Data boundary (MCP), auth on every route, access control before agents, audit trail", "Integrate & guard", "M3 · Week 4"),
    ("150-case eval suite, dashboard + alarm, incident drill, runbook, handover, demo", "Prove & hand over", "M4 · Week 5"),
]
ACCEPT_HEADING = "3. Acceptance criteria (= M0 success criteria; counted by AutoSure, never the agent)"
ACCEPT = [
    ("1. Decision accuracy", "model codes = golden labels (fallback = miss)", "≥90% clear · ≥75% edge · ≥85% all", "150-case suite, AutoSure CI, submitted commit"),
    ("2. Latency", "FNOL → decision card", "p95 ≤ 90 s · p50 ≤ 45 s", "≥150 deployed runs (CloudWatch)"),
    ("3. Adjuster confirmation", "confirmed unchanged by Senior Adjuster", "≥ 80%", "≥50 claims, claims-system records"),
    ("4. Fraud routing", "recall · false-route rate", "≥ 90% · ≤ 10%", "fraud / non-fraud subsets of suite"),
    ("5. Zero harm (gate)", "auto-decisions · leaks · obeyed injections · data to unentitled users", "= 0 (100% adversarial pass)", "adversarial family of the suite"),
    ("6. Entitlement", "two-user test on one claim", "claim vs refusal, both audited", "same claim, two identities"),
    ("7. Completeness", "recommendations created ÷ requests", "≥ 99%", "counted in claims management"),
    ("8. Operability", "4 runbook procedures + recovery", "first-time operator succeeds", "induced failure, deployed stack"),
]
OUT_OF_SCOPE = ("Auto-payment or any final claim status · production or personal data · customer correspondence · total-loss "
                "valuation and injury reserving · changes to AutoSure's systems of record · fine-tuning.")
TIMELINE = [
    ("M0 — Discovery & scoping", "Week 1 (course W13)", "Claims Director"),
    ("M1 — SoW, architecture, contracts, cloud", "Week 2 (W14)", "Claims Director + Legal/Procurement; Security consulted"),
    ("M2 — Production agents + CI gate", "Week 3 (W15)", "Senior Adjuster (demo on synthetic claims)"),
    ("M3 — Integration & access control", "Week 4 (W16)", "Security / Compliance (two-user test)"),
    ("M4 — Evaluation, observability, handover", "Week 5 (W17)", "Claims Director (go-live decision)"),
]
PRICING_MODEL = "fixed floor + capped acceptance bonus (assumptions: 3-pricing-model)"
PRICING = [
    ("Pilot fee (fixed floor)", "M0–M4 set; cost $163,200 + 20% margin", "$204,000"),
    ("Acceptance bonus (capped)", "$9,000 per criterion 1–4 met at Week 5, counted by AutoSure CI", "up to $36,000"),
    ("Phase 2 option", "$2.50 per adjuster-confirmed decision within SLA (claims system count)", "cap $30,000/month"),
]
PAYMENT = ("Payment schedule: 30% on M1 acceptance · 40% on M3 (two-user test passed) · 30% on M4 acceptance; bonus paid "
           "with M4. Criterion 5 is a gate, never a bonus.")
IP = ("Agents & orchestration code: licensed to AutoSure perpetually; vendor keeps the generic harness. Prompts: AutoSure owns "
      "prompts tuned on its data. Fine-tunes / weights: none created in the pilot. Embeddings & derived data (indexes, eval "
      "labels): owned by AutoSure, deleted on exit with proof.")
DATA = [
    ("Claims, policies, documents (synthetic)", "AutoSure AWS, us-east-1 (S3, mocks)", "pilot + 30 days", "scripted teardown + inventory", "AWS"),
    ("Clause corpus + embeddings", "S3, OpenSearch", "pilot + 30 days", "index + bucket deleted", "AWS, OpenAI"),
    ("Prompts / model I/O (PII-masked)", "OpenAI API", "zero retention requested", "provider terms; no training", "OpenAI"),
    ("Audit log", "DynamoDB → CloudWatch", "1 year, append-only", "exported to AutoSure, deleted", "AWS"),
]
SECURITY = ("Synthetic data only until Security's controls review passes. Agents act on behalf of the signed-in adjuster (Cognito "
            "JWT, no standing credential); scope is enforced in the data boundary's code before any agent runs, never in a prompt; "
            "every call, including refusals, is audited. Secrets in AWS Secrets Manager; 24-hour breach notification.")
CHANGE = ("Written request → estimate (T-shirt size × risk buffer) → price → Claims Director + Procurement approval before "
          "work starts; logged in DECISIONS.md.")
ASSUMPTIONS = ("Security reviews the auth model by Week 3 (top risk R1); IT/Cloud grants permissions within 3 days; the Senior "
               "Adjuster gives 2 h/week to label review; AutoSure confirms the (A) baselines.")
EXIT = ("Scripted teardown with a verified inventory report, vendor access removed, audit log exported to AutoSure, "
        "handover pack (runbook, evals, dashboards) delivered.")
SIGN = {"Vendor:": "Susan Wellington (FDE) ________ date ____    Client: Claims Director, AutoSure ________ date ____"}


def set_text(p, text):
    """Replace a paragraph's text, keeping the first run's formatting."""
    runs = p.runs
    runs[0].text = text
    for r in runs[1:]:
        r._element.getparent().remove(r._element)


def set_label_value(p, label, value):
    """'Label:  [ placeholder ]' → keep the label run(s), replace the bracketed part."""
    full = p.text
    assert full.startswith(label), (full, label)
    keep, rest = [], []
    acc = ""
    for r in p.runs:
        (keep if len(acc) < len(label) else rest).append(r)
        acc += r.text
    if not rest:                     # label and placeholder share one run
        keep[0].text = f"{label}  {value}"
        return
    rest[0].text = value if keep[-1].text.endswith(" ") else " " + value
    for r in rest[1:]:
        r._element.getparent().remove(r._element)


def fill_table(t, rows, size=None):
    """Write rows into a table (row 0 = header), cloning the last data row as needed."""
    template_row = copy.deepcopy(t.rows[1]._tr)
    while len(t.rows) - 1 > len(rows):
        t._tbl.remove(t.rows[-1]._tr)
    while len(t.rows) - 1 < len(rows):
        t._tbl.append(copy.deepcopy(template_row))
    for r, values in zip(t.rows[1:], rows):
        for cell, v in zip(r.cells, values):
            p = cell.paragraphs[0]
            set_text(p, v)
            if size:
                for run in p.runs:
                    run.font.size = Pt(size)


def set_col_widths(t, inches):
    """Set table grid + every cell width (Word honours tcW; the grid keeps other renderers consistent)."""
    from docx.oxml.ns import qn
    from docx.shared import Inches
    grid = t._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), inches):
        gc.set(qn("w:w"), str(int(w * 1440)))
    for row in t.rows:
        for cell, w in zip(row.cells, inches):
            cell.width = Inches(w)


WIDTHS = [[3.75, 1.45, 1.7], [1.5, 2.3, 1.6, 1.55], [2.75, 1.45, 2.7], [1.75, 3.85, 1.3], [1.75, 1.55, 1.2, 1.35, 1.1]]


def main(template, out):
    d = docx.Document(template)
    P = d.paragraphs
    set_text(P[0], TITLE)
    P[1]._element.getparent().remove(P[1]._element)          # drop the "fill the brackets" instruction
    P = d.paragraphs
    for p in P[:6]:
        for label, value in HEADER.items():
            if p.text.startswith(label):
                set_label_value(p, label, value)
    by_start = lambda s: next(p for p in d.paragraphs if p.text.startswith(s))
    def nxt(heading):                     # the paragraph after a heading (compare XML elements, not wrappers)
        ps = d.paragraphs
        i = next(k for k, p in enumerate(ps) if p._element is by_start(heading)._element)
        return ps[i + 1]
    set_text(nxt("1. Background"), BACKGROUND)
    set_text(by_start("3. Acceptance criteria"), ACCEPT_HEADING)
    set_text(nxt("4. Out of scope"), OUT_OF_SCOPE)
    set_label_value(by_start("Pricing model:"), "Pricing model:", PRICING_MODEL)
    set_text(by_start("Payment schedule:"), PAYMENT)
    set_text(nxt("7. IP"), IP)
    set_text(nxt("9. Security"), SECURITY)
    set_text(nxt("10. Change control"), CHANGE)
    set_text(nxt("11. Assumptions"), ASSUMPTIONS)
    set_text(nxt("12. Exit"), EXIT)
    for p in d.paragraphs[-3:]:
        if p.text.startswith("Vendor:"):
            set_label_value(p, "Vendor:", SIGN["Vendor:"])
        elif p.text.startswith("Client:"):                 # both signatures share one line
            p._element.getparent().remove(p._element)
    T = d.tables
    for t, rows in zip(T, (SCOPE, ACCEPT, TIMELINE, PRICING, DATA)):
        fill_table(t, rows, size=9.5)
        for cell in t.rows[0].cells:                 # header row to the same size
            for r in cell.paragraphs[0].runs:
                r.font.size = Pt(9.5)
    for t, w in zip(T, WIDTHS):
        set_col_widths(t, w)
    # remove leftover empty spacer paragraphs after tables to stay within two pages
    for p in list(d.paragraphs):
        if not p.text.strip() and not p._element.xpath(".//w:drawing"):
            p._element.getparent().remove(p._element)
    # Filled content is upright (the template italicises placeholders to mean "fill me in"), and spacing
    # is tightened slightly so the SoW fits the brief's two pages. Fonts, sizes and table styles unchanged.
    for p in d.paragraphs:
        is_heading = any(r.font.size and r.font.size.pt >= 13 for r in p.runs)
        if is_heading:
            p.paragraph_format.space_before = Pt(5 if p.runs[0].font.size.pt < 18 else 0)
            p.paragraph_format.space_after = Pt(2)
        else:
            p.paragraph_format.space_after = Pt(3)
            for r in p.runs:
                r.italic = False
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.space_after = Pt(0)
    leftovers = [p.text for p in d.paragraphs if "[" in p.text and "]" in p.text]
    leftovers += [c.text for t in d.tables for r in t.rows for c in r.cells if "[" in c.text]
    assert not leftovers, f"unfilled placeholders remain: {leftovers}"
    d.core_properties.title = TITLE
    d.core_properties.author = "Susan Wellington"
    d.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
