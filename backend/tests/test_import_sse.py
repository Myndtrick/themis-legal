# backend/tests/test_import_sse.py
"""Test SSE import streaming endpoint."""
import inspect
import pytest

from app.services.leropa_service import import_law


def test_import_law_accepts_on_progress_callback():
    """import_law function should accept on_progress parameter."""
    sig = inspect.signature(import_law)
    assert "on_progress" in sig.parameters
    param = sig.parameters["on_progress"]
    assert param.default is None


def test_import_law_on_progress_default_is_none():
    """on_progress parameter should default to None (backward-compatible)."""
    sig = inspect.signature(import_law)
    param = sig.parameters["on_progress"]
    assert param.default is None


def test_sse_endpoint_exists():
    """The SSE endpoint should be registered on the app."""
    from app.main import app
    routes = [r.path for r in app.routes]
    assert "/api/laws/import-suggestion/{mapping_id}/stream" in routes


def test_import_law_calls_progress_callback(monkeypatch):
    """import_law should call on_progress with phase=metadata after fetching metadata."""
    events = []

    def fake_fetch_metadata(ver_id):
        return {
            "doc": None,
            "history": [],
            "date_lookup": {},
        }

    def fake_fetch_and_store(db, ver_id, law=None, rate_limit_delay=2.0, override_date=None):
        mock_law = type("Law", (), {
            "id": 1, "title": "Test Law", "law_number": "1", "law_year": 2024,
            "document_type": "law",
        })()
        mock_version = type("Version", (), {"id": 1})()
        return mock_law, mock_version

    def fake_apply_metadata(db, law, doc):
        pass

    def fake_auto_categorize(db, law):
        pass

    monkeypatch.setattr(
        "app.services.leropa_service._fetch_law_metadata", fake_fetch_metadata
    )
    monkeypatch.setattr(
        "app.services.leropa_service.fetch_and_store_version", fake_fetch_and_store
    )
    monkeypatch.setattr(
        "app.services.leropa_service._apply_law_metadata", fake_apply_metadata
    )
    monkeypatch.setattr(
        "app.services.leropa_service._auto_categorize", fake_auto_categorize
    )

    # Patch DB operations so we don't need a real session
    import unittest.mock as mock

    class FakeDB:
        def add(self, obj): pass
        def commit(self): pass
        def query(self, model): return self
        def filter(self, *args): return self
        def all(self): return []

    def on_progress(event):
        events.append(event)

    result = import_law(FakeDB(), "test_ver_id", import_history=False, on_progress=on_progress)

    # Should have at least the metadata progress event
    phases = [e["data"]["phase"] for e in events]
    assert "metadata" in phases


def test_import_law_no_callback_does_not_raise(monkeypatch):
    """import_law should work fine with on_progress=None (default behavior)."""
    def fake_fetch_metadata(ver_id):
        return {
            "doc": None,
            "history": [],
            "date_lookup": {},
        }

    def fake_fetch_and_store(db, ver_id, law=None, rate_limit_delay=2.0, override_date=None):
        mock_law = type("Law", (), {
            "id": 1, "title": "Test Law", "law_number": "1", "law_year": 2024,
            "document_type": "law",
        })()
        mock_version = type("Version", (), {"id": 1})()
        return mock_law, mock_version

    monkeypatch.setattr(
        "app.services.leropa_service._fetch_law_metadata", fake_fetch_metadata
    )
    monkeypatch.setattr(
        "app.services.leropa_service.fetch_and_store_version", fake_fetch_and_store
    )
    monkeypatch.setattr(
        "app.services.leropa_service._apply_law_metadata", lambda db, law, doc: None
    )
    monkeypatch.setattr(
        "app.services.leropa_service._auto_categorize", lambda db, law: None
    )

    class FakeDB:
        def add(self, obj): pass
        def commit(self): pass
        def query(self, model): return self
        def filter(self, *args): return self
        def all(self): return []

    # Should not raise even with no on_progress provided
    result = import_law(FakeDB(), "test_ver_id", import_history=False)
    assert result["law_id"] == 1
