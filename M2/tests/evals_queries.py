import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
from script_replays import QUERY  # noqa: E402,F401
