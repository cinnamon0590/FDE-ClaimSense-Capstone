"""Two brains behind the same Agents SDK `Model` interface.

  * live:   OpenAI models (gpt-4o-mini / gpt-4o) via the SDK's Responses model. With record=True
            every model turn (tool calls + final typed output + token usage) is saved to
            M2/evals/replays/<claim_id>.json.
  * replay: ReplayModel returns those saved turns. The REAL Runner, tool execution, strict output
            parsing and guardrails all run; only the network call is replaced. Deterministic, $0,
            no key, so CI can gate every PR (W15: "mock brain in CI, live model before release").

A replay file says where it came from: "recorded" (captured from a live run) or "scripted" (written
by hand to exercise the harness before a key existed). The eval report prints the mix, and only the
live gate proves the model itself.
"""
import json
import os
import re
import uuid
from pathlib import Path

from agents import ModelResponse, Usage
from agents.tracing import generation_span
from agents.models.interface import Model
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

from . import config

CLAIM_RX = re.compile(r"CLM-\d{4}-\d{4}")


def _claim_of(system_instructions, input):
    text = input if isinstance(input, str) else json.dumps(input, default=str)
    m = CLAIM_RX.search(text)
    if not m:
        raise LookupError("replay brain: no claim ID in the model input")
    return m.group(0)


def _tool_turns(input):
    if isinstance(input, str):
        return 0
    return sum(1 for it in input if (it.get("type") if isinstance(it, dict) else getattr(it, "type", None)) == "function_call")


class ReplayStore:
    def __init__(self, root=None):
        self.root = root or config.REPLAY_DIR
        self._cache = {}

    def path(self, claim_id):
        return self.root / f"{claim_id}.json"

    def load(self, claim_id):
        if claim_id not in self._cache:
            p = self.path(claim_id)
            if not p.exists():
                raise LookupError(f"no replay recorded for {claim_id}")
            self._cache[claim_id] = json.loads(p.read_text())
        return self._cache[claim_id]

    def source(self, claim_id):
        try:
            return self.load(claim_id).get("source", "scripted")
        except LookupError:
            return "missing"

    # Recording is staged: turns collect in memory and the replay file is replaced only when the whole
    # claim (all four agents) has been recorded. A run that dies part-way (outage, no credits) never
    # damages a good replay.
    _staging = {}

    def start_recording(self, claim_id):
        self._staging[claim_id] = {"claim_id": claim_id, "source": "recorded", "agents": {}}

    def save_turn(self, claim_id, agent, turn, model_name):
        data = self._staging.setdefault(claim_id, {"claim_id": claim_id, "source": "recorded", "agents": {}})
        rec = data["agents"].setdefault(agent, {"model": model_name, "turns": []})
        rec["model"] = model_name
        rec["turns"].append(turn)

    def commit_recording(self, claim_id, prompt_version=None):
        data = self._staging.pop(claim_id, None)
        agents = (data or {}).get("agents", {})
        complete = all(a in agents and agents[a]["turns"] and "final" in agents[a]["turns"][-1]
                       for a in ("intake", "coverage", "assessment", "decision"))
        if not complete:
            return False
        if prompt_version:
            data["prompt_version"] = prompt_version
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write(self.path(claim_id), json.dumps(data, indent=1) + "\n")
        self._cache.pop(claim_id, None)
        return True

    def discard_recording(self, claim_id):
        self._staging.pop(claim_id, None)


