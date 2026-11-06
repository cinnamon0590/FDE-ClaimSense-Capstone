# M1 Deliverable 7: Cloud account provisioned, with resources evidenced

*(Required by the ClaimSense brief's Milestone 2: "Cloud account provisioned, with the created
resources evidenced". Submission 1 also needs evidence that the stack runs under the participant's own account.)*

**Account:** Susan Wellington's own AWS account (`4747****8384`, masked because the repo is public) ·
**Region:** us-east-1 · **Provisioned:** 2026-11-05 · **Evidence:** [`evidence/inventory-2026-11-05.txt`](evidence/inventory-2026-11-05.txt) · [console screenshot](evidence/aws-console-resource-group-2026-11-05.png)

## What exists now

| Resource | Name | Hardening | Used from |
|---|---|---|---|
| S3 bucket | `claimsense-autosure-docs-<acct>-us-east-1` | public access blocked (all 4), SSE-S3 encryption, versioning, bucket-owner-enforced | M2: synthetic documents + clause corpus |
| ECR repository | `claimsense/orchestrator` | immutable tags, scan on push, keep last 10 images | M2: CI pushes the image only if the eval gate passes |
| Cognito user pool | `claimsense-autosure-users` (`us-east-1_xhmobmkut`) | admin-created users only, 14-character passwords, TOTP MFA, admin-only recovery | M3: identity + JWT for the data boundary |
| Cognito groups | adjuster · senior-adjuster · fraud-investigator · total-loss-appraiser · customer-service | the entitlement source | M3: entitlement in code |
| DynamoDB | `claimsense-audit` | on-demand, encrypted, **point-in-time recovery** | M3: append-only audit log |
| DynamoDB | `claimsense-idempotency` | on-demand, encrypted, **30-day TTL** on `expires_at` | M3: Idempotency-Key store |
| CloudWatch log groups | `/claimsense/audit`, `/claimsense/orchestrator`, `/claimsense/data-boundary` | 30-day retention | M2–M4: logs, dashboard, alarm |
| Secrets Manager | `claimsense/openai-api-key` | placeholder value; the real key is set by the owner, never committed | M2: orchestrator reads it at runtime |
| AWS Budgets | `ClaimSense-pilot-monthly` | $25/month cost budget | cost guardrail (alert email pending owner confirmation) |
| Resource Group | `ClaimSense-pilot` | saved tag query (`Project=ClaimSense`, all supported types) | one view of every pilot resource: evidence, dashboards (M4), teardown checks |

Every resource is tagged `Project=ClaimSense · Client=AutoSure · Environment=pilot ·
DataClass=synthetic · Owner=SusanWellington`, so one tag query inventories the whole pilot
(first block of the evidence file). The **`ClaimSense-pilot` Resource Group** saves that query in
AWS: console → *Resource Groups* → *Saved Resource Groups* → `ClaimSense-pilot` lists all 9 resources in one view
(last block of the evidence file).

## What it costs

Near zero at pilot volume: S3, ECR, DynamoDB on-demand, CloudWatch Logs and Cognito all sit
inside free tiers or cost cents. The one fixed charge is **Secrets Manager at about $0.40/month**
for the one secret. The cost-bearing services (ECS Fargate, API Gateway + Lambda, OpenSearch) are
deliberately **not** created until M2/M3, when there's code to run. The budget shows when spending passes $25/month.

## Scripts

```bash
cd M1/7-cloud
./provision.sh                                   # idempotent: safe to re-run; skips what exists
./inventory.sh > evidence/inventory-$(date +%F).txt   # read-only evidence, account ID masked
./teardown.sh                                    # DESTRUCTIVE: asks you to type "delete claimsense"
```

`teardown.sh` is the scripted exit promised in SoW §12: delete everything, then re-run
`inventory.sh` to prove nothing remains.

## Notes and follow-ups

- **Identity (resolved 2026-11-05):** the initial provisioning ran under the account's root credentials via
  `aws login`. Root was then retired from day-to-day use: an IAM admin user **`FDE_PROJECT_ADMIN`** was created
  with `AdministratorAccess` (+ `IAMUserChangePassword`), **MFA enforced**, **no access keys** (the CLI uses short-lived
  `aws login` sessions). The CLI now runs as that user, and the refreshed inventory shows it. Resources belong to
  the account, not the creating identity, so nothing was migrated. Still to do (M2): a GitHub OIDC role for CI.
- **Budget alerts (done):** two alerts on `ClaimSense-pilot-monthly`: forecast > 80% and actual > 100%, emailed
  to the owner. The address is passed at run time (`BUDGET_ALERT_EMAIL=… ./provision.sh`), never committed, and
  masked in the evidence file. **One-time step:** AWS Budgets now delivers email through **AWS User Notifications**,
  which registers the address as a contact and sends a verification link. Alerts aren't delivered until it's
  clicked. If the link expires, resend it with
  `aws notificationscontacts send-activation-code --arn <contact-arn>` and check `status` is `active` with
  `aws notificationscontacts list-email-contacts`. Verified active on 2026-11-05.
- **Console screenshot (Submission 1):** [`evidence/aws-console-resource-group-2026-11-05.png`](evidence/aws-console-resource-group-2026-11-05.png).
  The `ClaimSense-pilot` Resource Group in Susan's own account shows **Group resources (10)**: all 9 pilot resources
  (S3, ECR, Cognito, both DynamoDB tables, 3 log groups, the secret) plus the group itself. Redacted copy: browser
  bar and URL removed, account ID masked. "Tag: Name (not tagged)" is expected; our tags are Project, Client,
  Environment, DataClass and Owner.
