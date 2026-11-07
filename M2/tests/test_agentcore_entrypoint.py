"""The AgentCore entry point (cloud/agentcore/app.py) wraps the unchanged pipeline; a session resumes its claim."""
import importlib.util
import sys
import types
from pathlib import Path

from claimsense.pipeline import run_sync

M2 = Path(__file__).resolve().parents[1]


def _load_app():
    stub = types.ModuleType("bedrock_agentcore")              # the SDK is only in the AgentCore image

    class BedrockAgentCoreApp:
        def entrypoint(self, fn):
            self.fn = fn
            return fn

        def run(self):
            raise RuntimeError("not in tests")
    stub.BedrockAgentCoreApp = BedrockAgentCoreApp
    sys.modules["bedrock_agentcore"] = stub
    spec = importlib.util.spec_from_file_location("agentcore_app", M2 / "cloud" / "agentcore" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_entrypoint_runs_the_pipeline_and_a_session_resumes_it():
    app = _load_app()
    ctx = types.SimpleNamespace(session_id="sess-123")
    first = run_sync(app.invoke({"claim_id": "CLM-2024-1800", "user_id": "alice"}, ctx))
    assert first["card"]["outcome"] == "approve" and first["run_id"] == "CLM-2024-1800:sess-123" and not first["resumed"]
    again = run_sync(app.invoke({"claim_id": "CLM-2024-1800", "user_id": "alice"}, ctx))
    assert again["resumed"] and again["cost_usd"] == 0 and again["card"] == first["card"]
    assert run_sync(app.invoke({"claim_id": "CLM-2024-1800"}))["error"]["code"] == "invalid_request"
