"""The registry and load_all: order, options, and one source failing."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import db, sources

FIXTURES = Path(__file__).parent / "fixtures"


def test_defaults_never_include_a_web_site():
    assert sources.DEFAULT_SOURCES == ["questie_forever", "wago"]
    for name in sources.DEFAULT_SOURCES:
        assert not sources.REGISTRY[name].startswith("pipeline.sources.sites.")


def test_every_registered_module_has_the_contract_interface():
    for name in sources.REGISTRY:
        module = sources.get_module(name)
        assert module.SOURCE == name
        assert module.PRIORITY == db.priority_of(name)
        assert module.NEEDS_NETWORK is True
        assert isinstance(module.OPTIONS, tuple)
        assert callable(module.load)


def test_unknown_source_and_unknown_option_fail_before_any_work():
    conn = db.connect()
    with pytest.raises(ValueError, match="unknown source 'wowhead'"):
        sources.load_all(conn, ["questie", "wowhead"], FIXTURES, offline=True)
    with pytest.raises(ValueError, match="biuld"):
        sources.load_all(conn, ["questie"], FIXTURES, offline=True, biuld="1.60.1.69913")
    assert conn.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0] == 0


def test_load_all_runs_then_resolves(tmp_path):
    conn = db.connect()
    # `build` belongs to wago; passing it while only questie runs is fine (a CLI always passes it).
    results = sources.load_all(conn, ["questie"], FIXTURES, offline=True, build="1.60.1.69913")
    assert [(r.source, r.rows_written) for r in results] == [("questie", 7)]
    assert conn.execute("SELECT COUNT(*) FROM quests").fetchone()[0] == 7
    assert conn.in_transaction is False  # committed


def _fake_module(name, priority, log, fail=False, options=()):
    def load(conn, raw_dir, *, offline=False, **kwargs):
        log.append((name, offline, kwargs))
        db.upsert_source_row(conn, db.QuestRow(id=priority * 100, source=name, title=f"from {name}"))
        if fail:
            raise RuntimeError("site changed its layout")
        return db.SourceResult(source=name, rows_written=1)
    return SimpleNamespace(SOURCE=name, PRIORITY=priority, NEEDS_NETWORK=True, OPTIONS=options, load=load)


def test_priority_order_options_and_a_failing_source(monkeypatch, tmp_path):
    log = []
    fakes = {
        "wago": _fake_module("wago", 3, log, options=("build",)),
        "questie": _fake_module("questie", 2, log),
        "wowforevertalents": _fake_module("wowforevertalents", 1, log, fail=True),
    }
    monkeypatch.setattr(sources, "get_module", lambda name: fakes[name])
    conn = db.connect()
    results = sources.load_all(conn, ["wago", "questie", "wowforevertalents", "questie"], tmp_path,
                               offline=True, build="9.9.9")

    # Text sources first, structure last; a repeated name runs once; options go where declared.
    assert log == [("wowforevertalents", True, {}), ("questie", True, {}), ("wago", True, {"build": "9.9.9"})]
    assert [r.source for r in results] == ["wowforevertalents", "questie", "wago"]
    assert results[0].rows_written == 0
    assert results[0].notes == ["FAILED: RuntimeError: site changed its layout"]
    # The failing source's half-done work is rolled back, the others' work is kept and resolved.
    assert [r[0] for r in conn.execute("SELECT source FROM source_rows ORDER BY id")] == ["questie", "wago"]
    assert [r[0] for r in conn.execute("SELECT id FROM quests ORDER BY id")] == [200, 300]


def test_questie_and_questie_forever_never_load_together():
    """Two versions of one database at one priority: running both would let leftovers of one
    fill the gaps of the other. Refused before any work."""
    conn = db.connect()
    with pytest.raises(ValueError, match="questie_forever"):
        sources.load_all(conn, ["questie", "questie_forever"], FIXTURES, offline=True)
    assert conn.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0] == 0
