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


def test_batches_inputs_above_128():
    """Voyage caps at 128 inputs per call; we must auto-chunk."""
    call_log = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        payload = json.loads(request.read())
        call_log.append(len(payload["input"]))
        return httpx.Response(200, json={
            "data": [
                {"index": i, "embedding": [float(i)] * 1024}
                for i in range(len(payload["input"]))
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

    # 200 inputs -> 128 + 72
    result = fn([f"doc-{i}" for i in range(200)])
    assert len(result) == 200
    assert call_log == [128, 72]
    # First batch results: index 0..127, embeddings = [0.0,...,127.0]
    # Second batch results: index 0..71, embeddings = [0.0,...,71.0]
    assert result[0][0] == 0.0
    assert result[127][0] == 127.0
    assert result[128][0] == 0.0
    assert result[199][0] == 71.0


def test_exactly_128_inputs_one_call():
    call_log = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        payload = json.loads(request.read())
        call_log.append(len(payload["input"]))
        return httpx.Response(200, json={
            "data": [
                {"index": i, "embedding": [0.0] * 1024} for i in range(len(payload["input"]))
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
    result = fn([f"doc-{i}" for i in range(128)])
    assert len(result) == 128
    assert call_log == [128]


def test_5xx_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    fn = AiccEmbeddingFunction(
        api_key="sk-cc-fake",
        base_url="https://aicc.test/v1",
        model="voyage-3",
        transport=_mock_transport(handler),
    )
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        fn(["x"])
    assert excinfo.value.response.status_code == 503


def test_401_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    fn = AiccEmbeddingFunction(
        api_key="sk-cc-fake",
        base_url="https://aicc.test/v1",
        model="voyage-3",
        transport=_mock_transport(handler),
    )
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        fn(["x"])
    assert excinfo.value.response.status_code == 401


def test_network_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    fn = AiccEmbeddingFunction(
        api_key="sk-cc-fake",
        base_url="https://aicc.test/v1",
        model="voyage-3",
        transport=_mock_transport(handler),
    )
    with pytest.raises(httpx.RequestError):
        fn(["x"])


def test_missing_api_key_raises_at_init():
    with pytest.raises(ValueError, match="api_key"):
        AiccEmbeddingFunction(api_key="", base_url="https://aicc.test/v1", model="voyage-3")


def test_missing_base_url_raises_at_init():
    with pytest.raises(ValueError, match="base_url"):
        AiccEmbeddingFunction(api_key="sk-cc-fake", base_url="", model="voyage-3")
