# Cost table (live brain, 40 cases)

| Agent | Model | Runs | Input tokens | of which cached | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-mini-2024-07-18 | 38 | 95,904 | 1,408 (1%) | 7,232 | 0.0186 | 0.00049 |
| Coverage Check | gpt-4o-2024-08-06 | 36 | 167,159 | 86,656 (52%) | 5,844 | 0.3680 | 0.00968 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 36 | 44,469 | 0 (0%) | 3,566 | 0.0088 | 0.00023 |
| Decision Draft | gpt-4o-2024-08-06 | 36 | 48,030 | 3,584 (7%) | 5,078 | 0.1664 | 0.00438 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 36 | 48,030 | 10,624 (22%) | 5,012 | 0.1569 | 0.00413 |
| **Total** | | | 403,592 | 102,272 (25%) | | **0.7187** | **0.01891** |

**Prompt caching** (W15 cost lever 2): every agent's static part (instructions, tool schemas) comes first and
the per-claim payload last, so repeated prefixes are served from the provider's cache. Cached input is billed
at the discounted rate (gpt-4o 50%, Claude on Bedrock 90% off). The cache applies to prefixes of 1,024+ tokens.

Prices: list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
