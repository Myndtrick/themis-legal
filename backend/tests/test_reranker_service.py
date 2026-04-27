"""LLM-based reranker tests. The LLM call is mocked so tests are fast and offline."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _articles(n: int) -> list[dict]:
    return [
        {
            "article_id": i + 1,
            "text": f"article body {i}",
            "role": "PRIMARY" if i == 0 else "SECONDARY",
            "distance": 0.5 + (i * 0.1),
            "bm25_rank": i + 1,
        }
        for i in range(n)
    ]


def _mock_llm_response(scores: list[dict]) -> MagicMock:
    """Build a fake OpenAI ChatCompletion-style response with our JSON payload."""
    import json
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = json.dumps({"scores": scores})
    return resp


def test_empty_input_returns_empty_no_llm_call():
    from app.services import reranker_service
    with patch("app.services.reranker_service._get_client") as m:
        result = reranker_service.rerank_articles("q", [], top_k=5)
        assert result == []
        m.assert_not_called()


def test_llm_scores_applied_with_tier_boost_and_sorted():
    from app.services import reranker_service

    articles = _articles(3)  # idx 0 PRIMARY, 1+2 SECONDARY
    fake_resp = _mock_llm_response([
        {"idx": 0, "score": 0.4},  # PRIMARY: 0.4 + 0.15 boost = 0.55
        {"idx": 1, "score": 0.7},  # SECONDARY: 0.7
        {"idx": 2, "score": 0.6},  # SECONDARY: 0.6
    ])

    with patch("app.services.reranker_service._get_client") as m:
        m.return_value.chat.completions.create.return_value = fake_resp
        result = reranker_service.rerank_articles("q", articles, top_k=3)

    assert [a["article_id"] for a in result] == [2, 3, 1]  # 0.7 > 0.6 > 0.55
    assert result[0]["reranker_score"] == 0.7
    assert result[2]["reranker_score"] == pytest.approx(0.55)


def test_llm_failure_falls_back_to_stub():
    from app.services import reranker_service

    articles = _articles(3)
    with patch("app.services.reranker_service._get_client") as m:
        m.return_value.chat.completions.create.side_effect = RuntimeError("boom")
        result = reranker_service.rerank_articles("q", articles, top_k=3)

    # All articles get a stub score; PRIMARY still gets the tier boost so it
    # ends up first only if its stub score + boost beats the others' stub.
    assert len(result) == 3
    for a in result:
        assert "reranker_score" in a


def test_top_k_truncation():
    from app.services import reranker_service

    articles = _articles(5)
    fake_resp = _mock_llm_response([{"idx": i, "score": 1.0 - i * 0.1} for i in range(5)])
    with patch("app.services.reranker_service._get_client") as m:
        m.return_value.chat.completions.create.return_value = fake_resp
        result = reranker_service.rerank_articles("q", articles, top_k=2)

    assert len(result) == 2
    # PRIMARY (idx 0) gets +0.15 boost → 1.15; idx 1 gets 0.9
    assert result[0]["article_id"] == 1
    assert result[1]["article_id"] == 2


def test_malformed_llm_json_falls_back():
    from app.services import reranker_service

    articles = _articles(2)
    bad_resp = MagicMock()
    bad_resp.choices = [MagicMock()]
    bad_resp.choices[0].message.content = "not json at all"

    with patch("app.services.reranker_service._get_client") as m:
        m.return_value.chat.completions.create.return_value = bad_resp
        result = reranker_service.rerank_articles("q", articles, top_k=2)

    assert len(result) == 2
    for a in result:
        assert "reranker_score" in a


def test_articles_above_max_get_stub_scores():
    """Only first 60 articles go to LLM; rest get stub scoring."""
    from app.services import reranker_service

    articles = _articles(70)
    # Mock returns scores only for the 60 we send
    fake_resp = _mock_llm_response([{"idx": i, "score": 0.5} for i in range(60)])
    with patch("app.services.reranker_service._get_client") as m:
        m.return_value.chat.completions.create.return_value = fake_resp
        result = reranker_service.rerank_articles("q", articles, top_k=70)

    # All 70 get a score; the last 10 used stub
    assert len(result) == 70
    assert all("reranker_score" in a for a in result)
