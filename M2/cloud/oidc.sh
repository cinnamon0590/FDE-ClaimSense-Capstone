#!/usr/bin/env bash
# GitHub Actions -> AWS with OIDC: short-lived credentials for CI, no stored AWS keys (M2).
# Creates (idempotently) the GitHub OIDC identity provider and the role `claimsense-github-ci`, which
#   * can be assumed ONLY by workflows in cinnamon0590/FDE-ClaimSense-Capstone on main or demo/* branches
#   * can ONLY push images to the claimsense/orchestrator ECR repository (nothing else in the account)
#
# Usage:  ./oidc.sh            create / update
#         ./oidc.sh --delete   remove role + provider (exit / offboarding)
# Afterwards store the printed role ARN as the GitHub secret AWS_CI_ROLE_ARN (the ARN contains the
# account ID, so it lives in a secret and never in the repo).
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
REPO_SLUG="cinnamon0590/FDE-ClaimSense-Capstone"
ROLE=claimsense-github-ci
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
PROVIDER_ARN="arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
ECR_ARN="arn:aws:ecr:${REGION}:${ACCOUNT}:repository/claimsense/orchestrator"

if [[ "${1:-}" == "--delete" ]]; then
  aws iam delete-role-policy --role-name "$ROLE" --policy-name ecr-push-orchestrator 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE" 2>/dev/null && echo "role deleted" || true
  aws iam delete-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" 2>/dev/null && echo "provider deleted" || true
  exit 0
fi

if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
  aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com --tags Key=Project,Value=ClaimSense >/dev/null
  echo "created GitHub OIDC provider"
fi

TRUST=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Federated":"${PROVIDER_ARN}"},
  "Action":"sts:AssumeRoleWithWebIdentity",
  "Condition":{
    "StringEquals":{"token.actions.githubusercontent.com:aud":"sts.amazonaws.com"},
    "StringLike":{"token.actions.githubusercontent.com:sub":[
      "repo:${REPO_SLUG}:ref:refs/heads/main",
      "repo:${REPO_SLUG}:ref:refs/heads/demo/*"]}}}]}
JSON
)
POLICY=$(cat <<JSON
{"Version":"2012-10-17","Statement":[
  {"Sid":"EcrLogin","Effect":"Allow","Action":"ecr:GetAuthorizationToken","Resource":"*"},
  {"Sid":"PushOrchestratorOnly","Effect":"Allow","Resource":"${ECR_ARN}","Action":[
    "ecr:BatchCheckLayerAvailability","ecr:InitiateLayerUpload","ecr:UploadLayerPart",
    "ecr:CompleteLayerUpload","ecr:PutImage","ecr:BatchGetImage","ecr:DescribeImages"]}]}
JSON
)
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "$TRUST"
else
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" --max-session-duration 3600 \
    --description "ClaimSense CI: push orchestrator image after the eval gate passes" \
    --tags Key=Project,Value=ClaimSense Key=Milestone,Value=M2 >/dev/null
  echo "created role $ROLE"
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name ecr-push-orchestrator --policy-document "$POLICY"
echo "role ready. Store it in GitHub (run from the repo):"
echo "  gh secret set AWS_CI_ROLE_ARN --body \"\$(aws iam get-role --role-name $ROLE --query Role.Arn --output text)\""
