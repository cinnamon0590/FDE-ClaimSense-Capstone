"""Write the client's label spot-check sheet (D-046): 15 sampled non-adversarial cases + every new adversarial case.

    python3 -I M4/evals/make_label_review.py      # writes M4/evals/label-review.md
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
cases = json.loads((HERE / "cases-m4.json").read_text())["cases"]
ordinary = [c for c in cases if c["category"] != "adversarial"]
sample = sorted(random.Random(4417).sample(ordinary, 15), key=lambda c: c["case_id"])
adv = [c for c in cases if c["category"] == "adversarial"]
by_id = {c["case_id"]: c for c in cases}
labels = json.loads((HERE.parents[1] / "M2" / "evals" / "agent-labels.json").read_text())["labels"]
coverage_new = [(cid, e["Coverage Check"]) for cid, e in labels.items()
                if cid in by_id and (e.get("Coverage Check") or {}).get("signoff_required")]


def row(c):
    cl, p, e = c["claim"], c["policy"], c["expected"]
    want = e["outcome"] + (f" → {e['route_to']}" if e.get("route_to") else "")
    if e.get("net_payable") is not None:
        want += f" (net ${e['net_payable']:,})"
    facts = (f"{cl['loss_type']} {cl['incident_date']} · cover {'/'.join(p['coverage'])} {p['term_start']}→{p['term_end']}"
             f" · ACV ${cl['acv']:,} est ${cl['repair_estimate']:,} ded ${p['deductible']:,} · fraud {cl['fraud_risk_score']}"
             + (" · injury" if cl["injury_reported"] else "") + (f" · time {cl['incident_time']}" if cl.get("incident_time") else "")
             + (f" · prior claims {cl['prior_claims_24m']}" if cl.get("prior_claims_24m") else "")
             + (f" · renewal submitted {p['renewal_submitted']}, not processed" if p.get("renewal_submitted") else "")
             + f" · docs {', '.join(c['documents'])}"
             + (f" · requested by **{c['requesting_user']['id']}** ({c['requesting_user']['group']})" if c["requesting_user"]["id"] != "alice" else ""))
    trap = "; ".join(f"*{k}*: “{v}”" for k, v in (c.get("document_facts") or {}).items())
    if c["category"] == "adversarial" and "narrative" not in trap and any(w in cl["narrative"] for w in ("AI", "CLM-", "decode", "queue")):
        trap = (trap + "; " if trap else "") + f"*narrative*: “{cl['narrative']}”"
    guard = f" · guardrail must fire: `{e['guardrail']}`" if e.get("guardrail") else ""
    return (f"| {c['case_id']} | {c['title']} | {facts}" + (f"<br>{trap}" if trap else "") +
            f" | **{want}**{guard}<br>cite {', '.join(e.get('must_cite', [])) or '—'} | {c['rationale']} | ☐ OK ☐ change |")


head = "| Case | Scenario | Facts (and the trap, for adversarial cases) | Expected first decision | Why | Your call |\n|---|---|---|---|---|---|"
fams = sorted({c["adversarial_family"] for c in adv})
fam_counts = ", ".join(f"{f} {sum(c['adversarial_family'] == f for c in adv)}" for f in fams)
md = [
    "# Label spot-check: the 110 new eval cases (M4)",
    "",
    "**What to do:** read each row and tick **OK** if the expected decision is what a senior adjuster would want "
    "the co-pilot to draft, or **change** with a note. Labels follow the engagement's rules, in this order: deny on "
    "an exclusion or out of term → senior adjuster when cover is unresolved → specialist route (fraud, then injury, "
    "then total loss) → senior adjuster over $25,000 or with documents missing → approve. Fraud *indicators* (late "
    "night, prior claims) never refer a claim on their own. Net payable = repair (or ACV for a total loss) − deductible.",
    "",
    f"- **Part A:** 15 cases sampled at random from the 76 new clear/edge cases (seed 4417).",
    f"- **Part B:** all {len(adv)} new adversarial cases ({fam_counts}).",
    "",
    f"- **Part C:** {len(coverage_new)} coverage judgments on the new referral and senior-adjuster cases.",
    "",
    "Reply in chat with “labels OK” or the case IDs to change. Once signed off, the labels lock and the release gate runs.",
    "",
    "## Part A: sampled clear and edge cases", "", head, *[row(c) for c in sample], "",
    "## Part B: every new adversarial case", "", head, *[row(c) for c in adv], "",
    "## Part C: coverage judgments to sign off (per-agent labels, as you did for the first 9)", "",
    "For each referral or senior-adjuster case, the Coverage agent is scored on whether cover is **covered** or "
    "**ambiguous**. Tick OK if you agree.", "",
    "| Case | Scenario | Coverage label | Reason | Your call |", "|---|---|---|---|---|",
    *[f"| {cid} | {by_id[cid]['title']} | **{lab['coverage_finding']}** | {lab['basis']} | ☐ OK ☐ change |"
      for cid, lab in coverage_new], "",
]
(HERE / "label-review.md").write_text("\n".join(md) + "\n")
print(f"label-review.md: {len(sample)} sampled + {len(adv)} adversarial + {len(coverage_new)} coverage labels")
