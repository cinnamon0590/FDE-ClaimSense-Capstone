"""Integration-topology selector for the ClaimSense pilot (stdlib only).

Selector logic taken from the course's W14 notebook §5 (point-to-point vs iPaaS vs event mesh);
inputs are AutoSure's pilot and expansion contexts.

    python3 -I topology.py
"""
from dataclasses import dataclass


@dataclass
class TopologyContext:
    num_systems: int
    realtime_required: bool
    governance_required: bool
    time_to_ship_weeks: int
    expected_growth: str


def select_topology(ctx):
    scores = {"P2P (point-to-point)": 0, "iPaaS (managed hub)": 0, "Event mesh (pub/sub)": 0}
    why = {k: [] for k in scores}
    if ctx.num_systems <= 4:
        scores["P2P (point-to-point)"] += 2; why["P2P (point-to-point)"].append("few systems (<=4)")
    else:
        scores["iPaaS (managed hub)"] += 2; why["iPaaS (managed hub)"].append("many systems -> N^2 wiring")
    if ctx.time_to_ship_weeks <= 12:
        scores["P2P (point-to-point)"] += 2; why["P2P (point-to-point)"].append("tight ship deadline")
    if ctx.realtime_required:
        scores["Event mesh (pub/sub)"] += 3; why["Event mesh (pub/sub)"].append("real-time / event-driven flows")
    else:
        scores["P2P (point-to-point)"] += 1; why["P2P (point-to-point)"].append("synchronous request/reply")
    if ctx.governance_required:
        scores["iPaaS (managed hub)"] += 2; why["iPaaS (managed hub)"].append("central governance needed")
    if ctx.expected_growth == "high":
        for k in ("iPaaS (managed hub)", "Event mesh (pub/sub)"):
            scores[k] += 1; why[k].append("high growth ahead")
    return max(scores, key=scores.get), scores, why


def report(title, ctx):
    pick, sc, why = select_topology(ctx)
    print("=" * 78); print(title); print("=" * 78)
    for k in sc:
        print(f"  {k:24} score={sc[k]}   ({'; '.join(why[k]) or '—'})")
    print(f"  → {pick}")
    return pick


if __name__ == "__main__":
    report("ClaimSense pilot: 3 systems, request/reply first pass, 5-week ship",
           TopologyContext(3, False, False, 5, "high"))
    print("  Implementation: point-to-point, but every call funnels through the ONE data boundary (MCP server),")
    print("  so the pilot still has a single governed door for RBAC + audit.\n")
    report("Expansion: FNOL events pushed from claims mgmt, + payments, SIU case mgmt, telematics, repair network, CRM",
           TopologyContext(8, True, True, 26, "high"))
    print("  Revisit trigger (DECISIONS D-010): when a 5th system joins the boundary or claims management starts")
    print("  pushing FNOL events, re-run this selector. At full expansion it picks a managed hub: AutoSure's iPaaS")
    print("  if it has one, otherwise EventBridge + Step Functions on AWS, still behind the same governed door.")
