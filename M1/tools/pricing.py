"""ClaimSense AI × AutoSure Insurance: estimation and pricing model (stdlib only, $0).

Method adapted from the course's W14 companion notebook (sections 1–2: T-shirt sizing with
per-risk-class buffers, then three pricing models plus the recommended fixed floor + capped bonus).
The milestones, assumptions and bonus design here are ClaimSense-specific.

    python3 -I pricing.py            # prints the full model; output/pricing-results.txt is this output

Every number in the SoW and the pricing worksheet comes from this script. Change an assumption
here, re-run, and the documents' figures are regenerated from the output.
"""
from dataclasses import dataclass

# ── Assumptions (all stated; change here, re-run) ─────────────────────────────────────────────
BLENDED_DAY_RATE = 1_800          # USD per FDE-day, blended team rate (course's illustrative rate)
WORKING_DAYS_PER_WEEK = 5
ENGAGEMENT_WEEKS = 5              # fixed by the brief: five weekly milestones
FIXED_OVERHEAD = {                # pass-through and non-labour cost for the pilot
    "AWS pilot environment (5 weeks: ECS Fargate, API Gateway + Lambda, S3, OpenSearch, Cognito, CloudWatch)": 2_500,
    "OpenAI API tokens (build, 150-case eval runs in CI, demo)": 1_500,
    "Synthetic data + golden-label authoring (SME review hours)": 6_000,
    "Tooling, CI minutes, project management": 2_000,
}
DAYS_PER_YEAR = 220               # billable days, for the revenue-per-engineer sanity check
REV_PER_ENGINEER_BAND = (600_000, 1_000_000)   # course: ~3–5 accounts × ~$200K ≈ $0.6–1.0M / engineer / yr

TSHIRT = {"S": (3, 5), "M": (8, 12), "L": (15, 25), "XL": (30, 50)}   # day ranges (course standard)
RISK_BUFFER = {                   # multiplier on the HIGH end, per risk class (course standard)
    "low": 1.10,                  # well-understood work
    "integration": 1.35,          # boundary, identity provider, mocked legacy systems
    "access_politics": 1.80,      # Security/Compliance review, cloud permissions: the long pole
    "novel": 1.50,                # model judgment quality, eval design
}


@dataclass
class Milestone:
    name: str
    size: str
    risk_class: str
    why: str


MILESTONES = [
    Milestone("M0 Discovery & scoping (W13)", "S", "low",
              "charter, RACI, criteria, 20 eval cases (done)"),
    Milestone("M1 SoW, architecture, contracts, data, cloud (W14)", "M", "low",
              "paper + typed contracts + synthetic data + account setup"),
    Milestone("Controls review & access (Security, IT/Cloud)", "M", "access_politics",
              "auth model, data handling, IAM/ECR/ECS permissions: runs in parallel, gates M3"),
    Milestone("M2 Four agents, cited RAG, containers, CI gate (W15)", "L", "novel",
              "model judgment + retrieval quality are the unproven parts"),
    Milestone("M3 Data boundary, auth on every route, RBAC, audit (W16)", "L", "integration",
              "three systems behind one door, identity, two-user test"),
    Milestone("M4 150-case evals, dashboard, drill, runbook, handover (W17)", "L", "novel",
              "adversarial families, alarms, incident drill, operability without the author"),
]


def money(v):
    """Whole dollars, except small unit prices (e.g. $2.50 per decision)."""
    return f"${v:,.2f}" if abs(v) < 100 and v != int(v) else f"${v:,.0f}"


def rule(t):
    print("=" * 78); print(t); print("=" * 78)


# ── 1. Estimate ──────────────────────────────────────────────────────────────────────────────
def estimate(milestones, buffers=RISK_BUFFER):
    rows, lo, ex, hi = [], 0.0, 0.0, 0.0
    for m in milestones:
        l, h = TSHIRT[m.size]
        e, hb = (l + h) / 2, h * buffers[m.risk_class]
        rows.append((m, l, e, hb, buffers[m.risk_class]))
        lo, ex, hi = lo + l, ex + e, hi + hb
    return rows, lo, ex, hi


# ── 2. Price ─────────────────────────────────────────────────────────────────────────────────
def price_tm_cap(cost, markup=1.35, cap_multiple=1.25):
    exp = cost * markup
    return dict(model="T&M with a cap", expected=exp, low=cost * markup * 0.85, high=exp * cap_multiple,
                margin=(exp - cost) / exp, risk="Low for vendor: overruns billed up to the cap")


def price_fixed(cost, target_margin=0.30):
    p = cost / (1 - target_margin)
    return dict(model="Fixed price", expected=p, low=p, high=p, margin=(p - cost) / p,
                overrun_margin=(p - cost * 1.25) / p,
                risk="High for vendor: a 25% overrun eats most of the margin")


