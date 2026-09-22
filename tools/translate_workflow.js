// Monke Do translation workflow for the Claude Code Workflow tool.
//
//   Workflow({ scriptPath: "tools/translate_workflow.js",
//              args: { chunks: ["001", "002"], model: "sonnet", editors: false } })
//
// One Sonnet translator per chunk in pipeline/out/translate/in/, self-checked against the
// real validator (`python -m pipeline check`). With editors: true an independent editor
// reads each chunk afterwards and writes corrections to pipeline/out/translate/fix/.
//
// Cost notes from the pilot (2 chunks of 120 quests, translator + editor each): every
// agent turn re-sends ~70k of context, and the pilot agents took 10-12 turns. The lean
// translator below is written to finish in about five turns: read the prompt and the
// chunk in one go, write the whole file in one call, check, fix, check.

export const meta = {
  name: 'monke-translate',
  description: 'Translate quest chunks into Monke Do summaries with Sonnet, checked against the real validator',
  phases: [
    { title: 'Translate', detail: 'one Sonnet translator per chunk, few turns', model: 'sonnet' },
    { title: 'Edit', detail: 'optional independent editor per chunk' },
  ],
}

const REPO = 'C:\\Users\\pc3\\Documents\\GitHub\\monke-do'
const chunks = (args && args.chunks) || []
const translatorModel = (args && args.model) || 'sonnet'
const withEditors = !!(args && args.editors)

const COMMON = `Repo root: ${REPO} (Windows; Git Bash available). You may only create or edit files under pipeline/out/translate/. Do not touch any other file, do not run git, and do not run any "python -m pipeline" subcommand except "check".

Monke Do is a free World of Warcraft addon that replaces the wall of quest text with one or two sentences of lore plus short caveman task bullets, with a plain-English voice as an equal option. Many players who install it have ADHD or simply want less reading. They are never the joke; the joke is the narrator, "Monke", a cheerful, not very bright ape who is always on the player's side.`

function translatePrompt(chunk) {
  return `${COMMON}

YOUR JOB: write the Monke Do summaries for chunk ${chunk}. Work in as few turns as you can; every turn costs the same as re-reading everything you have seen.

TURN 1: read BOTH of these in the same message (two Read calls at once):
  pipeline/llm/prompts/v1.md            your system prompt: both voices, the JSON shape, the order of tasks, every validator rule, and "Mistakes an editor keeps finding". Follow it exactly.
  pipeline/out/translate/in/chunk_${chunk}.jsonl   one line per quest: {"id": <quest id>, "request": "<the message the prompt describes>"}

TURN 2: write pipeline/out/translate/out/chunk_${chunk}.jsonl in ONE Write call, every quest, same order as the input, one JSON object per line:
  {"id": <same id>, "lore_monke": "...", "lore_plain": "...", "tasks": ["...", "..."], "group_line": null}
  UTF-8, no blank lines, no comments, no markdown fences. Use the Write tool, never echo or a shell heredoc (shell quoting corrupts apostrophes such as "Abercrombie's").

TURN 3: validate from the repo root:
  uv run --no-sync python -m pipeline check --summaries-file pipeline/out/translate/out/chunk_${chunk}.jsonl
  It prints one JSON line per failing quest with the validator's complaints, a "words to eyeball" line, then "== check: N summaries, M failed".

TURN 4 (only if something failed): fix every failing line with Edit calls, all in one message, keeping the passing lines untouched. Also glance at "words to eyeball": a capitalised word there that is not in that quest's text is an invented name; fix those too.

TURN 5: run the check again. Stop when it says 0 failed, or after 3 fix rounds at most.

QUALITY BAR, beyond what the validator can see (the prompt's "Mistakes an editor keeps finding" section is the list of things that were wrong in the pilot; read it twice):
- Faithful: only what the request text says. Most classic quests give you a title and one sentence; the lore is then a fun, short restatement of that sentence. No motives, places, directions, characters, pronouns or game knowledge from memory.
- The Monke lore says who wants what, or why, in caveman talk. It is not a copy of the task bullet, and it reads clearly the first time.
- Variety across the chunk: vary the shape of the lore line; a catchphrase in at most one quest in six.
- Proper nouns exactly as written, including apostrophes and capitals; no capitals mid-sentence on ordinary words.
- Tasks: one bullet per structured objective, in order, house verbs, names not pluralised, digits, no count when the amount is 1, "Do the thing: ..." for an objective that carries "text:", then hints only when the text really has one, then the turn-in line last: "Go back to X." for the giver, "Go see X." when marked "(not the quest giver)" or "(an object, not a person)". With "Structured objectives (0)" write no objective bullets at all.
- PG, warm, never mocking the player or any group of people.

Report the numbers asked for in the output schema; "still_failing" lists quest ids the validator still rejects.`
}