def atomic_write(path, text):
    """Write via a temp file + rename, so a concurrent reader never sees a half-written file."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _usage(u):
    from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails
    u = u or {}
    i, o = int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
    return Usage(requests=1, input_tokens=i, output_tokens=o, total_tokens=i + o,
                 input_tokens_details=InputTokensDetails(cached_tokens=int(u.get("cached_tokens", 0)), cache_write_tokens=0),
                 output_tokens_details=OutputTokensDetails(reasoning_tokens=0))


def usage_dict(u):
    details = getattr(u, "input_tokens_details", None)
    return {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
            "cached_tokens": int(getattr(details, "cached_tokens", 0) or 0)}


async def completed_stream(resp: ModelResponse, model_name: str):
    """Stream a finished ModelResponse as one `response.completed` event, so a non-streaming brain (replay,
    scripted) runs under Runner.run_streamed exactly like a live model does (W15: stream by default)."""
    from openai.types.responses import Response, ResponseCompletedEvent
    from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails, ResponseUsage
    u = resp.usage
    usage = ResponseUsage(input_tokens=u.input_tokens, output_tokens=u.output_tokens, total_tokens=u.total_tokens,
                          input_tokens_details=InputTokensDetails(cached_tokens=usage_dict(u)["cached_tokens"], cache_write_tokens=0),
                          output_tokens_details=OutputTokensDetails(reasoning_tokens=0))
    r = Response.model_construct(id=f"resp_{uuid.uuid4().hex[:12]}", created_at=0.0, model=model_name,
                                 object="response", output=list(resp.output), parallel_tool_calls=False,
                                 tool_choice="auto", tools=[], usage=usage, status="completed")
    yield ResponseCompletedEvent.model_construct(type="response.completed", response=r, sequence_number=0)


class ReplayModel(Model):
    def __init__(self, agent_key, store):
        self.agent_key, self.store = agent_key, store

    def recorded_model(self, claim_id):
        return self.store.load(claim_id)["agents"][self.agent_key].get("model", "unknown")

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs,
                           tracing, *, previous_response_id=None, conversation_id=None, prompt=None, **kw):
        claim_id = _claim_of(system_instructions, input)
        turns = self.store.load(claim_id)["agents"][self.agent_key]["turns"]
        n = _tool_turns(input)
        turn = turns[min(n, len(turns) - 1)]
        if turn.get("tool_calls"):
            out = [ResponseFunctionToolCall(type="function_call", id=f"fc_{uuid.uuid4().hex[:12]}",
                                            call_id=f"call_{uuid.uuid4().hex[:12]}", name=tc["name"],
                                            arguments=tc.get("arguments", "{}"), status="completed")
                   for tc in turn["tool_calls"]]
        else:
            text = turn["final"] if isinstance(turn["final"], str) else json.dumps(turn["final"])
            out = [ResponseOutputMessage(id=f"msg_{uuid.uuid4().hex[:12]}", type="message", role="assistant",
                                         status="completed",
                                         content=[ResponseOutputText(type="output_text", text=text, annotations=[])])]
        usage = _usage(turn.get("usage"))
        with generation_span(model=f"replay:{self.recorded_model(claim_id)}",
                             usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}):
            pass                                   # same span shape a live model call leaves in the trace
        return ModelResponse(output=out, usage=usage, response_id=None)

    async def stream_response(self, *a, **kw):
        resp = await self.get_response(*a, **kw)
        async for ev in completed_stream(resp, "replay"):
            yield ev


class RecordingModel(Model):
    """Delegates to a live model and saves every turn so the run can be replayed in CI."""

    def __init__(self, inner, agent_key, model_name, store):
        self.inner, self.agent_key, self.model_name, self.store = inner, agent_key, model_name, store

    async def get_response(self, system_instructions, input, *a, **kw):
        resp = await self.inner.get_response(system_instructions, input, *a, **kw)
        try:
            claim_id = _claim_of(system_instructions, input)
        except LookupError:
            return resp
        self._save(claim_id, resp.output, resp.usage)
        return resp

    def _save(self, claim_id, output, usage_obj):
        calls = [{"name": it.name, "arguments": it.arguments} for it in output
                 if getattr(it, "type", "") == "function_call"]
        usage = usage_dict(usage_obj)
        if calls:
            turn = {"tool_calls": calls, "usage": usage}
        else:
            text = "".join(c.text for it in output if getattr(it, "type", "") == "message"
                           for c in it.content if getattr(c, "type", "") == "output_text")
            try:
                final = json.loads(text)
            except ValueError:
                final = text
            turn = {"final": final, "usage": usage}
        self.store.save_turn(claim_id, self.agent_key, turn, self.model_name)

    async def stream_response(self, system_instructions, input, *a, **kw):
        """Pass the live stream through untouched and record the turn from its completed response."""
        async for ev in self.inner.stream_response(system_instructions, input, *a, **kw):
            if getattr(ev, "type", "") == "response.completed":
                try:
                    claim_id = _claim_of(system_instructions, input)
                    r = ev.response
                    self._save(claim_id, r.output, _usage({"input_tokens": r.usage.input_tokens,
                                                           "output_tokens": r.usage.output_tokens,
                                                           "cached_tokens": getattr(r.usage.input_tokens_details,
                                                                                    "cached_tokens", 0) or 0}))
                except (LookupError, AttributeError):
                    pass
            yield ev
