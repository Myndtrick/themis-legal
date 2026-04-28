"""POST /internal/scheduler/rates-update — HMAC-signed by AICC scheduler."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


SECRET = "test-scheduler-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr("app.routers.internal_scheduler.AICC_SCHEDULER_SECRET", SECRET)


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_signed_request_accepts_and_returns_202(client, monkeypatch):
    called = {}
    def fake_run():
        called["yes"] = True
        return {"fx_inserted": 1}
    monkeypatch.setattr("app.services.rates.run.run_rates_update_check", fake_run)

    body = json.dumps({"taskId": "x"}).encode()
    r = client.post(
        "/internal/scheduler/rates-update",
        content=body,
        headers={"X-AICC-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert r.json()["job"] == "rates-update"


def test_unsigned_request_rejected_with_401(client):
    r = client.post(
        "/internal/scheduler/rates-update",
        content=b'{"taskId":"x"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_wrong_signature_rejected_with_401(client):
    r = client.post(
        "/internal/scheduler/rates-update",
        content=b'{"taskId":"x"}',
        headers={"X-AICC-Signature": "sha256=bogus", "Content-Type": "application/json"},
    )
    assert r.status_code == 401
