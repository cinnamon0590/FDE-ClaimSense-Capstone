# Cost table (live brain, 40 cases)

| Agent | Model | Runs | Input tokens | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-mini-2024-07-18 | 38 | 65,428 | 4,328 | 0.0124 | 0.00033 |
| Coverage Check | gpt-4o-2024-08-06 | 36 | 155,755 | 6,015 | 0.4495 | 0.01183 |
| Claim Assessment | gpt-4o-mini-2024-07-18 | 36 | 32,124 | 3,291 | 0.0068 | 0.00018 |
| Decision Draft | gpt-4o-2024-08-06 | 36 | 42,273 | 4,854 | 0.1542 | 0.00406 |
| Decision Draft · second opinion | gpt-4o-2024-08-06 | 36 | 42,273 | 4,886 | 0.1545 | 0.00407 |
| **Total** | | | | | **0.7775** | **0.02046** |

Prices: OpenAI list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
