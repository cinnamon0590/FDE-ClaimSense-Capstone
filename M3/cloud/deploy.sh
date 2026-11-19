#!/usr/bin/env bash
# Deploy the ClaimSense governed door to AWS (M3 D-1): API Gateway (HTTP API, Cognito JWT authorizer) -> Lambda
# (container image, Lambda Web Adapter) -> the door, writing the append-only DynamoDB audit table M1 provisioned.
# Idempotent: re-running updates in place. Reuses M1's Cognito user pool (5 groups) and claimsense-audit table.
#
#   aws login            # Susan runs this herself
#   M3/cloud/deploy.sh   # ~3 min; prints the door URL; expected cost ≈ $0 (free tiers), see README
#   M3/cloud/teardown.sh # removes everything this script created (keeps M1's pool and table)
#
# Secrets: none in the repo, the image, or this script's output. The synthetic users' random passwords and the
# pool/client ids go ONLY to ~/.claimsense/cognito.json (0600) for the proof scripts; the AWS account id is masked.
set -euo pipefail
REGION=${AWS_REGION:-us-east-1}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
POOL_NAME=claimsense-autosure-users
CLIENT_NAME=claimsense-door-proofs
REPO=claimsense/door
FN=claimsense-door
ROLE=claimsense-door-lambda
API=claimsense-door-api
AUDIT_TABLE=claimsense-audit
CONF_DIR="$HOME/.claimsense"
TAG=$(git -C "$ROOT" rev-parse --short HEAD)$( [ -n "$(git -C "$ROOT" status --porcelain)" ] && echo -dirty || true)
mask() { sed -E 's/[0-9]{12}/<acct>/g'; }
say() { printf '\n==> %s\n' "$*" | mask; }
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export AWS_DEFAULT_REGION=$REGION

say "Cognito: M1's user pool $POOL_NAME + an app client for the door"
POOL_ID=$(aws cognito-idp list-user-pools --max-results 60 --query "UserPools[?Name=='$POOL_NAME'].Id | [0]" --output text)
[ "$POOL_ID" != "None" ] || { echo "M1 pool $POOL_NAME not found (run M1/7-cloud/provision.sh)"; exit 1; }
ISSUER="https://cognito-idp.$REGION.amazonaws.com/$POOL_ID"
CLIENT_ID=$(aws cognito-idp list-user-pool-clients --user-pool-id "$POOL_ID" --max-results 60 \
  --query "UserPoolClients[?ClientName=='$CLIENT_NAME'].ClientId | [0]" --output text)
if [ "$CLIENT_ID" = "None" ]; then
  CLIENT_ID=$(aws cognito-idp create-user-pool-client --user-pool-id "$POOL_ID" --client-name "$CLIENT_NAME" \
    --no-generate-secret --explicit-auth-flows ALLOW_ADMIN_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH \
    --id-token-validity 60 --access-token-validity 60 --token-validity-units IdToken=minutes,AccessToken=minutes \
    --prevent-user-existence-errors ENABLED --query UserPoolClient.ClientId --output text)
fi
echo "pool + client ready (ids written to $CONF_DIR/cognito.json only)"

say "Cognito: the five synthetic adjusters, groups = the directory's (users.json)"
mkdir -p "$CONF_DIR" && chmod 700 "$CONF_DIR"
python3 - "$ROOT" "$POOL_ID" "$CLIENT_ID" "$REGION" "$CONF_DIR/cognito.json" <<'PY'
import json, os, secrets, string, subprocess, sys
root, pool, client, region, out = sys.argv[1:]
users = json.load(open(f"{root}/M1/6-synthetic-data/fixtures/users.json"))["records"]
old = json.load(open(out)) if os.path.exists(out) else {}
pw = old.get("passwords", {}) if old.get("pool_id") == pool else {}
def aws(*a, check=True):
    return subprocess.run(["aws", "cognito-idp", *a, "--region", region], capture_output=True, text=True, check=check)
for u in users:
    name = u["user_id"]
    if name not in pw:     # 14+ chars, all four classes (M1's password policy), never printed
        pw[name] = "Cs-" + secrets.token_urlsafe(18) + "9a!"
    if aws("admin-get-user", "--user-pool-id", pool, "--username", name, check=False).returncode != 0:
        aws("admin-create-user", "--user-pool-id", pool, "--username", name, "--message-action", "SUPPRESS",
            "--user-attributes", f"Name=name,Value={u['display_name']}")
    aws("admin-set-user-password", "--user-pool-id", pool, "--username", name, "--password", pw[name], "--permanent")
    current = json.loads(aws("admin-list-groups-for-user", "--user-pool-id", pool, "--username", name).stdout)
    have = {g["GroupName"] for g in current["Groups"]}
    for g in set(u["groups"]) - have:
        aws("admin-add-user-to-group", "--user-pool-id", pool, "--username", name, "--group-name", g)
    for g in have - set(u["groups"]):
        aws("admin-remove-user-from-group", "--user-pool-id", pool, "--username", name, "--group-name", g)
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump({"region": region, "pool_id": pool, "client_id": client, "passwords": pw}, f)
print(f"{len(users)} users in their directory groups")
PY