# Outcome bonus, designed for a SYNTHETIC-DATA pilot: production outcomes can't be counted until
# Security clears real data, so the pilot bonus pays per acceptance criterion met at the Week 5
# acceptance run. The run is executed by AutoSure's own CI on the submitted commit, so the client
# counts it, not the vendor. SC-5 (adversarial 100%) is a gate, never a bonus: safety is not for sale.
BONUS_CRITERIA = {
    "SC-1 decision accuracy (≥90% clear / ≥75% edge / ≥85% overall, model verdicts only)": 9_000,
    "SC-2 latency (p95 ≤ 90 s, p50 ≤ 45 s on ≥150 deployed runs)": 9_000,
    "SC-3 adjuster confirmation (≥80% confirmed unchanged, ≥50 claims)": 9_000,
    "SC-4 fraud routing (≥90% recall, ≤10% false-route)": 9_000,
}
EXPECTED_CRITERIA_MET = 3         # planning assumption: one criterion may slip in a 5-week pilot


def price_outcome(cost, floor_margin=0.05):
    floor = cost / (1 - floor_margin)
    pool = sum(BONUS_CRITERIA.values())
    per = pool / len(BONUS_CRITERIA)
    exp = floor + EXPECTED_CRITERIA_MET * per
    return dict(model="Outcome-based (thin floor + per-criterion bonus)", expected=exp, low=floor,
                high=floor + pool, margin=(exp - cost) / exp,
                risk="High variance: thin floor, most margin rides on criteria met")


def price_floor_plus_bonus(cost, floor_margin=0.20):
    floor = cost / (1 - floor_margin)
    pool = sum(BONUS_CRITERIA.values())
    per = pool / len(BONUS_CRITERIA)
    exp = floor + EXPECTED_CRITERIA_MET * per
    return dict(model="Fixed floor + capped acceptance bonus (RECOMMENDED)", expected=exp, low=floor,
                high=floor + pool, margin=(exp - cost) / exp, floor=floor, pool=pool,
                risk="Shared: floor covers cost + margin through the access fight; bonus aligns on results")


# Phase 2 (option, after Security clears production data): outcome pricing per adjuster-confirmed
# first decision delivered within the latency SLA, counted in the CLAIMS MANAGEMENT SYSTEM (the
# confirmation record), reconciled monthly against the audit log. Never the agent's own count.
PHASE2_FEE_PER_CONFIRMED_DECISION = 2.50
PHASE2_CLAIMS_PER_DAY = 450       # discovery assumption (A)
PHASE2_CONFIRMED_SHARE = 0.80     # = SC-3 target
PHASE2_MONTHLY_CAP = 30_000


