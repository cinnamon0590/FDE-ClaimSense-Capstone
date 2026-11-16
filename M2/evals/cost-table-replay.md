# Cost table (replay brain, 40 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| G1b injection classifier | gpt-4o-mini-2024-07-18 | 167 | 58,457 | 0 (0%) | 5,346 | 0.0120 | 0.00032 |
| Document Intake | replay:gpt-4o-mini-2024-07-18 | 36 | 69,352 | 0 (0%) | 4,025 | 0.0128 | 0.00034 |
| Coverage Check | replay:gpt-4o-2024-08-06 | 36 | 157,219 | 84,480 (54%) | 5,839 | 0.3458 | 0.00910 |
| Claim Assessment | replay:gpt-4o-mini-2024-07-18 | 36 | 33,682 | 0 (0%) | 2,763 | 0.0067 | 0.00018 |
| Decision Draft | replay:gpt-4o-2024-08-06 | 36 | 43,326 | 0 (0%) | 5,186 | 0.1602 | 0.00422 |
| Decision Draft · second opinion | replay:gpt-4o-2024-08-06 | 36 | 43,326 | 2,048 (5%) | 5,120 | 0.1570 | 0.00413 |
| Document Intake | replay:gpt-4o-mini | 2 | 4,400 | 0 (0%) | 224 | 0.0008 | 0.00002 |
| **Total** | | | 409,762 | 86,528 (21%) | | **0.6953** | **0.01830** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
