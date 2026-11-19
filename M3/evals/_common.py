"""Shared helpers for the M3 running-stack checks (the local compose stack by default; the deployed API with
DOOR_URL / ORCH_URL and --cognito). Evidence files follow the class format: a header (what, when, where, exit,
status) then the verbatim output."""
import os
import subprocess
import sys
import time
from pathlib import Path

M3 = Path(__file__).resolve().parents[1]
ROOT = M3.parent
sys.path[:0] = [str(ROOT / "M2"), str(M3 / "door")]
DOOR = os.environ.get("DOOR_URL", "http://localhost:8002").rstrip("/")
ORCH = os.environ.get("ORCH_URL", "http://localhost:8003").rstrip("/")
COMPOSE = ["docker", "compose", "-f", str(M3 / "docker-compose.yml")]


def tokens(cognito=False):
    if cognito or os.environ.get("CLAIMSENSE_COGNITO"):
        from claimsense_door.cognito import token_for
        return token_for
    from claimsense_door.clients import dev_tokens
    return dev_tokens(DOOR)


def in_container(service, *argv):
    """Run a command INSIDE a container (secrets and keys never leave it); returns stdout."""
    return subprocess.run(COMPOSE + ["exec", "-T", service, *argv], capture_output=True, text=True, check=True).stdout


class Report:
    def __init__(self, number, slug, title):
        self.path = M3 / "evidence" / f"{number:02d}-{slug}.txt"
        self.title, self.lines, self.ok = title, [], True

    def check(self, label, cond, detail=""):
        self.ok &= bool(cond)
        self.lines.append(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
        return bool(cond)

    def say(self, *lines):
        self.lines.extend(lines)

    def finish(self, cmd):
        head = [f"# {self.path.stem} — {self.title}", f"# run: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
                f"# door: {DOOR} · orchestrator: {ORCH}", f"# command: {cmd}",
                f"# exit: {0 if self.ok else 1}   status: {'PASS' if self.ok else 'FAIL'}", ""]
        text = "\n".join(head + self.lines + ["", f"RESULT: {'PASS' if self.ok else 'FAIL'}"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text + "\n")
        print(text)
        return 0 if self.ok else 1
