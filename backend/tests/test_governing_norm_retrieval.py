"""Tests for governing norm retrieval logic."""
from unittest.mock import patch, MagicMock
from app.services.pipeline_service import _fetch_governing_norm, _extract_law_key


def test_extract_law_key_from_ref():
    assert _extract_law_key("Legea 85/2014 art.169") == "85/2014"
    assert _extract_law_key("Legea 31/1990 art.197 alin.(3)") == "31/1990"
    assert _extract_law_key("something without law ref") == ""
    assert _extract_law_key("") == ""
    assert _extract_law_key(None) == ""


def test_fetch_governing_norm_skips_present_status():
    """Should return empty list when governing norm is PRESENT."""
    issue = {
        "governing_norm_status": {"status": "PRESENT"},
    }
    result = _fetch_governing_norm(issue, {}, MagicMock())
    assert result == []


def test_fetch_governing_norm_skips_inferred_status():
    """Should return empty list when governing norm is INFERRED."""
    issue = {
        "governing_norm_status": {"status": "INFERRED"},
    }
    result = _fetch_governing_norm(issue, {}, MagicMock())
    assert result == []


@patch("app.services.pipeline_service._fetch_missing_articles")
def test_fetch_governing_norm_tries_exact_first(mock_fetch):
    """Should try exact reference fetch first."""
    mock_fetch.return_value = [{"article_id": 999, "text": "Art. 169..."}]
    issue = {
        "governing_norm_status": {
            "status": "MISSING",
            "missing_norm_ref": "Legea 85/2014 art.169",
            "expected_norm_description": "Administrator liability",
        },
    }
    state = {"selected_versions": {}}
    db = MagicMock()
    result = _fetch_governing_norm(issue, state, db)
    assert len(result) == 1
    mock_fetch.assert_called_once_with(["Legea 85/2014 art.169"], state, db)


@patch("app.services.pipeline_service._semantic_search_for_norm")
@patch("app.services.pipeline_service._fetch_missing_articles")
def test_fetch_governing_norm_falls_back_to_semantic(mock_fetch, mock_semantic):
    """Should fall back to semantic search when exact fetch returns nothing."""
    mock_fetch.return_value = []
    mock_semantic.return_value = [{"article_id": 888, "text": "Art. 169..."}]
    issue = {
        "governing_norm_status": {
            "status": "MISSING",
            "missing_norm_ref": "Legea 85/2014 art.169",
            "expected_norm_description": "Administrator liability provision",
        },
    }
    state = {"selected_versions": {}}
    db = MagicMock()
    result = _fetch_governing_norm(issue, state, db)
    assert len(result) == 1
    mock_semantic.assert_called_once_with("Administrator liability provision", "85/2014", state, db)
