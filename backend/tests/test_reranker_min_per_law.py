"""Tests for min_per_law guarantee in reranker."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_article(article_id, law_number, law_year, score, role="PRIMARY"):
    return {
        "article_id": article_id,
        "law_number": law_number,
        "law_year": law_year,
        "text": f"Article {article_id} text",
        "role": role,
        "reranker_score": score,
    }


def test_min_per_law_rescues_missing_law(monkeypatch):
    """Law with zero articles in top_k gets min_per_law articles via swap."""
    from app.services import reranker_service

    articles = [
        _make_article(1, "31", "1990", 5.0),
        _make_article(2, "31", "1990", 4.5),
        _make_article(3, "31", "1990", 4.0),
        _make_article(4, "31", "1990", 3.5),
        _make_article(5, "85", "2014", 2.0),
        _make_article(6, "85", "2014", 1.5),
        _make_article(7, "85", "2014", 1.0),
        _make_article(8, "286", "2009", -1.0),
        _make_article(9, "286", "2009", -1.5),
        _make_article(10, "286", "2009", -2.0),
    ]

    # Fake the cross-encoder to return pre-set scores
    class FakeModel:
        def predict(self, pairs):
            return [a["reranker_score"] for _, a in zip(pairs, articles)]

    monkeypatch.setattr(reranker_service, "_model", FakeModel())

    result = reranker_service.rerank_articles("test question", articles, top_k=5, min_per_law=2)

    law_286_count = sum(
        1 for a in result
        if a["law_number"] == "286" and a["law_year"] == "2009"
    )
    assert law_286_count >= 2, (
        f"Expected at least 2 articles from 286/2009, got {law_286_count}. "
        f"Result laws: {[(a['law_number'] + '/' + a['law_year']) for a in result]}"
    )


def test_min_per_law_expands_when_all_at_minimum(monkeypatch):
    """When all laws are at minimum, new articles expand the selection."""
    from app.services import reranker_service

    articles = [
        _make_article(1, "31", "1990", 5.0),
        _make_article(2, "85", "2014", 4.0),
        _make_article(3, "286", "2009", -1.0),
    ]

    class FakeModel:
        def predict(self, pairs):
            return [a["reranker_score"] for _, a in zip(pairs, articles)]

    monkeypatch.setattr(reranker_service, "_model", FakeModel())

    result = reranker_service.rerank_articles("test", articles, top_k=2, min_per_law=1)

    laws = set(f"{a['law_number']}/{a['law_year']}" for a in result)
    assert "286/2009" in laws, f"286/2009 missing from result. Laws: {laws}"
