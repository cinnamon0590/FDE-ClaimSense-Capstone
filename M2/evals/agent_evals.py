"""Per-agent evals (D-031): score EACH agent's own output against its golden labels, before code corrects it.

The end-to-end eval scores the final card, and code deliberately overrides some agent outputs (the
required-documents checklist, the fraud rule, routing priority). So the system can be right while an agent is
wrong. This scores every agent on its own, and reports how often code had to override it.

    python M2/evals/agent_evals.py                  # replay brain (recorded live outputs), $0
    python M2/evals/agent_evals.py --brain live     # fresh live run (~$0.80)
    python M2/evals/agent_evals.py --gate           # exit 1 if an agent regressed below its floor (the ratchet)

Writes M2/evidence/agent-evals.txt (replay) or agent-evals-live.txt.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from claimsense.cases import all_cases  # noqa: E402
from claimsense.pipeline import Pipeline, run_sync  # noqa: E402

LABELS = HERE / "agent-labels.json"
BAR = {"Document Intake": 0.90, "Coverage Check": 0.90, "Claim Assessment": 0.90, "Decision Draft": 0.90}   # the target
# The RATCHET: the measured share of fully-right cases (replay = recorded live outputs). CI fails if an agent drops
# below its floor. Raise a floor whenever an agent improves; never lower one to make CI pass.
#   2026-11-16 m2-v8: Intake 37/38 · Coverage 36/36 · Assessment 26/36 · Decision 33/36
#   2026-11-16 m2-v9 (D-032 fixes): every agent 100%, 0 code overrides -> floors raised to 1.0
FLOOR = {"Document Intake": 1.0, "Coverage Check": 1.0, "Claim Assessment": 1.0, "Decision Draft": 1.0}
FIELDS = {
    "Document Intake": ["documents_on_file", "missing_documents", "injury_indicated", "has_inconsistencies"],
    "Coverage Check": ["coverage_finding"],
    "Claim Assessment": ["fraud_suspected", "total_loss", "injury_exposure", "recommended_route"],
    "Decision Draft": ["outcome_and_route", "cites_required_clauses"],
}
OVERRIDES = {"Document Intake": ["intake.missing_documents"],
             "Claim Assessment": ["assessment.fraud_suspected", "assessment.recommended_route"]}


def observed(agent, out):
    """The agent's own answer for each scored field."""
    if agent == "Document Intake":
        return {"documents_on_file": sorted(out.get("documents_on_file", [])),
                "missing_documents": sorted(out.get("missing_documents", [])),
                "injury_indicated": out.get("injury_indicated"),
                "has_inconsistencies": bool(out.get("inconsistencies"))}
    if agent == "Coverage Check":
        return {"coverage_finding": out.get("coverage_finding")}
    if agent == "Claim Assessment":
        got = {k: out.get(k) for k in FIELDS[agent]}
        if got["recommended_route"] == "none":            # m2-v9 schema: an explicit "none" means no specialist
            got["recommended_route"] = None
        return got
    return {"outcome_and_route": (out.get("outcome"), out.get("route_to")),
            "cites": {c["source_id"] for c in out.get("citations", [])}}


def expected(agent, label):
    if agent == "Document Intake":
        return {k: (sorted(label[k]) if isinstance(label[k], list) else label[k]) for k in FIELDS[agent]}
    if agent == "Coverage Check":
        return {"coverage_finding": label["coverage_finding"]}
    if agent == "Claim Assessment":
        return dict(label)
    return {"outcome_and_route": (label["outcome"], label["route_to"]), "must_cite": set(label["must_cite"])}


def compare(agent, got, want):
    """{field: True/False} for one case."""
    if agent == "Decision Draft":
        (go, gr), (wo, wr) = got["outcome_and_route"], want["outcome_and_route"]
        # same rule as the end-to-end scorer (M0 score.fail_reason): the route is checked when the outcome is route
        return {"outcome_and_route": go == wo and (wo != "route" or gr == wr),
                "cites_required_clauses": want["must_cite"] <= got["cites"]}
    return {f: got[f] == want[f] for f in FIELDS[agent]}


