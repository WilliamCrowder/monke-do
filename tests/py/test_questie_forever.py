import base64
import hashlib
import io
import json
import struct
import time
import zipfile

import pytest

from pipeline import cbor, db
from pipeline.sources import load_all, questie_forever


def _head(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([major << 5 | n])
    for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
        if n < 256 ** size:
            return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    raise ValueError(n)


def enc(value) -> bytes:
    """What C_EncodingUtil.SerializeCBOR writes: Lua strings as byte strings."""
    if value is None:
        return b"\xf6"
    if value is True or value is False:
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        return _head(0, value) if value >= 0 else _head(1, -1 - value)
    if isinstance(value, float):
        return b"\xfb" + struct.pack(">d", value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _head(2, len(raw)) + raw
    if isinstance(value, list):
        return _head(4, len(value)) + b"".join(enc(v) for v in value)
    if isinstance(value, dict):
        return _head(5, len(value)) + b"".join(enc(k) + enc(v) for k, v in value.items())
    raise TypeError(value)


def b64(value) -> str:
    return base64.b64encode(enc(value)).decode("ascii")


def release(*, flavor="Forever", extra_lines=(), drop=()) -> bytes:
    """A small QuestieDB-Forever.zip: the toc holds the store, as on v1.0.6. `drop` leaves out
    the lines of those keys (a later release without them)."""
    lines = [
        "## Interface: 16001",
        "## Title: QuestieDB",
        f"## X-Flavor: {flavor}",
        "## X-BUILD-COMMIT: 0123456789abcdef",
        # Scout Riell, as in the real release (field 6 and 17 are ignored).
        f"## X-Quest-214-S: {b64({1: 'Red Silk Bandanas', 4: 14, 5: 17, 6: 77, 23: 8, 'p': 33559174})}",
        f"## X-Quest-214-2: {b64([[820]])}",
        f"## X-Quest-214-3: {b64([[820]])}",
        f"## X-Quest-214-8: {b64(['Scout Riell at the Sentinel Hill Tower wants you to bring her 10 Red Silk Bandanas.'])}",
        f"## X-Quest-214-10: {b64({3: [[915, None, 0]]})}",
        # A new Forever quest: four creature objectives, its sentence split into chunks.
        f"## X-Quest-92867-S: {b64({1: 'Ground to Keep', 4: 32, 5: 39, 'p': 640})}",
        "## X-Quest-92867-8: ~2~",
        f"## X-Quest-92867-10: {b64([[[2569, None, 0], [2590, None, 0]]])}",
        # Given and taken in by different NPCs.
        f"## X-Quest-97292-S: {b64({1: 'Unending Torment', 4: 16, 5: 21, 'p': 134})}",
        f"## X-Quest-97292-2: {b64([[2054]])}",
        f"## X-Quest-97292-3: {b64([[2055]])}",
        f"## X-Quest-97292-8: {b64(['Inject the Hissing Serum into the system above the body for Faranell.'])}",
        # Name only: meta, no row.
        f"## X-Quest-5634-S: {b64({4: 10, 5: 10, 'p': 6})}",
        f"## X-Npc-820-S: {b64({1: 'Scout Riell', 4: 25})}",
        f"## X-Npc-2054-S: {b64({1: 'Apprentice Nimbus'})}",
        f"## X-Npc-2055-S: {b64({1: 'Master Apothecary Faranell'})}",
        f"## X-Npc-2569-S: {b64({1: 'Boulderfist Mauler'})}",
        f"## X-Npc-2590-S: {b64({1: 'Syndicate Conjuror'})}",
        f"## X-Item-915-S: {b64({1: 'Red Silk Bandana'})}",
        *extra_lines,
    ]
    sentence = b64(["Defeat the Boulderfist and Syndicate intruders in Stromgarde Keep."])
    lines += [f"## X-Quest-92867-8-1: {sentence[:20]}", f"## X-Quest-92867-8-2: {sentence[20:]}"]
    lines = [line for line in lines if not any(line.startswith(f"## {key}: ") for key in drop)]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        # A fixed date: the same arguments must give the same bytes, or the pin would flicker.
        entry = zipfile.ZipInfo(questie_forever.TOC, date_time=(2026, 10, 12, 0, 0, 0))
        archive.writestr(entry, "\n".join(lines) + "\n")
    return buffer.getvalue()


def fake_fetch(calls, content=None):
    def fetch(url, etag):
        calls.append(url)
        return questie_forever.questie.Download(content=content or release(), etag='"v1"')
    return fetch


@pytest.fixture(autouse=True)
def pin(monkeypatch):
    """The real pin names the real v1.0.6 zip; these tests download small fakes under that
    tag, so the pin is pointed at the fake. Call `pin(content)` to pin another one."""
    def pin_content(content: bytes | None = None) -> bytes:
        content = content or release()
        monkeypatch.setattr(questie_forever, "RELEASE_SHA256", hashlib.sha256(content).hexdigest(),
                            raising=False)
        monkeypatch.setattr(questie_forever, "RELEASE_BYTES", len(content), raising=False)
        return content
    pin_content()
    return pin_content


@pytest.fixture
def loaded(tmp_path):
    conn = db.connect()
    calls = []
    result = questie_forever.load(conn, tmp_path, fetch=fake_fetch(calls))
    return conn, result, calls, tmp_path


def test_the_fake_release_is_the_same_bytes_every_time():
    """The pin fixture hashes release() once and the fake download builds it again: an entry
    stamped with the clock would make the two differ whenever a second ticks in between."""
    entry = zipfile.ZipFile(io.BytesIO(release())).getinfo(questie_forever.TOC)
    assert entry.date_time == (2026, 10, 12, 0, 0, 0)
    assert release() == release()


def test_cbor_round_trip():
    value = {1: "Bandana", 2: [1, None, -3], "p": 2 ** 33, 4: 1.5, 5: True}
    assert cbor.loads(enc(value)) == value
    with pytest.raises(cbor.CBORError):
        cbor.loads(enc(1) + b"\x00")


def test_rows_objectives_and_turn_ins(loaded):
    conn, result, calls, _ = loaded
    assert result.rows_written == 3
    riell = conn.execute("SELECT * FROM source_rows WHERE id = 214").fetchone()
    assert riell["source"] == "questie_forever"
    assert riell["title"] == "Red Silk Bandanas"
    assert riell["turnin_npc"] == "Scout Riell"
    assert riell["turnin_kind"] == "giver"
    objective = conn.execute("SELECT * FROM objectives WHERE quest_id = 214").fetchone()
    assert (objective["type"], objective["target_name"], objective["amount"], objective["amount_source"]) \
        == ("item", "Red Silk Bandana", 10, "text")
    assert objective["source"] == "questie_forever"
    meta = conn.execute("SELECT * FROM quest_meta WHERE quest_id = 214").fetchone()
    assert (meta["level"], meta["required_level"], meta["flags"]) == (17, 14, 8)

    faranell = conn.execute("SELECT * FROM source_rows WHERE id = 97292").fetchone()
    assert (faranell["turnin_npc"], faranell["turnin_kind"]) == ("Master Apothecary Faranell", "other")


def test_chunked_values_and_new_quests(loaded):
    conn, result, _, _ = loaded
    keep = conn.execute("SELECT * FROM source_rows WHERE id = 92867").fetchone()
    assert keep["objectives_text"] == "Defeat the Boulderfist and Syndicate intruders in Stromgarde Keep."
    assert keep["turnin_npc"] is None  # Questie withheld the finisher
    names = [r[0] for r in conn.execute("SELECT target_name FROM objectives WHERE quest_id = 92867 ORDER BY idx")]
    assert names == ["Boulderfist Mauler", "Syndicate Conjuror"]
    assert any("2 of them new in Forever" in note for note in result.notes)


def test_new_in_forever_means_absent_from_classic(tmp_path, pin):
    """Quest 490 is below 90000 and new in Forever: Classic Questie does not have it."""
    content = pin(release(extra_lines=[f"## X-Quest-490-S: {b64({1: 'A Forever Quest', 'p': 0})}"]))
    result = questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([], content))
    assert any("3 of them new in Forever" in note for note in result.notes)


def test_title_less_quest_is_meta_only_and_every_id_is_known(loaded):
    conn, result, _, _ = loaded
    assert conn.execute("SELECT COUNT(*) FROM source_rows WHERE id = 5634").fetchone()[0] == 0
    assert conn.execute("SELECT level FROM quest_meta WHERE quest_id = 5634").fetchone()[0] == 10
    ids = [r[0] for r in conn.execute("SELECT id FROM known_ids WHERE build = 'questie-forever' ORDER BY id")]
    assert ids == [214, 5634, 92867, 97292]
    assert any("neither a title nor objectives text" in note for note in result.notes)


def test_release_is_downloaded_once_per_tag(loaded):
    conn, _, calls, tmp_path = loaded
    assert calls == [questie_forever.RELEASE_URL.format(tag=questie_forever.RELEASE)]
    folder = tmp_path / "questie_forever" / questie_forever.RELEASE
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["bytes"] == (folder / questie_forever.ASSET).stat().st_size
    fetched_at = conn.execute("SELECT fetched_at FROM source_rows WHERE id = 214").fetchone()[0]
    assert fetched_at == manifest["fetched_at"]

    second = questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch(calls))
    assert len(calls) == 1 and second.rows_written == 3
    questie_forever.load(db.connect(), tmp_path, questie_release="v9.9.9", fetch=fake_fetch(calls))
    assert calls[-1].endswith("/v9.9.9/QuestieDB-Forever.zip")


