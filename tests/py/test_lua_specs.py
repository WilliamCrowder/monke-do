"""Runs the addon's Lua specs from pytest so one command covers both halves of the repo."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_lua_specs_pass():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "lua" / "run_specs.py")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
