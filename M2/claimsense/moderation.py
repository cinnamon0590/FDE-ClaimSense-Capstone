"""G9: a MANAGED policy layer in front of the agents (W17 Architect: "managed guardrails layered in front of the agent,
with a written when-managed-vs-hand-rolled rationale", D-059). It uses OpenAI's moderation endpoint
(`omni-moderation-latest`): a policy model the provider trains and maintains, free to call.

What it adds that the hand-rolled guardrails can't:
  * hand-rolled G1-G8 encode OUR domain: injection, citations, money, entitlement, PII. They are precise and
    auditable, but only catch what we thought of;
  * the managed layer catches harm categories we would otherwise have to write and maintain ourselves (threats,
    self-harm, sexual content involving minors, violent wrongdoing), across languages, updated by the provider.

Safe by construction (same rules as G1b):
  * it can only ESCALATE: a high-severity category holds the claim for a senior adjuster via the Intake tripwire. It
    never approves, clears or un-flags anything, and its verdict never reaches the model as an instruction;
  * it is SCOPED: ordinary claim language that moderation also scores (a car crash, an injury, a hospital visit is
    "violence" to a general-purpose filter) is recorded, never acted on. Only HOLD_CATEGORIES hold a claim;
  * it fails closed: an API error holds the claim ("moderation unavailable") rather than passing it unchecked;
  * results are cached by text hash (`evals/g9-moderation-cache.json`): the replay brain and CI never call the API.
    A replay cache miss is treated as "not run", never as "clean", and counted.
"""
import asyncio
import hashlib
import json
from pathlib import Path

from . import config

CACHE = Path(__file__).resolve().parents[1] / "evals" / "g9-moderation-cache.json"
MODEL = "omni-moderation-latest"
# act only on unambiguous harm; anything else moderation flags (e.g. "violence" for a described crash) is recorded
HOLD_CATEGORIES = {"self-harm/intent", "self-harm/instructions", "sexual/minors", "harassment/threatening",
                   "hate/threatening", "illicit/violent"}


def _key(text):
    return hashlib.sha256((text or "").encode()).hexdigest()[:24]


class ManagedModeration:
    def __init__(self, brain, cache_path=CACHE):
        self.brain, self.path = brain, Path(cache_path)
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.misses, self._dirty = 0, False

    async def _ask(self, client, text):
        try:
            r = await client.moderations.create(model=MODEL, input=text)
            res = r.results[0]
            cats = res.categories.model_dump(by_alias=True)
            flagged = sorted(k for k, v in cats.items() if v)
            return {"flagged": flagged, "hold": sorted(set(flagged) & HOLD_CATEGORIES), "model": r.model}
        except Exception as e:                                  # fail closed
            return {"flagged": [], "hold": ["moderation-unavailable"], "model": MODEL,
                    "error": f"{type(e).__name__}"}

    async def check(self, texts):
        """Return [(text, result)] for each non-trivial text; result = {flagged, hold, model}."""
        texts = [t for t in dict.fromkeys(texts) if t and len(t.strip()) >= 12]
        out, todo = {}, []
        for t in texts:
            if (hit := self.cache.get(_key(t))) is not None:
                out[t] = dict(hit, cached=True)
            elif self.brain == "live":
                todo.append(t)
            else:
                self.misses += 1
                out[t] = {"flagged": [], "hold": [], "model": MODEL, "cache_miss": True}
        if todo:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            for t, v in zip(todo, await asyncio.gather(*[self._ask(client, t) for t in todo])):
                out[t] = v
                if not v.get("error"):
                    self.cache[_key(t)] = {k: v[k] for k in ("flagged", "hold", "model")}
                    self._dirty = True
        return [(t, out[t]) for t in texts]

    def save(self):
        if self._dirty:
            try:                                                # a read-only image keeps it in memory
                self.path.write_text(json.dumps(self.cache, indent=1, sort_keys=True) + "\n")
            except OSError:
                pass
            self._dirty = False
