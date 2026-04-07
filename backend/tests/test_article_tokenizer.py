"""Tests for the article tokenizer."""
from app.services.article_tokenizer import tokenize_article, AtomicUnit


def test_empty_string_returns_empty_list():
    assert tokenize_article("") == []


def test_plain_sentence_no_markers_returns_one_intro_unit():
    units = tokenize_article("Articolul 100 se abrogă.")
    assert units == [
        AtomicUnit(
            alineat_label=None,
            marker_kind="intro",
            label="",
            text="Articolul 100 se abrogă.",
        )
    ]


def test_plain_sentence_collapses_internal_whitespace():
    units = tokenize_article("  Articolul 100   se abrogă.\n  ")
    assert len(units) == 1
    assert units[0].text == "Articolul 100 se abrogă."


def test_single_alineat_emits_alineat_unit():
    units = tokenize_article("(1) Statul român este suveran.")
    assert units == [
        AtomicUnit(
            alineat_label=None,  # the alineat marker itself sits at the boundary
            marker_kind="alineat",
            label="(1)",
            text="Statul român este suveran.",
        )
    ]


def test_two_alineate_emit_two_units():
    units = tokenize_article("(1) Primul alineat. (2) Al doilea alineat.")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Primul alineat."),
        AtomicUnit(None, "alineat", "(2)", "Al doilea alineat."),
    ]


def test_text_before_first_alineat_becomes_intro():
    units = tokenize_article("Preambul al articolului. (1) Conținutul.")
    assert units == [
        AtomicUnit(None, "intro", "", "Preambul al articolului."),
        AtomicUnit(None, "alineat", "(1)", "Conținutul."),
    ]


def test_numbered_marker_inside_alineat():
    units = tokenize_article("(1) Intro: 1. primul punct. 2. al doilea punct.")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "numbered", "1.", "primul punct."),
        AtomicUnit("(1)", "numbered", "2.", "al doilea punct."),
    ]


def test_litera_marker_inside_alineat():
    units = tokenize_article("(1) Intro: a) prima literă; b) a doua literă;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "litera", "a)", "prima literă;"),
        AtomicUnit("(1)", "litera", "b)", "a doua literă;"),
    ]


def test_upper_litera_marker():
    units = tokenize_article("(1) Intro: A. primul; B. al doilea;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "upper_litera", "A.", "primul;"),
        AtomicUnit("(1)", "upper_litera", "B.", "al doilea;"),
    ]


def test_bullet_marker():
    # Bullet uses U+2013 en-dash + space.
    units = tokenize_article("(1) Intro: – primul; – al doilea;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", "Intro:"),
        AtomicUnit("(1)", "bullet", "–", "primul;"),
        AtomicUnit("(1)", "bullet", "–", "al doilea;"),
    ]


def test_alineat_caret_variant():
    units = tokenize_article("(4^1) Conținut.")
    assert units == [AtomicUnit(None, "alineat", "(4^1)", "Conținut.")]


def test_numbered_caret_variant():
    units = tokenize_article("(1) 42^2. punct nou.")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", ""),
        AtomicUnit("(1)", "numbered", "42^2.", "punct nou."),
    ]


def test_litera_caret_variant():
    units = tokenize_article("(1) a^1) variantă a literei a;")
    assert units == [
        AtomicUnit(None, "alineat", "(1)", ""),
        AtomicUnit("(1)", "litera", "a^1)", "variantă a literei a;"),
    ]


def test_false_positive_alineat_in_alin_reference():
    units = tokenize_article(
        "(1) Conform art. 90 alin. (1) și (2) se aplică prevederile."
    )
    # Only ONE alineat unit — the leading (1). The (1) and (2) inside
    # 'alin. (1) și (2)' are references and must NOT spawn extra alineat units.
    assert len(units) == 1
    assert units[0].marker_kind == "alineat"
    assert units[0].label == "(1)"


