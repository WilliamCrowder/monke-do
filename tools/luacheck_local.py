"""Run the real luacheck without a Lua toolchain.

luacheck is pure Lua. This runs it on the Lua 5.1 bundled with the `lupa` package, with a
small stand-in for LuaFileSystem (only the calls luacheck makes for explicit file inputs).
Needs a checkout of https://github.com/lunarmodules/luacheck at LUACHECK_SRC (default:
%TEMP%/luacheck). CI runs the installed luacheck; this exists so lint failures show up here
first.

    uv run python tools/luacheck_local.py addon tests/lua
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LFS_SHIM = r"""
package.preload["lfs"] = function()
    local lfs = {}
    function lfs.attributes(path, what)
        local f = io.open(path, "r")
        if not f then return nil end
        local ok = f:read(0) -- opening a directory succeeds on Windows; reading it does not
        f:close()
        if what == "mode" then return ok and "file" or "directory" end
        if what == "modification" then return 0 end
        return { mode = "file", modification = 0 }
    end
    function lfs.currentdir() return CWD end
    function lfs.dir() error("directory listing is not supported by the shim; pass files") end
    function lfs.mkdir() return nil, "read-only shim" end
    return lfs
end
"""


def main(targets: list[str]) -> int:
    from lupa import lua51

    src = Path(os.environ.get("LUACHECK_SRC") or Path(os.environ.get("TEMP", "/tmp")) / "luacheck") / "src"
    if not (src / "luacheck" / "init.lua").exists():
        sys.exit(f"luacheck source not found at {src}; git clone https://github.com/lunarmodules/luacheck there")
    files: list[Path] = []
    for target in targets or ["addon", "tests/lua"]:
        path = ROOT / target
        files += sorted(path.rglob("*.lua")) if path.is_dir() else [path]
    # No filtering here: .luacheckrc's exclude_files must do it, as it does in CI.

    lua = lua51.LuaRuntime(unpack_returned_tuples=True)
    g = lua.globals()
    g.CWD = str(ROOT) + os.sep  # luacheck expects the platform's own separators
    lua.execute(f'package.path = "{src.as_posix()}/?.lua;{src.as_posix()}/?/init.lua;" .. package.path')
    lua.execute(LFS_SHIM)
    run = lua.eval("""
    function(config_path, paths)
        local runner = require "luacheck.runner"
        local r, err = runner.new({ config = config_path })
        if not r then error(err) end
        local inputs = {}
        for i = 1, #paths do inputs[i] = { path = paths[i] } end
        local report = assert(r:check(inputs))
        return r:format(report, { formatter = "default", color = false }), report.warnings, report.errors
    end
    """)
    lua_paths = lua.table_from([f.relative_to(ROOT).as_posix() for f in files])
    os.chdir(ROOT)
    text, warnings, errors = run(".luacheckrc", lua_paths)
    print(text)
    return 1 if (warnings or errors) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
