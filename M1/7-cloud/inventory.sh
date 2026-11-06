#!/usr/bin/env bash
# Capture evidence of every ClaimSense resource (read-only). The account ID is masked so the
# output is safe to commit to a public repo.
#
# Usage:  ./inventory.sh > evidence/inventory-$(date +%F).txt
set -uo pipefail
REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$REGION"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
mask() { sed -E "s/${ACCOUNT}/${ACCOUNT:0:4}****${ACCOUNT:8:4}/g; s/([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+)/\1***@\2/g"; }
run() { printf '\n$ %s\n' "$*" | mask; "$@" 2>&1 | mask; }

BUCKET="claimsense-autosure-docs-${ACCOUNT}-${REGION}"
POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='claimsense-autosure-users'].Id | [0]" --output text)

echo "ClaimSense AI × AutoSure — cloud resource inventory"
echo "captured: $(date -u +%Y-%m-%dT%H:%M:%SZ) · region: $REGION · account: ${ACCOUNT:0:4}****${ACCOUNT:8:4}"
echo "identity:"; aws sts get-caller-identity --query Arn --output text | mask

run aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=ClaimSense \
    --query 'ResourceTagMappingList[].ResourceARN' --output table
run aws s3api get-public-access-block --bucket "$BUCKET" --output table
run aws s3api get-bucket-encryption --bucket "$BUCKET" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault' --output table
run aws s3api get-bucket-versioning --bucket "$BUCKET" --output table
run aws ecr describe-repositories --repository-names claimsense/orchestrator \
    --query 'repositories[0].{name:repositoryName,uri:repositoryUri,tags:imageTagMutability,scanOnPush:imageScanningConfiguration.scanOnPush}' --output table
run aws cognito-idp describe-user-pool --user-pool-id "$POOL_ID" \
    --query 'UserPool.{id:Id,name:Name,mfa:MfaConfiguration,adminCreateOnly:AdminCreateUserConfig.AllowAdminCreateUserOnly,minPassword:Policies.PasswordPolicy.MinimumLength}' --output table
run aws cognito-idp list-groups --user-pool-id "$POOL_ID" --query 'Groups[].GroupName' --output table
for t in claimsense-audit claimsense-idempotency; do
  run aws dynamodb describe-table --table-name "$t" \
      --query 'Table.{name:TableName,status:TableStatus,billing:BillingModeSummary.BillingMode,keys:KeySchema[].AttributeName,encrypted:SSEDescription.Status}' --output table
done
run aws dynamodb describe-continuous-backups --table-name claimsense-audit \
    --query 'ContinuousBackupsDescription.PointInTimeRecoveryDescription.PointInTimeRecoveryStatus' --output text
run aws dynamodb describe-time-to-live --table-name claimsense-idempotency --query 'TimeToLiveDescription' --output table
run aws logs describe-log-groups --log-group-name-prefix /claimsense/ \
    --query 'logGroups[].{name:logGroupName,retentionDays:retentionInDays}' --output table
run aws secretsmanager describe-secret --secret-id claimsense/openai-api-key \
    --query '{name:Name,created:CreatedDate,tags:length(Tags)}' --output table
run aws budgets describe-budget --account-id "$ACCOUNT" --budget-name ClaimSense-pilot-monthly \
    --query 'Budget.{name:BudgetName,limit:BudgetLimit.Amount,unit:BudgetLimit.Unit,period:TimeUnit}' --output table
run aws resource-groups list-group-resources --group-name ClaimSense-pilot \
    --query 'Resources[].Identifier.[ResourceType,ResourceArn]' --output table
run aws budgets describe-notifications-for-budget --account-id "$ACCOUNT" --budget-name ClaimSense-pilot-monthly \
    --query 'Notifications[].{type:NotificationType,over:Threshold,unit:ThresholdType}' --output table
