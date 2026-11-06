# DECISIONS.md: ClaimSense AI engagement (M1 entries)

Continues the engagement decision log (D-008 to D-016). **D-001 to D-007** (discovery, the deterministic spine,
cited retrieval, access in code, the four-agent split, synthetic data, the eval suite as contract)
are in [`../M0/DECISIONS.md`](../M0/DECISIONS.md). Newest first. Each entry records Why,
Alternatives and a Revisit trigger, so scope can't be silently rewritten later.

---

## D-016 · 2026-11-05 · Guardrails are executable code with a human as the safe default; injection and auto-decision pressure handled differently
- **Decision:** Content guardrails (G1–G7 in `2-architecture/guardrails.md`) are implemented as deterministic code
  and proven by tests driven by the M0 adversarial cases and graded by the M0 scorer. An injection, an invalid
  citation or a cross-record reference routes the case to a senior adjuster. **Pressure to auto-decide** ("pay
  immediately", "no adjuster review") keeps a correct verdict but strips any finalisation. Guardrail messages never
  echo redacted data.
- **Why:** The two threats differ. An injection means the model's reasoning can't be trusted, so a human takes over.
  Auto-decision pressure leaves the verdict (e.g. deny on a lapsed policy, CS-018) valid; the danger is skipping the
  human, so we block only that. The tests caught a real leak where the cross-record guardrail echoed the redacted
  claim ID in its own explanation.
- **Alternatives considered:** (a) Ask the model to self-check. Rejected because a guardrail the model can talk its way
  past is a prompt, not a control. (b) Route every guardrail hit to a human. Rejected because it degrades CS-018 from
  a correct deny to flag_review, adding queue load for no safety gain. (c) A managed service only (e.g. Bedrock
  Guardrails). It covers generic classes but not our domain rules (citations ⊆ retrieved, code-owned money);
  evaluate as an extra layer in M4.
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** The guardrail-fire rate in M4 shows false positives above 2% on clean cases, or a new adversarial
  family appears.

## D-015 · 2026-11-05 · Audit log in DynamoDB (append-only), streamed to CloudWatch
- **Decision:** The data boundary writes one audit record per call to the `claimsense-audit` table
  (pk `resource`, sk `ts#request_id`, point-in-time recovery). IAM grants the boundary `PutItem` only;
  no role may update or delete. Records stream to CloudWatch for search and alarms.
- **Why:** Security's questionnaire item #8 wants every action logged immutably, including denials,
  and exportable. A key-value table gives exact per-resource history for the two-user test and for
  disputes. PITR protects against accidental table damage.
- **Alternatives considered:** (a) CloudWatch Logs only. Rejected because querying by resource is
  awkward and retention isn't a contract. (b) S3 with Object Lock (WORM). A strong compliance option,
  but heavier to query; revisit for production. (c) Logging in the application. Rejected because an
  agent-side log can be skipped, while the boundary can't be bypassed.
- **Owner:** Susan Wellington (FDE); Security approves the format (M3).
- **Revisit when:** Production go-live (consider S3 Object Lock for a 7-year retention requirement).

## D-014 · 2026-11-05 · Provision cloud foundations now; cost-bearing services only when there's code
- **Decision:** Create S3, ECR, Cognito with 5 groups, two DynamoDB tables, log groups, a
  Secrets Manager placeholder and a $25/month budget now, all tagged `Project=ClaimSense`, through an
  idempotent script with a teardown. ECS, API Gateway + Lambda and OpenSearch wait for M2/M3.
- **Why:** The brief requires the cloud account provisioned and evidenced this week, and Submission 1
  needs proof it runs under my own account. Idle compute is "silent burn", the course's cost lesson.
  Scripted provisioning and teardown make the SoW's exit clause provable.
- **Alternatives considered:** (a) Provision everything now. Rejected: OpenSearch and Fargate cost money
  while idle. (b) Console clicks. Rejected because they're not reproducible and leave no evidence.
  (c) Terraform/CDK. Better at scale, but heavier than a 5-week pilot needs; revisit if the account
  expands.
- **Owner:** Susan Wellington (FDE); IT/Cloud is Accountable for the account (RACI).
- **Revisit when:** M2 needs ECS and OpenSearch, or the pilot moves to AutoSure's organisation account.
- **Note:** Initial provisioning ran under root via `aws login`. The same day, root was retired from daily use:
  the MFA-protected IAM admin `FDE_PROJECT_ADMIN` (no access keys) now runs the CLI. A GitHub OIDC CI role follows in M2.

## D-013 · 2026-11-05 · Synthetic fixtures are generated from the eval cases
- **Decision:** `generate_fixtures.py` derives claims, policies, documents, the clause corpus and
  users from `M0/evals/cases.json`, deterministically. `validate_data.py` proves the fixtures match the
  cases field by field. Each clause carries a `manifest_sha256` provenance hash.
- **Why:** If the test data and the run data are maintained separately, they drift, and a test
  passes against data the system never sees. One source of truth removes that failure. The manifest
  is what lets retrieval quarantine a tampered chunk (CS-020).
- **Alternatives considered:** (a) Hand-maintained fixtures. Rejected because of drift. (b) Faker-style
  random data. Rejected because random records carry no labels and no edge cases. (c) Wait for issued
  fixtures. Rejected: none were issued (D-006).
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** The suite grows past the seed (M4), or official fixtures appear.

## D-012 · 2026-11-05 · Typed contracts with JSON Schema; idempotent drafts; human-only confirmation
- **Decision:** JSON Schema (draft 2020-12) is the source of truth for every request, response and error
  at the data boundary, with a typed Python mirror and an executable reference implementation (17 tests).
  Writes need an `Idempotency-Key`: the same key and payload replays the original response, the same key
  with a different payload is a 409 conflict, and keys are kept 30 days in DynamoDB with a conditional write.
  Recommendations are always drafts. Confirmation is a separate write that agent identities can't make.
  Missing and unentitled records return the same error.
- **Why:** Contracts let M2 (agents) and M3 (boundary) be built in parallel against one spec.
  Idempotency makes retries safe, because a network blip must never create two recommendations. A
  human-only write turns "an adjuster confirms every outcome" into a gate the model can't open.
- **Alternatives considered:** (a) OpenAPI only. Equivalent schemas, but no executable spec;
  OpenAPI can be generated from these later (useful for AgentCore Gateway). (b) Ignore duplicate
  writes silently. Rejected because the course flags it: a replay must return the original. (c) Let
  agents confirm low-risk outcomes. Rejected because the brief requires a licensed adjuster for every outcome.
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** A fourth system joins the boundary, or Security changes the identity pattern.

## D-011 · 2026-11-05 · Agent pattern: a fixed orchestrated sequence, not a free ReAct loop
- **Decision:** The orchestrator fixes the plan in code: Intake → Coverage → Assessment → Decision
  Draft, with explicit handoffs and a narrow toolset per agent. Only Coverage Check may retrieve, and
  no agent can write.
- **Why:** Per the Week 14 agentic-design-patterns masterclass, the first pass is a predictable,
  tool-heavy workflow (favouring a planned sequence) with distinct domains that need different
  security boundaries (favouring multi-agent). A fixed sequence bounds cost and latency (SC-2) and gives
  every claim the same trace shape for incidents.
- **Alternatives considered:** (a) One ReAct agent with all tools. Rejected for unbounded iterations
  and an agent choosing its own path to data. (b) Fully parallel agents. Rejected because Coverage
  needs Intake's extracted facts, and parallelism multiplies token cost. (c) An autonomous supervisor
  agent. Rejected as unnecessary adaptability for a structured workflow.
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** Latency forces Assessment to run in parallel with Coverage, or the workflow
  gains open-ended investigation steps (SIU support in a later phase).

## D-010 · 2026-11-05 · Integration topology: point-to-point through the one data boundary
- **Decision:** For the pilot, connect the three systems point-to-point, but only through the data
  boundary (MCP server). Topology selector: point-to-point 5, iPaaS 1, event mesh 1.
- **Why:** Three systems, synchronous request/reply and a 5-week ship. A hub or event mesh adds
  operations without benefit at this size, while the single door still gives one place for RBAC and audit.
- **Alternatives considered:** (a) iPaaS (MuleSoft/Boomi). Rejected for the pilot because of cost and lock-in, but
  it's the selector's pick at expansion. (b) Event mesh (EventBridge/Kafka). Rejected: overkill for
  synchronous lookups.
- **Owner:** Susan Wellington (FDE)
- **Revisit when:** A 5th system joins the boundary, or claims management starts pushing FNOL events.
  Re-run `tools/topology.py`.

## D-009 · 2026-11-05 · Stack: OpenAI Agents SDK + OpenAI API, hosted on AWS
- **Decision:** OpenAI Agents SDK with OpenAI models (gpt-4o-mini by default, gpt-4o for Coverage and
  Decision Draft, `text-embedding-3-large`), hosted on AWS: ECS Fargate, API Gateway + Lambda, S3,
  OpenSearch, Cognito, DynamoDB, CloudWatch. Scored 4.65 vs Bedrock 4.20, Azure 3.55, GCP 2.80
  (`tools/stack_matrix.py`).
- **Why:** It's the cohort's technology standard and AutoSure hosts on AWS. Strict structured output
  suits the typed DecisionCard, and AWS gives Cognito/IAM identity and the audit path.
- **Alternatives considered:** (a) Claude on Bedrock. It keeps all data in the AWS account (it scores
  higher on data-path control), but diverges from the standard. (b) Azure OpenAI / Foundry. Wrong
  platform for an AWS client. (c) Google ADK + Gemini. Off-standard and off-platform.
- **Owner:** Susan Wellington (FDE)
- **Revisit when (flip triggers):** Security forbids an external model provider, so Bedrock wins (4.55).
  Or AutoSure is an M365/Entra shop on Azure, so Azure wins (4.15). The harness is unchanged either way.

## D-008 · 2026-11-05 · Pricing: fixed floor + capped acceptance bonus, with Phase 2 outcome pricing
- **Decision:** A fixed floor of $204,000 (cost $163,200 + 20%), plus up to $36,000 in bonus at
  $9,000 for each of acceptance criteria 1–4 met at the Week 5 run, counted by AutoSure's CI.
  Criterion 5 (zero harm) is a gate, not a bonus. Phase 2: $2.50 per adjuster-confirmed decision,
  capped at $30,000/month. Payments 30/40/30 at M1/M3/M4.
- **Why:** The class recommends this for a nervous, regulated client. The floor gives Procurement a
  ceiling and protects us through the access fight, and the bonus aligns us with the outcome. The pilot
  bonus is tied to acceptance criteria because synthetic-only data means real claim outcomes can't
  be counted yet. Expected 29.4% margin; revenue per engineer ≈ $605K/yr, inside the band.
- **Alternatives considered:** (a) T&M with a cap ($220,320, 25.9%). Procurement dislikes open hours.
  (b) Fixed price ($233,143, 30%). Fragile: a 25% overrun leaves 12.5%. (c) Pure outcome pricing on
  resolved claims. Not measurable on synthetic data, and it puts the vendor's revenue on a number
  Security won't let anyone measure for weeks.
- **Owner:** Susan Wellington (FDE) proposes; Claims Director + Legal/Procurement approve (RACI).
- **Revisit when:** The real rate card replaces $1,800/day, the access review slips more than a week
  (change control), or Phase 2 starts.
