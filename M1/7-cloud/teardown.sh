#!/usr/bin/env bash
# Delete every resource provision.sh created (exit / offboarding, SoW §12). DESTRUCTIVE.
# Requires typing the confirmation phrase. Run ./inventory.sh afterwards to prove deletion.
#
# Usage:  ./teardown.sh
set -uo pipefail
REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="$REGION"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
read -r -p "This permanently deletes all ClaimSense pilot resources in ${REGION}. Type 'delete claimsense' to continue: " ans
[[ "$ans" == "delete claimsense" ]] || { echo "aborted"; exit 1; }

BUCKET="claimsense-autosure-docs-${ACCOUNT}-${REGION}"
echo "emptying + deleting s3://$BUCKET (all versions)"
aws s3api list-object-versions --bucket "$BUCKET" --output json 2>/dev/null | python3 -c '
import json, subprocess, sys
d = json.load(sys.stdin) if not sys.stdin.isatty() else {}
objs = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in (d.get("Versions") or []) + (d.get("DeleteMarkers") or [])]
for i in range(0, len(objs), 1000):
    subprocess.run(["aws", "s3api", "delete-objects", "--bucket", sys.argv[1], "--delete", json.dumps({"Objects": objs[i:i + 1000]})], check=False)
print(f"deleted {len(objs)} object versions")' "$BUCKET"
aws s3api delete-bucket --bucket "$BUCKET"
aws ecr delete-repository --repository-name claimsense/orchestrator --force >/dev/null && echo "ECR repository deleted"
POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='claimsense-autosure-users'].Id | [0]" --output text)
[[ "$POOL_ID" != "None" ]] && aws cognito-idp delete-user-pool --user-pool-id "$POOL_ID" && echo "Cognito pool deleted"
for t in claimsense-audit claimsense-idempotency; do aws dynamodb delete-table --table-name "$t" >/dev/null && echo "$t deleted"; done
for lg in /claimsense/audit /claimsense/orchestrator /claimsense/data-boundary; do aws logs delete-log-group --log-group-name "$lg" && echo "$lg deleted"; done
aws secretsmanager delete-secret --secret-id claimsense/openai-api-key --force-delete-without-recovery >/dev/null && echo "secret deleted"
aws resource-groups delete-group --group-name ClaimSense-pilot >/dev/null && echo "resource group deleted"
aws budgets delete-budget --account-id "$ACCOUNT" --budget-name ClaimSense-pilot-monthly && echo "budget deleted"
"$(dirname "$0")/../../M2/cloud/oidc.sh" --delete || true      # M2: GitHub OIDC role + provider
echo "teardown complete — run ./inventory.sh to verify nothing remains"
