# Cost table (replay brain, 40 cases)

| Agent | Model | Runs | Input tokens | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|
| Document Intake | replay:gpt-4o-mini | 38 | 66,480 | 4,320 | 0.0126 | 0.00033 |
| Coverage Check | replay:gpt-4o | 36 | 157,567 | 5,778 | 0.4517 | 0.01189 |
| Claim Assessment | replay:gpt-4o-mini | 36 | 31,901 | 3,314 | 0.0068 | 0.00018 |
| Decision Draft | replay:gpt-4o | 36 | 42,064 | 4,787 | 0.1530 | 0.00403 |
| **Total** | | | | | **0.6241** | **0.01642** |

Prices: OpenAI list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