def score(results, labels):
    """results: {case_id: pipeline result}. Returns (per-agent stats, per-case misses)."""
    stats = {a: {"cases": 0, "all_ok": 0, "fields": defaultdict(lambda: [0, 0]), "overrides": 0} for a in FIELDS}
    misses = []
    for cid, r in results.items():
        lab = labels[cid]
        outs = {e["name"]: e["output"] for e in r["events"] if e["kind"] == "agent_end"}
        override_names = [e["name"] for e in r["events"] if e["kind"] == "code_override"]
        for agent in lab.get("agents_run", []):
            st = stats[agent]
            st["cases"] += 1
            if agent not in outs:                  # an Intake injection hold: the right answer is to stop
                ok = r["decided_by"] == "guardrail_hold" and lab.get("note", "").startswith("injection hold")
                st["all_ok"] += ok
                st["fields"]["held_for_a_human"][0] += ok
                st["fields"]["held_for_a_human"][1] += 1
                if not ok:
                    misses.append((cid, agent, "held_for_a_human", "held", r["decided_by"]))
                continue
            got, want = observed(agent, outs[agent]), expected(agent, lab[agent])
            res = compare(agent, got, want)
            for f, ok in res.items():
                st["fields"][f][0] += ok
                st["fields"][f][1] += 1
                if not ok:
                    g = got.get(f, got.get("cites")) if f != "cites_required_clauses" else sorted(got["cites"])
                    w = want.get(f, sorted(want.get("must_cite", [])))
                    misses.append((cid, agent, f, w, g))
            st["all_ok"] += all(res.values())
            st["overrides"] += sum(1 for n in override_names if n in OVERRIDES.get(agent, []))
    return stats, misses


def report(stats, misses, brain, signoff):
    lines = [f"ClaimSense per-agent evals · brain={brain} · {time.strftime('%Y-%m-%d %H:%M:%S')}",
             "Each agent's OWN output, before code corrects it, against golden labels from the fixtures and code rules",
             f"(evals/agent-labels.json; Senior Adjuster sign-off: {signoff or 'PENDING'}).", ""]
    ok_all, held = True, True
    for agent, st in stats.items():
        n, rate = st["cases"], (st["all_ok"] / st["cases"] if st["cases"] else 0)
        passed, floor_ok = rate >= BAR[agent], rate >= FLOOR[agent] - 1e-9
        ok_all &= passed
        held &= floor_ok
        lines.append(f"{agent:<17} {st['all_ok']:>2}/{n:<2} cases fully right = {rate:5.1%}  (bar ≥ {BAR[agent]:.0%}; "
                     f"floor {FLOOR[agent]:.1%})  {'PASS' if passed else 'BELOW BAR'}"
                     + ("" if floor_ok else "  ✗ REGRESSED BELOW FLOOR")
                     + (f" · code overrode it on {st['overrides']} case(s)" if agent in OVERRIDES else ""))
        for f, (good, tot) in st["fields"].items():
            lines.append(f"    {f:<24} {good:>2}/{tot}")
    if misses:
        lines += ["", "Misses (case · agent · field · expected → got):"]
        lines += [f"  {cid}  {agent:<17} {f:<24} {w} → {g}" for cid, agent, f, w, g in misses]
    lines += ["", f"AGENT EVALS: {'PASS' if ok_all else 'BELOW BAR'} · ratchet: {'HELD' if held else 'REGRESSED'}"
              + ("" if ok_all else " (CI enforces the floor; the bar is the target)")]
    return "\n".join(lines), ok_all, held


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", choices=["replay", "live"], default="replay")
    ap.add_argument("--gate", action="store_true", help="exit 1 if any agent regressed below its floor")
    a = ap.parse_args(argv)
    data = json.loads(LABELS.read_text())
    pipe = Pipeline(brain=a.brain)
    results = {c["case_id"]: run_sync(pipe.run(c["claim"]["claim_id"], c["requesting_user"]["id"],
                                               run_id=f"agent-eval:{c['case_id']}:{time.time_ns()}"))
               for c in all_cases()}
    stats, misses = score(results, data["labels"])
    text, ok, held = report(stats, misses, a.brain, data["signoff"].get("by"))
    print(text)
    out = HERE.parent / "evidence" / ("agent-evals.txt" if a.brain == "replay" else "agent-evals-live.txt")
    out.write_text(text + "\n")
    return 0 if (held or not a.gate) else 1


if __name__ == "__main__":
    sys.exit(main())
