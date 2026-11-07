# ClaimSense runbook (M2 pilot)

Who uses this: the on-call FDE and the AutoSure claims-operations lead. Every procedure below is
**safe by default**: when in doubt, ClaimSense sends claims to a human, and nothing it does moves
money without a licensed adjuster.

## Signals to watch

| Signal | Where | Normal | Act when |
|---|---|---|---|
| Fallback share (`decided_by=fallback`) | eval report, orchestrator logs | 0% | > 2% over an hour → **Model outage** |
| Guardrail holds (`guardrail_hold`) | console badge, `/audit` | a few % (real injections) | sudden jump → **Hold spike** |
| Second-opinion holds (`consistency_hold`) | console badge, release gate | 0 in 120 live claim runs (M2) | > 5% → **Model unsure** |
| Cost per claim | cost table, OpenAI usage page | ~$0.02 | > $0.05 (budget cap fires) → **Cost spike** |
| p95 latency | eval report | ~19 s | > 60 s → **Slow model** |
| Boundary denials | `/audit` (senior adjusters only) | refusals of unassigned claims | many denials for one user → **Access probe** |

## Procedures

### Model outage (OpenAI errors, timeouts, 429s)
1. Nothing to stop: every claim falls back to the **labelled deterministic card**. It never approves, is
   badged "Deterministic fallback (not AI)", and an adjuster works the claim as today.
2. Check https://status.openai.com and the orchestrator logs (`make logs`).
3. If it's a quota (429 `insufficient_quota`): top up credit. Replays are safe, because recording commits
   only complete claims (tested).
4. After recovery, run `make smoke`, which should show `decided_by=agents` again.

### Orchestrator crashed or was redeployed mid-claim
1. Nothing is lost. Every finished agent step is checkpointed on the `/state` volume (D-027).
2. Re-submit the claim with the `run_id` from the failed response or the logs:
   `POST /claims/<id>/recommend {"user_id": ..., "run_id": ...}`. It resumes, finished agents are not re-run
   or re-billed, and the draft write-back is idempotent (no duplicate).
3. Never run `docker compose down -v`: `-v` deletes the state volume (checkpoints, drafts, idempotency).

### Adjuster's console tab was refreshed, closed or the console restarted
1. Nothing to do. The page URL holds the run (`?claim=&user=&run=`); reopening it joins the run if it is still
   going, or shows the result from checkpoints ($0). A closed tab never cancels the run.
2. Ask the adjuster for the URL (or the `run_id` in the caption) if they need the draft again.

### Boundary restarted
1. Drafts, idempotency records and confirmations persist in `/state/boundary.db`; the audit is reloaded.
2. A draft is decided exactly once: a second confirm or override under a new key returns `already_confirmed`.

### Hold spike (many `guardrail_hold`)
1. Open three held claims in the console. Is it a real attack (same garage or template), or a false positive?
2. **Real attack:** leave the holds; notify SIU with the claim IDs (the audit log has the spans).
3. **False positive:** add the benign sentence to `BENIGN_NEAR_MISSES` in `evals/fuzz_guardrails.py`, fix the
   pattern or the G1b prompt, and run `make test` (the fuzz gate) and `make release` before deploying.
   Never switch a guardrail off in production. A hold costs adjuster time, not money.

### Model unsure (`consistency_hold` above 5%)
1. Run `make release` and read `evals/results-live-stability.txt`: which cases flip?
2. A flip means a rule is still being decided by the model. Move it into code (verified facts or
   deterministic rules), as was done for the fraud rule, routing priority and term dates (D-001).

### Cost spike
1. The per-claim cap (`CASE_BUDGET_USD`) already stops a runaway claim and falls back.
2. Check the cost table for which agent grew. Usually it's a retrieval loop (too many `search_clauses`
   calls); `max_turns=10` bounds it.

### Rotate the OpenAI key
1. Create a new key in OpenAI.
2. `aws secretsmanager put-secret-value --secret-id claimsense/openai-api-key --secret-string ...`
   (run it yourself; the key never goes in chat, a file in the repo, or an environment variable in AWS).
3. `gh secret set OPENAI_API_KEY` for CI; update `M2/.env` locally.
4. Revoke the old key; run `make smoke`.

### Roll back a release
1. Images are tagged with the commit SHA and tags are immutable: pick the last known-good SHA from
   `aws ecr describe-images --repository-name claimsense/orchestrator`.
2. Point the deployment at that tag (Lambda: `cloud/lambda/deploy.sh <sha>`). No rebuild needed.
3. Open an issue with the failing case IDs; add them to the eval set before the fix (the gate then
   protects against a repeat).

### Adopt a new model snapshot
1. Set `MODEL_SMART` / `MODEL_FAST` to the new dated snapshot in `M2/.env`.
2. `make release` (3 live runs). Adopt only if the release gate passes; re-record replays (`make record`).
3. Update `config.py` defaults and `observability.PRICES`; commit with the stability report.

## Release checklist
- [ ] `make test`: unit, integration, guardrail fuzz and restart-survival tests ($0)
- [ ] `make restart-test`: restart survival on the running containers ($0)
- [ ] `make evals`: replay gate PASS ($0)
- [ ] `make release`: 3 live runs, RELEASE GATE PASS (~$2.70)
- [ ] CI green, including `supply-chain` (no fixable HIGH/CRITICAL CVE; SBOM attached)
- [ ] `DECISIONS.md` entry for any prompt, model or guardrail change
- [ ] A senior adjuster has reviewed any new or changed eval labels