function editPrompt(chunk) {
  return `${COMMON}

YOUR JOB: you are the independent editor for chunk ${chunk}. A translator has already written pipeline/out/translate/out/chunk_${chunk}.jsonl from pipeline/out/translate/in/chunk_${chunk}.jsonl, and the validator has passed it. You check what the validator cannot. Work in few turns: read the prompt, the input and the output in one message.

Judge each quest on fidelity (nothing that is not in the request text: motives, places, directions, characters, pronouns, cross-quest "again"/"too"), task bullets (one per objective in order, house verbs, exact names, counts, "Do the thing:" for objectives with their own text, the right turn-in wording), tone (PG, never mocking people), clarity, variety (no catchphrase in more than one quest in six), and completeness (every input id exactly once).

For every quest that needs a change, write the COMPLETE corrected JSON line to pipeline/out/translate/fix/chunk_${chunk}.jsonl (only changed or added quests; an empty file if nothing needs fixing), in one Write call. Then validate until it reports 0 failed:
  uv run --no-sync python -m pipeline check --summaries-file pipeline/out/translate/out/chunk_${chunk}.jsonl --summaries-file pipeline/out/translate/fix/chunk_${chunk}.jsonl

Be a real editor, not a rubber stamp and not a rewriter: leave good lines alone. Report honestly in the output schema; "reasons" holds at most 30 entries, most important first.`
}

const TRANSLATE_SCHEMA = {
  type: 'object',
  properties: {
    chunk: { type: 'string' },
    quests_in: { type: 'integer' },
    lines_written: { type: 'integer' },
    check_rounds: { type: 'integer' },
    still_failing: { type: 'array', items: { type: 'integer' } },
    notes: { type: 'string', description: 'validator complaints that seemed wrong, odd inputs; short' },
  },
  required: ['chunk', 'quests_in', 'lines_written', 'check_rounds', 'still_failing', 'notes'],
}

const EDIT_SCHEMA = {
  type: 'object',
  properties: {
    chunk: { type: 'string' },
    reviewed: { type: 'integer' },
    changed: { type: 'integer' },
    still_failing: { type: 'array', items: { type: 'integer' } },
    verdict: { type: 'string', enum: ['good', 'mixed', 'poor'] },
    reasons: {
      type: 'array',
      items: {
        type: 'object',
        properties: { id: { type: 'integer' }, reason: { type: 'string' } },
        required: ['id', 'reason'],
      },
    },
    notes: { type: 'string' },
  },
  required: ['chunk', 'reviewed', 'changed', 'still_failing', 'verdict', 'reasons', 'notes'],
}

if (!chunks.length) {
  log('no chunks given; pass args: { chunks: ["001", "002"] }')
  return { error: 'no chunks' }
}

const stages = [
  chunk => agent(translatePrompt(chunk), {
    label: `translate:${chunk}`, phase: 'Translate', schema: TRANSLATE_SCHEMA, model: translatorModel, effort: 'medium',
  }),
]
if (withEditors) {
  stages.push((translated, chunk) => agent(editPrompt(chunk), {
    label: `edit:${chunk}`, phase: 'Edit', schema: EDIT_SCHEMA, effort: 'high',
  }).then(edited => ({ chunk, translated, edited })))
} else {
  stages.push((translated, chunk) => ({ chunk, translated }))
}

const results = await pipeline(chunks, ...stages)
const done = results.filter(Boolean)
const dropped = chunks.filter(c => !done.some(r => r.chunk === c))
if (dropped.length) log(`chunks that did not finish: ${dropped.join(', ')}`)
const failing = done.flatMap(r => (r.translated && r.translated.still_failing) || [])
log(`done ${done.length}/${chunks.length} chunks; ${failing.length} quests still failing the validator`)
return { done, dropped, failing }
