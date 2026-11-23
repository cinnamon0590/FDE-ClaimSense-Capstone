"""Score the llm-rubric judge against golden labels (W17 notebook §5b): per-class agreement, overall agreement,
Cohen's kappa (agreement corrected for chance; >= 0.8 before a judge may sit in a gate) and pass^k (the share of
cards the judge graded identically in every repeat).

    python3 -I M4/evals/promptfoo/judge_calibration.py    # reads ../../evidence/judge-calibration-results.json
"""
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
labels = {l["id"]: l for l in json.loads((HERE / "calibration-labels.json").read_text())}
raw = json.loads((HERE.parents[1] / "evidence" / "judge-calibration-results.json").read_text())
rows = raw["results"]["results"] if isinstance(raw["results"], dict) else raw["results"]

verdicts = defaultdict(list)
for r in rows:
    tid = (r.get("testCase") or {}).get("description") or r.get("description")
    verdicts[tid].append("PASS" if (r.get("gradingResult") or {}).get("pass") else "FAIL")

first = {t: v[0] for t, v in verdicts.items()}
pairs = [(labels[t]["golden"], first[t]) for t in first]
n = len(pairs)
agree = sum(g == j for g, j in pairs)
by_class = {c: (sum(1 for g, j in pairs if g == c and j == c), sum(1 for g, _ in pairs if g == c)) for c in ("PASS", "FAIL")}
po = agree / n
pg = sum(g == "PASS" for g, _ in pairs) / n
pj = sum(j == "PASS" for _, j in pairs) / n
pe = pg * pj + (1 - pg) * (1 - pj)
kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
k = min(len(v) for v in verdicts.values())
consistent = sum(len(set(v)) == 1 for v in verdicts.values())
misses = [f"{t} ({labels[t]['kind']}): golden {labels[t]['golden']}, judge {first[t]}" for t in first if labels[t]["golden"] != first[t]]

lines = [
    "ClaimSense judge calibration: llm-rubric (openai gpt-4o-2024-08-06) vs golden labels",
    f"cards: {n} ({by_class['PASS'][1]} genuine = PASS, {by_class['FAIL'][1]} corrupted = FAIL) · repeats per card: {k}",
    "",
    f"agreement on golden-PASS cards: {by_class['PASS'][0]}/{by_class['PASS'][1]}",
    f"agreement on golden-FAIL cards: {by_class['FAIL'][0]}/{by_class['FAIL'][1]}   (a missed FAIL = the judge passed a bad card)",
    f"overall agreement: {agree}/{n} = {po:.1%}",
    f"Cohen's kappa: {kappa:.2f}   (bar >= 0.80 before a judge may sit in a gate)",
    f"pass^{k} (same verdict in every repeat): {consistent}/{len(verdicts)}",
    "",
    "disagreements: " + ("; ".join(misses) if misses else "none"),
    "",
    f"VERDICT: {'TRUSTED for the rubric grader' if kappa >= 0.8 and consistent == len(verdicts) else 'NOT TRUSTED: fix the rubric or the judge before it gates anything'}",
]
text = "\n".join(lines)
print(text)
(HERE.parents[1] / "evidence" / "judge-calibration.txt").write_text(text + "\n")
