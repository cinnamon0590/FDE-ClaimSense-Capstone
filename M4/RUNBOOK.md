# ClaimSense runbook (operations, M4)

For the AutoSure team that runs ClaimSense after handover. Every procedure is in the same shape:
**symptom → signal → decision → command → how you know it worked.** Each one was executed on the real system before
this page was written; the "Tested" line links the run.

**Where things are:**
- console: https://d2jfndltae6j40.cloudfront.net;
- dashboard: CloudWatch `ClaimSense-Operations`;
- alarm: `ClaimSense-door-error-rate` → SNS `claimsense-alerts`;
- audit: DynamoDB `claimsense-audit`, and `AUDIT` lines in `/aws/lambda/claimsense-door`.

**Prerequisites:**
- `aws login`, the repo, and `.venv`;
- deploy scripts refuse an uncommitted tree, because images are tagged with the commit.

**Golden rule:** change the door and its configuration **only** through `M3/cloud/deploy.sh`, never the AWS
console. That script syncs the data, runs a smoke test as a real adjuster, and rolls itself back if the smoke
fails. The one incident so far started with a console edit ([RCA](drill/RCA-2026-11-23.md)).

| Procedure | When | Time (measured) |
|---|---|---|
| [1 · Add or remove a user](#1--add-or-remove-a-user) | someone joins, changes role, or leaves | ≈ 4 min |
| [2 · Roll back a deployment](#2--roll-back-a-deployment) | a release misbehaves | door ≈ 15 s · frontend ≈ 2.5 min |
| [3 · Escalate a flagged claim manually](#3--escalate-a-flagged-claim-manually) | a person decides a claim needs SIU | ≈ 1 min |
| [4 · Update the policy corpus](#4--update-the-policy-corpus) | AutoSure changes policy wording | ≈ 15 min incl. the gate |
| [5 · Door error rate alarm](#5--door-error-rate-alarm) | the alarm email arrives | drill: 279 s to verified recovery |
| [6 · Eval pass rate below SLO](#6--eval-pass-rate-below-slo) | continuous eval exits 1 | — |

---

## 1 · Add or remove a user
- **Symptom:** a new adjuster can't sign in; someone changed role; someone left.
- **Signal:** HR or a team lead request. In the audit trail, `authenticate deny … token user is not in the
  directory` means the person isn't in the directory yet (or any more).
- **Decision:**
  - **who decides:** the claims operations manager approves the **group**, because the group alone decides what
    the person can open (adjuster = assigned claims only; senior adjuster = all; specialists = claims routed to
    them; customer service = none);
  - **no shared accounts.**
- **Command:**
  ```bash
  # 1. the directory is the source of record: add / edit / remove the person here
  $EDITOR M1/6-synthetic-data/source/users.json        # {"user_id", "display_name", "groups": [...]}
  cd M1/6-synthetic-data && python generate_fixtures.py && python validate_data.py && cd ../..
  python -m pytest -q && git commit -am "Directory: add <user> (<group>)"
  # 2. Cognito follows the directory (creates, regroups, or signs out + disables + deletes leavers), then the
  #    door ships the new directory and smoke-tests itself
  (cd M3 && cloud/deploy.sh)
  # 3. the console lists the directory's users; the orchestrator checks groups against it
  python M4/cloud/frontend.py apply
  ```
- **Worked when:**
  - `deploy.sh` prints `N users in their directory groups` (and `removed <user>` for a leaver);
  - the person runs a claim they are entitled to;
  - for a leaver, an old token returns 401 at once, because the door checks the directory on every call, not
    only when the token expires.
- **Passwords:** `deploy.sh` creates a user with a random password. Give the person a password they can type with
  `python M4/ops/set_password.py <user>`: it is strong (about 95 bits), set in Cognito, saved only in
  `~/.claimsense/cognito.json` and `logins.json` (0600), and never printed. Hand it over privately. The console has
  no user picker: each person signs in as themselves (D-056).
- **Tested:** [`evidence/runbook-add-remove-user.txt`](evidence/runbook-add-remove-user.txt). frank was added,
  ran a claim to approve $2,700, and was removed; his old token was refused and Cognito showed the user gone.

## 2 · Roll back a deployment
- **Symptom:** errors, wrong answers or a broken page right after a release.
- **Signal:**
  - the alarm;
  - the dashboard error-rate panel (the app line *and* the edge line);
  - a failed post-deploy smoke (`deploy.sh` has then already rolled back);
  - the continuous eval.
- **Decision:**
  - **roll back first, debug second;**
  - for a door release, `deploy.sh` will already have restored the previous release if its smoke failed. The
    commands below are for "it passed the smoke but is still wrong".
- **Command:**
  ```bash
  python M4/ops/rollback.py list                      # images per component, newest first, * = live
  python M4/ops/rollback.py door --to <tag>           # re-points the Lambda (+ --previous-config to restore the
                                                      #   configuration deploy.sh saved), then runs the smoke
  python M4/ops/rollback.py frontend --to <tag>       # console + orchestrator (ECS), then a health check
  ```
  - Tags are commits, and images are immutable and already passed the gate, so nothing is rebuilt.
  - Last resort for the door configuration only: `python M4/drill/incident_drill.py rollback` (the drill's
    saved last-good).
- **Worked when:**
  - `door rollback to <tag>: OK` (smoke PASS) or `frontend rollback to <tag>: OK · console health 'ok'`;
  - then open an issue, and add the failing case to the eval set **before** the fix, so the gate guards the
    repeat.
- **Tested:** [`evidence/runbook-rollback.txt`](evidence/runbook-rollback.txt). The door went back one release
  and forward in 15 s and 14 s, smoke PASS both ways; the frontend went back and forward in 154 s and 164 s,
  healthy both ways.

## 3 · Escalate a flagged claim manually
- **Symptom:** a claim the co-pilot flagged (`flag_review`, or a guardrail hold) needs the Special Investigations
  Unit, or an adjuster suspects fraud the co-pilot didn't flag.
- **Signal:** the card says FLAG_REVIEW / ROUTE, or "Guardrails fired"; or the adjuster's own judgment.
- **Decision:**
  - **a person escalates**, never the co-pilot on its own;
  - allowed: anyone who may open the claim (an assigned adjuster, a senior adjuster, the specialist it was
    routed to);
  - not allowed: customer service (the door refuses);
  - write the **reason** in plain words. The ticket carries the claim id and the reason, never claim data.
- **Command:**
  - **in the console:** under the card, **🚩 Escalate to SIU (manual)**, then enter the reason and priority and
    click **Escalate to SIU**;
  - **from a terminal** (on call, or when the console is down):
    ```bash
    python M4/ops/escalate.py --as <you> --claim <CLM-…> --reason "<why>" [--priority high] [--door aws]
    python M4/ops/escalate.py --as <you> --claim <CLM-…> --status
    ```
- **Worked when:** you get a ticket id (`SIU-…`, status `open`).
  - Re-sending the same request returns the **same** ticket (`idempotent_replay: true`). It never opens two.
  - **Ticketing down:** you get `503 … the escalation is queued and will be delivered` and status
    `pending_delivery`. Do nothing: the door delivers the queue on its own once ticketing is back.
  - **Ticketing not configured** (today's AWS pilot, where SIU ticketing is a local-only mock): page SIU on call
    with the claim id and reason, and record the SIU reference on the claim. This is the escalation map's
    manual path.
- **Tested:** [`evidence/runbook-escalate.txt`](evidence/runbook-escalate.txt).
  - CS-098: customer service and an unentitled specialist were refused; bob opened SIU-9005; the repeat
    returned the same ticket.
  - CS-099, with ticketing stopped: the escalation was queued, then delivered as SIU-9006 after a restart.
  - Testing this procedure **found a bug**: queued escalations were never delivered (nothing called the
    outbox). It is fixed and covered by `M3/tests/test_escalation_outbox_delivery.py`.

## 4 · Update the policy corpus
- **Symptom:** AutoSure changes policy wording (a new clause, a corrected one, a withdrawn one).
- **Signal:** a signed wording change from AutoSure's policy owner.
- **Decision:**
  - **who signs off:** the policy owner approves the text. The manifest of clause hashes is the provenance
    record, so a clause that isn't in it is quarantined and never cited;
  - **what must pass:** the gate must pass before release. Wording drives what the agents cite.
- **Command:**
  ```bash
  $EDITOR M1/6-synthetic-data/source/clauses.json      # add / edit the clause; bump "version"
  cd M1/6-synthetic-data && python generate_fixtures.py && python validate_data.py && cd ../..   # new signed manifest
  python -m pytest -q
  (cd M2 && CLAIMSENSE_LLM_REQUIRED=false python evals/run_evals.py --brain replay --suite full)  # $0, all 150
  python M4/ops/continuous_eval.py --sample 10 --no-publish                                     # live, ≈ $0.25
  git commit -am "Corpus <version>: <what changed> (approved by <policy owner>)"   # CI runs the live 150 + Promptfoo
  (cd M3 && cloud/deploy.sh)            # syncs S3 AND ships the matching manifest in the same release, then smoke
  python M4/cloud/frontend.py apply     # the console shows clause text from the same corpus
  ```
- **Worked when:**
  - `GET /policy-kb/search?q=<topic>` on the door returns the clause with `provenance: manifest` and `quarantined:
    []`;
  - the KB audit row says `0 quarantined`;
  - `M3/evals/s3_doc_store_check.py --deployed` passes.
- **Never:** edit the corpus in the S3 bucket by hand. The edited clause is (correctly) quarantined as unsigned,
  and the agents stop citing it.
- **Undo:** revert the commit and run the same two deploy commands (or procedure 2).
- **Tested:** [`evidence/runbook-corpus-update.txt`](evidence/runbook-corpus-update.txt). Corpus 2024.2 added
  CLS-RNT-013 (rental reimbursement):
  - checks before release: replay gate 150/150 with 0 adversarial failures; live sample 10/10;
  - on the deployed door it is retrieved for a rental question with manifest provenance and 0 quarantined,
    collision questions are unchanged, and alice's claim still approves at $2,700.

## 5 · Door error rate alarm
- **Symptom:** the email "ALARM: ClaimSense-door-error-rate"; adjusters see "Claim systems unavailable: nothing
  decided, try again".
- **Signal:** the dashboard error-rate panel.
  - **Edge line up, app line flat:** the door can't start (configuration, data store, permissions).
  - **Both lines up:** the door runs but fails (code, a dependency).
  - Read `/aws/lambda/claimsense-door` for the first traceback.
- **Decision:**
  - if a release or a configuration change happened in the last hour, **roll it back** (procedure 2) before
    anything else;
  - otherwise check the dependency named in the traceback (S3 bucket, DynamoDB table, Cognito).
- **Command:**
  ```bash
  python M4/ops/door_smoke.py                          # what fails, as a real adjuster and as the agents (RCA-2)
  python M4/ops/rollback.py list && python M4/ops/rollback.py door --to <last good> [--previous-config]
  ```
- **Worked when:**
  - the smoke passes;
  - the alarm returns to OK, and the "OK" email arrives;
  - a claim decides again.
  - Write a one-page RCA ([template](drill/RCA-2026-11-23.md)) for anything over 15 minutes.
- **Tested:** two incident drills ([`evidence/incident-drill-2.txt`](evidence/incident-drill-2.txt)). The alarm
  fired at +2 min 22 s, and recovery was verified at 279 s.

## 6 · Eval pass rate below SLO
- **Symptom:** `continuous_eval.py` exits 1, or the dashboard eval-pass panel is under 90%.
- **Signal:** the failing case ids it prints. **Any adversarial failure is a stop, whatever the rate.**
- **Decision:**
  - if a model snapshot or prompt changed, roll back (procedure 2);
  - otherwise read the failures: data drift, a corpus change, or a model provider issue (M2 runbook,
    "Model outage").
- **Command:**
  ```bash
  python M4/ops/continuous_eval.py --sample 25 --no-publish       # confirm with a bigger live sample
  (cd M2 && python evals/run_evals.py --suite full --concurrency 6) # the full live 150 (≈ $3.65)
  ```
- **Worked when:** the full live run passes the gate (≥ 90%, adversarial 100%) and the next continuous eval is
  back within the SLO.

---

**More failure modes:** model outage, orchestrator crash or redeploy mid-claim, hold spikes, model unsure, cost
spikes, key rotation, adopting a new model snapshot. These are in [`../M2/RUNBOOK.md`](../M2/RUNBOOK.md), still
current. Their rollback step now points here.
