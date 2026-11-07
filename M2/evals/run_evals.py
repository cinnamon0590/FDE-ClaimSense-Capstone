"""Score the ClaimSense pipeline on the eval set with the M0 scorer (same gate, same rules).

    python M2/evals/run_evals.py                      # replay brain: $0, no key, deterministic (CI)
    python M2/evals/run_evals.py --brain live         # live OpenAI models (needs OPENAI_API_KEY)
    python M2/evals/run_evals.py --brain live --record   # ...and save every model turn as a replay
    python M2/evals/run_evals.py --suite smoke        # the 20 M0 cases only
    python M2/evals/run_evals.py --brain live --repeat 3 # RELEASE gate: stability across 3 live runs

Exit code 0 = DEPLOY GATE PASS (overall >= 85% AND adversarial 100% AND every verdict model-produced),
1 = BLOCKED. CI uses the exit code to block the image push.

With --repeat N (run by hand before a release) the RELEASE GATE is stricter than one lucky run:
every case correct in at least 2 of 3 runs (ceil(2N/3) of N), every adversarial case correct in
every run, every verdict model-produced, and the deploy gate passing on each run.
"""
import math
import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from claimsense._m1 import score  # noqa: E402
from claimsense.cases import all_cases  # noqa: E402
from claimsense.pipeline import Pipeline, run_sync  # noqa: E402


def for_scoring(result):
    """Adapt a pipeline response to the scorer's view (citations as a list of source IDs)."""
    r = dict(result["response"])
    if "citations" in r:
        r["citations"] = [c["source_id"] for c in r["citations"]]
        r["returns_claim_data"] = True
    return r


async def run_all(pipe, cases, concurrency):
    sem = asyncio.Semaphore(concurrency)

    async def one(c):
        async with sem:
            return c["case_id"], await pipe.run(c["claim"]["claim_id"], c["requesting_user"]["id"],
                                                run_id=f"eval:{c['case_id']}:{time.time_ns()}")
    return dict(await asyncio.gather(*[one(c) for c in cases]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", choices=["replay", "live"], default="replay")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--suite", choices=["smoke", "full"], default="full")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default=None, help="write the report here (default: results-<brain>.txt)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--repeat", type=int, default=1, help="run the suite N times and apply the release gate")
    a = ap.parse_args(argv)

    cases = all_cases()
    if a.suite == "smoke":
        cases = cases[:20]
    if a.repeat > 1:
        return release_gate(a, cases)
    return evaluate(a, cases, Pipeline(brain=a.brain, record=a.record),
                    Path(a.out) if a.out else HERE / f"results-{a.brain}.txt")[0]


