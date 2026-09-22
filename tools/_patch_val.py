import pathlib
p = pathlib.Path(r"C:\Users\pc3\Documents\GitHub\monke-do\pipeline\validate.py"); s = p.read_text(encoding="utf-8")

# abbreviations: company suffixes and ranks seen in quest names ("Venture Co.", "Mt.")
old = '''    "jr", "sr", "vs", "etc", "no", "e.g", "i.e",
)'''
new = '''    "jr", "sr", "vs", "etc", "e.g", "i.e", "co", "inc", "bros", "mt", "ft", "pvt", "cpt", "maj",
)
# "no." is an abbreviation only when a number follows ("No. 5"), not at "Kobolds say no."
_NUMBERED_ABBREVIATION_RE = re.compile(r"\b(no)\.(?=\s*\d)", re.IGNORECASE)'''
assert old in s, "abbr"; s = s.replace(old, new)

old = '''    text = _ABBREVIATION_RE.sub(r"\1", text)              # Mr. -> Mr'''
new = '''    text = _ABBREVIATION_RE.sub(r"\1", text)              # Mr. -> Mr
    text = _NUMBERED_ABBREVIATION_RE.sub(r"\1", text)     # No. 5 -> No 5'''
assert old in s, "abbr2"; s = s.replace(old, new)

# progress: "0 of 10", "(0 out of 10)"
old = '''_PROGRESS_RE = re.compile(r"\(?\b\d+\s*/\s*\d+\b\)?")'''
new = '''_PROGRESS_RE = re.compile(r"\(?\b\d+\s*(?:/|\s(?:out\s+)?of\s)\s*\d+\b\)?")'''
assert old in s, "progress"; s = s.replace(old, new)

# list markers: "(1)", "1)", "a.", "[x]", "→"
old = '''_BULLET_LEAD_RE = re.compile(r"^\s*(?:[-*\u2022\u00B7\u2013\u2014\u25AA\u25E6\u2023\u25CF\u25CB>]|\d+[.)]\s)")'''
new = '''_BULLET_LEAD_RE = re.compile(
    r"^\s*(?:[-*\u2022\u00B7\u2013\u2014\u25AA\u25E6\u2023\u25CF\u25CB>\u2192\u27A4\u2714\u2611\u2610]"
    r"|\(?\w{1,2}[.):]\s|\[.?\]\s?)"
)'''
assert old in s, "bullet"; s = s.replace(old, new)

# sentence start after an opening quote or a closing bracket/dash
old = '''def _starts_sentence(text: str, start: int) -> bool:
    before = text[:start].rstrip(_OPENERS)
    return not before or before[-1] in _SENTENCE_START_CHARS'''
new = '''def _starts_sentence(text: str, start: int) -> bool:
    """True when the word at `start` opens a sentence or quoted speech ('say "Please...')."""
    raw = text[:start]
    stripped = raw.rstrip(_OPENERS)
    if len(stripped) < len(raw) and any(c in "\\"\u201C\u2018'" for c in raw[len(stripped):]):
        return True  # first word inside quotes
    before = stripped.rstrip("\\"'\u2019\u201D)]")  # closing marks between the end and the word
    before = before.rstrip()
    return not before or before[-1] in _SENTENCE_START_CHARS + "\u2013\u2014-"'''
assert old in s, "starts"; s = s.replace(old, new)

# lore: count sentences with game names masked ("Venture Co. Workers")
old = '''def _check_lore(summary: dict) -> list[str]:
    errors = []
    for key in ("lore_monke", "lore_plain"):
        text = summary[key]
        if len(text) >= MAX_LORE_CHARS:
            errors.append(f"{key} is {len(text)} characters; it must be under {MAX_LORE_CHARS}.")
        sentences = count_sentences(text)'''
new = '''def _check_lore(summary: dict, ctx: QuestContext | None = None) -> list[str]:
    errors = []
    names = ctx.names() if ctx is not None else []
    for key in ("lore_monke", "lore_plain"):
        text = summary[key]
        if len(text) >= MAX_LORE_CHARS:
            errors.append(f"{key} is {len(text)} characters; it must be under {MAX_LORE_CHARS}.")
        # A full stop inside a game name ("Venture Co. Workers") is not a sentence end.
        sentences = count_sentences(_mask_names(text, names))'''
assert old in s, "lore"; s = s.replace(old, new)

# profanity: a blocklisted word the game itself uses as a proper noun is fine
old = '''def _check_profanity(summary: dict, ctx: QuestContext) -> list[str]:
    errors = []
    for label, text in _fields(summary):
        bad = [m.group() for m in _words(_mask_names(text, ctx.names()))
               if _normalise(m.group()) not in PROFANITY_ALLOWLIST
               and _PROFANITY_RE.match(_normalise(m.group()))]'''
new = '''def _proper_nouns(text: str) -> set[str]:
    """Capitalised words that do not start a sentence: the game's own names in its text
    ("Temple of the Damned"). Lower-cased for comparison."""
    return {_normalise(m.group()) for m in _words(text)
            if m.group()[0].isupper() and not _starts_sentence(text, m.start())}


def _check_profanity(summary: dict, ctx: QuestContext) -> list[str]:
    errors = []
    allowed = PROFANITY_ALLOWLIST | _proper_nouns(ctx.source_text()) | _proper_nouns(ctx.title or "")
    for label, text in _fields(summary):
        bad = [m.group() for m in _words(_mask_names(text, ctx.names()))
               if _normalise(m.group()) not in allowed
               and _PROFANITY_RE.match(_normalise(m.group()))]'''
assert old in s, "profanity"; s = s.replace(old, new)
p.write_text(s, encoding="utf-8", newline="\n")
print("ok")
