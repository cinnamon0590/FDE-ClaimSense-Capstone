"""M3 tests run offline: the door in-process, the boundary app on its baked-in fixtures (SYSTEMS_URL=local), the
replay brain ($0), tokens from a throwaway dev issuer. No containers, no key, no network."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "M2"), str(ROOT / "M2" / "services"), str(ROOT / "M3" / "door"), str(ROOT / "M3" / "services")]
_TMP = Path(tempfile.mkdtemp(prefix="claimsense-m3-tests-"))
os.environ.update({"MOCK_BRAIN": "1", "OPENAI_API_KEY": "", "CLAIMSENSE_LLM_REQUIRED": "false",
                   "SYSTEMS_URL": "local", "AUDIT_LOG": str(_TMP / "state" / "audit.jsonl"),
                   "BOUNDARY_STATE": str(_TMP / "state" / "boundary.db"), "CLAIMSENSE_SECRETS_DIR": str(_TMP / "secrets"),
                   "CLAIMSENSE_STATE": str(_TMP / "state"), "CLAIMSENSE_DEV_ISSUER": "0"})
os.environ.pop("OPENSEARCH_URL", None)
os.environ.pop("OPENAI_SECRET_ID", None)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def real_tokens_only(monkeypatch):
    """M3 tests use real tokens, never header identity. Scoped to M3's tests (not a process-wide pop) so a bare
    `pytest -q` from the repo root also keeps M2's suite, which runs its in-process tests with header identity ON."""
    monkeypatch.delenv("CLAIMSENSE_ALLOW_HEADER_IDENTITY", raising=False)


@pytest.fixture(scope="session")
def app_and_tokens():
    """The real boundary app (REST + /mcp + webhook) on the fixtures, and a function minting real RS256 tokens."""
    from fastapi.testclient import TestClient
    import boundary.app as appmod
    client = TestClient(appmod.app)
    return client, (lambda user: appmod.ISSUER.mint(user, appmod.B.users[user]["groups"])), appmod


@pytest.fixture()
def door():
    from claimsense_door.clients import InProcess
    from claimsense_door.proofs import _client
    tc, _ = _client()
    return InProcess(ticketing=tc)
