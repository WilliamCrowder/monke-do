import time

import pytest

from pipeline import luatable
from pipeline.luatable import LuaParseError, parse

REAL_ROW_214 = (
    '{"Red Silk Bandanas",{{820}},{{820}},14,17,77,nil,{"Scout Riell at the Sentinel Hill Tower '
    'wants you to bring her 10 Red Silk Bandanas."},nil,{nil,nil,{{915}}},nil,nil,{155},nil,nil,nil,'
    "1581,nil,nil,nil,nil,nil,8,nil,nil,{{72,250}}}"
)


def test_scalars():
    assert parse("nil") is None
    assert parse("true") is True
    assert parse("false") is False
    assert parse("42") == 42
    assert parse("-7") == -7
    assert parse("3.25") == 3.25
    assert parse("-0.5") == -0.5
    assert parse("1e3") == 1000.0
    assert parse("0x1F") == 31
    assert parse("-0x10") == -16
    assert isinstance(parse("42"), int)
    assert isinstance(parse("42.0"), float)


def test_strings_and_escapes():
    assert parse('"plain"') == "plain"
    assert parse("'single'") == "single"
    assert parse(r'"say \"hi\""') == 'say "hi"'
    assert parse(r"'Recruit\'s Shirt'") == "Recruit's Shirt"
    assert parse(r'"a\\b"') == "a\\b"
    assert parse(r'"line\nnext\ttab\rcr"') == "line\nnext\ttab\rcr"
    assert parse(r'"\65\066C"') == "ABC"
    # \ddd is a byte: two of them make one UTF-8 character
    assert parse(r'"caf\195\169"') == "café"
    assert parse('"already é"') == "already é"
    assert parse('"it\'s -- not a comment { }"') == "it's -- not a comment { }"


def test_positional_entries_keep_their_position_when_nil_is_between():
    assert parse('{ "a", nil, {1} }') == {1: "a", 3: {1: 1}}
    assert parse("{nil,nil,{{915}}}") == {3: {1: {1: 915}}}
    assert parse("{nil}") == {}


def test_key_styles_and_trailing_separators():
    table = parse("""{ [123] = "num", ["str key"] = 2, ['single'] = 3, name = 4, [-1] = "neg",
                      "first", "second", }""")
    assert table == {123: "num", "str key": 2, "single": 3, "name": 4, -1: "neg", 1: "first", 2: "second"}
    assert parse("{1; 2; 3}") == {1: 1, 2: 2, 3: 3}
    assert parse("{}") == {}
    assert parse("{ nested = { deeper = { [1] = true } } }") == {"nested": {"deeper": {1: True}}}
    assert parse("{ truely = 1, nilly = 2 }") == {"truely": 1, "nilly": 2}
    assert parse("{[1.0] = 'float key is the integer key'}") == {1: "float key is the integer key"}


def test_comments_are_skipped_everywhere():
    text = """
    -- leading comment with a brace {
    return { -- after the brace
        1, --[[ block
        comment with } and "quote ]] 2,
        --[==[ level two ]] still inside ]==]
        [3] = 3, -- ['ghost'] = 9,
    }
    -- trailing
    """
    assert parse(text) == {1: 1, 2: 2, 3: 3}


def test_long_string_value():
    assert parse("{ [[raw \\n text]], [==[with ]] inside]==] }") == {1: "raw \\n text", 2: "with ]] inside"}


def test_real_questie_row_lookup_by_key_number_is_exact():
    row = parse(REAL_ROW_214)
    assert row[1] == "Red Silk Bandanas"
    assert row[3] == {1: {1: 820}}
    assert row[4] == 14 and row[5] == 17
    assert 7 not in row and 9 not in row
    assert row[8][1].endswith("10 Red Silk Bandanas.")
    assert row[10] == {3: {1: {1: 915}}}
    assert row[23] == 8
    assert row[26] == {1: {1: 72, 2: 250}}


