"""Real Cognito ID tokens for the synthetic adjusters on the DEPLOYED door (proof scripts only).

deploy.sh creates the five synthetic users in M1's user pool with random passwords and writes them, with the pool
and app-client ids, to ~/.claimsense/cognito.json (0600, outside the repo, never committed or printed). This module
signs a user in with AdminInitiateAuth (it needs the deployer's AWS credentials too) and returns the ID token.
"""
import json
import os
from functools import lru_cache
from pathlib import Path

CONF = Path(os.environ.get("CLAIMSENSE_COGNITO_CONF", Path.home() / ".claimsense" / "cognito.json"))


@lru_cache(maxsize=1)
def conf():
    if not CONF.exists():
        raise SystemExit(f"{CONF} not found: run M3/cloud/deploy.sh first")
    return json.loads(CONF.read_text())


@lru_cache(maxsize=16)
def token_for(user):
    import boto3
    c = conf()
    r = boto3.client("cognito-idp", region_name=c["region"]).admin_initiate_auth(
        UserPoolId=c["pool_id"], ClientId=c["client_id"], AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": user, "PASSWORD": c["passwords"][user]})
    return r["AuthenticationResult"]["IdToken"]
