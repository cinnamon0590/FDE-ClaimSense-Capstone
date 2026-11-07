# DECISIONS.md: ClaimSense AI engagement (M2 entries)

Continues the engagement decision log (D-017 to D-023). D-001 to D-007 are in
[`../M0/DECISIONS.md`](../M0/DECISIONS.md), D-008 to D-016 in [`../M1/DECISIONS.md`](../M1/DECISIONS.md).
Newest first. Each entry records Why, Alternatives and a Revisit trigger.

---

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
