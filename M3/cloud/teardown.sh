#!/usr/bin/env bash
# Remove everything M3/cloud/deploy.sh created. Keeps M1's Cognito pool (and its groups) and the DynamoDB tables,
# which belong to the M1 provisioning (M1/7-cloud/teardown.sh removes those). Safe to re-run.
set -uo pipefail
REGION=${AWS_REGION:-us-east-1}; export AWS_DEFAULT_REGION=$REGION
mask() { sed -E 's/[0-9]{12}/<acct>/g'; }
API_ID=$(aws apigatewayv2 get-apis --query "Items[?Name=='claimsense-door-api'].ApiId | [0]" --output text)
[ "$API_ID" != "None" ] && aws apigatewayv2 delete-api --api-id "$API_ID" && echo "deleted API $API_ID"
aws lambda delete-function --function-name claimsense-door 2>/dev/null && echo "deleted Lambda claimsense-door"
aws iam delete-role-policy --role-name claimsense-door-lambda --policy-name door-least-privilege 2>/dev/null
aws iam delete-role --role-name claimsense-door-lambda 2>/dev/null && echo "deleted role claimsense-door-lambda"
aws ecr delete-repository --repository-name claimsense/door --force >/dev/null 2>&1 && echo "deleted ECR claimsense/door"
POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='claimsense-autosure-users'].Id | [0]" --output text)
if [ "$POOL_ID" != "None" ]; then
  for u in alice bob carol eve dave; do
    aws cognito-idp admin-delete-user --user-pool-id "$POOL_ID" --username "$u" 2>/dev/null && echo "deleted user $u"
  done
  CID=$(aws cognito-idp list-user-pool-clients --user-pool-id "$POOL_ID" --max-results 60 \
    --query "UserPoolClients[?ClientName=='claimsense-door-proofs'].ClientId | [0]" --output text)
  [ "$CID" != "None" ] && aws cognito-idp delete-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CID" \
    && echo "deleted app client"
fi
rm -f "$HOME/.claimsense/cognito.json" "$HOME/.claimsense/deploy.json"
echo "teardown complete (M1's pool, groups and tables kept)" | mask