def test_offline_without_the_release_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="not cached"):
        questie_forever.load(db.connect(), tmp_path, offline=True)


def test_a_release_for_another_flavour_is_refused(tmp_path, pin):
    classic = pin(release(flavor="Classic"))
    with pytest.raises(ValueError, match="not Forever"):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([], classic))


def test_a_missing_chunk_is_corruption(tmp_path, pin):
    bad = pin(release(extra_lines=["## X-Quest-1-8: ~3~"]))
    with pytest.raises(ValueError, match="parts"):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([], bad))


def test_it_is_a_default_source_and_takes_its_release_option(tmp_path):
    from pipeline.sources import DEFAULT_SOURCES

    assert "questie_forever" in DEFAULT_SOURCES and "questie" not in DEFAULT_SOURCES
    questie_forever.ensure_cache(tmp_path, "v1.0.6", offline=False, fetch=fake_fetch([]))
    results = load_all(db.connect(), ["questie_forever"], tmp_path, offline=True,
                       build="1.60.1.70338", questie_release="v1.0.6")
    assert results[0].rows_written == 3


# ---------------------------------------------------------------- the release is checked, not trusted


def _folder(tmp_path, tag=questie_forever.RELEASE):
    return tmp_path / "questie_forever" / tag


@pytest.mark.parametrize(("name", "value"), [("RELEASE_SHA256", "0" * 64), ("RELEASE_BYTES", 1)])
def test_a_download_that_is_not_the_pinned_release_is_refused(tmp_path, monkeypatch, name, value):
    """A tag can be moved and an asset replaced; the pinned digest cannot."""
    monkeypatch.setattr(questie_forever, name, value, raising=False)
    with pytest.raises(ValueError, match="not the pinned release"):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([]))
    assert not (_folder(tmp_path) / questie_forever.ASSET).exists()  # nothing is cached
    assert not (_folder(tmp_path) / (questie_forever.ASSET + ".part")).exists()


