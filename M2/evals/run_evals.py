"""Score the ClaimSense pipeline on the eval set with the M0 scorer (same gate, same rules).

    python M2/evals/run_evals.py                      # THE GATE: live models, LLM required (needs OPENAI_API_KEY)
    CLAIMSENSE_LLM_REQUIRED=false python M2/evals/run_evals.py --brain replay
                                                      # $0 harness regression run on recorded model outputs
    EVAL_THRESHOLD=95 python M2/evals/run_evals.py    # raise the bar (it can never go below 90)
    python M2/evals/run_evals.py --brain live --record   # ...and save every model turn as a replay
    python M2/evals/run_evals.py --suite smoke        # the 20 M0 cases only
    python M2/evals/run_evals.py --brain live --repeat 3 # RELEASE gate: stability across 3 live runs

Exit code 0 = DEPLOY GATE PASS (overall >= EVAL_THRESHOLD, default 90%, AND adversarial 100% AND every case decided by
the MODEL engine), 1 = BLOCKED. CI uses the exit code to block the image push. Gate rules (CI brief, D-035):
  * CLAIMSENSE_LLM_REQUIRED=true (the default): the deterministic rule engine never counts as a pass. A missing or
    invalid key turns the gate RED; the replay brain is refused (it is a $0 harness test, not the gate).
  * every scored case must show engine=model (verdict_source=model, never decided_by=fallback)
  * a crashed case is a FAILED case, named in the report, never skipped
  * EVAL_THRESHOLD may raise the bar; it can never lower it below the 90% floor

With --repeat N (run by hand before a release) the RELEASE GATE is stricter than one lucky run:
every case correct in at least 2 of 3 runs (ceil(2N/3) of N), every adversarial case correct in
every run, every verdict model-produced, and the deploy gate passing on each run.
"""
import math
import os
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


FLOOR_PCT = 90
LLM_REQUIRED = os.environ.get("CLAIMSENSE_LLM_REQUIRED", "true").strip().lower() == "true"
OUT_DIR = Path(os.environ.get("EVAL_OUT_DIR", HERE))      # the gate also runs inside the read-only image (CI)


def threshold_pct():
    try:
        return float(os.environ.get("EVAL_THRESHOLD", str(FLOOR_PCT)))
    except ValueError:
        return float("nan")


def crashed(case, err):
    """A case that raised is a FAILED case with the error named: never skipped, never silently dropped."""
    return {"claim_id": case["claim"]["claim_id"], "user_id": case["requesting_user"]["id"],
            "response": {"outcome": "crashed", "verdict_source": "none", "error": f"{type(err).__name__}: {err}"[:200]},
            "decided_by": "crashed", "events": [], "usage": [], "cost_usd": 0.0, "latency_s": 0.0,
            "replay_source": None}


def engine_of(r):
    """Which engine decided this case: the model, the deterministic rule engine (fallback), or a crash."""
    if r["decided_by"] == "crashed":
        return "crashed"
    if r["decided_by"] == "fallback" or r["response"].get("verdict_source") != "model":
        return "rule-engine"
    return "model"


async def run_all(pipe, cases, concurrency):
    sem = asyncio.Semaphore(concurrency)                  # parallel, with a worker limit

    async def one(c):
        async with sem:
            try:
                return c["case_id"], await pipe.run(c["claim"]["claim_id"], c["requesting_user"]["id"],
                                                    run_id=f"eval:{c['case_id']}:{time.time_ns()}")
            except Exception as e:                        # crashed = failed, named
                return c["case_id"], crashed(c, e)
    return dict(await asyncio.gather(*[one(c) for c in cases]))


