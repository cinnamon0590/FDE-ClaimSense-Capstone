"""Build evidence/eval-report.html: one self-contained page (no scripts, no network) from the committed
result files, so the report always matches the evidence.

    python M2/evals/make_report.py
"""
import html
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVID = HERE.parent / "evidence"
ROW = re.compile(r"^\s+(PASS|FAIL)\s+(CS-\d+)\s+(\w+)\s+want (\S+)\s+got (\S+)\s+(\w+)\s*(\S*)")


def runs():
    out = []
    for p in sorted(EVID.glob("results-live-run*.txt")):
        rows = {m.group(2): m.groups() for line in p.read_text().splitlines() if (m := ROW.match(line))}
        out.append((p.name, rows, p.read_text()))
    return out


def metric(text, label):
    m = re.search(rf"^{re.escape(label)}.*$", text, re.M)
    return m.group(0) if m else ""


def main():
    rs = runs()
    stability = (EVID / "results-live-stability.txt").read_text() if (EVID / "results-live-stability.txt").exists() else ""
    fuzz = (EVID / "guardrail-fuzz.txt").read_text() if (EVID / "guardrail-fuzz.txt").exists() else ""
    cost = (EVID / "cost-table-live.md").read_text() if (EVID / "cost-table-live.md").exists() else ""
    gate = re.search(r"RELEASE GATE: (\w+)", stability)
    gate = gate.group(1) if gate else "n/a"
    ids = sorted({cid for _, rows, _ in rs for cid in rows})
    body = []
    for cid in ids:
        cells = [rows.get(cid) for _, rows, _ in rs]
        first = next(c for c in cells if c)
        ok = sum(1 for c in cells if c and c[0] == "PASS")
        tds = "".join(
            f'<td class="{"ok" if c and c[0] == "PASS" else "bad"}">{html.escape(c[4]) if c else "–"}'
            f'<small>{html.escape(c[5]) if c else ""}{(" · " + html.escape(c[6].replace(",", ", "))) if c and c[6] else ""}</small></td>'
            for c in cells)
        body.append(f'<tr><td><b>{cid}</b></td><td><span class="tag {first[2]}">{first[2]}</span></td>'
                    f'<td>{html.escape(first[3])}</td>{tds}<td class="{"ok" if ok == len(rs) else "warn"}">{ok}/{len(rs)}</td></tr>')
    heads = "".join(f"<th>Run {i + 1}</th>" for i in range(len(rs)))
    summary = "".join(f"<li>{html.escape(metric(t, 'SC-1'))}<br>{html.escape(metric(t, 'SC-5'))} · "
                      f"{html.escape(metric(t, 'cost:'))}</li>" for _, _, t in rs)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ClaimSense Eval Report</title>
<style>
:root{{--bg:#fbfbf9;--fg:#1d1d1b;--mute:#6b6b66;--line:#e4e2dc;--ok:#1f7a4d;--okbg:#e7f4ec;--bad:#a8321e;--badbg:#fbeae6;--warn:#8a5a00;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161614;--fg:#ecebe6;--mute:#a3a29b;--line:#34332f;--ok:#6fd39f;--okbg:#17301f;--bad:#ff9b85;--badbg:#3a1d17;--warn:#f0c060;--card:#1f1f1c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:18px;margin:32px 0 8px}} p.sub{{color:var(--mute);margin:0 0 20px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.kpi b{{display:block;font-size:24px}} .kpi span{{color:var(--mute);font-size:13px}}
.wrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}}
th{{color:var(--mute);font-weight:600}} td small{{display:block;color:var(--mute);font-size:11px}}
td.ok{{background:var(--okbg)}} td.bad{{background:var(--badbg);color:var(--bad)}} td.warn{{color:var(--warn);font-weight:700}}
.tag{{font-size:11px;padding:1px 7px;border-radius:9px;border:1px solid var(--line)}} .adversarial{{color:var(--bad)}}
pre{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow-x:auto;font-size:12px}}
</style></head><body><main>
<h1>ClaimSense M2 · live evaluation</h1>
<p class="sub">AutoSure Insurance motor claims · synthetic data · {len(ids)} cases × {len(rs)} live runs ·
pinned gpt-4o-2024-08-06 / gpt-4o-mini-2024-07-18 · every outcome is confirmed by a licensed adjuster</p>
<div class="kpis">
<div class="kpi"><b>{gate}</b><span>release gate (≥ 2/3 per case, adversarial 3/3)</span></div>
<div class="kpi"><b>{html.escape((re.search(r"stable \(same answer every run\): (\S+)", stability) or [None, "n/a"])[1])}</b><span>cases stable across runs</span></div>
<div class="kpi"><b>{html.escape((re.search(r"second-opinion holds[^:]*: (\d+ of \d+)", stability) or [None, "n/a"])[1])}</b><span>claim runs where the two drafts disagreed</span></div>
<div class="kpi"><b>{html.escape((re.search(r"v3: novel attacks caught (\S+)", fuzz) or [None, "n/a"])[1])}</b><span>never-seen injections caught (G1 + G1b, held-out v3)</span></div>
</div>
<h2>Per run</h2><ul>{summary}</ul>
<h2>Every case, every run</h2>
<div class="wrap"><table><thead><tr><th>Case</th><th>Category</th><th>Expected</th>{heads}<th>Correct</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div>
<h2>Stability (release gate)</h2><pre>{html.escape(stability)}</pre>
<h2>Guardrail fuzz suite</h2><pre>{html.escape(fuzz)}</pre>
<h2>Cost</h2><pre>{html.escape(cost)}</pre>
</main></body></html>"""
    (EVID / "eval-report.html").write_text(page)
    print(f"wrote {EVID / 'eval-report.html'} ({len(ids)} cases, {len(rs)} runs, release gate {gate})")


if __name__ == "__main__":
    main()
