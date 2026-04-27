"""Unit tests for AiccEmbeddingFunction — wraps AICC /v1/embeddings."""
from __future__ import annotations

import httpx
import pytest

from app.services.aicc_embedding import AiccEmbeddingFunction


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_returns_vectors_in_input_order():
    received_inputs = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        import json
        payload = json.loads(body)
        received_inputs.append(payload["input"])
        # Voyage returns one embedding per input, same order
        return httpx.Response(200, json={
            "data": [
                {"index": 0, "embedding": [0.1] * 1024},
                {"index": 1, "embedding": [0.2] * 1024},
            ],
            "model": "voyage-3",
            "object": "list",
        })

    fn = AiccEmbeddingFunction(
        api_key="sk-cc-fake",
        base_url="https://aicc.test/v1",
        model="voyage-3",
        transport=_mock_transport(handler),
    )

    result = fn(["hello", "world"])
    assert len(result) == 2
    assert len(result[0]) == 1024
    assert result[0][0] == 0.1
    assert result[1][0] == 0.2
    assert received_inputs == [["hello", "world"]]


def test_passes_model_in_request_body():
    captured_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        captured_payload.update(json.loads(request.read()))
        return httpx.Response(200, json={
            "data": [{"index": 0, "embedding": [0.0] * 1024}],
            "model": "voyage-3-lite",
            "object": "list",
        })

    fn = AiccEmbeddingFunction(
        api_key="sk-cc-fake",
        base_url="https://aicc.test/v1",
        model="voyage-3-lite",
        transport=_mock_transport(handler),
    )
    fn(["x"])
    assert captured_payload["model"] == "voyage-3-lite"
