"""Deny-by-default with explicit grants (M3 stretch, D-037).

`granted(caller, action)` is True only when the caller's directory groups (or service identity) hold an explicit
grant for `action` in grants.json. Everything else is denied: an unknown group, a group with no grants, an action
nobody declared, a typo. There is no wildcard and no "default allow" branch anywhere.
"""
import json
from functools import lru_cache
from pathlib import Path

GRANTS_FILE = Path(__file__).with_name("grants.json")


@lru_cache(maxsize=1)
def table():
    t = json.loads(GRANTS_FILE.read_text())
    assert t.get("default") == "deny", "grants.json must be deny-by-default"
    declared = set(t["actions"])
    for who, actions in list(t["roles"].items()) + list(t["services"].items()):
        unknown = set(actions) - declared
        assert not unknown, f"{who} is granted undeclared actions {sorted(unknown)}"
    return t


def actions():
    return set(table()["actions"])


def granted(caller, action):
    """caller = {"user_id": ..., "groups": [...]}. Deny unless an explicit grant exists."""
    t = table()
    if action not in t["actions"]:
        return False                                          # undeclared action: never granted
    if action in t["services"].get(caller.get("user_id", ""), []):
        return True                                           # a service identity (e.g. system:ticketing)
    return any(action in t["roles"].get(g, []) for g in caller.get("groups") or [])


def matrix():
    """role -> sorted granted actions (for the docs and the evidence)."""
    t = table()
    return {who: sorted(acts) for who, acts in list(t["roles"].items()) + list(t["services"].items())}
