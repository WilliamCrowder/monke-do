# Monke Do data contract

Status: **frozen at schema v3**. Owned by the orchestrator. Workers never change
this file in a worker branch; open an issue instead.

Two parts, one contract. The addon is a pure consumer of generated Lua tables.
The pipeline is the only place that knows about sources, LLMs or servers.

## 1. Hard constraints (from the build plan)

- No network from Lua. Everything the addon shows ships as a static Lua table.
- Quest lore text is server-sent and cannot be enumerated by ID in-game.
- Target client: WoW: Forever, `## Interface: 16001`, Retail API surface
  (`WOW_PROJECT_ID == WOW_PROJECT_MAINLINE`). Never gate on
  `select(4, GetBuildInfo()) >= 100000`; Forever answers `16001`.
- Blizzard addon policy: free, no obfuscation, no donation prompts, no ads,
  nothing that reads combat data. The addon collects nothing from players.
- GPLv3, because Questie data seeds the database.
- Lua is 5.1: no `goto`, no bit ops, no `os`/`io`.
- `addon/MonkeDo/Data/*.lua` is written only by `pipeline/export.py`.
- SavedVariables may not load (beta bug). Settings must default sanely.

## 2. Addon data: `MonkeDB`

`addon/MonkeDo/Data/MonkeDB.lua` defines one global table, keyed by quest ID,
sorted by ID in the file:

```lua
MonkeDB = {
  [214] = { l = "...", p = "...", t = { "...", "..." }, tp = { "..." }, n = 1, e = "Scout Riell", v = 3 },
}
```

Fields are written in the order `l, p, t, tp, n, e, d, g, v`.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `l` | string | no | Lore in monke voice. 1-2 sentences, under 160 characters. |
| `p` | string | no | Lore in plain-English voice. Same limits. |
| `t` | list of strings | no | Ordered task bullets in monke voice. No progress counts, no bullet glyphs. |
| `tp` | list of strings | no | Plain-voice objective bullets, one per structured objective, in order: `pipeline/rules.py` `task_for(o, PLAIN)`, the templates `Rules.lua` uses for plain voice. Written only when the quest has structured objectives (`n > 0`), so it has exactly `n` entries. No turn-in line, no progress counts. |
| `n` | integer | no (default 0) | How many leading entries of `t` map 1:1, in order, to the quest's live objectives. |
| `e` | string | no | Turn-in NPC name ("end"), when a source gives one. |
| `d` | boolean | no (default false) | True when `e` is not the quest giver (a different NPC, or an object such as a mailbox): "Go see" / "Go to" rather than "Go back to" / "Return to". |
| `g` | string or nil | no | Group line in monke voice. |
| `v` | integer | yes | Schema version. Currently `3`. |

A record with neither `l` nor `t` is never exported.

### Rendering rules the addon follows

1. Lore: `l` in monke voice, `p` in plain voice. If the chosen one is missing,
   use the other. If both are missing, the lore section shows Blizzard's own short
   objectives sentence instead (for a quest with none, the first sentence or two of
   its description, at most 160 characters) and a grey line pointing at the
   original-text toggle. The full description is shown only by that toggle.
2. Objective bullets, monke voice: if `t` exists and `n` equals the number of
   live objectives, use `t[1..n]`. Otherwise build them from the live objectives
   with `Rules.lua`. Plain voice builds them from the live objectives with
   `Rules.lua`; with no live objectives it uses `tp` (rule 4).
3. Live progress such as `(3/15)` is appended to objective bullets only, and
   always comes from `C_QuestLog.GetQuestObjectives`, never from the DB.
4. Trailing bullets: monke voice appends `t[n+1..#t]` (hints, then the turn-in
   line last). Plain voice appends a rule-based turn-in line using `e` and `d`.
   With no record, both voices append a generic turn-in line. When the game
   reports no objectives at all (a quest that is offered but not yet accepted),
   monke voice shows `t[1..n]` as they are, without progress, and plain voice
   shows `tp[1..n]` the same way when `tp` has at least `n` entries. A `tp` that
   is not a list of strings is ignored on its own; the rest of the record still
   counts. Older addons ignore `tp`, which is why the schema stays at 3.
5. Group line: shown when the suggested group size is above 1 or the quest tag
   is Elite, Group, Dungeon or Raid. Monke voice uses `g` when present, else
   the `Voice.lua` template.
6. Records with `v` greater than the addon understands are ignored (rule-based
   fallback), never an error.

### String encoding

UTF-8, double-quoted Lua strings. `export.py` escapes `\`, `"`, `\n`, `\r` and
control characters. Summaries contain no Blizzard placeholders (`$n`, `$c`...)
and no UI escape codes (`|c`, `|T`, `|H`).

