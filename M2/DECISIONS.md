# DECISIONS.md: ClaimSense AI engagement (M2 entries)

Continues the engagement decision log (D-017 to D-023). D-001 to D-007 are in
[`../M0/DECISIONS.md`](../M0/DECISIONS.md), D-008 to D-016 in [`../M1/DECISIONS.md`](../M1/DECISIONS.md).
Newest first. Each entry records Why, Alternatives and a Revisit trigger.

---

## D-028 · 2026-11-07 · Closing the W15 deck: all six primitives, streaming, caching, the queue, AgentCore, leaderboard, Bedrock
- **Context:** a line-by-line re-check against the W15 deck, the companion notebook and the class codebase
  (`labs/w15-build`) found items the floor didn't force but the class asks for. All are now in.
- **Decision:**
  - **Gate floor 90%** (was the M0 charter's 85%): the W15 eval gate is `--min-pass 0.9`. Adversarial stays 100%.
  - **All six SDK primitives fire in the product.** The pipeline stays a fixed, code-orchestrated sequence
    (D-018). The adjuster's follow-up chat, **Ask ClaimSense**, is where a model-routed **handoff** belongs
    (Q&A → Coverage specialist for policy-wording questions). Each adjuster-claim conversation is an SDK
    **`SQLiteSession`** on `/state` that survives restarts, and replies **stream** (`run_streamed`). An output
    tripwire withholds any answer citing an unretrieved clause or another claim, and never keeps it in memory.
  - **Stream by default:** every pipeline agent runs under `Runner.run_streamed`; replay/scripted brains stream
    a `response.completed` event, so CI exercises the same code path.
  - **Prompt caching measured:** cached input tokens are metered from SDK usage and billed at the cached rate;
    the cost table shows the share. Live smoke: 27% of input cached (Coverage 52%), $0.0166 per claim.
  - **The adjuster queue:** drafts land in the ops team's own queue (W15 CIO constraint); entitlement-filtered,
    audited, Confirm from the list.
  - **AgentCore config written out** (`cloud/agentcore/`): entry point, toolkit config, least-privilege role.
  - **Leaderboard-compatible output:** `pass rate: NN% (x/y)`, `--suite golden`, `--cases`, a `leaderboard:` line, a
    spend ledger summed from SDK usage, and `SPEND.txt` at the repo root (a bare number, as the script reads it).
  - **Bedrock option:** `MODEL_PROVIDER=bedrock` runs Claude Haiku 4.5 / Sonnet 4.5 on Bedrock through the SDK's
    LiteLLM bridge (`litellm.modify_params=True`), with the classifier and retrieval also staying inside AWS.
- **Honest notes:** M2's cumulative OpenAI spend ($10.25, verified on the OpenAI usage page) is above the leaderboard's $5; it is disclosed in
  `SPEND.txt` and the replay brain competes in the $0 mock division
  at 100%. Bedrock invocation needs the account's one-time Anthropic use-case form; until then a Bedrock run
  fails closed to labelled fallback cards.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** W17 sets the golden-suite bar (0.95 per the class gate).

## D-027 · 2026-11-07 · Restart-survivable state: resumable runs and a persistent boundary
- **Decision:**
  - **Resumable runs.** Every agent step's typed output is checkpointed in SQLite on the `/state` volume,
    keyed by `run_id`, together with the retrieval state (clause IDs **and their text**, so quotes are still
    the retrieved wording after a resume). Every result returns its `run_id`. `POST /recommend` with the same
    `run_id` resumes: finished agents are restored, not re-run or re-billed. The write-back idempotency key
    is derived from `run_id` and the card, so a resumed run never stores a duplicate draft.
  - **Persistent boundary.** Drafts and idempotency records persist in SQLite (`/state/boundary.db`, a local
    twin of the `claimsense-idempotency` DynamoDB table provisioned in M1). The audit log is reloaded from
    its append-only file at start-up.
  - **Refresh-safe console sessions.** The console puts the run in its URL (`?claim=&user=&run=`). A refresh,
    a reopened tab or a console restart picks the same run up again: a finished run comes back from
    checkpoints at $0; an unfinished one resumes. A run **still in progress is joined**: the orchestrator
    keeps a registry of in-flight runs, and a reconnecting request receives the buffered events, the live
    ones and the result, so nothing runs (or is billed) twice. A closed tab never cancels the run. Only the
    same user on the same claim can join, and a `run_id` is bound to its claim. Confirm/Override use a
    stable idempotency key per draft, user and decision, so a resubmit replays the receipt.
  - **Decided exactly once.** A second confirm or override under a new key is refused with
    `already_confirmed` (added to the M1 error contract). The same key still replays the original receipt.
  - **Proof on every push.** CI's stack-smoke job runs `evals/restart_survival.py` against the real containers.
    It kills the orchestrator mid-claim (test-only fault injection, off unless `CLAIMSENSE_FAULT_INJECTION=1`),
    lets Docker restart it, resumes the run, and restarts the boundary twice. Evidence:
    [`evidence/restart-survival.txt`](evidence/restart-survival.txt).
- **Why per-step checkpoints, not the SDK's `SQLiteSession`:** `SQLiteSession` stores conversation history
  for multi-turn chat. ClaimSense is a fixed, code-orchestrated sequence of single-turn agents (D-018), so
  the state worth surviving a crash is each step's validated typed output. That is what a checkpoint stores,
  and it makes resume exact (no model call is replayed) and $0.
- **Found while building it:** a resumed run used the model's paraphrased clause quotes, because only clause
  IDs were checkpointed, not their text; and the M1 boundary allowed a second confirm under a new key. Both
  fixed, with tests.
- **AWS path:** Lambda's `/tmp` is ephemeral, so on Lambda a resume works only within a warm instance. M3
  moves checkpoints and boundary state to DynamoDB (tables already provisioned) behind the same interfaces.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** M3 deploys the boundary to API Gateway + Lambda.

## D-026 · 2026-11-07 · Guardrails are fuzzed, and G1 gets a model-based second layer (G1b)
- **Decision:**
  - **Fuzz suite as a CI gate** (`evals/fuzz_guardrails.py`, `tests/test_guardrail_fuzz.py`, $0). Known
    attacks and PII values are mutated in 15 ways: case, whitespace, zero-width characters, Cyrillic
    look-alikes, full-width text, leetspeak, punctuation, HTML/markdown wrappers, quoting, base64 and five
    languages. The bar is 99% caught and zero false positives on all 155 benign claim texts.
  - **G1 and G3 hardened.** Text is scanned as written, normalised and as a matching-only skeleton; base64
    is decoded and rescanned; patterns cover paraphrases and five languages. PII masking normalises Unicode
    first and masks VINs in any case. Result: G1 from 16.9% to 99.9%; G3 from 79% to 100%.
  - **G1b classifier.** Signatures don't generalise: on held-out sets written before each test and never
    tuned on, G1 caught 2/20 (v2) and 1/15 (v3) new phrasings. G1b runs inside `get_claim_file` on the
    PII-masked text, BEFORE the Intake model sees it. `ai_instruction` withholds the text and trips the
    Intake tripwire (human handoff); `pressure_to_skip_review` fires G6 and keeps the verdict. With
    G1 + G1b: 13/15 (v3) and 19/20 (v2) caught; 0/15 and 1/20 false positives.
- **Why it is safe to ask a model here** (M1 said no guardrail asks a model): G1b can only ESCALATE to a
  human; it never approves, clears or un-flags. It fails closed (an error counts as `ai_instruction`). An
  attacker who fools it is exactly as well off as with no G1b, because every deterministic guardrail still
  runs. The deterministic rule from M1 still holds for every guardrail that can *allow* something.
- **Cost:** about $0.0002 a claim (gpt-4o-mini on 3–5 short texts). Verdicts are cached by text hash
  (`evals/g1b-cache.json`), so the replay brain and CI apply G1b at $0, and a test fails if any eval text
  lacks a cached verdict.
- **Residual risk:** v3 misses 2/15 (phrased as favours or "pre-cleared", classed as pressure, so G6 still
  flags them). Held-out sets are small. M3 will add a red-team set of 100+ attacks and track both rates.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** the held-out catch rate drops below 85% or the
  false-positive rate on real claims exceeds 2%.

## D-025 · 2026-11-07 · Pinned model snapshots, a second-opinion Decision Draft, and a stability release gate
- **Decision:** Three changes so run-to-run variation is measured and handled instead of tolerated:
  - **Pinned snapshots.** `gpt-4o-2024-08-06` and `gpt-4o-mini-2024-07-18`, the versions the aliases pointed
    to during tuning, never the moving aliases. A newer snapshot is adopted only after the release gate passes
    on it. (`text-embedding-3-large` has no dated snapshot; a change there would show up in retrieval tests.)
  - **Second opinion (G8).** Every live claim runs Decision Draft twice, independently. If the outcome or
    route differs, the card goes to a senior adjuster (`model_disagreement`, `decided_by=consistency_hold`).
    Only Decision is doubled: it sets the outcome and costs about $0.004 a claim. Doubling Coverage too would
    roughly double the per-claim cost.
  - **Release gate** (`make release`, by hand before a release): 3 live runs; every case right in at least 2
    of 3, adversarial right 3 of 3, every verdict model-produced, and the deploy gate passing on each run.
    CI keeps the replay gate on every PR and the 20-case live smoke on main.
- **Why:** The earlier README said the live model "varies from run to run" without measuring it on the final
  prompts; every earlier live run used a different prompt version. A licensed adjuster should see "the model
  is unsure" rather than a confident coin flip.
- **Cost:** about $0.021 a claim instead of $0.016 (+30%), roughly $200 a month at 450 claims a day.
  `CONSISTENCY_CHECK=0` turns it off.
- **Alternatives considered:** (a) Majority vote of 3. Rejected: 3x the Decision cost, and it hides
  disagreement instead of surfacing it to a human. (b) Higher temperature sampling for diversity. Rejected:
  production runs at temperature 0, and the check should measure the variation production actually has.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** a newer snapshot is evaluated, or the hold rate on
  real claims exceeds about 5% (then the prompt, not the check, needs work).

## D-024 · 2026-11-07 · The boundary trusts neither the caller's headers nor the writer's numbers
- **Decision:** At the data boundary:
  - A confirm request that carries `X-On-Behalf-Of-Agent` is treated as coming from that agent and refused
    (`human_confirmation_required`), even when the human it acts for could confirm.
  - Every draft written back is validated against the DecisionCard contract for *that* claim. Its
    `computed` section is re-derived in code before storage, so the $25K authority check at confirm time
    uses code's number, never the writer's.
  - Malformed bodies get a 400 `invalid_request` and an audit row, not a crash.
- **Why:** Found in the pre-review guardrail audit. Today no agent has a confirm tool, and the pipeline
  already overwrites `computed` (G4). The boundary is the last door, though, and M3 exposes it as an API,
  so it must hold on its own (defence in depth, M1 D-003).
- **Alternatives considered:** Rely on the pipeline alone. Rejected: any second writer (a script, a future
  agent, a compromised orchestrator) would bypass it.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** M3 moves identity to Cognito JWTs (agent identity
  then comes from the token, not a header).

## D-023 · 2026-11-06 · The OpenAI key is read from Secrets Manager at runtime, never from an image or an environment variable in AWS
- **Decision:** Locally the key comes from `M2/.env` (gitignored; Susan pastes it). In CI it is the
  `OPENAI_API_KEY` GitHub secret. In AWS the orchestrator reads `claimsense/openai-api-key` from Secrets
  Manager at start-up (`OPENAI_SECRET_ID`); the Lambda role may read only that one secret. With no key the
  service runs the replay brain, so nothing ever silently calls a paid API.
- **Why:** Lambda environment variables are visible to anyone with read access to the function configuration.
  The M1 security questionnaire promised "secrets out of code, read at runtime"; this keeps that promise.
- **Alternatives considered:** (a) Env var on the function. Rejected for the reason above (the first draft of
  `deploy.sh` did this; corrected before any deploy). (b) Parameters and Secrets Lambda extension. Fine, but
  one more moving part for the same result.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** key rotation is automated (M4 runbook).

## D-022 · 2026-11-06 · Every verdict says what decided it; fallback can never pass as AI
- **Decision:** Every card carries `verdict_source` (`model` | `deterministic_fallback`), and every pipeline
  result carries `decided_by` (`agents` | `guardrail_hold` | `boundary_refusal` | `fallback`). The console shows
  a badge for each. The fallback rule engine runs only when the model fails, times out, returns unparseable
  output or exceeds the per-claim budget. It never approves, and its reasoning starts `[DETERMINISTIC FALLBACK`.
  The eval gate counts fallback verdicts as misses (D-007), so an outage turns the gate red (test
  `test_gate_blocks_when_the_model_is_down`).
- **Labelling rule:** `verdict_source: model` means the co-pilot's own decision path produced the outcome: the
  agents, possibly re-routed by a guardrail (named in `guardrails_fired`), or a refusal at the boundary (no data,
  no agent). This matches the M0 oracle that defined the gate. `decided_by` gives the finer distinction for
  people.
- **Why:** The brief grades "outcomes from deterministic fallback only" as weak, and risk R3 is the AI silently
  becoming a rule table during an outage. Labelling at source and scoring by label makes that impossible to hide.
- **Alternatives considered:** (a) Fall back silently. Rejected: that is exactly R3. (b) Add a third
  `verdict_source` value for guardrail holds. Rejected for now because it would change the M1 contract;
  `decided_by` carries it without a breaking change. (c) No fallback at all (fail with an error). Rejected
  because adjusters still need the code-computed facts during an outage.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** M3 contract review; if Security wants guardrail holds
  in the contract itself, add the enum value then.

## D-021 · 2026-11-06 · The CI gate runs twice: a replay brain on every PR, the live models before any push
- **Decision:**
  - **Every push and PR** runs the four-agent pipeline on the **replay brain**: recorded model turns played
    back through the real Runner, tools, strict parsing and guardrails. It is $0, needs no key, is
    deterministic, and blocks the merge if the gate fails.
  - **Main (and `demo/*`)** additionally run the **live gate** on gpt-4o-mini / gpt-4o: the 20-case smoke
    suite in CI (about $0.30 per push, Susan's choice on 2026-11-07), the full 40 cases by hand before a release.
  - `build-push` needs every job, so a red gate means no image.
  - Replay files are labelled `scripted` (hand-written to exercise the harness before a key existed) or
    `recorded` (captured from a live run with `--record`). The report prints the mix.
- **Why:** This is W15's pattern ("mock brain in CI, live model before release"). Running the live model on
  every PR would cost money and be non-deterministic. A mock-only gate would prove the harness but never the
  model.
- **Alternatives considered:** (a) Live on every PR. Rejected on cost and flakiness. (b) Mock only. Rejected:
  the M5 bar is "gate passes with the model required". (c) A canned-answer mock that bypasses the SDK. Rejected:
  it would not test tool calling, strict output parsing or the tripwires.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** live-gate cost exceeds $2 per run, or replays drift from
  live behaviour (re-record on every prompt change).

## D-020 · 2026-11-06 · SDK tripwires fail closed to a senior adjuster; the M1 rules make the final pass
- **Decision:**
  - The M1 guardrail code (`reference_guardrails.py`) is imported, not copied.
  - It is wired into the Agents SDK as an **input guardrail** on every agent (G1) and three **output
    tripwires**: Intake (G1 hits found in documents), Coverage (cited ⊆ retrieved, G5) and Decision Draft
    (G5/G6/G7).
  - A tripped wire stops the run, and the claim goes to a senior adjuster with the reason.
  - `apply_guardrails` then makes a final code-owned pass on **every** card.
  - Untrusted text is PII-masked (G3), has foreign claim IDs masked, and has instruction-like spans removed
    **before** any model sees it.
- **Found and fixed:** the M1 spec copied injected text into the card's reasoning when it routed to a human (it
  would re-deliver the payload, and CS-016's `must_not` caught it). It now reports a count. Same class of bug as
  the cross-record echo fixed in D-016.
- **Why:** Defence in depth: never let the model see the attack, stop the run if it is present anyway, and
  re-check the output in code whatever the model did.
- **Alternatives considered:** (a) Halt on any guardrail. Rejected for auto-decision pressure (CS-018/CS-037):
  the verdict stays and only finalisation is stripped (D-016). (b) Only post-hoc checks. Rejected: then the
  attack text still reaches the model.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** M4 shows tripwire false positives above 2% on clean cases.

## D-019 · 2026-11-06 · Retrieval: lexical (TF-IDF) offline, OpenAI embeddings live, OpenSearch behind the same interface
- **Decision:**
  - One `search(query, k)` interface over the 12-clause corpus.
  - The replay brain and CI use a numpy TF-IDF index ($0, no key).
  - Live runs use `text-embedding-3-large`, with vectors cached on disk.
  - The OpenSearch k-NN adapter is the AWS path, enabled once the corpus outgrows memory or M3 needs a shared
    index.
  - The index deliberately contains the planted unprovenanced chunk; G2 (manifest hash) drops it before the
    model sees it.
- **Why:** At 12 clauses an OpenSearch domain would cost about $25–$90 a month to hold what fits in one array.
  Provenance, not the retriever, decides trust, so the retriever can change without weakening the control.
- **Alternatives considered:** (a) OpenSearch now. Deferred on cost (M1 D-014: cost-bearing services only when
  needed). (b) Embeddings in CI. Rejected: needs a key, so it isn't $0 or deterministic.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** the corpus exceeds about 500 chunks or real policy
  wordings arrive.

## D-018 · 2026-11-06 · Code orchestrates a fixed sequence of four typed agents (no model handoffs)
- **Decision:**
  - Intake → Coverage → Assessment → Decision Draft, each a `Runner.run` with a strict Pydantic `output_type`.
  - Code passes each typed result to the next step, and code computes dates and money between steps (G4).
  - Model routing: gpt-4o-mini for Intake and Assessment, gpt-4o for Coverage and Decision Draft.
  - Each step's output is checkpointed in SQLite, so a crashed run resumes without paying again.
- **Why:** Every claim must get every check (M1 D-011). With handoffs, the model chooses the path and can skip
  Coverage. Typed steps make each agent separately testable and replayable.
- **Alternatives considered:** (a) SDK handoffs (the W15 demo pattern). Rejected for this domain for the reason
  above; kept for an adjuster Q&A agent later. (b) One big agent. Rejected: no per-step model routing, no
  per-step guardrails.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** a step needs conditional sub-agents (e.g. a theft
  specialist).

## D-017 · 2026-11-06 · Local stack: four containers, one command, internal-only systems of record
- **Decision:**
  - `docker compose up --build` (`make up`) starts four services: mock AutoSure systems, the data boundary,
    the orchestrator and the Streamlit console.
  - The mock systems are reachable only on the internal network. The boundary is the only door (M1 D-003).
  - Host ports bind to 127.0.0.1 only. The console is on 8510 because 8501 was already in use on the laptop.
  - Docker runs on Colima (free, no Docker Desktop licence).
  - The orchestrator image is the one CI pushes to ECR. It also runs unchanged on Lambda (Web Adapter).
- **Why:** The brief asks for a single-command start. Mirroring the AWS topology locally means M3 swaps
  transports, not architecture.
- **Alternatives considered:** (a) A single process. Rejected: it would hide the boundary. (b) Docker Desktop.
  It works too; Colima avoids licence questions for a client laptop.
- **Owner:** Susan Wellington (FDE) · **Revisit when:** M3 replaces the boundary container with API Gateway +
  Lambda + Cognito.
