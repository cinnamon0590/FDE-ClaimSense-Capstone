import json
import os
import shutil
import sys
from pathlib import Path

import pytest

M2 = Path(__file__).resolve().parents[1]
# Tests never call a paid API or export traces, whatever M2/.env says.
os.environ["MOCK_BRAIN"] = "1"
os.environ["OPENAI_API_KEY"] = ""
os.environ.pop("OPENAI_SECRET_ID", None)
# unit tests address in-process boundaries by user id; tests/test_rbac.py switches this OFF to prove tokens are required
os.environ["CLAIMSENSE_ALLOW_HEADER_IDENTITY"] = "1"
# unit tests run the eval runner on the $0 replay brain as a HARNESS check; tests/test_eval_gate.py turns the real
# gate rule (LLM required) back on to prove a missing key, the replay brain or a low threshold turn it red
os.environ["CLAIMSENSE_LLM_REQUIRED"] = "false"
sys.path.insert(0, str(M2))


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    from claimsense import config
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    yield


@pytest.fixture
def replay_copy(tmp_path):
    """A private copy of the replay files that a test can tamper with."""
    from claimsense.brains import ReplayStore
    root = tmp_path / "replays"
    shutil.copytree(M2 / "evals" / "replays", root)

    def edit(claim_id, fn):
        p = root / f"{claim_id}.json"
        d = json.loads(p.read_text())
        fn(d)
        p.write_text(json.dumps(d))
    store = ReplayStore(root)
    store.edit = edit
    return store
