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
- `--sources questie,wago` is the default. Web sources such as `wowforevertalents` run only
  when named here, only from your machine, never in CI. Ask the site owner before the first run.
- `--offline` uses the cached raw files and touches no network.

Hand-pinned summaries live in `pipeline/llm/overrides.jsonl` and always win over the LLM.

Never edit `addon/MonkeDo/Data/*.lua` by hand; `pipeline/export.py` is the only writer.

### Release

Tag `vX.Y.Z`. The BigWigs packager builds the zip and uploads to CurseForge and Wago using the
`CF_API_KEY` and `WAGO_API_TOKEN` repository secrets and the project IDs in `MonkeDo.toc`.
Before tagging, run the [in-game checklist](docs/INGAME_CHECKLIST.md).
