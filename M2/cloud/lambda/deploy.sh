#!/usr/bin/env bash
# Deploy ladder, rung 2 (W15 demo 4): run the gated orchestrator image on AWS Lambda.
# Uses the image CI pushed to ECR (tag = commit SHA). Function URL with AWS_IAM auth (never public).
# On Lambda the boundary runs in-process on the synthetic fixtures; M3 points BOUNDARY_URL at the
# API Gateway + Lambda boundary. Tear down with ./teardown.sh: idle deployments are silent burn.
#
# Usage: ./deploy.sh <image-tag>      e.g. ./deploy.sh $(git rev-parse HEAD)
set -euo pipefail
TAG="${1:?usage: deploy.sh <image tag pushed by CI>}"
REGION="${AWS_REGION:-us-east-1}"; export AWS_DEFAULT_REGION="$REGION"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
FN=claimsense-orchestrator; ROLE=claimsense-orchestrator-lambda
IMAGE="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/claimsense/orchestrator:${TAG}"
SECRET_ARN=$(aws secretsmanager describe-secret --secret-id claimsense/openai-api-key --query ARN --output text)

if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" --tags Key=Project,Value=ClaimSense --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  aws iam put-role-policy --role-name "$ROLE" --policy-name read-openai-key --policy-document \
    "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"${SECRET_ARN}\"}]}"
  echo "created role $ROLE (waiting for IAM propagation)"; sleep 12
fi
ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)
# The function reads the key from Secrets Manager at start-up (OPENAI_SECRET_ID); it is never in an env var,
# the image or git. MOCK_BRAIN=0 asks for the live models; with the M1 placeholder still in the secret the
# service falls back to the replay brain by itself.
ENV="Variables={MOCK_BRAIN=0,OPENAI_SECRET_ID=claimsense/openai-api-key,CLAIMSENSE_STATE=/tmp/state}"

if aws lambda get-function --function-name "$FN" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --image-uri "$IMAGE" >/dev/null
  aws lambda wait function-updated --function-name "$FN"
  aws lambda update-function-configuration --function-name "$FN" --environment "$ENV" >/dev/null
else
  aws lambda create-function --function-name "$FN" --package-type Image --code ImageUri="$IMAGE" \
    --role "$ROLE_ARN" --timeout 120 --memory-size 1024 --environment "$ENV" \
    --tags Project=ClaimSense,Milestone=M2 >/dev/null
fi
aws lambda wait function-active-v2 --function-name "$FN"
aws logs put-retention-policy --log-group-name "/aws/lambda/$FN" --retention-in-days 30 2>/dev/null || true
aws lambda create-function-url-config --function-name "$FN" --auth-type AWS_IAM >/dev/null 2>&1 || true
echo "deployed $FN from :${TAG}. Next: ./invoke.sh CLM-2024-1800"
