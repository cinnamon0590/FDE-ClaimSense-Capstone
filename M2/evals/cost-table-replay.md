# Cost table (replay brain, 40 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| G1b injection classifier | gpt-4o-mini-2024-07-18 | 167 | 58,457 | 0 (0%) | 5,346 | 0.0120 | 0.00032 |
| Document Intake | replay:gpt-4o-mini-2024-07-18 | 36 | 62,080 | 0 (0%) | 4,132 | 0.0118 | 0.00031 |
| Coverage Check | replay:gpt-4o-2024-08-06 | 36 | 157,580 | 0 (0%) | 5,845 | 0.4524 | 0.01191 |
| Claim Assessment | replay:gpt-4o-mini-2024-07-18 | 36 | 32,009 | 0 (0%) | 3,252 | 0.0068 | 0.00018 |
| Decision Draft | replay:gpt-4o-2024-08-06 | 36 | 42,122 | 0 (0%) | 4,826 | 0.1536 | 0.00404 |
| Decision Draft · second opinion | replay:gpt-4o-2024-08-06 | 36 | 42,122 | 0 (0%) | 4,815 | 0.1535 | 0.00404 |
| Document Intake | replay:gpt-4o-mini | 2 | 4,400 | 0 (0%) | 224 | 0.0008 | 0.00002 |
| **Total** | | | 398,770 | 0 (0%) | | **0.7908** | **0.02081** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
