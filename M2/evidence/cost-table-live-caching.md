# Cost table (live brain, 20 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-mini-2024-07-18 | 19 | 32,996 | 0 (0%) | 2,176 | 0.0063 | 0.00033 |
| Coverage Check | gpt-4o-2024-08-06 | 18 | 79,370 | 41,216 (52%) | 2,996 | 0.1769 | 0.00931 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 18 | 16,033 | 0 (0%) | 1,629 | 0.0034 | 0.00018 |
| Decision Draft | gpt-4o-2024-08-06 | 18 | 21,090 | 0 (0%) | 2,345 | 0.0762 | 0.00401 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 18 | 21,090 | 5,120 (24%) | 2,343 | 0.0698 | 0.00367 |
| **Total** | | | 170,579 | 46,336 (27%) | | **0.3324** | **0.01750** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
