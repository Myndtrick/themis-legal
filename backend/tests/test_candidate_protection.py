"""Tests for Variant 3 candidate protection in Steps 7/9."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_article(article_id, law_number, law_year, source="semantic",
                  protected=False, text="article text"):
    return {
        "article_id": article_id,
        "law_version_id": 1,
        "article_number": str(article_id),
        "text": text,
        "label": str(article_id),
        "source": source,
        "tier": "tier1_primary",
        "role": "PRIMARY",
        "law_number": law_number,
        "law_year": law_year,
        "is_abrogated": False,
        "doc_type": "article",
        "protected": protected,
    }


def test_protected_articles_bypass_reranker(monkeypatch):
    """Protected articles are not passed to reranker and always appear in output."""
    from app.services import pipeline_service

    protected = [
        _make_article(1, "286", "2009", source="concept_search", protected=True),
        _make_article(2, "286", "2009", source="candidate_validated", protected=True),
    ]
    searchable = [
        _make_article(10, "31", "1990", source="semantic"),
        _make_article(11, "31", "1990", source="bm25"),
        _make_article(12, "85", "2014", source="semantic"),
    ]

    state = {
        "question": "test question",
        "legal_issues": [{"issue_id": "ISSUE-1"}],
        "retrieved_articles_raw": protected + searchable,
        "run_id": "test",
    }

    def fake_rerank(question, articles, top_k=25, min_per_law=3):
        # Verify protected articles are NOT in the input
        for a in articles:
            assert not a.get("protected"), "Protected article was passed to reranker!"
        for i, a in enumerate(articles):
            a["reranker_score"] = float(len(articles) - i)
        return articles[:top_k]

    monkeypatch.setattr("app.services.reranker_service.rerank_articles", fake_rerank)
    monkeypatch.setattr(pipeline_service, "log_step", lambda *a, **kw: None)

    state = pipeline_service._step6_select_articles(state, db=None)

    result = state["retrieved_articles"]
    result_ids = {a["article_id"] for a in result}

    # Protected articles must be in result
    assert 1 in result_ids, "Protected article 1 missing from result"
    assert 2 in result_ids, "Protected article 2 missing from result"
    # Searchable articles should also be present
    assert any(aid in result_ids for aid in [10, 11, 12])


def test_reranker_receives_only_non_protected(monkeypatch):
    """Reranker should receive exactly the non-protected articles."""
    from app.services import pipeline_service

    state = {
        "question": "test",
        "legal_issues": [{"issue_id": "ISSUE-1"}],
        "retrieved_articles_raw": [
            _make_article(1, "286", "2009", protected=True),
            _make_article(2, "31", "1990", protected=False),
            _make_article(3, "85", "2014", protected=False),
        ],
        "run_id": "test",
    }

    received_count = []
    def fake_rerank(question, articles, top_k=25, min_per_law=3):
        received_count.append(len(articles))
        for a in articles:
            a["reranker_score"] = 0.0
        return articles

    monkeypatch.setattr("app.services.reranker_service.rerank_articles", fake_rerank)
    monkeypatch.setattr(pipeline_service, "log_step", lambda *a, **kw: None)

    pipeline_service._step6_select_articles(state, db=None)

    assert received_count[0] == 2, f"Reranker received {received_count[0]} articles, expected 2"