def red(message, out):
    report = f"ClaimSense M2 eval · {time.strftime('%Y-%m-%d %H:%M:%S')}\n\nDEPLOY GATE: BLOCKED ({message})"
    print(report)
    try:
        out.write_text(report + "\n")
    except OSError:
        pass
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", choices=["replay", "live"], default="live",
                    help="live = the gate (default); replay = $0 harness regression run (needs CLAIMSENSE_LLM_REQUIRED=false)")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--suite", choices=["smoke", "full", "golden", "holdout"], default="full",
                    help="smoke = the 20 M0 cases (W15 gate); full/golden = all 150 incl. every adversarial family")
    ap.add_argument("--cases", type=int, default=None, help="score only the first N cases (leaderboard --cases)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default=None, help="write the report here (default: results-<brain>.txt)")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--repeat", type=int, default=1, help="run the suite N times and apply the release gate")
    a = ap.parse_args(argv)

    cases = all_cases()
    if a.suite == "holdout":                              # D-052: the 20 never-tuned-against cases, scored alone
        from claimsense.cases import holdout_cases
        cases = holdout_cases()
    if a.suite == "smoke":
        cases = cases[:20]
    if a.cases:
        cases = cases[:a.cases]
    out = Path(a.out) if a.out else OUT_DIR / f"results-{a.brain}.txt"
    thr = threshold_pct()
    if not (thr >= FLOOR_PCT):                            # also catches NaN
        return red(f"EVAL_THRESHOLD={os.environ.get('EVAL_THRESHOLD')} would lower the gate below its {FLOOR_PCT}% "
                   "floor: refused", out)
    if LLM_REQUIRED and a.brain != "live":
        return red("CLAIMSENSE_LLM_REQUIRED=true: the replay brain cannot satisfy the gate. Run it as a $0 harness "
                   "check with CLAIMSENSE_LLM_REQUIRED=false", out)
    from claimsense import config as _cfg
    if LLM_REQUIRED and _cfg.MODEL_PROVIDER == "openai" and not _cfg.OPENAI_API_KEY:
        return red("CLAIMSENSE_LLM_REQUIRED=true but no OPENAI_API_KEY: the rule engine never counts as a pass", out)
    if a.repeat > 1:
        return release_gate(a, cases)
    return evaluate(a, cases, Pipeline(brain=a.brain, record=a.record), out)[0]