def main():
    rows, lo, ex, hi = estimate(MILESTONES)
    overhead = sum(FIXED_OVERHEAD.values())
    cost = ex * BLENDED_DAY_RATE + overhead

    rule("1. ESTIMATE — ClaimSense AI pilot (T-shirt sizes → day ranges, buffer per risk class)")
    print(f"{'Milestone':62} {'Sz':2} {'risk class':15} {'low':>4} {'exp':>5} {'high*':>6}")
    print("-" * 100)
    for m, l, e, hb, b in rows:
        print(f"{m.name:62.62} {m.size:2} {m.risk_class:15} {l:4} {e:5.1f} {hb:6.1f}")
    print("-" * 100)
    print(f"{'TOTAL (FDE-days)':62} {'':2} {'':15} {lo:4.0f} {ex:5.0f} {hi:6.1f}")
    print("* high end carries the per-class buffer; the access/controls line carries the biggest (1.8x).")
    team = ex / (ENGAGEMENT_WEEKS * WORKING_DAYS_PER_WEEK)
    print(f"\nTeam implied by a {ENGAGEMENT_WEEKS}-week timeline: {ex:.0f} days ÷ {ENGAGEMENT_WEEKS * WORKING_DAYS_PER_WEEK}"
          f" working days ≈ {team:.1f} FDE-equivalents")
    print(f"Blended day rate {money(BLENDED_DAY_RATE)} → labour low / expected / high:"
          f" {money(lo * BLENDED_DAY_RATE)} / {money(ex * BLENDED_DAY_RATE)} / {money(hi * BLENDED_DAY_RATE)}")
    print("Fixed overhead:")
    for k, v in FIXED_OVERHEAD.items():
        print(f"  {money(v):>8}  {k}")
    print(f"EXPECTED DELIVERY COST (the floor every model must clear): {money(cost)}"
          f"  (high case: {money(hi * BLENDED_DAY_RATE + overhead)})")

    pess = dict(RISK_BUFFER, access_politics=2.20)
    _, _, _, hi2 = estimate(MILESTONES, pess)
    print(f"\nSensitivity: access buffer 1.8x → 2.2x moves the high case by {money((hi2 - hi) * BLENDED_DAY_RATE)}"
          " — the access assumption moves the number more than the code does.")

    rule("2. PRICE — same scope, four commercial wrappers (margin = (price − cost) ÷ price)")
    quotes = [price_tm_cap(cost), price_fixed(cost), price_outcome(cost), price_floor_plus_bonus(cost)]
    print(f"{'Model':52} {'low':>10} {'expected':>10} {'high':>10} {'margin':>7}")
    print("-" * 94)
    for q in quotes:
        print(f"{q['model']:52.52} {money(q['low']):>10} {money(q['expected']):>10} {money(q['high']):>10} {q['margin'] * 100:6.1f}%")
    print("-" * 94)
    for q in quotes:
        extra = f"  (margin after a 25% overrun: {q['overrun_margin'] * 100:.1f}%)" if "overrun_margin" in q else ""
        print(f"  {q['model']}: {q['risk']}{extra}")
    print("  Markup is not margin: the T&M 35% markup is a "
          f"{(1 - 1 / 1.35) * 100:.1f}% margin.")

    rec = quotes[-1]
    rule("3. RECOMMENDED — fixed floor + capped acceptance bonus")
    print(f"  Fixed floor (procurement's ceiling on the base): {money(rec['floor'])}  (cost + 20% margin)")
    print(f"  Acceptance bonus pool (capped): {money(rec['pool'])}, paid per criterion met at the Week 5 acceptance run:")
    for k, v in BONUS_CRITERIA.items():
        print(f"    {money(v):>8}  {k}")
    print("    SC-5 adversarial 100% is a GATE, not a bonus — failing it blocks acceptance outright.")
    print(f"  Expected revenue ({EXPECTED_CRITERIA_MET} of {len(BONUS_CRITERIA)} criteria): {money(rec['expected'])}"
          f"  · maximum: {money(rec['high'])}  · expected margin: {rec['margin'] * 100:.1f}%")
    print("  WHO COUNTS: AutoSure's own CI run of the eval suite on the submitted commit (brief acceptance #4);")
    print("  SC-2 from CloudWatch, SC-3 from adjuster confirmations in the claims system — never the agent's own report.")
    print("  Payment schedule: 30% on M1 acceptance · 40% on M3 (two-user test passed) · 30% on M4 acceptance; bonus on M4.")

    rule("4. SANITY CHECKS")
    margin_abs = rec["expected"] - cost
    print(f"  Price − cost − access buffer: {money(rec['expected'])} − {money(cost)} = {money(margin_abs)} margin"
          f" (access buffer already inside the high case; floor alone clears expected cost by {money(rec['floor'] - cost)})")
    print(f"  High-case cost {money(hi * BLENDED_DAY_RATE + overhead)} vs floor {money(rec['floor'])}: "
          + ("floor covers the buffered high case" if rec['floor'] >= hi * BLENDED_DAY_RATE + overhead
             else f"floor is {money(hi * BLENDED_DAY_RATE + overhead - rec['floor'])} short of the worst case — change control protects it"))
    rpe = rec["expected"] / ex * DAYS_PER_YEAR
    band = "inside" if REV_PER_ENGINEER_BAND[0] <= rpe <= REV_PER_ENGINEER_BAND[1] else "outside"
    print(f"  Revenue per engineer: {money(rec['expected'])} ÷ {ex:.0f} days × {DAYS_PER_YEAR} days/yr ≈ {money(rpe)}/yr"
          f" → {band} the $0.6–1.0M band")

    rule("5. PHASE 2 OPTION — production outcome pricing (only after Security clears real data)")
    monthly = PHASE2_CLAIMS_PER_DAY * 21 * PHASE2_CONFIRMED_SHARE * PHASE2_FEE_PER_CONFIRMED_DECISION
    print(f"  {money(PHASE2_FEE_PER_CONFIRMED_DECISION)} per adjuster-confirmed first decision delivered within the SLA,"
          f" capped at {money(PHASE2_MONTHLY_CAP)}/month")
    print(f"  At {PHASE2_CLAIMS_PER_DAY} claims/day (A) × 21 days × {PHASE2_CONFIRMED_SHARE:.0%} confirmed ≈ {money(monthly)}/month"
          f" → billed {money(min(monthly, PHASE2_MONTHLY_CAP))}/month")
    print("  Counted in the claims management system's confirmation records, reconciled monthly with the audit log.")


if __name__ == "__main__":
    main()
