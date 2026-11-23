# Cost table (live brain, 150 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-2024-08-06 | 145 | 406,803 | 215,552 (53%) | 28,035 | 1.0279 | 0.00709 |
| Coverage Check | gpt-4o-2024-08-06 | 132 | 606,685 | 306,944 (51%) | 20,346 | 1.3365 | 0.00922 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 132 | 162,374 | 1,024 (1%) | 12,993 | 0.0321 | 0.00022 |
| Decision Draft | gpt-4o-2024-08-06 | 132 | 179,371 | 2,304 (1%) | 18,480 | 0.6303 | 0.00435 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 132 | 179,371 | 18,944 (11%) | 18,513 | 0.6099 | 0.00421 |
| **Total** | | | 1,534,604 | 544,768 (35%) | | **3.6367** | **0.02508** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