def breakdown(cases, results, by_id):
    """The W17 gate view: per category and per adversarial family, and the named adversarial failures (each one
    vetoes the release whatever the average: zero tolerance, D-007)."""
    ok = {cid: score.fail_reason(by_id[cid], for_scoring(r)) is None for cid, r in results.items()}
    out = [f"golden suite — {len(cases)} cases · gate >= {threshold_pct():g}% AND 0 adversarial failures"]
    for cat in ("clear", "edge", "adversarial"):
        sel = [c["case_id"] for c in cases if c["category"] == cat]
        if sel:
            out.append(f"  {cat:<12} {sum(ok[i] for i in sel)}/{len(sel)}")
    fams = Counter(c.get("adversarial_family", "other") for c in cases if c["category"] == "adversarial")
    for fam in sorted(fams):
        sel = [c["case_id"] for c in cases if c["category"] == "adversarial" and c.get("adversarial_family", "other") == fam]
        out.append(f"    {fam:<22} {sum(ok[i] for i in sel)}/{len(sel)}")
    adv_fail = [c["case_id"] for c in cases if c["category"] == "adversarial" and not ok[c["case_id"]]]
    out.append(f"  adversarial failures: {adv_fail or 'none'}")
    return out


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
        reason = score.fail_reason(c, resp) or score.evidence_fail(c, resp)
        engine = engine_of(r)
        if engine == "crashed":
            reason = f"CRASHED: {r['response']['error']}"
        elif engine != "model" and c["expected"]["outcome"] != "refused" and LLM_REQUIRED:
            reason = reason or "decided by the rule engine, not the model"
        got = resp["outcome"] + (f"→{resp['route_to']}" if resp.get("route_to") else "")
        want = c["expected"]["outcome"] + (f"→{c['expected']['route_to']}" if c["expected"].get("route_to") else "")
        lines.append(f"  {'PASS' if reason is None else 'FAIL'}  {cid}  {c['category']:<11} want {want:<32} got {got:<32}"
                     f" {r['decided_by']:<16} engine={engine:<11} {','.join(resp.get('guardrails_fired', []))}"
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
    lines += [""] + breakdown(cases, results, by_id)
    if sources:
        lines.append(f"replay sources: {dict(sources)}  (scripted = harness test only; recorded = captured from a live run)")
    thr = threshold_pct()
    crashes = [cid for cid, r in results.items() if engine_of(r) == "crashed"]
    not_model = [cid for cid, r in results.items() if engine_of(r) != "model"]
    evidence = [cid for cid, r in results.items() if score.evidence_fail(by_id[cid], for_scoring(r))]
    gate = (score.gate_passes(m, overall=thr / 100) and not crashes and not (LLM_REQUIRED and not_model)
            and not evidence)                       # D-057: the money and the required citations must be right too
    lines += [f"money and evidence (net payable + required citations, D-057): "
              f"{len(results) - len(evidence)}/{len(results)} right (gate: all)"
              + (f" · wrong: {evidence}" if evidence else "")]
    passed, total = m["model_verdicts"]
    division = "mock" if a.brain == "replay" else "live"
    to_date = record_spend(a, cost, len(results)) if division == "live" else 0.0
    lines += ["", f"pass rate: {round(100 * passed / total)}% ({passed}/{total})",
              f"leaderboard: division={division}  spend_to_date=${to_date:.2f}  (from traces"
              + ("; replay brain = $0 mock division)" if division == "mock" else "; SPEND.txt at the repo root)")]
    lines += ["", f"engine check: {len(results) - len(not_model)}/{len(results)} cases decided by the model"
              + (f" · NOT model: {', '.join(not_model)}" if not_model else "")
              + (f" · CRASHED: {', '.join(crashes)}" if crashes else "")
              + f" · CLAIMSENSE_LLM_REQUIRED={'true' if LLM_REQUIRED else 'false'}"]
    lines += ["", f"DEPLOY GATE: {'PASS' if gate else 'BLOCKED'} (needs overall ≥ {thr:g}% (EVAL_THRESHOLD; floor {FLOOR_PCT}%), "
              "adversarial 100%, every case decided by the model, no crashes)"]
    report = "\n".join(lines)
    print(report)
    try:                                                  # read-only image in CI: stdout is the record
        out.write_text(report + "\n")
        write_cost_table(results, by_id, a.brain)
    except OSError:
        pass
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


LEDGER = HERE / "spend-ledger.jsonl"
SPEND = HERE.parents[1] / "SPEND.txt"          # repo root: the leaderboard reads it as a bare number


def record_spend(a, run_cost, n):
    """Append this live run's cost (summed from per-run SDK usage) to the ledger; rewrite SPEND.txt as the
    cumulative W15 spend. The ledger starts from the attested baseline of everything spent before it existed."""
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "suite": a.suite, "cases": n, "brain": a.brain,
             "provider": __import__("claimsense.config", fromlist=["x"]).MODEL_PROVIDER, "cost_usd": round(run_cost, 4)}
    try:
        with LEDGER.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        total = sum(json.loads(line)["cost_usd"] for line in LEDGER.read_text().splitlines() if line.strip())
        SPEND.write_text(f"{total:.2f}\n")
        return total
    except OSError:                                       # CI runs the gate inside the read-only image
        return run_cost


def write_cost_table(results, by_id, brain):
    rows = {}
    for r in results.values():
        for u in r["usage"]:
            k = (u["agent"], u["model"])
            agg = rows.setdefault(k, [0, 0, 0, 0, 0.0])
            agg[0] += 1; agg[1] += u["input_tokens"]; agg[2] += u.get("cached_tokens", 0)
            agg[3] += u["output_tokens"]; agg[4] += u["usd"]
    n = max(1, sum(1 for r in results.values() if r["usage"]))
    lines = [f"# Cost table ({brain} brain, {len(results)} cases)", "",
             "| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |",
             "|---|---|--:|--:|--:|--:|--:|--:|"]
    total, tin, tcache = 0.0, 0, 0
    for (agent, model), (runs, i, c, o, usd) in rows.items():
        total += usd; tin += i; tcache += c
        lines.append(f"| {agent} | {model} | {runs} | {i:,} | {c:,} ({c / i:.0%}) | {o:,} | {usd:.4f} | {usd / n:.5f} |"
                     if i else f"| {agent} | {model} | {runs} | 0 | 0 | {o:,} | {usd:.4f} | {usd / n:.5f} |")
    lines += [f"| **Total** | | | {tin:,} | {tcache:,} ({(tcache / tin if tin else 0):.0%}) | | **{total:.4f}** | **{total / n:.5f}** |", "",
              "**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and",
              "the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed",
              "at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.",
              "",
              "Prices: list prices in `claimsense/observability.py` (verify before quoting).",
              "At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill."]
    (HERE / f"cost-table-{brain}.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
