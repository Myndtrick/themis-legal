"""Tests for Step 2 version preparation with DB lookups."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _find_version_for_date, _fallback_version


class FakeVersion:
    """Minimal LawVersion stand-in for unit tests."""
    def __init__(self, id, date_in_force, is_current=False, ver_id=None):
        self.id = id
        self.date_in_force = date_in_force
        self.is_current = is_current
        self.ver_id = ver_id or f"ver_{id}"


def test_find_version_for_date_exact():
    """Selects newest version with date_in_force <= target."""
    versions = [
        FakeVersion(3, "2026-01-01", is_current=True),
        FakeVersion(2, "2025-06-01"),
        FakeVersion(1, "2024-01-01"),
    ]
    result = _find_version_for_date(versions, "2025-08-01")
    assert result.id == 2


def test_find_version_for_date_future():
    """For future target date, returns latest enacted version."""
    versions = [
        FakeVersion(3, "2026-01-01", is_current=True),
        FakeVersion(2, "2025-06-01"),
    ]
    result = _find_version_for_date(versions, "2027-06-01")
    assert result.id == 3


def test_find_version_for_date_none():
    """Returns None when no version has date_in_force <= target."""
    versions = [
        FakeVersion(3, "2026-01-01"),
    ]
    result = _find_version_for_date(versions, "2025-01-01")
    assert result is None


def test_fallback_version_prefers_current():
    """Fallback returns the current version."""
    versions = [
        FakeVersion(3, "2026-01-01", is_current=True),
        FakeVersion(2, "2025-06-01"),
    ]
    result = _fallback_version(versions)
    assert result.id == 3


def test_fallback_version_first_if_no_current():
    """Fallback returns first version if none is current."""
    versions = [
        FakeVersion(3, "2026-01-01"),
        FakeVersion(2, "2025-06-01"),
    ]
    result = _fallback_version(versions)
    assert result.id == 3
