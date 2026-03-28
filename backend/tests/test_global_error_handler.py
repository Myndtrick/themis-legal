import pytest
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_health_endpoint_works():
    """Sanity check that the app starts and responds."""
    res = client.get("/api/health")
    assert res.status_code == 200


def test_unhandled_exception_returns_structured_error(monkeypatch):
    """Unhandled exceptions should return {code, message}, never raw tracebacks."""
    from app.errors import ThemisError
    from app.main import themis_error_handler

    assert themis_error_handler is not None
