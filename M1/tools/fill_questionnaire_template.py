"""Fill the course's security-questionnaire template with ClaimSense's answers.

    python fill_questionnaire_template.py /path/to/security-questionnaire.md.docx ../security-questionnaire.docx

Requires python-docx. Answers are parsed from ../security-questionnaire.md (single source of truth),
so the Markdown and the Word file can't disagree. Adds an answer column to the template's table,
switches to landscape for readability, and names the client (AutoSure) instead of Meridian.
"""
import re
import sys
from pathlib import Path

import docx
from docx.enum.section import WD_ORIENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from fill_sow_template import set_text

MD = Path(__file__).resolve().parent.parent / "security-questionnaire.md"


def answers():
    rows = {}
    for line in MD.read_text().splitlines():
        m = re.match(r"^\| (\d+) \| [^|]+ \| (.+) \|$", line)
        if m:
            rows[int(m.group(1))] = re.sub(r"\*\*(.+?)\*\*", r"\1", m.group(2)).replace("`", "")
    assert len(rows) == 15, f"expected 15 answers, parsed {len(rows)}"
    return rows


def borders(table):
    tbl_pr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4"); e.set(qn("w:color"), "8EAADB")
        b.append(e)
    tbl_pr.append(b)


def shade(cell, hex_fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    s = OxmlElement("w:shd")
    s.set(qn("w:val"), "clear"); s.set(qn("w:color"), "auto"); s.set(qn("w:fill"), hex_fill)
    tc_pr.append(s)


def main(template, out):
    ans = answers()
    d = docx.Document(template)
    sec = d.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Inches(0.6))

    P = [p for p in d.paragraphs if p.text.strip()]
    set_text(P[0], "AutoSure Vendor Security Questionnaire — 15 items · ClaimSense AI answers")
    for r in P[0].runs:
        r.font.size = Pt(16); r.bold = True
    set_text(P[1], "Every answer names the control, where it lives (code, integration layer or system of record, never the "
                   "model) and the proof a reviewer can re-run. Synthetic data only. Prepared by Susan Wellington (FDE), 2026-11-05.")

    t = d.tables[0]
    t.add_column(Inches(5.2))
    widths = [Inches(0.35), Inches(1.45), Inches(2.85), Inches(5.15)]
    hdr = t.rows[0].cells
    set_text(hdr[3].paragraphs[0], "Our answer: control · where it lives · proof") if hdr[3].paragraphs[0].runs else hdr[3].paragraphs[0].add_run("Our answer: control · where it lives · proof")
    for i, row in enumerate(t.rows):
        for c, w in zip(row.cells, widths):
            c.width = w
        if i == 0:
            for c in row.cells:
                shade(c, "D9E2F3")
                for run in c.paragraphs[0].runs:
                    run.bold = True; run.font.size = Pt(9.5)
            continue
        q = row.cells[2]
        set_text(q.paragraphs[0], q.text.replace("Meridian", "AutoSure").replace("a Reg E deadline", "a policy-period or coverage rule"))
        cell = row.cells[3]
        if cell.paragraphs[0].runs:
            set_text(cell.paragraphs[0], ans[i])
        else:
            cell.paragraphs[0].add_run(ans[i])
        for c in row.cells:
            for p in c.paragraphs:
                p.paragraph_format.space_after = Pt(0)
                for run in p.runs:
                    run.font.size = Pt(9)
    grid = t._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(w.inches * 1440)))
    borders(t)
    tbl_pr = t._tbl.tblPr                     # fixed layout at full landscape width, or Word autofits narrow
    for tag in ("w:tblW", "w:tblLayout"):
        for old in tbl_pr.findall(qn(tag)):
            tbl_pr.remove(old)
    tw = OxmlElement("w:tblW"); tw.set(qn("w:w"), str(int(sum(w.inches for w in widths) * 1440))); tw.set(qn("w:type"), "dxa")
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed")
    tbl_pr.append(tw); tbl_pr.append(lay)
    d.core_properties.title = "AutoSure vendor security questionnaire — ClaimSense AI answers"
    d.core_properties.author = "Susan Wellington"
    d.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