def test_the_cached_copy_is_checked_before_every_load(tmp_path):
    questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([]))
    path = _folder(tmp_path) / questie_forever.ASSET
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    for offline in (True, False):
        with pytest.raises(ValueError, match="sha256"):
            questie_forever.load(db.connect(), tmp_path, offline=offline, fetch=fake_fetch([]))
    path.write_bytes(release()[:1000])  # a copy cut short
    with pytest.raises(ValueError, match="bytes"):
        questie_forever.load(db.connect(), tmp_path, offline=True)


def test_an_unpinned_tag_is_trusted_on_first_use_and_checked_after(tmp_path):
    result = questie_forever.load(db.connect(), tmp_path, questie_release="v9.9.9", fetch=fake_fetch([]))
    assert any("not pinned" in note for note in result.notes)
    folder = _folder(tmp_path, "v9.9.9")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == hashlib.sha256(release()).hexdigest()
    (folder / questie_forever.ASSET).write_bytes(release() + b"\0")
    with pytest.raises(ValueError, match="sha256"):
        questie_forever.load(db.connect(), tmp_path, questie_release="v9.9.9", offline=True)


def test_a_crash_while_writing_never_leaves_a_half_file_under_the_real_name(tmp_path, monkeypatch):
    real_replace = questie_forever.os.replace
    crash = {"on": True}

    def replace(src, dst):
        if crash["on"]:
            raise OSError("disk full")
        real_replace(src, dst)

    monkeypatch.setattr(questie_forever.os, "replace", replace)
    with pytest.raises(OSError, match="disk full"):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([]))
    assert not (_folder(tmp_path) / questie_forever.ASSET).exists()
    crash["on"] = False
    calls = []
    questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch(calls))  # downloads again
    assert len(calls) == 1
    assert sorted(p.name for p in _folder(tmp_path).iterdir()) == [questie_forever.ASSET, "manifest.json"]


