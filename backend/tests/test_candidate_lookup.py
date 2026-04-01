"""Tests for candidate article direct lookup in Step 7 retrieval."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _fetch_candidate_articles


def test_fetch_candidate_articles_finds_matching():
    """Direct lookup returns articles matching candidate references."""
    state = {
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "candidate_articles": [
                    {"law_key": "31/1990", "article": "72", "reason": "test"},
                ],
                "applicable_laws": ["31/1990"],
            },
        ],
        "unique_versions": {"31/1990": [10]},
    }

    class FakeArticle:
        id = 101
        law_version_id = 10
        article_number = "72"
        full_text = "Art. 72 Obligatiile administratorilor..."
        is_abrogated = False
        label = None
        amendment_notes = []

    class FakeQuery:
        def __init__(self):
            self._filters = []
        def filter(self, *args):
            self._filters.extend(args)
            return self
        def first(self):
            return FakeArticle()

    class FakeDB:
        def query(self, model):
            return FakeQuery()

    result = _fetch_candidate_articles(state, FakeDB())
    assert len(result) >= 1
    assert result[0]["article_number"] == "72"
    assert result[0]["source"] == "candidate_lookup"


def test_fetch_candidate_articles_empty_when_no_candidates():
    """Returns empty list when no candidate_articles in issues."""
    state = {
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "applicable_laws": ["31/1990"],
            },
        ],
        "unique_versions": {"31/1990": [10]},
    }

    class FakeDB:
        def query(self, model):
            class FQ:
                def filter(self, *a): return self
                def first(self): return None
            return FQ()

    result = _fetch_candidate_articles(state, FakeDB())
    assert result == []


def test_fetch_candidate_articles_skips_missing():
    """Skips articles not found in DB without error."""
    state = {
        "legal_issues": [
            {
                "issue_id": "ISSUE-1",
                "candidate_articles": [
                    {"law_key": "286/2009", "article": "999", "reason": "nonexistent"},
                ],
                "applicable_laws": ["286/2009"],
            },
        ],
        "unique_versions": {"286/2009": [20]},
    }

    class FakeDB:
        def query(self, model):
            class FQ:
                def filter(self, *a): return self
                def first(self): return None
            return FQ()

    result = _fetch_candidate_articles(state, FakeDB())
    assert result == []
