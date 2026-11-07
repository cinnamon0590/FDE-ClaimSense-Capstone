"""Tracing, cost metering and checkpoints (W15: sessions + tracing = the flight recorder).

* Every SDK span (agent, generation, tool call, guardrail) is written to
  .state/traces/<trace_id>.jsonl by a local TracingProcessor. When the brain is live the SDK also
  exports to the OpenAI Traces dashboard. PII never reaches either: tools mask it first (G3).
* Cost per claim comes from the SDK's token usage times the price table below.
* Checkpoints: each completed step's typed output is stored in SQLite, so a run that dies after
  Coverage resumes at Assessment instead of paying for Intake and Coverage again.
"""
import json
import sqlite3
import threading

from agents import set_trace_processors, add_trace_processor
from agents.tracing.processor_interface import TracingProcessor

from . import config

# USD per 1M tokens (OpenAI list prices; re-check https://openai.com/api/pricing before quoting)
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.00), "gpt-4.1-mini": (0.40, 1.60),
          "gpt-4.1": (2.00, 8.00), "text-embedding-3-large": (0.13, 0.0)}


def cost_usd(model, input_tokens, output_tokens):
    pin, pout = PRICES.get(model.split(":")[-1], (2.50, 10.00))      # unknown model: price as the smart tier
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 6)


class JsonlTraceProcessor(TracingProcessor):
    def __init__(self, root=None):
        self._root = root
        self.lock = threading.Lock()

    @property
    def root(self):
        return (self._root or config.STATE_DIR) / "traces"

    def _write(self, trace_id, rec):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.lock, open(self.root / f"{trace_id}.jsonl", "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def on_trace_start(self, trace):
        self._write(trace.trace_id, {"event": "trace_start", **(trace.export() or {})})

    def on_trace_end(self, trace):
        self._write(trace.trace_id, {"event": "trace_end", "trace_id": trace.trace_id})

    def on_span_start(self, span):
        pass

    def on_span_end(self, span):
        rec = span.export() or {}
        data = rec.get("span_data") or {}
        for k in ("input", "output"):               # keep the file small; full payloads live in the replay
            if k in data and len(json.dumps(data[k], default=str)) > 4000:
                data[k] = "[truncated]"
        self._write(span.trace_id, {"event": "span", **rec})

    def shutdown(self):
        pass

    def force_flush(self):
        pass


_configured = False


def configure_tracing():
    global _configured
    if _configured:
        return
    local = JsonlTraceProcessor()
    if config.MOCK_BRAIN:
        set_trace_processors([local])               # no key: local file only, nothing leaves the laptop
    else:
        add_trace_processor(local)                  # live: OpenAI Traces dashboard + local file
    _configured = True


class Checkpoints:
    def __init__(self, path=None):
        self.path = path or config.STATE_DIR / "checkpoints.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS steps (run_id TEXT, step TEXT, output TEXT, "
                       "PRIMARY KEY (run_id, step))")

    def get(self, run_id, step):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT output FROM steps WHERE run_id=? AND step=?", (run_id, step)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, run_id, step, output):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO steps VALUES (?,?,?)", (run_id, step, json.dumps(output)))
