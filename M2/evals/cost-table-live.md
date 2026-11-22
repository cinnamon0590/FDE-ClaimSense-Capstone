# Cost table (live brain, 150 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-mini-2024-07-18 | 145 | 368,327 | 4,352 (1%) | 26,811 | 0.0710 | 0.00049 |
| Coverage Check | gpt-4o-2024-08-06 | 132 | 597,975 | 274,560 (46%) | 20,255 | 1.3543 | 0.00934 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 132 | 161,015 | 0 (0%) | 12,784 | 0.0318 | 0.00022 |
| Decision Draft | gpt-4o-2024-08-06 | 132 | 173,957 | 0 (0%) | 18,509 | 0.6200 | 0.00428 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 132 | 173,957 | 19,328 (11%) | 18,477 | 0.5955 | 0.00411 |
| G1b injection classifier | gpt-4o-mini-2024-07-18 | 371 | 129,063 | 0 (0%) | 12,176 | 0.0267 | 0.00018 |
| **Total** | | | 1,604,294 | 298,240 (19%) | | **2.6993** | **0.01862** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
