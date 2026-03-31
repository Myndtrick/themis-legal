"""Tests for ChromaDB index verification."""
import pytest
from unittest.mock import MagicMock, patch


def test_verify_detects_missing_versions():
    """verify_index_completeness returns mismatches when ChromaDB is missing articles."""
    from app.services.chroma_service import verify_index_completeness

    mock_db = MagicMock()
    mock_version = MagicMock()
    mock_version.id = 54
    mock_version.law_id = 3
    mock_db.query.return_value.join.return_value.filter.return_value.group_by.return_value.all.return_value = [
        (mock_version, 100)
    ]

    with patch("app.services.chroma_service.get_collection") as mock_col:
        mock_col.return_value.get.return_value = {"ids": []}
        result = verify_index_completeness(mock_db)

    assert len(result) == 1
    assert result[0]["law_version_id"] == 54
    assert result[0]["db_count"] == 100
    assert result[0]["chroma_count"] == 0
    assert result[0]["status"] == "MISSING"


def test_verify_no_mismatch_when_indexed():
    """verify_index_completeness returns empty list when all versions are indexed."""
    from app.services.chroma_service import verify_index_completeness

    mock_db = MagicMock()
    mock_version = MagicMock()
    mock_version.id = 54
    mock_version.law_id = 3
    mock_db.query.return_value.join.return_value.filter.return_value.group_by.return_value.all.return_value = [
        (mock_version, 100)
    ]

    with patch("app.services.chroma_service.get_collection") as mock_col:
        mock_col.return_value.get.return_value = {"ids": [f"art-{i}" for i in range(100)]}
        result = verify_index_completeness(mock_db)

    assert len(result) == 0
