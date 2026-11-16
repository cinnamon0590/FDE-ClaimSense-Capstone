# Cost table (live brain, 40 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-mini-2024-07-18 | 38 | 73,104 | 5,120 (7%) | 4,231 | 0.0131 | 0.00035 |
| Coverage Check | gpt-4o-2024-08-06 | 36 | 159,008 | 82,560 (52%) | 5,859 | 0.3529 | 0.00929 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 36 | 33,752 | 0 (0%) | 2,715 | 0.0067 | 0.00018 |
| Decision Draft | gpt-4o-2024-08-06 | 36 | 43,348 | 0 (0%) | 5,045 | 0.1588 | 0.00418 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 36 | 43,348 | 9,728 (22%) | 5,120 | 0.1474 | 0.00388 |
| **Total** | | | 352,560 | 97,408 (28%) | | **0.6790** | **0.01787** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
