"""Tests for structured version diff service."""
import difflib

from app.services.article_tokenizer import AtomicUnit
from app.services.structured_diff import _diff_alineat_items, word_diff_html


# --- word_diff_html (kept from the previous version) ---


def test_word_diff_html_marks_replacement():
    a = "pensiile facultative din fonduri"
    b = "pensiile ocupaționale din fonduri"
    html = word_diff_html(a, b)
    assert "<del>facultative</del>" in html
    assert "<ins>ocupaționale</ins>" in html


def test_word_diff_html_identical_returns_plain():
    text = "același text neschimbat"
    assert word_diff_html(text, text) == text


# --- _diff_alineat_items: content-based alignment ---


def _u(label: str, text: str, alineat: str = "(1)", kind: str = "numbered") -> AtomicUnit:
    return AtomicUnit(alineat_label=alineat, marker_kind=kind, label=label, text=text)


def test_diff_alineat_identical_lists_all_unchanged():
    items = [_u("1.", "primul"), _u("2.", "al doilea")]
    leaves = _diff_alineat_items(items, items)
    assert [l["change_type"] for l in leaves] == ["unchanged", "unchanged"]


def test_diff_alineat_pure_insert_in_b():
    a = [_u("1.", "primul"), _u("3.", "al treilea")]
    b = [_u("1.", "primul"), _u("2.", "al doilea"), _u("3.", "al treilea")]
    leaves = _diff_alineat_items(a, b)
    types = [l["change_type"] for l in leaves]
    labels = [l["label"] for l in leaves]
    assert "added" in types
    added_idx = types.index("added")
    assert labels[added_idx] == "2."
    assert leaves[added_idx]["text_b"] == "al doilea"


def test_diff_alineat_pure_delete_in_b():
    a = [_u("1.", "primul"), _u("2.", "al doilea"), _u("3.", "al treilea")]
    b = [_u("1.", "primul"), _u("3.", "al treilea")]
    leaves = _diff_alineat_items(a, b)
    types = [l["change_type"] for l in leaves]
    labels = [l["label"] for l in leaves]
    assert "removed" in types
    removed_idx = types.index("removed")
    assert labels[removed_idx] == "2."


def test_diff_alineat_replace_with_high_similarity_becomes_modified():
    # Same label, slightly edited text — should be one modified leaf, not add+remove.
    a = [_u("1.", "fonduri facultative din pensii")]
    b = [_u("1.", "fonduri ocupaționale din pensii")]
    leaves = _diff_alineat_items(a, b)
    assert len(leaves) == 1
    assert leaves[0]["change_type"] == "modified"
    assert "<ins>ocupaționale</ins>" in leaves[0]["diff_html"]


def test_diff_alineat_replace_with_low_similarity_becomes_add_plus_remove():
    # Same label slot but completely different content — must NOT pair.
    a = [_u("1.", "primul punct vorbește despre A")]
    b = [_u("1.", "complet diferit subiect total")]
    leaves = _diff_alineat_items(a, b)
    types = sorted(l["change_type"] for l in leaves)
    assert types == ["added", "removed"]


def test_diff_alineat_duplicate_labels_match_by_content():
    """The original art-5 bug: many items share label 'a)'. Content-based
    matching must pair them by text, not by collapsing into one bucket."""
    a = [
        _u("a)", "orice acord master de netting"),
        _u("a)", "continuarea activităților contractate"),
        _u("a)", "sediul social al persoanei juridice"),
    ]
    b = [
        _u("a)", "orice acord master de netting"),
        _u("a)", "continuarea activităților contractate"),
        _u("a)", "sediul social al persoanei juridice"),
        _u("a)", "definiție complet nouă"),  # genuinely new
    ]
    leaves = _diff_alineat_items(a, b)
    types = [l["change_type"] for l in leaves]
    assert types.count("unchanged") == 3
    assert types.count("added") == 1
    # Critically: zero fake 'modified' between unrelated 'a)' items.
    assert types.count("modified") == 0


def test_diff_alineat_duplicate_labels_with_one_modified_item():
    """Stronger version of the duplicate-label regression: items_a and items_b
    share the labels but one item in the middle has substantively edited text.
    The diff must produce one modified pair (or removed+added if similarity is
    too low) for that one item, and unchanged for the other duplicates. The
    original bug would fake-modify all duplicates against each other.
    """
    a = [
        _u("a)", "orice acord master de netting"),
        _u("a)", "continuarea activităților contractate în condițiile prezentei legi"),
        _u("a)", "sediul social al persoanei juridice"),
    ]
    b = [
        _u("a)", "orice acord master de netting"),
        # Same label, slightly edited text — should be paired as MODIFIED via the
        # replace-block similarity pairing.
        _u("a)", "continuarea activităților contractate, conform obiectului de activitate"),
        _u("a)", "sediul social al persoanei juridice"),
    ]
    leaves = _diff_alineat_items(a, b)
    types = [l["change_type"] for l in leaves]
    # Expectations:
    # - "orice acord master de netting" matches as unchanged (identical text)
    # - "sediul social al persoanei juridice" matches as unchanged
    # - The middle item is either modified (if SequenceMatcher pairs it via
    #   replace+greedy) OR appears as one removed + one added (if the similarity
    #   ratio between the two texts falls below 0.5)
    assert types.count("unchanged") == 2, f"expected 2 unchanged, got {types}"
    # Critically: NEVER produce a fake-modified pair between unrelated items.
    # The unchanged items must remain unchanged — they must NOT participate in
    # any modified pairing.
    modified_or_changes = [l for l in leaves if l["change_type"] in ("modified", "added", "removed")]
    # For each modified leaf, its text_a must be at least 0.3 similar to its text_b
    # (proves the pairing was content-aware, not arbitrary).
    import difflib
    for l in modified_or_changes:
        if l["change_type"] == "modified":
            ratio = difflib.SequenceMatcher(None, l["text_a"], l["text_b"]).ratio()
            assert ratio >= 0.3, (
                f"modified leaf with low similarity ratio {ratio:.2f}: "
                f"text_a={l['text_a']!r} text_b={l['text_b']!r}"
            )
