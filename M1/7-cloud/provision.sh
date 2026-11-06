#!/usr/bin/env bash
# ClaimSense AI × AutoSure — M1 cloud provisioning (idempotent: safe to re-run).
#
# Creates ONLY low-cost / free-tier foundations that later milestones build on. Everything is
# tagged Project=ClaimSense so it can be inventoried and torn down (teardown.sh) in one pass.
#   S3 bucket (documents + clause corpus) · ECR repository · Cognito user pool + 5 groups ·
#   DynamoDB audit + idempotency tables · CloudWatch log groups · Secrets Manager placeholder ·
#   AWS Budgets monthly cost budget · Resource Group ClaimSense-pilot (saved tag query)
# Not created here (cost-bearing until there's something to run): ECS services, API Gateway/Lambda,
# OpenSearch — those arrive in M2/M3.
#
# Usage:  BUDGET_ALERT_EMAIL=you@example.com ./provision.sh   (AWS CLI v2 signed in: `aws login`;
#         the email is optional and never stored in the repo)
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$REGION"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
TAGS_KV=(Project=ClaimSense Client=AutoSure Environment=pilot DataClass=synthetic Owner=SusanWellington)
TAGS_JSON='[{"Key":"Project","Value":"ClaimSense"},{"Key":"Client","Value":"AutoSure"},{"Key":"Environment","Value":"pilot"},{"Key":"DataClass","Value":"synthetic"},{"Key":"Owner","Value":"SusanWellington"}]'
TAGS_SHORTHAND="Key=Project,Value=ClaimSense Key=Client,Value=AutoSure Key=Environment,Value=pilot Key=DataClass,Value=synthetic Key=Owner,Value=SusanWellington"

BUCKET="claimsense-autosure-docs-${ACCOUNT}-${REGION}"
ECR_REPO="claimsense/orchestrator"
POOL_NAME="claimsense-autosure-users"
COGNITO_GROUPS=(adjuster senior-adjuster fraud-investigator total-loss-appraiser customer-service)
AUDIT_TABLE="claimsense-audit"
IDEM_TABLE="claimsense-idempotency"
LOG_GROUPS=(/claimsense/audit /claimsense/orchestrator /claimsense/data-boundary)
SECRET="claimsense/openai-api-key"
BUDGET="ClaimSense-pilot-monthly"
BUDGET_USD="25"

say() { printf '\n==> %s\n' "$*"; }

# ── S3: documents + clause corpus ─────────────────────────────────────────────────────────────
say "S3 bucket $BUCKET"
if aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then echo "exists"; else
  aws s3api create-bucket --bucket "$BUCKET" >/dev/null       # us-east-1 takes no LocationConstraint
  echo "created"
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging "{\"TagSet\":$TAGS_JSON}"
aws s3api put-bucket-ownership-controls --bucket "$BUCKET" --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'
echo "public access blocked · SSE-S3 encryption · versioning · tags"

# ── ECR: container images ─────────────────────────────────────────────────────────────────────
say "ECR repository $ECR_REPO"
if aws ecr describe-repositories --repository-names "$ECR_REPO" >/dev/null 2>&1; then echo "exists"; else
  aws ecr create-repository --repository-name "$ECR_REPO" --image-tag-mutability IMMUTABLE \
    --image-scanning-configuration scanOnPush=true --encryption-configuration encryptionType=AES256 \
    --tags $TAGS_SHORTHAND >/dev/null
  echo "created (immutable tags, scan on push)"
fi
aws ecr put-lifecycle-policy --repository-name "$ECR_REPO" --lifecycle-policy-text \
  '{"rules":[{"rulePriority":1,"description":"keep last 10 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}' >/dev/null
echo "lifecycle: keep last 10 images"

