# Monke Do

Quest text for smooth brains. A World of Warcraft: Forever addon that replaces quest text with
one or two sentences of lore and a caveman task list, with one click back to the original.

```
Bad men wear red hankies. Scout lady want them.

• Grab 10 Red Silk Bandana (3/10)
• Go back to Scout Riell.

Monke get: 875 XP, 4s
```

- Two voices: **Monke** and **Plain English**. Same information, with or without the joke.
- Live progress on every task, straight from the game.
- A toggle on the quest frame (and `/monke lore`) restores Blizzard's text exactly.
- Every quest gets a task list, even ones the database has not seen yet. Quests without a
  summary show the game's own one-line version, never the wall of text.
- The quest log shows your tasks once, at the top, under "Monke do:".
- **The Now line**: one short line at the bottom middle of the screen, where your eyes already
  are, with the single next thing to do for the quest you are following and how far away it
  is: `Grab 7 more Red Silk Bandana · 240 yd`. A monke finger at its start points the way,
  turning as you turn (`/monke pointer arrow` swaps in a gold arrow). It fades during a fight and glows when one ends or after a loading
  screen, for "what was I doing?". Drag it anywhere.
- **Monke pick**: "which quest now?" in one key. It picks a quest you can hand in, otherwise the
  nearest one, and points the game's own arrow at it. Press again for another. Set the key in
  Options > Keybindings > AddOns, or click the Now line, or type `/monke pick`.
- **The Monke Do list** (`/monke list on`): like a honey-do list, every quest's next step and
  how far away it is, nearest first, re-sorted as you walk. Click a line to follow that quest.

`/monke` opens the settings. `/monke help` lists the commands. `/monke now off` hides the Now
line; `/monke now reset` puts it back at the bottom middle.

## What it collects

Nothing. The addon has no network access (no WoW addon does), reads no combat data, and saves
only your own settings. All quest summaries are written offline and ship inside the addon as a
static Lua table.

## Missing or wrong quest?

Forever's new quests only reach the database once public sites list them. Until then a quest
still gets a task list, and its story slot shows the game's own one-line summary with "Long
story? Poke Wrinkle." under it. If you see that, or a task is wrong,
[report the quest ID](../../issues/new?template=missing-quest.yml).

## Credits and licence

Quest titles, objective sentences, turn-in NPCs and objective targets for vanilla quests come
from the [Questie](https://github.com/Questie/Questie) project's database
([QuestieDB](https://github.com/Questie/QuestieDB)), published under the GNU GPL v3. Monke Do is
therefore licensed under the **GNU GPL v3** (GPL-3.0-only); see [LICENSE](LICENSE) and
[CREDITS.txt](addon/MonkeDo/CREDITS.txt), which ships inside the addon. Thank you to everyone
who has contributed to Questie's data over the years.

The quests new in WoW: Forever come from QuestieDB's published Forever release, used as
published. Questions about where that data comes from belong with
[QuestieDB](https://github.com/Questie/QuestieDB).

World of Warcraft and its quest text are the property of Blizzard Entertainment. Monke Do is free,
has no ads and asks for no donations in game.

---

## For developers

One monorepo, two deployables: the addon in `addon/MonkeDo/` and the offline pipeline in
`pipeline/` that generates `addon/MonkeDo/Data/*.lua`. Read
[docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md) first; it is the only thing both halves share.

### Set up

```bash
uv sync
```

### Test everything

```bash
uv run pytest
```

That runs the pipeline tests and the addon's busted specs (through the Lua 5.1 bundled with
`lupa`, so no Lua toolchain is needed). CI also runs real `busted` and `luacheck`.

### Build the database

```bash
uv run python -m pipeline run
```

Loads the sources, joins structure, writes summaries, validates them, exports
`MonkeDB.lua` and `MonkeDB_Meta.lua`, prints the coverage report and writes the spot-check
sample to `pipeline/out/review.md`. Every LLM call is cached, so a re-run costs nothing.

- `--provider none` (default) exports rule-based tasks only and spends nothing.
- `--provider batch` writes lore with Claude through the Message Batches API. It needs
  `ANTHROPIC_API_KEY` in your environment and `uv sync --extra llm`.
- `--provider file --summaries-file FILE.jsonl` imports summaries written elsewhere.
- `--sources questie_forever,wago` is the default. `questie_forever` reads the pinned
  QuestieDB Forever release; `--questie-release vX.Y.Z` tries another one. Web sources such
  as `wowforevertalents` run only when named here, only from your machine, never in CI. Ask the
  site owner before the first run.
- `--offline` uses the cached raw files and touches no network.
- `--retry-rejected` forgets rejected summaries first; with `--provider batch` or `direct`
  they go to the API instead of the same committed text.

Every summary written so far is committed in `pipeline/llm/summaries/*.jsonl` and applied on
every run, to every quest whatever `--ids` and `--limit` say, so a fresh clone exports the same
lore without spending anything. Each line carries a stamp of the quest version it was written
for (`prompt_version`, `text_hash`, `context_hash`) and applies to that version only: a quest
whose text, objectives, turn-in or group data changed gets rule-based tasks until it is written
again, and a line without a stamp is never applied. Files apply in version order (`v1.0.10`
after `v1.0.6`), the newest fitting line winning. The export refuses to drop more than 10% of
the shipped lore unless you pass `--force`. Hand-pinned summaries live in
`pipeline/llm/overrides.jsonl` and always win over the LLM.

### Updating from a new QuestieDB release

1. Bump `RELEASE`, `RELEASE_SHA256` and `RELEASE_BYTES` in
   `pipeline/sources/questie_forever.py` (and `DEFAULT_BUILD` in `pipeline/sources/wago.py` for a
   new game build). To look at a release first, pass `--questie-release vX.Y.Z`: an unpinned tag
   is checked only against its own first download, whose sha256 and size are in
   `pipeline/sources/raw/questie_forever/<tag>/manifest.json`.
2. `uv run python -m pipeline run`: loads the release, applies the committed summaries, exports.
   Quests that changed lose their lore until they are written again; if that is more than 10% of
   the shipped lore the export refuses (write them first, or pass `--force`).
3. `uv run python -m pipeline requests --chunk-size 120` lists every quest that needs a summary,
   new or changed, each with its stamp; `requests --rejected` lists the ones the validator
   rejected, with its errors. Have them written (the writer copies each request's stamp into
   its answer), then `uv run python -m pipeline check --summaries-file <answers> --out
   pipeline/llm/summaries/<YYYY-MM>_<name>.jsonl` writes every passing line, stamped.
4. `uv run python -m pipeline run` again, then commit the summaries and the Data files.

Never edit `addon/MonkeDo/Data/*.lua` by hand; `pipeline/export.py` is the only writer.

### Release

Tag `vX.Y.Z`. The BigWigs packager builds the zip and uploads to CurseForge and Wago using the
`CF_API_TOKEN` and `WAGO_API_TOKEN` repository secrets and the project IDs in `MonkeDo.toc`.
A tag with `beta` in it (`v0.9.0-beta1`) goes up as a beta file, one with `alpha` as an alpha.
The upload's release notes are the whole of `CHANGELOG.md`, so put the new version at the top
before tagging.
Before tagging, run the [in-game checklist](docs/INGAME_CHECKLIST.md).
