#!/usr/bin/env bash
# Remove the Lambda rung (function, URL config, role, log group). Run on camera: idle deployments are silent burn.
set -uo pipefail
export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
FN=claimsense-orchestrator; ROLE=claimsense-orchestrator-lambda
aws lambda delete-function-url-config --function-name "$FN" 2>/dev/null
aws lambda delete-function --function-name "$FN" && echo "function deleted"
aws iam delete-role-policy --role-name "$ROLE" --policy-name read-openai-key 2>/dev/null
aws iam detach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole 2>/dev/null
aws iam delete-role --role-name "$ROLE" && echo "role deleted"
aws logs delete-log-group --log-group-name "/aws/lambda/$FN" 2>/dev/null && echo "log group deleted"