def test_an_oversized_toc_is_refused_before_it_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(questie_forever, "MAX_TOC_BYTES", 1000, raising=False)
    with pytest.raises(ValueError, match="more than the 1000 allowed"):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([]))


@pytest.mark.parametrize("count", ["0", "2000000", "9" * 40])
def test_a_chunk_count_the_store_cannot_hold_is_refused_at_once(tmp_path, pin, count):
    bad = pin(release(extra_lines=[f"## X-Quest-1-8: ~{count}~"]))
    started = time.perf_counter()
    with pytest.raises(ValueError, match=f"declares {count} parts; "):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([], bad))
    assert time.perf_counter() - started < 5


def test_a_value_that_is_not_base64_names_its_key(tmp_path, pin):
    bad = pin(release(extra_lines=["## X-Quest-77-S: !!!not base64!!!"]))
    with pytest.raises(ValueError, match="X-Quest-77-S"):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([], bad))


def test_list_shaped_scalar_rows_are_read_like_any_other(tmp_path, pin):
    """A Lua table holding only fields 1..n is written as a CBOR array. v1.0.6 has 3,140 S rows
    like that (2 quests, 1,428 NPCs, 7 items, 1,703 objects). The release ships as QuestieDB
    publishes it (the owner's decision, DATA_CONTRACT section 8), so they are read too: field
    1 of an array is field 1 of the row."""
    content = pin(release(extra_lines=[
        f"## X-Npc-3575-S: {b64(['Praenus Raxxeus', None, None, 1, 1])}",
        f"## X-Quest-80001-S: {b64(['Rekindle'])}",
    ]))
    conn = db.connect()
    result = questie_forever.load(conn, tmp_path, fetch=fake_fetch([], content))
    assert not [n for n in result.notes if "list-shaped" in n]
    row = conn.execute("SELECT title FROM source_rows WHERE id = 80001").fetchone()
    assert row is not None and row[0] == "Rekindle"
    store = {"X-Npc-3575-S": b64(["Praenus Raxxeus", None, None, 1, 1])}
    assert questie_forever.names_of(store, "Npc") == {3575: "Praenus Raxxeus"}


# ---------------------------------------------------------------- each load is authoritative


def _tables(conn):
    return {table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")]
            for table in ("source_rows", "quests", "objectives", "known_ids")}


