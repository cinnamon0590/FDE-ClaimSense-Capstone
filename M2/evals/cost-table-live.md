# Cost table (live brain, 3 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-mini-2024-07-18 | 3 | 5,747 | 0 (0%) | 315 | 0.0011 | 0.00035 |
| Coverage Check | gpt-4o-2024-08-06 | 3 | 12,097 | 5,888 (49%) | 353 | 0.0264 | 0.00880 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 3 | 2,645 | 0 (0%) | 225 | 0.0005 | 0.00018 |
| Decision Draft | gpt-4o-2024-08-06 | 3 | 3,443 | 1,024 (30%) | 367 | 0.0110 | 0.00367 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 3 | 3,443 | 0 (0%) | 358 | 0.0122 | 0.00406 |
| **Total** | | | 27,375 | 6,912 (25%) | | **0.0512** | **0.01706** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