@pytest.mark.parametrize("bad", [
    "{1, 2", '{"unterminated}', "{1 2}", "{a = }", "print('hi')", "{x = y}", "{1} trailing",
    "{[nil] = 1}", "{[{}] = 1}", "{é = 1}", "", r'"\999"', "os.execute('calc')", "{ f() }",
])
def test_bad_input_raises_and_nothing_is_executed(bad):
    with pytest.raises(LuaParseError):
        parse(bad)


def test_error_message_names_the_line():
    with pytest.raises(LuaParseError, match="line 3"):
        parse("{\n1,\n?\n}")


def test_extract_long_string_and_key_enum():
    source = """
    QuestieDB.questKeys = {
        ['name'] = 1, -- string
        ['startedBy'] = 2, -- table
            --['creatureStart'] = 1, -- table {creature(int),...}
            --['objectStart'] = 2,
        ['finishedBy'] = 3,
    }
    QuestieDB.questData = [[return {
[1] = {"One"},
[2] = {"Two"},
}]]
    QuestieDB.other = [==[ level ]] two ]==]
    """
    keys = luatable.parse_key_enum(source, "QuestieDB.questKeys")
    assert keys == {"name": 1, "startedBy": 2, "finishedBy": 3}
    body = luatable.extract_long_string(source, "QuestieDB.questData")
    assert body.startswith("return {") and body.endswith("}")
    assert parse(body) == {1: {1: "One"}, 2: {1: "Two"}}
    assert luatable.extract_long_string(source, "QuestieDB.other") == " level ]] two "
    with pytest.raises(LuaParseError):
        luatable.extract_long_string(source, "QuestieDB.missing")
    with pytest.raises(LuaParseError):
        luatable.parse_key_enum(source, "QuestieDB.missing")
    with pytest.raises(LuaParseError):
        luatable.parse_key_enum("X = { ['name'] = 'one' }", "X")


def test_an_assignment_inside_a_comment_or_string_is_not_the_assignment():
    source = """
    -- X.keys = { ['name'] = 99 }
    --[[ X.keys = { ['name'] = 98 }
         X.data = [=[return {"commented"}]=] ]]
    local hint = "X.keys = { ['name'] = 97 }"
    X.keys = { ['name'] = 1 }
    X.data = [[return {"real"}]]
    """
    assert luatable.parse_key_enum(source, "X.keys") == {"name": 1}
    assert luatable.extract_long_string(source, "X.data") == 'return {"real"}'


def test_iter_rows_does_not_depend_on_line_structure():
    body = """return {
    [5] = {"five",
           {1, 2,
            3}}, [6] = {"six"}, -- two rows on one line, one row on three
    [7] = nil,
    "positional",
    }"""
    assert list(luatable.iter_rows(body)) == [
        (5, {1: "five", 2: {1: 1, 2: 2, 3: 3}}), (6, {1: "six"}), (1, "positional"),
    ]


def test_iter_rows_max_index_skips_the_rest_of_each_row():
    body = """return {
    [1] = {'Name One', {[10]={{1.5,2.5}}}, "} tricky ' string", --[[ } ]] 9},
    [2] = {nil, 'second field'},
    [3] = {'Name Three'},
    [4] = {},
    }"""
    rows = dict(luatable.iter_rows(body, max_index=1))
    assert rows == {1: {1: "Name One"}, 2: {}, 3: {1: "Name Three"}, 4: {}}
    rows = dict(luatable.iter_rows(body, max_index=2))
    assert rows[1] == {1: "Name One", 2: {10: {1: {1: 1.5, 2: 2.5}}}}
    assert rows[2] == {2: "second field"}


def test_a_megabyte_with_4000_rows_parses_in_a_few_seconds():
    row = REAL_ROW_214[:-1] + ",{[40]={{56.41,47.61},{10.5,20.25},{11.0,-3.5}}}}"
    body = "return {\n" + "".join(f"[{i}] = {row},\n" for i in range(1, 4001)) + "}"
    assert len(body) > 1_000_000
    start = time.perf_counter()
    rows = dict(luatable.iter_rows(body))
    elapsed = time.perf_counter() - start
    assert len(rows) == 4000
    assert rows[4000][27][40][3] == {1: 11.0, 2: -3.5}
    assert elapsed < 5.0, f"took {elapsed:.1f}s"
