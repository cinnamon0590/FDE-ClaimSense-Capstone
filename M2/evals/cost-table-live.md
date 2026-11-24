# Cost table (live brain, 150 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-2024-08-06 | 145 | 406,803 | 206,592 (51%) | 28,172 | 1.0405 | 0.00718 |
| Coverage Check | gpt-4o-2024-08-06 | 132 | 614,172 | 329,088 (54%) | 20,387 | 1.3279 | 0.00916 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 132 | 162,517 | 0 (0%) | 12,869 | 0.0321 | 0.00022 |
| Decision Draft | gpt-4o-2024-08-06 | 132 | 179,388 | 0 (0%) | 18,468 | 0.6331 | 0.00437 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 132 | 179,388 | 32,256 (18%) | 18,480 | 0.5929 | 0.00409 |
| **Total** | | | 1,542,268 | 567,936 (37%) | | **3.6266** | **0.02501** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
