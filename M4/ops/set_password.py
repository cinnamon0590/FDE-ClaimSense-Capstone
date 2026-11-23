"""Give a person a new Cognito password (runbook "Add or remove a user", D-056): strong, easy to type, never printed.

    python M4/ops/set_password.py alice carol      # new passwords for these users

Each password is 4 groups of 4 from an alphabet with no look-alike characters (no I l 1 O 0), plus upper case, lower
case, a digit and a symbol, e.g. `Kq7M-4tZp-9WxR-bc3!` (≈ 95 bits). It is set in Cognito as permanent, saved to
`~/.claimsense/cognito.json` (so `M3/cloud/deploy.sh` keeps it), and to `~/.claimsense/logins.json` for the owner to
hand to that person over a private channel. Both files are 0600; nothing is printed, committed or logged. The user
must be in the directory (`M1/6-synthetic-data/source/users.json`).
"""
import json
import os
import secrets
import sys
from pathlib import Path

import boto3

CONF = Path.home() / ".claimsense"
UPPER, LOWER, DIGIT = "ABCDEFGHJKMNPQRSTUVWXYZ", "abcdefghjkmnpqrstuvwxyz", "23456789"


def new_password():
    pool = UPPER + LOWER + DIGIT
    while True:
        groups = ["".join(secrets.choice(pool) for _ in range(4)) for _ in range(4)]
        pw = "-".join(groups) + "!"
        if any(c in UPPER for c in pw) and any(c in LOWER for c in pw) and any(c in DIGIT for c in pw):
            return pw


def save(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.chmod(path, 0o600)


def main(users):
    root = Path(__file__).resolve().parents[2]
    directory = {u["user_id"] for u in json.loads((root / "M1/6-synthetic-data/fixtures/users.json").read_text())["records"]}
    cog = json.loads((CONF / "cognito.json").read_text())
    logins_path = CONF / "logins.json"
    logins = json.loads(logins_path.read_text()) if logins_path.exists() else {}
    for u in users:
        if u not in directory:
            sys.exit(f"{u} is not in the directory")
        pw = new_password()
        boto3.client("cognito-idp", region_name=cog.get("region", "us-east-1")).admin_set_user_password(
            UserPoolId=cog["pool_id"], Username=u, Password=pw, Permanent=True)   # SDK: never on a command line
        cog["passwords"][u] = pw
        logins[u] = {"username": u, "password": pw}
        print(f"{u}: new password set in Cognito (saved to ~/.claimsense/logins.json, not shown)")
    save(CONF / "cognito.json", cog)
    save(logins_path, logins)


if __name__ == "__main__":
    main(sys.argv[1:] or sys.exit("usage: set_password.py <user> [<user> ...]"))