# ── Cognito: identity + groups (entitlement source for the data boundary) ─────────────────────
say "Cognito user pool $POOL_NAME"
POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='$POOL_NAME'].Id | [0]" --output text)
if [[ "$POOL_ID" != "None" && -n "$POOL_ID" ]]; then echo "exists ($POOL_ID)"; else
  POOL_ID=$(aws cognito-idp create-user-pool --pool-name "$POOL_NAME" \
    --policies 'PasswordPolicy={MinimumLength=14,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=true,TemporaryPasswordValidityDays=3}' \
    --admin-create-user-config AllowAdminCreateUserOnly=true \
    --username-configuration CaseSensitive=false \
    --account-recovery-setting 'RecoveryMechanisms=[{Priority=1,Name=admin_only}]' \
    --user-pool-tags Project=ClaimSense,Client=AutoSure,Environment=pilot,DataClass=synthetic,Owner=SusanWellington \
    --query UserPool.Id --output text)
  echo "created ($POOL_ID): admin-created users only, 14-char passwords"
fi
aws cognito-idp set-user-pool-mfa-config --user-pool-id "$POOL_ID" \
  --software-token-mfa-configuration Enabled=true --mfa-configuration OPTIONAL >/dev/null
echo "TOTP (authenticator-app) MFA enabled, optional per user"
for g in "${COGNITO_GROUPS[@]}"; do
  if aws cognito-idp get-group --user-pool-id "$POOL_ID" --group-name "$g" >/dev/null 2>&1; then echo "group $g exists"; else
    aws cognito-idp create-group --user-pool-id "$POOL_ID" --group-name "$g" \
      --description "ClaimSense role: $g (entitlement scope enforced in the data boundary)" >/dev/null
    echo "group $g created"
  fi
done

# ── DynamoDB: audit (append-only) + idempotency keys (30-day TTL) ─────────────────────────────
say "DynamoDB tables"
if aws dynamodb describe-table --table-name "$AUDIT_TABLE" >/dev/null 2>&1; then echo "$AUDIT_TABLE exists"; else
  aws dynamodb create-table --table-name "$AUDIT_TABLE" --billing-mode PAY_PER_REQUEST \
    --attribute-definitions AttributeName=resource,AttributeType=S AttributeName=ts_request,AttributeType=S \
    --key-schema AttributeName=resource,KeyType=HASH AttributeName=ts_request,KeyType=RANGE \
    --sse-specification Enabled=true --tags $TAGS_SHORTHAND >/dev/null
  echo "$AUDIT_TABLE created (pk resource, sk ts#request_id; on-demand; encrypted)"
fi
if aws dynamodb describe-table --table-name "$IDEM_TABLE" >/dev/null 2>&1; then echo "$IDEM_TABLE exists"; else
  aws dynamodb create-table --table-name "$IDEM_TABLE" --billing-mode PAY_PER_REQUEST \
    --attribute-definitions AttributeName=scope_key,AttributeType=S \
    --key-schema AttributeName=scope_key,KeyType=HASH \
    --sse-specification Enabled=true --tags $TAGS_SHORTHAND >/dev/null
  echo "$IDEM_TABLE created (pk caller|operation|key; on-demand; encrypted)"
fi
aws dynamodb wait table-exists --table-name "$AUDIT_TABLE"
aws dynamodb wait table-exists --table-name "$IDEM_TABLE"
aws dynamodb update-continuous-backups --table-name "$AUDIT_TABLE" \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true >/dev/null
aws dynamodb update-time-to-live --table-name "$IDEM_TABLE" \
  --time-to-live-specification Enabled=true,AttributeName=expires_at >/dev/null 2>&1 || echo "TTL already enabled"
echo "audit: point-in-time recovery on · idempotency: TTL on expires_at (30 days)"

