# Cost table (live brain, 40 cases)

| Agent | Model | Runs | Input tokens | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|
| Document Intake | gpt-4o-mini | 36 | 62,080 | 4,096 | 0.0118 | 0.00033 |
| Coverage Check | gpt-4o | 36 | 157,567 | 5,778 | 0.4517 | 0.01255 |
| Claim Assessment | gpt-4o-mini | 36 | 31,901 | 3,314 | 0.0068 | 0.00019 |
| Decision Draft | gpt-4o | 36 | 42,064 | 4,787 | 0.1530 | 0.00425 |
| **Total** | | | | | **0.6233** | **0.01731** |

Prices: OpenAI list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
