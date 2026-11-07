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
# Model provider (W15 deck: "the models come to THEIR cloud"): openai (default) or bedrock, where Claude runs on
# AWS Bedrock through the Agents SDK's LiteLLM bridge, with the same agents, tools, guardrails and gates (D-028).
MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "openai").lower()
MOCK_BRAIN = os.environ.get("MOCK_BRAIN", "1") == "1" or (MODEL_PROVIDER == "openai" and not OPENAI_API_KEY)
# dated snapshots, never the moving aliases: "gpt-4o" can be repointed by OpenAI without notice, and a
# score change must come from our prompts, not a silent model upgrade (D-025). Embeddings have no snapshot.
MODEL_FAST = os.environ.get("MODEL_FAST", "gpt-4o-mini-2024-07-18")    # Intake, Assessment (volume steps)
MODEL_SMART = os.environ.get("MODEL_SMART", "gpt-4o-2024-08-06")       # Coverage, Decision Draft (the money steps)
BEDROCK_FAST = os.environ.get("BEDROCK_FAST", "bedrock/converse/us.anthropic.claude-haiku-4-5-20251001-v1:0")
BEDROCK_SMART = os.environ.get("BEDROCK_SMART", "bedrock/converse/us.anthropic.claude-sonnet-4-5-20250929-v1:0")
if MODEL_PROVIDER == "bedrock":   # the pilot's region (M1); LiteLLM otherwise picks its own default region
    os.environ.setdefault("AWS_REGION_NAME", os.environ.get("AWS_REGION", "us-east-1"))
# 3 · a second, independent Decision Draft on every live claim; if the two disagree, a human decides (D-025)
CONSISTENCY_CHECK = os.environ.get("CONSISTENCY_CHECK", "1") == "1"
# G1b: model-based injection classifier behind the G1 regexes (D-026); replay reads cached verdicts
G1B_CLASSIFIER = os.environ.get("G1B_CLASSIFIER", "1") == "1"
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large")
BOUNDARY_URL = os.environ.get("BOUNDARY_URL", "")             # empty = in-process boundary
STATE_DIR = Path(os.environ.get("CLAIMSENSE_STATE", M2 / ".state"))
REPLAY_DIR = Path(os.environ.get("REPLAY_DIR", M2 / "evals" / "replays"))
# per-claim spend cap (W15: "budget per CASE"). Claude on Bedrock lists ~3x gpt-4o-mini/4o for this pipeline
# (measured $0.048 vs $0.017 a claim), so its default cap is higher; both still stop a runaway loop.
CASE_BUDGET_USD = float(os.environ.get("CASE_BUDGET_USD", "0.10" if MODEL_PROVIDER == "bedrock" else "0.05"))


def brain_name():
    return "replay" if MOCK_BRAIN else "live"