def test_rows_left_by_the_classic_source_are_purged(tmp_path, pin):
    """A database that once ran `questie` (the Classic files) ends up exactly like a fresh one:
    both sources have priority 2, so a leftover Classic row would refill what the release lacks."""
    conn = db.connect()
    db.upsert_source_row(conn, db.QuestRow(id=348, source="questie", title="Stranglethorn Fever",
                                           objectives_text="Find Witch Doctor Unbagwa.",
                                           turnin_npc="Witch Doctor Unbagwa", fetched_at="2026-09-21T19:27:38Z"))
    db.replace_objectives(conn, 348, [db.Objective(348, 1, "monster", 1511, "Mokk the Savage", 1, "default",
                                                   None, "questie")])
    db.add_known_ids(conn, [348, 214], "questie-classic")
    content = pin(release(extra_lines=[f"## X-Quest-348-S: {b64({1: 'Stranglethorn Fever', 'p': 0})}"]))
    questie_forever.load(conn, tmp_path, fetch=fake_fetch([], content))
    db.resolve_quests(conn)

    fresh = db.connect()
    questie_forever.load(fresh, tmp_path, offline=True)
    db.resolve_quests(fresh)
    assert _tables(conn) == _tables(fresh)
    quest = conn.execute("SELECT * FROM quests WHERE id = 348").fetchone()
    assert (quest["objectives_text"], quest["turnin_npc"]) == (None, None)
    assert db.get_objectives(conn, 348) == []


def test_a_quest_a_newer_release_drops_leaves_the_database(tmp_path):
    conn = db.connect()
    with_999 = release(extra_lines=[f"## X-Quest-999-S: {b64({1: 'Bogus Import', 'p': 128})}",
                                    f"## X-Quest-999-8: {b64(['Kill 5 things.'])}",
                                    f"## X-Quest-999-10: {b64({1: [[2569, None, 0]]})}"])
    questie_forever.load(conn, tmp_path, questie_release="v1.0.7", fetch=fake_fetch([], with_999))
    assert db.get_objectives(conn, 999)
    questie_forever.load(conn, tmp_path, questie_release="v1.0.8", fetch=fake_fetch([], release()))
    db.resolve_quests(conn)
    for table, column in (("source_rows", "id"), ("quests", "id"), ("objectives", "quest_id"),
                          ("known_ids", "id")):
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = 999").fetchone()[0] == 0, table


def test_objectives_a_newer_release_lacks_are_removed_but_db2_rows_stay(tmp_path):
    conn = db.connect()
    questie_forever.load(conn, tmp_path, questie_release="v1.0.7", fetch=fake_fetch([], release()))
    assert len(db.get_objectives(conn, 92867)) == 2
    db.replace_objectives(conn, 214, [db.Objective(214, 1, "item", 915, None, 10, "db2", None, "wago")])
    later = release(drop=("X-Quest-92867-10", "X-Quest-214-10"))
    questie_forever.load(conn, tmp_path, questie_release="v1.0.8", fetch=fake_fetch([], later))
    assert db.get_objectives(conn, 92867) == []
    assert [o["amount_source"] for o in db.get_objectives(conn, 214)] == ["db2"]  # wago's amounts win


def test_a_quest_that_loses_its_text_loses_its_row_and_objectives(tmp_path):
    conn = db.connect()
    questie_forever.load(conn, tmp_path, questie_release="v1.0.7", fetch=fake_fetch([], release()))
    later = release(drop=("X-Quest-92867-S", "X-Quest-92867-8"),
                    extra_lines=[f"## X-Quest-92867-S: {b64({4: 32, 5: 39, 'p': 0})}"])
    questie_forever.load(conn, tmp_path, questie_release="v1.0.8", fetch=fake_fetch([], later))
    assert conn.execute("SELECT COUNT(*) FROM source_rows WHERE id = 92867").fetchone()[0] == 0
    assert db.get_objectives(conn, 92867) == []