# ── CloudWatch log groups ─────────────────────────────────────────────────────────────────────
say "CloudWatch log groups"
for lg in "${LOG_GROUPS[@]}"; do
  if [[ $(aws logs describe-log-groups --log-group-name-prefix "$lg" --query "length(logGroups[?logGroupName=='$lg'])" --output text) == "1" ]]; then
    echo "$lg exists"
  else
    aws logs create-log-group --log-group-name "$lg" --tags Project=ClaimSense,Client=AutoSure,Environment=pilot,DataClass=synthetic,Owner=SusanWellington
    echo "$lg created"
  fi
  aws logs put-retention-policy --log-group-name "$lg" --retention-in-days 30
done
echo "retention: 30 days"

# ── Secrets Manager: OpenAI key placeholder (real value set by the owner, never committed) ────
say "Secrets Manager $SECRET"
if aws secretsmanager describe-secret --secret-id "$SECRET" >/dev/null 2>&1; then echo "exists (value not touched)"; else
  aws secretsmanager create-secret --name "$SECRET" \
    --description "OpenAI API key for the ClaimSense orchestrator. Placeholder until the owner sets it." \
    --secret-string "REPLACE_ME_WITH_OPENAI_KEY" --tags "$TAGS_JSON" >/dev/null
  echo "created with a placeholder value"
fi

# ── AWS Budgets: monthly cost guardrail for the pilot ─────────────────────────────────────────
say "AWS Budgets $BUDGET (\$$BUDGET_USD/month)"
if aws budgets describe-budget --account-id "$ACCOUNT" --budget-name "$BUDGET" >/dev/null 2>&1; then echo "exists"; else
  aws budgets create-budget --account-id "$ACCOUNT" --budget "{
    \"BudgetName\": \"$BUDGET\", \"BudgetType\": \"COST\", \"TimeUnit\": \"MONTHLY\",
    \"BudgetLimit\": {\"Amount\": \"$BUDGET_USD\", \"Unit\": \"USD\"}}"
  echo "created"
fi
# Alerts: 80% of FORECAST (early warning) and 100% of ACTUAL. The recipient is passed at run time
# (BUDGET_ALERT_EMAIL) so no email address is ever committed to the repo.
if [[ -n "${BUDGET_ALERT_EMAIL:-}" ]]; then
  for spec in "FORECASTED 80" "ACTUAL 100"; do
    set -- $spec
    if aws budgets describe-notifications-for-budget --account-id "$ACCOUNT" --budget-name "$BUDGET" \
         --query "Notifications[?NotificationType=='$1' && Threshold==\`$2\`] | length(@)" --output text | grep -q '^1$'; then
      echo "alert $1 > $2% exists"
    else
      aws budgets create-notification --account-id "$ACCOUNT" --budget-name "$BUDGET" \
        --notification "NotificationType=$1,ComparisonOperator=GREATER_THAN,Threshold=$2,ThresholdType=PERCENTAGE" \
        --subscribers "SubscriptionType=EMAIL,Address=$BUDGET_ALERT_EMAIL"
      echo "alert $1 > $2% created"
    fi
  done
else
  echo "no BUDGET_ALERT_EMAIL set: budget exists without alerts"
fi

# ── Resource Group: one saved, tag-based view of every pilot resource ─────────────────────────
say "Resource Group ClaimSense-pilot"
if aws resource-groups get-group --group-name ClaimSense-pilot >/dev/null 2>&1; then echo "exists"; else
  aws resource-groups create-group --name ClaimSense-pilot \
    --description "Every ClaimSense pilot resource tagged Project ClaimSense - evidence dashboards and teardown checks" \
    --resource-query '{"Type":"TAG_FILTERS_1_0","Query":"{\"ResourceTypeFilters\":[\"AWS::AllSupported\"],\"TagFilters\":[{\"Key\":\"Project\",\"Values\":[\"ClaimSense\"]}]}"}' \
    --tags Project=ClaimSense,Client=AutoSure,Environment=pilot,DataClass=synthetic,Owner=SusanWellington >/dev/null
  echo "created (tag query: Project=ClaimSense, all supported types)"
fi

say "Done. Run ./inventory.sh to capture evidence."
