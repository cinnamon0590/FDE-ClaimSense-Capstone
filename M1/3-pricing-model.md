# M1 Deliverable 3: Pricing model with the underlying assumptions

**Engagement:** ClaimSense AI · AutoSure Insurance (motor) · **FDE:** Susan Wellington · **Date:** 2026-11-05

Formal worksheet (course template): [`3-pricing-model.docx`](3-pricing-model.docx). Every number
here is computed by [`tools/pricing.py`](tools/pricing.py) (full output:
[`tools/output/pricing-results.txt`](tools/output/pricing-results.txt)). Change an assumption, re-run,
and the numbers update. The method follows the Week 14 notebook: cost first, then price; the price
has to clear the cost.

## Assumptions (all stated)

| Assumption | Value | Why |
|---|---|---|
| Blended day rate | **$1,800 per FDE-day** | Course illustrative rate; re-price with the real rate card |
| Engagement length | **5 weeks** (fixed by the brief) | One milestone per week |
| T-shirt day ranges | S 3–5 · M 8–12 · L 15–25 · XL 30–50 | Course standard |
| Risk buffers (on the high end) | low 1.10 · integration 1.35 · **access politics 1.80** · novel 1.50 | Data access is the long pole at a regulated insurer |
| Fixed overhead | **$12,000**: AWS pilot environment $2,500 · OpenAI tokens $1,500 · synthetic data + golden-label authoring $6,000 · tooling/CI/PM $2,000 | Non-labour costs the price must clear |
| Bonus criteria expected to be met | **3 of 4** | One may slip in a 5-week pilot |
| Revenue-per-engineer band | $0.6–1.0M per engineer per year | Course sanity check (≈ 3–5 accounts × ~$200K) |
| Phase 2 volume | 450 claims/day **(A)**, 80% confirmed | Discovery assumption; = SC-3 target |

## 1. Estimate: the cost basis

| Milestone | Size | Risk class | Days low / exp / high* |
|---|:-:|---|---|
| M0 Discovery & scoping (W13) | S | low | 3 / 4 / 5.5 |
| M1 SoW, architecture, contracts, data, cloud (W14) | M | low | 8 / 10 / 13.2 |
| Controls review & access (Security, IT/Cloud) | M | **access politics (1.8×)** | 8 / 10 / 21.6 |
| M2 Four agents, cited retrieval, containers, CI gate (W15) | L | novel | 15 / 20 / 37.5 |
| M3 Data boundary, auth, RBAC, audit (W16) | L | integration | 15 / 20 / 33.8 |
| M4 150-case evals, dashboard, drill, runbook, handover (W17) | L | novel | 15 / 20 / 37.5 |
| **Total** | | | **64 / 84 / 149.1** |

\*The high end carries the per-class buffer. 84 expected days over 25 working days ≈ **3.4 FDE-equivalents**.

**Cost (labour + $12,000 overhead): low $127,200 · expected $163,200 · high $280,290.**
Sensitivity: raising only the access buffer from 1.8× to 2.2× adds **$8,640** to the high case. The access
assumption moves the number more than the code does.

## 2. Access-politics buffer
The controls review runs **in parallel** with the build, because the architecture starts on synthetic
data. A slow review delays M3 (the data boundary), not M2 (the agents). It carries the largest buffer
(1.8×, high case 21.6 days). It's the top risk in the register (R1), and Security is consulted in M1 so
it doesn't first see the auth model in capstone Week 4.

## 3. Four ways to price the same scope

| Model | Low | Expected | High | Margin | Risk |
|---|---|---|---|---|---|
| T&M with a cap | $187,272 | $220,320 | $275,400 | 25.9% | Low for vendor; the client carries overruns up to the cap |
| Fixed price | $233,143 | $233,143 | $233,143 | 30.0% | High for vendor: a 25% overrun cuts margin to 12.5% |
| Outcome-based (thin floor) | $171,789 | $198,789 | $207,789 | 17.9% | High variance: most margin rides on criteria met |
| **Fixed floor + capped acceptance bonus** | **$204,000** | **$231,000** | **$240,000** | **29.4%** | **Shared; recommended** |

Markup isn't margin: a 35% markup on cost is a **25.9%** margin.

## 4. Recommendation: fixed floor + capped acceptance bonus

- **Fixed floor $204,000** (cost + 20% margin). Procurement gets its ceiling, and the floor covers
  cost through the access fight.
- **Bonus up to $36,000:** **$9,000 for each of acceptance criteria 1–4** (decision accuracy,
  latency, adjuster confirmation, fraud routing) met at the Week 5 acceptance run.
- **Criterion 5 (zero harm) is a gate, never a bonus.** Failing it blocks acceptance outright;
  safety isn't for sale.
- **Who counts the outcomes:** AutoSure's own CI runs the eval suite on the submitted commit.
  Latency comes from CloudWatch, and confirmations from the claims system's records, never the agent's own report.
- **Why an acceptance bonus rather than a per-claim one:** the pilot runs on synthetic data, so real
  claim outcomes can't be counted until Security clears production data. Per-claim outcome pricing
  is therefore the **Phase 2 option**.
- **Payment schedule:** 30% on M1 acceptance · 40% on M3 (two-user test passed) · 30% on M4
  acceptance; bonus paid with M4.

## 5. Margin check
- Price − cost = $231,000 − $163,200 = **$67,800 expected margin (29.4%)**. The floor alone clears
  expected cost by $40,800.
- The access buffer sits in the high case ($280,290), $76,290 above the floor. **Change control**
  and **milestone payments** protect that tail.
- Revenue per engineer: $231,000 ÷ 84 days × 220 ≈ **$605,000/yr**, inside the $0.6–1.0M band.
  The pilot clears cost + buffer + margin, so **no scope cut is needed**.

## 6. Phase 2 option (production, after Security clears real data)
**$2.50 per adjuster-confirmed first decision delivered within the SLA**, capped at $30,000/month.
At 450 claims/day **(A)** × 21 days × 80% confirmed ≈ **$18,900/month**. Counted in the claims
management system's confirmation records and reconciled monthly against the audit log.
