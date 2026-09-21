import pytest

from pipeline.placeholders import canonical_tokens, from_web, normalise


@pytest.mark.parametrize(("web", "client"), [
    ("Well met, <name>.", "Well met, $n."),
    ("A <class> of your skill", "A $c of your skill"),
    ("no <race> has returned", "no $r has returned"),
    ("<Name>, <CLASS>, <Race>", "$n, $c, $r"),
    ("tell <his/her> keeper", "tell $ghis:her; keeper"),
    ("give it to <him/her>", "give it to $ghim:her;"),
    ("<he/she> waits", "$ghe:she; waits"),
    ("my <brother/sister>", "my $gbrother:sister;"),
    ("good <lad/lass>", "good $glad:lass;"),
    ("<Lord/Lady> of the keep", "$gLord:Lady; of the keep"),
    ("<good sir/my lady>", "$ggood sir:my lady;"),
])
def test_web_renderings_map_back_to_client_tokens(web, client):
    assert normalise(web) == client


@pytest.mark.parametrize(("raw", "canonical"), [
    ("Hello, $N.", "Hello, $n."),
    ("a $C and a $R", "a $c and a $r"),
    ("line one$B$Bline two", "line one$b$bline two"),
    ("$G his : her ;", "$ghis:her;"),
    ("$Gbrother:sister;", "$gbrother:sister;"),
    ("$g lad:lass;", "$glad:lass;"),
    ("already $n, $ghis:her; fine", "already $n, $ghis:her; fine"),
])
def test_client_tokens_become_lower_case(raw, canonical):
    assert normalise(raw) == canonical
    assert canonical_tokens(raw) == canonical


@pytest.mark.parametrize("text", [
    "Bring 10 Red Silk Bandanas.",
    "It costs $5, or 2 < 3 > 1.",
    "<UNUSED> quest",
    "a </p> tag and <br/> and <a href=\"x/y\">link</a>",
    "and/or, his/her without brackets",
    "<1/2>",
    "$1w and $o stay",
])
def test_everything_else_is_left_alone(text):
    assert normalise(text) == text


def test_missing_text_stays_none():
    assert normalise(None) is None
    assert normalise("") is None
    assert normalise("   \n") is None


def test_canonical_tokens_does_not_touch_angle_brackets():
    # Questie text is game data: an angle bracket there is literal, not a rendered token.
    assert canonical_tokens("<his/her> $N") == "<his/her> $n"
    assert from_web("<his/her> $N") == "$ghis:her; $N"


def test_both_spellings_compare_equal_after_normalising():
    assert normalise("Go, <name>, find <his/her> blade.") == normalise("Go, $N, find $Ghis:her; blade.")