say "ECR $REPO: build the door image (linux/amd64, single manifest for Lambda) and push tag $TAG"
aws ecr describe-repositories --repository-names "$REPO" >/dev/null 2>&1 || \
  aws ecr create-repository --repository-name "$REPO" --image-scanning-configuration scanOnPush=true \
    --image-tag-mutability IMMUTABLE --tags Key=Project,Value=ClaimSense Key=DataClass,Value=synthetic >/dev/null
REG="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
aws ecr get-login-password | docker login --username AWS --password-stdin "$REG" 2>&1 | mask
IMAGE="$REG/$REPO:$TAG"
if ! aws ecr describe-images --repository-name "$REPO" --image-ids imageTag="$TAG" >/dev/null 2>&1; then
  docker build --provenance=false --platform linux/amd64 -f "$ROOT/M3/cloud/door.Dockerfile" -t "$IMAGE" "$ROOT" -q | mask
  docker push -q "$IMAGE" | mask
fi
docker logout "$REG" >/dev/null 2>&1   # never leave the ECR token in ~/.docker/config.json
DIGEST=$(aws ecr describe-images --repository-name "$REPO" --image-ids imageTag="$TAG" --query 'imageDetails[0].imageDigest' --output text)
echo "image $REPO:$TAG @ $DIGEST"

say "IAM $ROLE: logs + append-only writes and reads on $AUDIT_TABLE, nothing else"
TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam get-role --role-name "$ROLE" >/dev/null 2>&1 || \
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "$TRUST" >/dev/null
POLICY=$(cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
  "Resource":"arn:aws:logs:$REGION:$ACCOUNT:log-group:/aws/lambda/$FN:*"},
 {"Effect":"Allow","Action":["dynamodb:PutItem","dynamodb:Scan"],
  "Resource":"arn:aws:dynamodb:$REGION:$ACCOUNT:table/$AUDIT_TABLE"}]}
JSON
)
aws iam put-role-policy --role-name "$ROLE" --policy-name door-least-privilege --policy-document "$POLICY"
ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)

say "API Gateway $API (HTTP API): Cognito JWT authorizer on every route except health, keys, metadata, token exchange, webhook"
API_ID=$(aws apigatewayv2 get-apis --query "Items[?Name=='$API'].ApiId | [0]" --output text)
[ "$API_ID" != "None" ] || API_ID=$(aws apigatewayv2 create-api --name "$API" --protocol-type HTTP \
  --tags Project=ClaimSense,DataClass=synthetic --query ApiId --output text)
URL="https://$API_ID.execute-api.$REGION.amazonaws.com"

say "Lambda $FN (image, 1024 MB, 30 s, reserved concurrency 1)"
ENVV="Variables={COGNITO_JWKS_URL=$ISSUER/.well-known/jwks.json,CLAIMSENSE_JWT_ISSUER=$ISSUER,CLAIMSENSE_JWT_AUDIENCE=$CLIENT_ID,CLAIMSENSE_AUTH_SERVER=$ISSUER,CLAIMSENSE_AUDIT_TABLE=$AUDIT_TABLE,CLAIMSENSE_PUBLIC_URL=$URL}"
if aws lambda get-function --function-name "$FN" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --image-uri "$IMAGE" >/dev/null
  aws lambda wait function-updated --function-name "$FN"
  aws lambda update-function-configuration --function-name "$FN" --environment "$ENVV" >/dev/null
else
  for _ in 1 2 3 4 5 6; do   # a new role takes a few seconds to become assumable
    aws lambda create-function --function-name "$FN" --package-type Image --code ImageUri="$IMAGE" \
      --role "$ROLE_ARN" --memory-size 1024 --timeout 30 --architectures x86_64 --environment "$ENVV" \
      --tags Project=ClaimSense,DataClass=synthetic >/dev/null 2>&1 && break
    sleep 10
  done
fi
aws lambda wait function-updated --function-name "$FN" 2>/dev/null || aws lambda wait function-active --function-name "$FN"
# one warm instance holds /tmp state; accounts with the minimum concurrency quota (10) can't reserve any, so fall back
aws lambda put-function-concurrency --function-name "$FN" --reserved-concurrent-executions 1 >/dev/null 2>&1 || \
  echo "note: account concurrency quota too low to reserve 1; running unreserved (sequential traffic stays on one warm instance)"
