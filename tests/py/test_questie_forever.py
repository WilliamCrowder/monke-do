import base64
import io
import json
import struct
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


def release(*, flavor="Forever", extra_lines=()) -> bytes:
    """A small QuestieDB-Forever.zip: the toc holds the store, as on v1.0.6."""
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
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(questie_forever.TOC, "\n".join(lines) + "\n")
    return buffer.getvalue()


def fake_fetch(calls, content=None):
    def fetch(url, etag):
        calls.append(url)
        return questie_forever.questie.Download(content=content or release(), etag='"v1"')
    return fetch


@pytest.fixture
def loaded(tmp_path):
    conn = db.connect()
    calls = []
    result = questie_forever.load(conn, tmp_path, fetch=fake_fetch(calls))
    return conn, result, calls, tmp_path


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


def test_a_release_for_another_flavour_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not Forever"):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([], release(flavor="Classic")))


def test_a_missing_chunk_is_corruption(tmp_path):
    bad = release(extra_lines=["## X-Quest-1-8: ~3~"])
    with pytest.raises(ValueError, match="parts"):
        questie_forever.load(db.connect(), tmp_path, fetch=fake_fetch([], bad))


def test_it_is_a_default_source_and_takes_its_release_option(tmp_path):
    from pipeline.sources import DEFAULT_SOURCES

    assert "questie_forever" in DEFAULT_SOURCES and "questie" not in DEFAULT_SOURCES
    questie_forever.ensure_cache(tmp_path, "v1.0.6", offline=False, fetch=fake_fetch([]))
    results = load_all(db.connect(), ["questie_forever"], tmp_path, offline=True,
                       build="1.60.1.70338", questie_release="v1.0.6")
    assert results[0].rows_written == 3
