# Monke Do

A World of Warcraft: Forever addon (Lua 5.1, `addon/MonkeDo/`) plus the offline Python pipeline
(`pipeline/`) that generates its quest database. Read `docs/DATA_CONTRACT.md` before changing
anything: it is the only thing the two halves share, and section 8 lists facts that were checked
against the real sources.

## Commands

```bash
uv sync                                   # once
uv run pytest                             # pipeline tests + the addon's Lua specs (via lupa, no Lua toolchain needed)
uv run python tests/lua/run_specs.py      # Lua specs only, sandboxed like real busted
uv run python tools/luacheck_local.py     # the real luacheck on lupa's Lua (needs a clone of luacheck in %TEMP%)
uv run python -m pipeline run --offline   # raw cache -> SQLite -> addon/MonkeDo/Data/*.lua, no network, no spend
uv run python -m pipeline --help
```

CI also runs real `busted` and `luacheck` (`.busted`, `.luacheckrc`). Specs must write fake-client
globals through `_G.` (busted sandboxes bare assignments; the local runner does the same).

## Rules

- `addon/MonkeDo/Data/*.lua` is generated. `pipeline/export.py` is the only writer.
- Addon Lua is 5.1: no `goto`, no bit ops, no `os`/`io`, no network, nothing that reads combat
  data. Every Blizzard global is nil-checked; a missing frame means "do nothing", never an error.
- Any new WoW global the addon reads must be added to `read_globals` in `.luacheckrc`; the
  `globals` spec in `tests/lua/display_spec.lua` fails otherwise.
- `addon/MonkeDo/Voice.lua` + `Rules.lua` and `pipeline/rules.py` are mirrors. Change both.
- The quest frame is hooked through `QuestInfo_Display`. `hooksecurefunc` on the
  `QuestInfo_Show*` globals never fires (the templates hold direct references).
- Web fetchers run only when named in `--sources`, never from tests or CI. There is no Wowhead
  fetcher on purpose (its terms forbid scraping).
- Never make a real LLM API call from tests. Providers are exercised with fakes.
- The game cannot be run from here. Anything in `Display.lua` or `Tracker.lua` needs a line in
  `docs/INGAME_CHECKLIST.md` for the human to check.
- Specs must stay inside the busted subset listed at the top of `tests/lua/mini_busted.lua`.

## Layout

- `pipeline/db.py` is the schema. Sources write through its helpers only.
- `pipeline/sources/` one module per source, same `load()` interface.
- `pipeline/llm/` prompt (`prompts/v1.md`), providers, summarize loop, `overrides.jsonl`
  (hand-pinned summaries that beat the LLM but not the validator).
- `pipeline/validate.py` decides what ships. `pipeline/export.py` writes the Lua. Cached
  summaries carry a fingerprint of the context they were written for; a mismatch means
  "stale", never "ship it".
- `pipeline/out/translate/` holds the chunked requests, the writers' output and the editors'
  corrections for summaries written by Claude Code subagents (`python -m pipeline requests
  --chunk-size 120`, then `summarize --provider file --summaries-file <out> --summaries-file <fix>`).
- `tests/lua/wow_stubs.lua` is the fake WoW client used by the specs.
- `tools/make_media.py` rebuilds the 64x64 icons from the source art.
