"""Registry of source modules and the one entry point that runs them.

Every source module has the same small interface (contract section 5):

    SOURCE, PRIORITY, NEEDS_NETWORK, OPTIONS
    load(conn, raw_dir, *, offline=False, **its own OPTIONS) -> db.SourceResult

so adding a site is: write the module, add one line to `REGISTRY`.
"""

from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from types import ModuleType

from pipeline import db

# Source key -> module path. Modules are imported only when asked for, so a questie
# run never imports BeautifulSoup and a typo cannot half-import anything.
REGISTRY: dict[str, str] = {
    "questie": "pipeline.sources.questie",
    "questie_forever": "pipeline.sources.questie_forever",
    "wago": "pipeline.sources.wago",
    "wowforevertalents": "pipeline.sources.sites.wowforevertalents",
}

# Web sites are never in the default list: they run only when named explicitly,
# and only after their owner has been asked. `questie_forever` replaces `questie` here: its
# release is the Classic data with Forever's corrections and new quests, and running both
# would let whichever downloaded last win on the shared priority.
DEFAULT_SOURCES = ["questie_forever", "wago"]


def get_module(name: str) -> ModuleType:
    if name not in REGISTRY:
        raise ValueError(f"unknown source {name!r}; known sources: {', '.join(sorted(REGISTRY))}")
    return importlib.import_module(REGISTRY[name])


def _check_options(options: dict, selected: list[ModuleType]) -> None:
    """An option that a source outside the selection takes is fine (a CLI passes
    `build=` whether or not wago runs). One that NO source takes is a typo."""
    stray = set(options) - {option for module in selected for option in module.OPTIONS}
    if not stray:
        return
    everywhere = {option for name in REGISTRY for option in get_module(name).OPTIONS}
    unknown = sorted(stray - everywhere)
    if unknown:
        raise ValueError(f"no source takes the option(s): {', '.join(unknown)}")


def load_all(
    conn: sqlite3.Connection,
    names: list[str],
    raw_dir: Path,
    *,
    offline: bool = False,
    **options,
) -> list[db.SourceResult]:
    """Run the named sources in priority order (text first, structure last), then
    rebuild `quests`.

    `options` are passed to the sources that declare them in `OPTIONS`, for example
    `build="1.60.1.69913"` reaches only wago. Each source is committed on its own, so
    one failing source is rolled back and recorded without losing the others' work.
    """
    modules = [get_module(name) for name in dict.fromkeys(names)]  # fail on a typo before any work
    _check_options(options, modules)
    modules.sort(key=lambda module: module.PRIORITY)  # stable: ties keep the caller's order

    results: list[db.SourceResult] = []
    for module in modules:
        own_options = {k: v for k, v in options.items() if k in module.OPTIONS}
        try:
            result = module.load(conn, Path(raw_dir), offline=offline, **own_options)
            conn.commit()
        except Exception as error:  # noqa: BLE001 - one broken source must not sink the run
            conn.rollback()
            result = db.SourceResult(source=module.SOURCE)
            result.notes.append(f"FAILED: {type(error).__name__}: {error}")
        results.append(result)
    db.resolve_quests(conn)
    from pipeline.sources.questie import infer_amounts  # local: the registry imports lazily

    reconciled = db.reconcile_amounts(conn, infer_amounts)
    if reconciled:
        results[-1].notes.append(f"{reconciled} objective counts re-read from a winning sentence")
    conn.commit()
    return results