FN_ARN=$(aws lambda get-function --function-name "$FN" --query Configuration.FunctionArn --output text)

say "API Gateway integration, authorizer, routes, stage"
INTEG=$(aws apigatewayv2 get-integrations --api-id "$API_ID" --query "Items[0].IntegrationId" --output text)
[ "$INTEG" != "None" ] || INTEG=$(aws apigatewayv2 create-integration --api-id "$API_ID" --integration-type AWS_PROXY \
  --integration-uri "$FN_ARN" --payload-format-version 2.0 --query IntegrationId --output text)
AUTH=$(aws apigatewayv2 get-authorizers --api-id "$API_ID" --query "Items[?Name=='cognito'].AuthorizerId | [0]" --output text)
[ "$AUTH" != "None" ] || AUTH=$(aws apigatewayv2 create-authorizer --api-id "$API_ID" --name cognito \
  --authorizer-type JWT --identity-source '$request.header.Authorization' \
  --jwt-configuration "Audience=$CLIENT_ID,Issuer=$ISSUER" --query AuthorizerId --output text)
route() {   # route key, authorizer (or NONE)
  local id; id=$(aws apigatewayv2 get-routes --api-id "$API_ID" --query "Items[?RouteKey=='$1'].RouteId | [0]" --output text)
  if [ "$2" = NONE ]; then
    [ "$id" != "None" ] || aws apigatewayv2 create-route --api-id "$API_ID" --route-key "$1" --target "integrations/$INTEG" >/dev/null
  else
    [ "$id" != "None" ] || aws apigatewayv2 create-route --api-id "$API_ID" --route-key "$1" --target "integrations/$INTEG" \
      --authorization-type JWT --authorizer-id "$2" >/dev/null
  fi
}
route '$default' "$AUTH"                               # everything: a valid Cognito token at the EDGE, then the door again
route 'GET /healthz' NONE
route 'GET /.well-known/{proxy+}' NONE                 # JWKS + RFC 9728 metadata
route 'POST /oauth/token' NONE                         # authenticated by the subject_token it exchanges (door verifies)
route 'POST /webhooks/ticketing' NONE                  # HMAC-signed by the ticketing system (door verifies)
aws apigatewayv2 get-stages --api-id "$API_ID" --query "Items[?StageName=='\$default'].StageName | [0]" --output text | \
  grep -q default || aws apigatewayv2 create-stage --api-id "$API_ID" --stage-name '$default' --auto-deploy >/dev/null
# edge refusals (a bad token stopped by the JWT authorizer never reaches the door) are recorded too: API Gateway
# access log, one JSON line per request with route, status and the authorizer's error, 30-day retention
LOGG=/claimsense/door-api-access
aws logs describe-log-groups --log-group-name-prefix "$LOGG" --query "logGroups[?logGroupName=='$LOGG'] | [0]" \
  --output text | grep -q "$LOGG" || { aws logs create-log-group --log-group-name "$LOGG"; \
  aws logs put-retention-policy --log-group-name "$LOGG" --retention-in-days 30; }
FMT='{"requestId":"$context.requestId","ip":"$context.identity.sourceIp","time":"$context.requestTime","route":"$context.routeKey","path":"$context.path","method":"$context.httpMethod","status":"$context.status","user":"$context.authorizer.claims.cognito:username","authError":"$context.authorizer.error"}'
ALS=$(python3 -c 'import json,sys; print(json.dumps({"DestinationArn": sys.argv[1], "Format": sys.argv[2]}))' \
  "arn:aws:logs:$REGION:$ACCOUNT:log-group:$LOGG" "$FMT")
aws apigatewayv2 update-stage --api-id "$API_ID" --stage-name '$default' --access-log-settings "$ALS" >/dev/null
aws lambda add-permission --function-name "$FN" --statement-id apigw-invoke --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:$REGION:$ACCOUNT:$API_ID/*" >/dev/null 2>&1 || true

say "Wait for the door to answer"
for _ in $(seq 1 30); do curl -fs "$URL/healthz" >/dev/null && break; sleep 4; done
curl -fs "$URL/healthz"; echo
python3 - "$CONF_DIR/deploy.json" "$URL" "$TAG" "$DIGEST" <<'PY'
import json, os, sys
out, url, tag, digest = sys.argv[1:]
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump({"door_url": url, "image_tag": tag, "image_digest": digest}, f)
PY
echo "door URL: $URL" | mask
echo "next:  DOOR_URL=$URL python -m claimsense_door.two_analyst_test --url $URL --cognito" | mask
