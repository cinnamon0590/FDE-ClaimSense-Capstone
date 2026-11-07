"""Runtime configuration from the environment (and M2/.env, which is gitignored)."""
import os
from pathlib import Path

M2 = Path(__file__).resolve().parents[1]


def _load_env():
    p = M2 / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()

def _key_from_secrets_manager():
    """In AWS the key lives in Secrets Manager and is read at runtime (never baked into an image or env)."""
    sid = os.environ.get("OPENAI_SECRET_ID", "")
    if not sid:
        return ""
    import boto3
    val = boto3.client("secretsmanager").get_secret_value(SecretId=sid)["SecretString"]
    return val if val.startswith("sk-") else ""          # the M1 placeholder isn't a key


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "") or _key_from_secrets_manager()
if OPENAI_API_KEY:
    os.environ.setdefault("OPENAI_API_KEY", OPENAI_API_KEY)
# The mock brain replays recorded model outputs: zero network, zero cost, deterministic.
# It's forced on when there's no key, so nothing ever silently calls a paid API.
MOCK_BRAIN = os.environ.get("MOCK_BRAIN", "1") == "1" or not OPENAI_API_KEY
MODEL_FAST = os.environ.get("MODEL_FAST", "gpt-4o-mini")      # Intake, Assessment (volume steps)
MODEL_SMART = os.environ.get("MODEL_SMART", "gpt-4o")         # Coverage, Decision Draft (the money steps)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large")
BOUNDARY_URL = os.environ.get("BOUNDARY_URL", "")             # empty = in-process boundary
STATE_DIR = Path(os.environ.get("CLAIMSENSE_STATE", M2 / ".state"))
REPLAY_DIR = Path(os.environ.get("REPLAY_DIR", M2 / "evals" / "replays"))
CASE_BUDGET_USD = float(os.environ.get("CASE_BUDGET_USD", "0.05"))   # per-claim spend cap


def brain_name():
    return "replay" if MOCK_BRAIN else "live"
