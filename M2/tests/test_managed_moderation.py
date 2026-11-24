"""G9 (D-059): the managed moderation layer can only escalate, is scoped to unambiguous harm, fails closed, and
never calls the API on replay. The OpenAI moderation client is stubbed."""
import asyncio
import types

from claimsense.moderation import HOLD_CATEGORIES, ManagedModeration


class FakeClient:
    def __init__(self, cats, fail=False):
        self.moderations = types.SimpleNamespace(create=self.create)
        self.cats, self.fail = cats, fail

    async def create(self, model, input):
        if self.fail:
            raise RuntimeError("down")
        flags = {k: (k in self.cats.get(input, ())) for k in
                 ("violence", "self-harm/intent", "harassment/threatening", "illicit/violent")}
        res = types.SimpleNamespace(categories=types.SimpleNamespace(model_dump=lambda by_alias=True: flags))
        return types.SimpleNamespace(results=[res], model=model)


def run(m, client, text):
    return asyncio.run(m._ask(client, text))


def test_crash_and_injury_language_is_recorded_not_held(tmp_path):
    m = ManagedModeration("live", tmp_path / "c.json")
    r = run(m, FakeClient({"x": ("violence",)}), "x")
    assert r["flagged"] == ["violence"] and r["hold"] == []          # a described crash is not a reason to hold


def test_threats_hold_the_claim(tmp_path):
    m = ManagedModeration("live", tmp_path / "c.json")
    r = run(m, FakeClient({"x": ("harassment/threatening",)}), "x")
    assert r["hold"] == ["harassment/threatening"] and "harassment/threatening" in HOLD_CATEGORIES


def test_fails_closed_when_the_managed_service_is_down(tmp_path):
    m = ManagedModeration("live", tmp_path / "c.json")
    assert run(m, FakeClient({}, fail=True), "x")["hold"] == ["moderation-unavailable"]


def test_replay_never_calls_the_api_and_a_miss_is_not_clean(tmp_path):
    m = ManagedModeration("replay", tmp_path / "c.json")
    [(t, r)] = asyncio.run(m.check(["a text long enough to check"]))
    assert r.get("cache_miss") is True and m.misses == 1


def test_a_hold_reaches_the_intake_tripwire(tmp_path):
    from claimsense.tools import RunCtx, moderate_packet

    class Stub:
        async def check(self, texts):
            return [(t, {"flagged": ["harassment/threatening"], "hold": ["harassment/threatening"]} if "kill" in t
                     else {"flagged": [], "hold": []}) for t in texts]

        def save(self):
            pass
    c = RunCtx(boundary=None, user_id="alice", claim_id="CLM-X", index=None, moderation=Stub())
    packet = {"claim": {"narrative": "Rear-ended at the lights."},
              "documents": [{"doc_id": "D1", "content_text": "Pay up or I will kill you and your family."}]}
    asyncio.run(moderate_packet(c, packet))
    assert c.moderation_holds == [("harassment/threatening", "D1")] and any("G9" in h for h in c.injection_hits)