## 3. Addon data: `MonkeDB_Meta`

```lua
MonkeDB_Meta = { build = "1.60.1.69913", generated = "2026-10-01", count = 3120, schema = 3, prompt = "v1" }
```

Shown by `/monke version`. `build` is the game build the structure data came
from, or `"unknown"`.

## 4. Pipeline database (SQLite, `pipeline/db.sqlite`)

`pipeline/db.py` is the single definition of this schema.

| Table | Key | Purpose |
| --- | --- | --- |
| `source_rows` | `(id, source)` | One row per quest per source, as fetched. |
| `quests` | `id` | The winning row per quest after source priority. |
| `text_diffs` | autoincrement | Logged disagreements between sources on one ID. |
| `objectives` | `(quest_id, idx)` | Structured objectives. |
| `quest_meta` | `quest_id` | Level, XP, flags, group size, tag. |
| `known_ids` | `(id, build)` | Every quest ID in a game build (from wago `QuestV2`). |
| `summaries` | `(quest_id, text_hash, prompt_version)` | LLM output cache and validation status. |

### `quests` and `source_rows` row shape

`id, title, detail, objectives_text, progress, complete, turnin_npc, turnin_kind,
source, fetched_at, text_hash`

- `detail` is the long description. `objectives_text` is the short summary.
  `progress` is the "not done yet" text, `complete` the turn-in reward text.
- `turnin_kind` is `giver` (an NPC who also offers the quest), `other` (a
  different NPC), `object`, or `NULL` when unknown. It travels with `turnin_npc`.
- Missing fields are `NULL`, never empty strings.
- `fetched_at` is UTC ISO 8601.
- `text_hash` is the first 16 hex characters of SHA-256 over
  `title, detail, objectives_text, progress, complete` joined with `\x1f`, each
  whitespace-collapsed and stripped, `NULL` as empty.

### Source priority

Lower number wins. Within one source the newest `fetched_at` wins.

| Priority | Source keys |
| --- | --- |
| 1 | `wowforevertalents`, other Forever web sources |
| 2 | `questie`, `questie_forever` |
| 3 | `wago` (structure only, never text) |

A field the winner lacks is filled from the next source that has it. When two
sources both have a field for one ID and the normalised text differs, a
`text_diffs` row is written. A Questie-versus-web diff on an ID below 90000
means Forever rewrote that vanilla quest.

### `objectives`

`quest_id, idx, type, target_id, target_name, amount, amount_source, text, source`

- `idx` is 1-based and matches the in-game objective order.
- `type` is one of the in-game API strings: `monster`, `item`, `object`,
  `event`, `spell`, `reputation`, `log`, `player`, `progressbar`.
- `amount` is a count of things to kill, collect or use. Reputation thresholds,
  money and progress bars are not counts: they store `amount = 1` and keep their
  wording in `text`.
- `amount_source` is `db2` (wago `QuestObjective.Amount`), `text` (parsed from
  the objectives sentence) or `default` (assumed 1).
- Questie order: monsters, kill credits, objects, items, reputation, spell, then
  the `triggerEnd` event ("Scout through the Fargodeep Mine"). This order is not
  verified against the live client, which is why the addon re-pairs bullets with
  live objectives by count and name before trusting positions.

### Placeholders

Every source normalises to the client's own tokens so texts compare across
sources: `$n` name, `$c` class, `$r` race, `$g male:female;` gender, `$b` line
break. Web sources that render `<name>`, `<class>`, `<race>`, `<his/her>` are
mapped back to these.

## 5. Source modules (`pipeline/sources/*.py`)

Each module exposes:

```python
SOURCE = "questie"            # source key
PRIORITY = 2
NEEDS_NETWORK = True
def load(conn, raw_dir: Path, *, offline: bool = False) -> SourceResult
```

Modules write `source_rows`, `objectives`, `quest_meta` and `known_ids` through
`pipeline/db.py` helpers only, and never write summaries.
`pipeline.sources.load_all(conn, names, raw_dir, offline=False)` runs them, then
calls `db.resolve_quests(conn)`.

Web fetchers respect `robots.txt`, wait 2 seconds between requests, cache raw
HTML on disk, stop on HTTP 403 or 429, run only when named in `--sources`, and
are never invoked by tests or CI.

## 6. Summary JSON (LLM output, one per quest)

```json
{ "lore_monke": "...", "lore_plain": "...", "tasks": ["..."], "group_line": null }
```

`tasks[1..k]` map in order to the `k` structured objectives. Any extra hints
follow. The last entry is the turn-in line. `export.py` maps this to
`l, p, t, n = k, e, g`, and adds `tp` from `pipeline/rules.py` (rule-based
records get `tp` too).

