#!/usr/bin/env bash
# Put the synthetic Policy & Coverage KB corpus, policy records and claim documents into M1's document bucket
# (private, SSE-S3, versioned): the Learning UI Viewer's "aws s3 sync ./data/policies/ s3://.../policies/" (D-044).
# The deployed door reads them from here (CLAIMSENSE_DOCS_BUCKET). Idempotent; ~$0. Needs `aws login`.
#
#   M3/cloud/sync_docs.sh            # stage + sync, then list what is in the bucket (account id masked)
set -euo pipefail
REGION=${AWS_REGION:-us-east-1}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
FIX="$ROOT/M1/6-synthetic-data/fixtures"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="claimsense-autosure-docs-${ACCOUNT}-${REGION}"          # created by M1/7-cloud/provision.sh
mask() { sed -E 's/[0-9]{12}/<acct>/g'; }
export AWS_DEFAULT_REGION=$REGION

aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1 || { echo "bucket missing: run M1/7-cloud/provision.sh" | mask; exit 1; }
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/data/policies" "$STAGE/data/documents"
cp "$FIX/clauses.json" "$FIX/policies.json" "$STAGE/data/policies/"
cp "$FIX/documents.json" "$STAGE/data/documents/"

echo "\$ aws s3 sync ./data/policies/ s3://$BUCKET/policies/" | mask
aws s3 sync "$STAGE/data/policies/" "s3://$BUCKET/policies/" --sse AES256 --delete --exact-timestamps --only-show-errors
echo "\$ aws s3 sync ./data/documents/ s3://$BUCKET/documents/" | mask
aws s3 sync "$STAGE/data/documents/" "s3://$BUCKET/documents/" --sse AES256 --delete --exact-timestamps --only-show-errors

echo; echo "in the bucket now (key · bytes · sha256 of the object · same as the fixture?):"
for key in policies/clauses.json policies/policies.json documents/documents.json; do
  aws s3 cp "s3://$BUCKET/$key" "$STAGE/got" --only-show-errors
  got=$(shasum -a 256 "$STAGE/got" | cut -c1-16); want=$(shasum -a 256 "$FIX/$(basename "$key")" | cut -c1-16)
  printf '  %-26s %8s bytes  %s…  %s\n' "$key" "$(wc -c < "$STAGE/got" | tr -d ' ')" "$got" \
    "$([ "$got" = "$want" ] && echo identical || echo DIFFERENT)"
done
aws s3api get-bucket-encryption --bucket "$BUCKET" --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' --output text | sed 's/^/  encryption: /'
aws s3api get-public-access-block --bucket "$BUCKET" --query 'PublicAccessBlockConfiguration.RestrictPublicBuckets' --output text | sed 's/^/  public access blocked: /'
