"""Unit tests for diff_renumbering.greedy_pair_by_text_ratio."""
from app.services.diff_renumbering import greedy_pair_by_text_ratio


def test_empty_inputs_return_empty_pairs_and_leftovers():
    pairs, left_a, left_b = greedy_pair_by_text_ratio([], [], threshold=0.85)
    assert pairs == []
    assert left_a == []
    assert left_b == []


def test_single_pair_above_threshold():
    a = [("a1", "Operatorul economic plătește accize.")]
    b = [("b1", "Operatorul economic plătește accize.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert pairs == [("a1", "b1")]
    assert left_a == []
    assert left_b == []


def test_single_pair_below_threshold_left_in_leftovers():
    a = [("a1", "Apple banana cherry.")]
    b = [("b1", "Completely different content here.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert pairs == []
    assert left_a == ["a1"]
    assert left_b == ["b1"]


def test_picks_best_match_greedily():
    """Each A item is paired with the highest-similarity B item available."""
    a = [
        ("a1", "Operatorul economic plătește accize."),
        ("a2", "Procedura de autorizare se aplică."),
    ]
    b = [
        ("b1", "Procedura de autorizare se aplică."),
        ("b2", "Operatorul economic plătește accize."),
    ]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert sorted(pairs) == [("a1", "b2"), ("a2", "b1")]
    assert left_a == []
    assert left_b == []


def test_b_item_is_consumed_only_once():
    """Once a B item is paired, it cannot be re-paired with another A item."""
    a = [
        ("a1", "Operatorul economic plătește accize."),
        ("a2", "Operatorul economic plătește accize."),  # identical to a1
    ]
    b = [("b1", "Operatorul economic plătește accize.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert len(pairs) == 1
    assert pairs[0][1] == "b1"
    assert len(left_a) == 1  # one A item is left over
    assert left_b == []


def test_partial_match_above_threshold_pairs():
    """Slightly different text above 0.85 ratio should still pair."""
    a = [("a1", "Operatorul economic plătește accize și taxe.")]
    b = [("b1", "Operatorul economic plătește accize și taxe vamale.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert pairs == [("a1", "b1")]


def test_none_text_treated_as_empty_string():
    """A row with None text shouldn't crash; it just doesn't match anything."""
    a = [("a1", None)]
    b = [("b1", "Some content.")]
    pairs, left_a, left_b = greedy_pair_by_text_ratio(a, b, threshold=0.85)
    assert pairs == []
    assert left_a == ["a1"]
    assert left_b == ["b1"]