def test_false_positive_numbered_in_art_reference():
    units = tokenize_article("(1) Conform art. 125. din lege.")
    # Only the (1) alineat — '125.' must NOT become a numbered marker because
    # it follows 'art. '.
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_false_positive_numbered_in_nr_reference():
    units = tokenize_article("(1) Decizie HP nr. 19/2020 publicată.")
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_false_positive_numbered_in_pct_reference():
    units = tokenize_article("(1) Conform pct. 8. din alineatul anterior.")
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_false_positive_litera_in_lit_reference():
    units = tokenize_article("(1) Conform lit. a) din alineatul anterior.")
    # 'a)' here is a reference, not a litera.
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_real_marker_after_reference_still_recognized():
    units = tokenize_article(
        "(1) Conform art. 90 alin. (1) se aplică: a) prima literă; b) a doua;"
    )
    # The (1) inside 'alin. (1)' is rejected, but the leading (1) and the
    # a) / b) literae must still be recognized.
    labels = [(u.marker_kind, u.label) for u in units]
    assert ("alineat", "(1)") in labels
    assert ("litera", "a)") in labels
    assert ("litera", "b)") in labels
    # No second alineat from the reference:
    assert sum(1 for k, _ in labels if k == "alineat") == 1


def test_decimal_inside_body_does_not_match_numbered():
    # The decimal '2.347' must NOT be picked up as numbered '347.'.
    units = tokenize_article("(1) Conform art. 2.347 din Codul civil.")
    assert len(units) == 1
    assert units[0].label == "(1)"


def test_fp_filter_respects_sentence_boundary_for_alineat():
    """A real (2) marker after a `; ` must not be dropped just because
    the prior sentence contained `art. 87 alin. (2)`."""
    text = "(1) Conform art. 87 alin. (2) și (3); (2) Pentru noul scop."
    units = tokenize_article(text)
    labels = [(u.marker_kind, u.label) for u in units]
    assert ("alineat", "(1)") in labels
    assert ("alineat", "(2)") in labels
    assert sum(1 for k, _ in labels if k == "alineat") == 2


def test_fp_filter_respects_sentence_boundary_for_numbered():
    """A real `68.` definition after `art. 159 și 161;... ` must not be dropped."""
    text = "(1) Conform art. 159 și 161;... 68. tabel definitiv de creanțe este..."
    units = tokenize_article(text)
    labels = [(u.marker_kind, u.label) for u in units]
    assert ("numbered", "68.") in labels


def test_fp_filter_alineatului_reference_dropped():
    """`alineatului (4)` is a reference and must NOT spawn a (4) alineat."""
    text = "(1) Conform alineatului (4) al Articolului V din LEGEA nr. 17."
    units = tokenize_article(text)
    # Only one real alineat — the leading (1).
    alineate = [u for u in units if u.marker_kind == "alineat"]
    assert len(alineate) == 1
    assert alineate[0].label == "(1)"


import json
from dataclasses import asdict
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tokenizer"


def _all_fixture_names() -> list[str]:
    return sorted(p.stem for p in _FIXTURE_DIR.glob("*.txt"))


@pytest.mark.parametrize("name", _all_fixture_names())
def test_tokenizer_snapshot(name: str):
    txt_path = _FIXTURE_DIR / f"{name}.txt"
    json_path = _FIXTURE_DIR / f"{name}.expected.json"

    full_text = txt_path.read_text(encoding="utf-8")
    actual = [asdict(u) for u in tokenize_article(full_text)]

    if not json_path.exists():
        pytest.fail(
            f"Missing snapshot file {json_path}. Generate it once with:\n"
            f"  python -c \""
            f"from app.services.article_tokenizer import tokenize_article; "
            f"from dataclasses import asdict; import json; "
            f"print(json.dumps([asdict(u) for u in tokenize_article("
            f"open('{txt_path}').read())], ensure_ascii=False, indent=2))"
            f"\" > {json_path}\n"
            f"Then OPEN AND REVIEW THE FILE before committing."
        )

    expected = json.loads(json_path.read_text(encoding="utf-8"))
    assert actual == expected, (
        f"Tokenizer output for {name} does not match snapshot. "
        f"If the change is intentional, regenerate {json_path}."
    )
