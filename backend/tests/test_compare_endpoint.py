import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.providers.base import LLMResponse, TokenUsage

client = TestClient(app)


def test_compare_no_models_returns_422():
    res = client.post("/api/assistant/compare", json={
        "question": "Test question",
        "models": [],
        "mode": "full",
    })
    assert res.status_code == 422


def test_compare_too_many_models_returns_422():
    res = client.post("/api/assistant/compare", json={
        "question": "Test question",
        "models": ["m1", "m2", "m3", "m4", "m5", "m6"],
        "mode": "full",
    })
    assert res.status_code == 422


def test_compare_returns_results_per_model():
    with patch("app.routers.compare.run_pipeline_for_model") as mock_run:
        mock_run.return_value = {
            "answer": "Legal answer here",
            "citations": [],
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "pipeline_steps": {},
        }

        res = client.post("/api/assistant/compare", json={
            "question": "Ce spune legea?",
            "models": ["claude-sonnet-4-6", "gpt-4.1"],
            "mode": "full",
        })
        assert res.status_code == 200
        data = res.json()
        assert len(data["results"]) == 2
        assert all(r["model_id"] in ["claude-sonnet-4-6", "gpt-4.1"] for r in data["results"])


def test_compare_one_model_fails_others_succeed():
    def side_effect(question, model_id, mode, db):
        if model_id == "gpt-4.1":
            raise RuntimeError("API rate limit exceeded")
        return {
            "answer": "Answer",
            "citations": [],
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "pipeline_steps": {},
        }

    with patch("app.routers.compare.run_pipeline_for_model", side_effect=side_effect):
        res = client.post("/api/assistant/compare", json={
            "question": "Test",
            "models": ["claude-sonnet-4-6", "gpt-4.1"],
            "mode": "full",
        })
        assert res.status_code == 200
        data = res.json()
        assert len(data["results"]) == 2
        success = next(r for r in data["results"] if r["model_id"] == "claude-sonnet-4-6")
        failure = next(r for r in data["results"] if r["model_id"] == "gpt-4.1")
        assert success["status"] == "success"
        assert failure["status"] == "error"
        assert "rate limit" in failure["error"]
