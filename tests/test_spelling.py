"""P1-9: the spelling advisory must check ALL-CAPS display type (booth
headlines are predominantly all-caps) and must make a missing dictionary
visible (WARN, never a silent NA/PASS).

Deterministic: a small fixture wordlist stands in for the system dictionary.
"""
import os

import pytest

import proofer


WORDS = ["exhibit", "exhibits", "solutions", "solution", "the", "best", "booth",
         "graphics", "designed", "design", "print", "printed", "quality",
         "trade", "show", "walls", "wall", "banner", "welcome", "new"]


@pytest.fixture
def wordlist(tmp_path):
    p = tmp_path / "words"
    p.write_text("\n".join(WORDS) + "\n")
    return str(p)


def _info(text):
    return {"kind": "pdf", "fonts": 1, "text": text}


def test_allcaps_misspelling_is_flagged(wordlist):
    st, msg = proofer.check_spelling(_info("EXIBIT SOLUTIONS"), dict_path=wordlist)
    assert st == "WARN"
    assert "EXIBIT" in msg
    assert "SOLUTIONS" not in msg.split(": ", 1)[1]   # correctly spelled caps pass


def test_flagged_caps_word_labeled_possible_acronym(wordlist):
    st, msg = proofer.check_spelling(_info("EXIBIT here"), dict_path=wordlist)
    assert st == "WARN"
    assert "EXIBIT (may be an acronym)" in msg


def test_short_allcaps_acronyms_skipped(wordlist):
    st, msg = proofer.check_spelling(_info("NASA WELCOME BOOTH"), dict_path=wordlist)
    assert st == "PASS"                                # NASA skipped (<= 4 caps)
    st, msg = proofer.check_spelling(_info("NASA"), dict_path=wordlist)
    assert st == "PASS"


def test_inflections_tolerated(wordlist):
    st, msg = proofer.check_spelling(_info("designed printed walls"), dict_path=wordlist)
    assert st == "PASS"


def test_pass_message_reports_word_count(wordlist):
    st, msg = proofer.check_spelling(_info("the best booth"), dict_path=wordlist)
    assert st == "PASS"
    assert "3 distinct word(s) checked" in msg


def test_lowercase_misspelling_still_flagged(wordlist):
    st, msg = proofer.check_spelling(_info("qualaty print"), dict_path=wordlist)
    assert st == "WARN" and "qualaty" in msg
    assert "(may be an acronym)" not in msg


def test_missing_dictionary_is_warn_never_na(tmp_path):
    st, msg = proofer.check_spelling(_info("some words"),
                                     dict_path=str(tmp_path / "no_such_dict"))
    assert st == "WARN"
    assert "spelling NOT checked" in msg and "dictionary unavailable" in msg


def test_see_dict_env_override(tmp_path, monkeypatch, wordlist):
    monkeypatch.setenv("SEE_DICT", wordlist)
    # make the default path certainly absent so only the env var can succeed
    monkeypatch.setattr(proofer, "DICT", str(tmp_path / "absent"))
    st, msg = proofer.check_spelling(_info("the best booth"))
    assert st == "PASS"


def test_no_text_stays_na(wordlist):
    st, msg = proofer.check_spelling({"kind": "pdf", "fonts": 0, "text": ""},
                                     dict_path=wordlist)
    assert st == "NA" and "outlined" in msg
    assert proofer.check_spelling({"kind": "raster", "text": ""},
                                  dict_path=wordlist)[0] == "NA"


def test_fix_instructions_dictionary_unavailable_gets_entry():
    results = {"spelling": ("WARN", "spelling NOT checked — dictionary unavailable (/x); "
                                    "install a word list or set SEE_DICT, and proofread manually")}
    fixes = proofer.fix_instructions(results, {}, {"settings": {}},
                                     {"name": "A", "w": 10, "h": 20})
    assert len(fixes) == 1 and fixes[0]["check"] == "spelling"
    assert "NOT checked" in fixes[0]["text"] and "manually" in fixes[0]["text"]


def test_fix_instructions_normal_spelling_warn_unchanged():
    results = {"spelling": ("WARN", "2 word(s) to review: Mamas, Creationz")}
    fixes = proofer.fix_instructions(results, {}, {"settings": {}},
                                     {"name": "A", "w": 10, "h": 20})
    assert "Creationz" in fixes[0]["text"]