def evaluate(a, cases, pipe, out, label=""):
    """One pass over the suite. Returns (exit code, per-case pass dict, results)."""
    t0 = time.time()
    results = run_sync(run_all(pipe, cases, a.concurrency))
    wall = time.time() - t0
    by_id = {c["case_id"]: c for c in cases}
    m = score.score(lambda c: for_scoring(results[c["case_id"]]), cases)

    lines = [f"ClaimSense M2 eval{label} · brain={a.brain} · suite={a.suite} · {len(cases)} cases · "
             f"{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for cid, r in results.items():
        c = by_id[cid]
        resp = for_scoring(r)
        reason = score.fail_reason(c, resp)
        got = resp["outcome"] + (f"→{resp['route_to']}" if resp.get("route_to") else "")
        want = c["expected"]["outcome"] + (f"→{c['expected']['route_to']}" if c["expected"].get("route_to") else "")
        lines.append(f"  {'PASS' if reason is None else 'FAIL'}  {cid}  {c['category']:<11} want {want:<32} got {got:<32}"
                     f" {r['decided_by']:<16} {','.join(resp.get('guardrails_fired', []))}"
                     + (f"  ({reason})" if reason else ""))
    lat = sorted(r["latency_s"] for r in results.values())
    p95 = lat[min(len(lat) - 1, int(round(0.95 * len(lat))) - 1)] if lat else 0
    cost = sum(r["cost_usd"] for r in results.values())
    decided = Counter(r["decided_by"] for r in results.values())
    sources = Counter(r["replay_source"] for r in results.values() if r["replay_source"])
    fallback_share = decided.get("fallback", 0) / len(results)
    pct = score.pct
    lines += ["",
              f"SC-1 decision accuracy   clear {pct(m['clear'])} (target ≥ 90%) · edge {pct(m['edge'])} (target ≥ 75%)"
              f" · overall {pct(m['overall'])}",
              f"     verdicts model-produced {pct(m['model_produced'])} (gate: 100%) · correct AND model-produced {pct(m['model_verdicts'])} · fallback share {fallback_share:.0%}"
              f" · decided_by {dict(decided)}",
              f"SC-2 latency p95 {p95:.2f}s per claim (target < 90s) · median {statistics.median(lat):.2f}s · wall {wall:.1f}s",
              f"SC-3 day-one proxy: confirmable as written {pct(m['confirmable'])}",
              f"SC-4 fraud recall {pct(m['fraud_recall'])} (target ≥ 90%) · false-route rate {pct(m['false_route'])} (target ≤ 10%)",
              f"SC-5 adversarial pass {pct(m['adversarial'])} (gate: 100%)",
              f"cost: ${cost:.4f} total · ${cost / len(results):.5f} per claim"
              + (" (replay: token counts from the replay files; scripted ones are estimates)" if a.brain == "replay" else ""),
              ]
    if sources:
        lines.append(f"replay sources: {dict(sources)}  (scripted = harness test only; recorded = captured from a live run)")
    gate = score.gate_passes(m)
    lines += ["", f"DEPLOY GATE: {'PASS' if gate else 'BLOCKED'} (needs overall ≥ 85%, adversarial 100%, model verdicts only)"]
    report = "\n".join(lines)
    print(report)
    out.write_text(report + "\n")
    write_cost_table(results, by_id, a.brain)
    passed = {cid: score.fail_reason(by_id[cid], for_scoring(r)) is None for cid, r in results.items()}
    return (0 if gate else 1), passed, results


def release_gate(a, cases):
    """Stability across N runs (the first may record replays). Writes results-<brain>-stability.txt."""
    n, runs = a.repeat, []
    for i in range(n):
        out = HERE / f"results-{a.brain}-run{i + 1}.txt"
        rc, passed, results = evaluate(a, cases, Pipeline(brain=a.brain, record=a.record and i == 0), out,
                                       label=f" · run {i + 1}/{n}")
        runs.append((rc, passed, results))
    need = math.ceil(2 * n / 3)
    by_id = {c["case_id"]: c for c in cases}
    lines = [f"ClaimSense M2 RELEASE gate · brain={a.brain} · {len(cases)} cases × {n} runs · {time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"model {runs[0][2][cases[0]['case_id']]['response'].get('model', {}).get('name', '?')} · "
             f"needs every case ≥ {need}/{n}, adversarial {n}/{n}, every verdict model-produced, deploy gate on each run", ""]
    unstable, weak, flips = [], [], 0
    for c in cases:
        cid = c["case_id"]
        ok = sum(r[1][cid] for r in runs)
        got = [r[2][cid]["response"]["outcome"] + (f"→{r[2][cid]['response']['route_to']}" if r[2][cid]["response"].get("route_to") else "")
               for r in runs]
        holds = sum(r[2][cid]["decided_by"] == "consistency_hold" for r in runs)
        stable = len(set(got)) == 1
        flips += not stable
        bar = n if c["category"] == "adversarial" else need
        if ok < bar:
            weak.append(cid)
        if not stable or ok < n or holds:
            unstable.append(cid)
            lines.append(f"  {'WEAK' if ok < bar else 'OK  '}  {cid}  {c['category']:<11} correct {ok}/{n}  outcomes {' | '.join(got)}"
                         + (f"  ({holds} run(s) sent to a human: drafts disagreed)" if holds else ""))
    produced = all(r[2][cid]["response"].get("verdict_source") == "model" for r in runs for cid in r[2])
    each = [r[0] == 0 for r in runs]
    holds_total = sum(r[2][cid]["decided_by"] == "consistency_hold" for r in runs for cid in r[2])
    cost = sum(x["cost_usd"] for r in runs for x in r[2].values())
    lines += ["" if unstable else "  every case gave the same correct answer in every run",
              f"stable (same answer every run): {len(cases) - flips}/{len(cases)} · correct every run: "
              f"{sum(all(r[1][c['case_id']] for r in runs) for c in cases)}/{len(cases)}",
              f"per-run accuracy: {' · '.join(f'{sum(r[1].values())}/{len(cases)}' for r in runs)} · deploy gate per run: "
              f"{' · '.join('PASS' if e else 'BLOCKED' for e in each)}",
              f"second-opinion holds (drafts disagreed → senior adjuster): {holds_total} of {n * len(cases)} claim runs",
              f"cost: ${cost:.4f} for {n} runs · ${cost / (n * len(cases)):.5f} per claim", ""]
    gate = not weak and produced and all(each)
    lines.append(f"RELEASE GATE: {'PASS' if gate else 'BLOCKED'}" + (f" (below the bar: {', '.join(weak)})" if weak else ""))
    report = "\n".join(lines)
    print(report)
    (HERE / f"results-{a.brain}-stability.txt").write_text(report + "\n")
    return 0 if gate else 1


def write_cost_table(results, by_id, brain):
    rows = {}
    for r in results.values():
        for u in r["usage"]:
            k = (u["agent"], u["model"])
            agg = rows.setdefault(k, [0, 0, 0, 0.0])
            agg[0] += 1; agg[1] += u["input_tokens"]; agg[2] += u["output_tokens"]; agg[3] += u["usd"]
    n = max(1, sum(1 for r in results.values() if r["usage"]))
    lines = [f"# Cost table ({brain} brain, {len(results)} cases)", "",
             "| Agent | Model | Runs | Input tokens | Output tokens | USD | USD per claim |", "|---|---|--:|--:|--:|--:|--:|"]
    total = 0.0
    for (agent, model), (runs, i, o, usd) in rows.items():
        total += usd
        lines.append(f"| {agent} | {model} | {runs} | {i:,} | {o:,} | {usd:.4f} | {usd / n:.5f} |")
    lines += [f"| **Total** | | | | | **{total:.4f}** | **{total / n:.5f}** |", "",
              "Prices: OpenAI list prices in `claimsense/observability.py` (verify before quoting).",
              "At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill."]
    (HERE / f"cost-table-{brain}.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
