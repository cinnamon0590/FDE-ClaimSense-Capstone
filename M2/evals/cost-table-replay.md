# Cost table (replay brain, 40 cases)

| Agent | Model | Runs | Input tokens | Output tokens | USD | USD per claim |
|---|---|--:|--:|--:|--:|--:|
| G1b injection classifier | gpt-4o-mini-2024-07-18 | 167 | 58,457 | 5,346 | 0.0120 | 0.00032 |
| Document Intake | replay:gpt-4o-mini-2024-07-18 | 36 | 62,080 | 4,132 | 0.0118 | 0.00031 |
| Coverage Check | replay:gpt-4o-2024-08-06 | 36 | 157,580 | 5,845 | 0.4524 | 0.01191 |
| Claim Assessment | replay:gpt-4o-mini-2024-07-18 | 36 | 32,009 | 3,252 | 0.0068 | 0.00018 |
| Decision Draft | replay:gpt-4o-2024-08-06 | 36 | 42,122 | 4,826 | 0.1536 | 0.00404 |
| Decision Draft · second opinion | replay:gpt-4o-2024-08-06 | 36 | 42,122 | 4,815 | 0.1535 | 0.00404 |
| Document Intake | replay:gpt-4o-mini | 2 | 4,400 | 224 | 0.0008 | 0.00002 |
| **Total** | | | | | **0.7908** | **0.02081** |

Prices: OpenAI list prices in `claimsense/observability.py` (verify before quoting).
At 450 claims/day (discovery assumption A) the per-claim figure × 450 × 21 gives the monthly model bill.
