# M0 Deliverable 2: Stakeholder map and RACI

**Engagement:** ClaimSense AI · AutoSure Insurance (motor) · **FDE:** Susan Wellington · **Date:** 2026-11-04

The person who signs the contract is not the person who can block the project, and neither is the
person who will use the system every day. This map names all of them before anything is built.

## The four roles the brief asks for

| Role in the brief | Who | Why them |
|---|---|---|
| **Approver** | **Claims Director** (sponsor) | Signed the engagement. Owns the business outcome (backlog, fraud leakage, speed). Accountable for the charter, the eval-gate threshold and the go-live decision. |
| **Reviewer of co-pilot output** | **Senior Adjuster / Team Lead** | Licensed; owns the quality of what the co-pilot produces. Reviews every flag_review case and anything above the $25K authority limit, audits the adjusters' confirm/override log weekly, owns the golden labels, and runs the SC-3 acceptance review. Accountable for every confirmed outcome (RACI). |
| **Daily user** | **Claims adjusters** (front-line licensed adjusters) | Run the co-pilot on every new claim in the Adjuster Console and confirm or override routine outcomes (approve / deny / route), giving a reason for each override. Today they are the integration layer across three systems. |
| **Who can block rollout** | **Security / Compliance** (hard veto) | Must approve the auth model, data handling and audit trail before any system touches claim data. Can stop the capstone Week 4 (M3) integration dead. |

**Exactly one Accountable for "the pilot succeeds": the Claims Director.**

## Stakeholder map (influence, veto, what they want, how we lose them)

| Stakeholder | Type | Veto | Wants | How we lose them |
|---|---|---|---|---|
| Claims Director | Sponsor / approver | None (sponsor, not a blocker) | Minutes-not-hours first pass, fewer fraud payouts, a defensible number for the CFO | Showing architecture instead of outcomes; criteria that can't settle "did it work?" |
| Senior Adjuster / Team Lead | Primary user / reviewer | **Quiet**: stops confirming and the tool dies | Accurate drafts with evidence already gathered; fewer juniors asking "is this covered?" | A confident wrong answer; citations that don't support the claim; extra clicks |
| Claims adjusters (front line) | Daily users, **not on the org chart as decision-makers** | **Quiet**: will route around a tool that slows them down | Less re-keying across three systems; a clear next step | Auto-decisions that leave their name on the outcome; latency above minutes |
| Security / Compliance | Blocker | **Hard**: no claim data without approval of auth, data handling, audit | Synthetic data only; access control in code, not prompts; every call audited (incl. refusals) | Asking for real data early; RBAC "in the prompt"; consulting them only in capstone Week 4 (M3) |
| IT / Cloud team | Technical enabler | **Bandwidth**: access, networking, ECR/ECS permissions wait on them | Containerised, documented, torn down when idle; nothing running in their account unexplained | Last-minute permission requests; idle cloud spend |
| Legal / Procurement | Contract gate | **Hard** (on the contract): must sign the SoW | Clear IP, data ownership and liability terms; a pricing model with a ceiling | Vague scope; synthetic-data and IP terms left implicit |
| CFO | Indirect influence | Budget | ROI, cost per claim, total engagement cost | No cost-per-claim figure at the capstone Week 5 (M4) readout |
| Fraud investigators (SIU) | Downstream receivers of `route` | Quiet (on routing) | Referrals that are real, with the inconsistency already cited | Being flooded with false routes (SC-4 false-route rate) |

**Off-org-chart veto:** the front-line adjusters and senior reviewers decide adoption by whether they
confirm the drafts, not by any sign-off. SC-3 measures exactly this.

## RACI: who does what

R = Responsible · A = Accountable (exactly one per row) · C = Consulted · I = Informed

| Deliverable / decision | Claims Dir | Senior Adj / TL | Adjusters | Security | IT / Cloud | Legal / Proc | CFO | FDE |
|---|---|---|---|---|---|---|---|---|
| Engagement charter (M0) | **A** | C | I | I | I | I | I | R |
| Success criteria & eval-gate threshold | **A** | C | C | I | I | I | I | R |
| Seed eval set & golden labels | C | **A** | C | I | – | – | – | R |
| SoW, pricing, IP & data terms (M1) | **A** | I | – | C | I | R | C | R |
| Architecture & code/model boundary (M1) | C | I | – | C | C | – | – | **R/A** |
| Auth model / RBAC & audit trail (M3) | C | I | – | **A** | C | – | – | R |
| Cloud account & deployment (M1–M4) | I | – | – | C | **A** | – | I | R |
| Agent pipeline build (M2) | I | C | I | I | I | – | – | **R/A** |
| Confirming each claim outcome (runtime) | I | **A** | R | – | – | – | – | I |
| Go-live decision (M4) | **A** | C | C | C | C | I | I | I |

**Practical rule (from discovery):** Security is Consulted on the auth model in M1 (course W14),
two weeks before it is Accountable for approving it in M3 (W16). If they first see it in capstone
Week 4 (M3), they will block it, and they'd be right to.

## Engagement cadence: how each stakeholder stays engaged

| Stakeholder | Touchpoint | Cadence | What they see | Risk it defuses |
|---|---|---|---|---|
| Claims Director | Written charter confirmation, then a weekly 15-min outcome readout | Within 24 h of discovery, then weekly | Eval scores vs targets (rule-table baseline → co-pilot), latency, open decisions | Criteria drift; a surprise at the capstone Week 5 (M4) readout |
| Senior Adjuster / Team Lead | Golden-label review and a hands-on session with decision cards | Weekly (labels), M2 onward (cards) | Every case label, override reasons, citation quality | Quiet veto: distrust of drafts |
| Claims adjusters | Short console walkthrough and feedback form | M2 demo, then the capstone Week 5 (M4) review | Decision cards on real-looking claims | Routing around the tool |
| Security / Compliance | Auth model, data handling and audit design review | M1 (consulted), M3 (approval) | Boundary design, RBAC matrix, audit row format, synthetic-data attestation | Hard veto at the capstone Week 4 (M3) integration |
| IT / Cloud | Resource plan and teardown policy | M1, then before each deploy | What runs where, IAM needs, idle-cost controls | Bandwidth veto; permission delays |
| Legal / Procurement | SoW review | M1 | IP, data ownership, liability, synthetic-data terms | Contract gate |
| CFO | Cost-per-claim line in the final readout | M4 | $/claim and engagement cost | Budget challenge |

## Who will own it after we leave

The **Senior Adjuster / Team Lead** owns day-to-day operation (confirmation queue, override reasons,
new eval cases). **IT / Cloud** owns the deployed stack and runbook (M4). The handover is signed off
only when they operate the system from the runbook without the FDE.