With `k = 0` the summary holds no objective bullets at all, only hints and the
turn-in line: the addon builds objective bullets from the live quest log and
appends `t` after them, so bullets written here would show twice.

Validation (`pipeline/validate.py`), each failure re-prompts with the error, at
most 2 retries, then the quest falls back to rule-based tasks only:

1. Shape: exactly the four keys; lore fields are non-empty strings, `tasks` is a
   non-empty list of non-empty single-line strings, `group_line` is a string or null.
2. Every structured objective with a confirmed amount above 1 appears in
   `tasks[i]` with that same number. Amounts with `amount_source = default` are
   not enforced.
3. `lore_*` is 1-2 sentences and strictly under 160 characters.
4. No cardinal directions or place names that are absent from the source text.
5. No profanity beyond the allowlist.
6. `tasks` ends with a turn-in line naming the turn-in NPC when one is known.
7. No placeholders or UI escape codes.
8. No progress counts such as `(3/15)` and no bullet glyphs or list markers in
   `tasks`. The addon draws both.

The group size counts the player: size 3 is "Bring 2 friends" in both
`Voice.lua` and `pipeline/rules.py`.

Cache key: `(quest_id, text_hash, prompt_version)`. Each row also stores a
fingerprint of the full context the writer saw (text, objectives, turn-in, group
data). A row whose fingerprint no longer matches is stale: the summarizer
requests it again and the exporter falls back to rule-based tasks.

An objective line in the request may carry `text: ...`, the objective's own
wording ("Heal and fortify Sentinel Shaya" on a `monster` objective). Its bullet
is then `Do the thing: {text}.`, never the type's verb; `pipeline/rules.py` and
`Rules.lua` build the same.

`Turn-in NPC:` may say `(not the quest giver)` or `(an object, not a person)`;
the turn-in line is then `Go see {npc}.` rather than `Go back to {npc}.`.

## 7. Addon modules

All files share the addon namespace table: `local ADDON_NAME, ns = ...`.

| Module | Role | Tested by busted |
| --- | --- | --- |
| `ns.Voice` | Monke and plain string tables, `Voice.Format(key, voice, vars)` | yes |
| `ns.Rules` | Objective to bullet templates, objective text parsing, progress | yes |
| `ns.Compose` | Pure function from quest inputs to the final text sections | yes |
| `ns.Core` | Settings, slash commands, DB lookup | yes |
| `ns.Display` | Quest frame hooks. Thin. Reads API, calls Compose, sets text | stubs only |
| `ns.Tracker` | Objective tracker header text | stubs only |

## 8. Facts verified on 2026-09-21

These correct assumptions in the build plan. Workers rely on these, not the plan.

- Questie's database moved to `github.com/Questie/QuestieDB`
  (`data/Classic/classicQuestDB.lua`, NPC, item and object DBs beside it).
- Questie quest rows hold only `name` and `objectivesText`. There is no detail,
  progress or completion text and no objective amounts. Turn-in NPCs and
  objective targets are IDs resolved through the NPC, item and object DBs.
- wago.tools lists the Forever beta under product `wow_classic_beta` (builds
  1.60.1.69876, .69893, .69913). `QuestV2` for 1.60.1.69913 has 6,600 quest IDs,
  1,742 of them at 90000 or above. `QuestObjective` and `QuestV2CliTask` are not
  published for that build yet ("Table not found"), so there are no db2 amounts
  and amounts are parsed from the objectives sentence. The wago module takes the
  build as a parameter, treats a missing table as empty, and falls back to the
  newest Classic Era build for the ID list when the requested build is unknown.
- `QuestInfo_Display` templates hold direct references to the
  `QuestInfo_Show*` functions, so `hooksecurefunc` on those globals never fires
  from the quest frame. Display hooks `QuestInfo_Display` instead.
- The Forever beta API dump (Thunderz96/forever-addon-kit) confirms the quest
  frame globals, `C_QuestLog.GetQuestObjectives`, `GetSuggestedGroupSize`,
  `QuestObjectiveTracker` and `AddonCompartmentFrame` exist.
- The BigWigs packager maps interface `16???` to game type `forever`
  (alias `camelot`, TOC suffix `_Camelot`). It packages tracked files only.
- Real busted sandboxes each spec file: a bare global assignment in a spec never
  reaches the addon. Specs write through `_G.`; `tests/lua/mini_busted.lua` does
  the same so the local runner catches it.
- `FontString:GetText()` returns nil for an empty string on the real client.
- Questie's `startedBy`/`finishedBy` tell a delivery quest from a return trip:
  1,796 of 4,244 vanilla quests are handed in to someone other than the giver
  (1,591) or to an object (205).
