"""Run the busted specs without a Lua toolchain.

CI uses real busted (`busted` from the repo root). This runner exists for machines that only
have Python: it loads tests/lua/mini_busted.lua, a small busted-compatible shim, into the
Lua 5.1 runtime bundled with the `lupa` package.

    uv run python tests/lua/run_specs.py [spec files...]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(spec_paths: list[str] | None = None) -> int:
    from lupa import lua51

    os.chdir(ROOT)  # the stubs and specs use repo-relative paths
    specs = spec_paths or sorted(p.as_posix() for p in Path("tests/lua").glob("*_spec.lua"))
    lua = lua51.LuaRuntime(unpack_returned_tuples=True)
    lua.execute('dofile("tests/lua/mini_busted.lua")')
    lua.execute('dofile("tests/lua/wow_stubs.lua")')
    table = "{" + ",".join('"%s"' % s.replace("\\", "/") for s in specs) + "}"
    return int(lua.eval(f"MiniBusted.runFiles({table})"))


if __name__ == "__main__":
    sys.exit(1 if run(sys.argv[1:] or None) else 0)
