# Cost table (live brain, 20 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| G1b injection classifier | gpt-4o-mini-2024-07-18 | 72 | 25,160 | 0 (0%) | 2,392 | 0.0052 | 0.00027 |
| Document Intake | gpt-4o-2024-08-06 | 19 | 53,182 | 22,528 (42%) | 3,687 | 0.1417 | 0.00746 |
| Coverage Check | gpt-4o-2024-08-06 | 18 | 83,808 | 46,464 (55%) | 2,869 | 0.1801 | 0.00948 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 18 | 22,258 | 0 (0%) | 1,763 | 0.0044 | 0.00023 |
| Decision Draft | gpt-4o-2024-08-06 | 18 | 24,572 | 0 (0%) | 2,601 | 0.0874 | 0.00460 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 18 | 24,572 | 2,304 (9%) | 2,599 | 0.0845 | 0.00445 |
| **Total** | | | 233,552 | 71,296 (31%) | | **0.5034** | **0.02649** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
