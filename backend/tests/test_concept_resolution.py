"""Tests for Step 1c concept-based article resolution."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _step1c_concept_resolution


class FakeArticle:
    def __init__(self, article_id, article_number, full_text, is_abrogated=False, label=None):
        self.id = article_id
        self.article_number = article_number
        self.full_text = full_text
        self.is_abrogated = is_abrogated
        self.label = label
        self.law_version_id = None


class FakeChromaCollection:
    def __init__(self, results_by_vid=None):
        self._results = results_by_vid or {}

    def query(self, query_texts, n_results, where, include=None):
        vid = where.get("law_version_id") if isinstance(where, dict) else None
        return self._results.get(vid, {
            "ids": [[]], "metadatas": [[]], "distances": [[]], "documents": [[]]
        })


def _make_state(issues, unique_versions):
    return {
        "legal_issues": issues,
        "unique_versions": unique_versions,
        "run_id": "test",
    }


def _make_fake_db(articles_by_key):
    """Create a fake DB that returns articles based on (version_id, article_number) lookup.
    articles_by_key: dict of "vid:art_num" -> FakeArticle
    """
    class FakeQuery:
        def __init__(self):
            self._filters = {}

        def filter(self, *args):
            for arg in args:
                s = str(arg)
                if hasattr(arg, 'right'):
                    right = arg.right
                    right_cls = type(right).__name__
                    if right_cls == 'False_':
                        # ArticleModel.is_abrogated == False
                        self._filters['not_abrogated'] = True
                    elif hasattr(right, 'value'):
                        if 'law_version_id' in s:
                            self._filters['vid'] = right.value
                        elif 'article_number' in s:
                            self._filters['art'] = right.value
            return self

        def first(self):
            vid = self._filters.get('vid')
            art = self._filters.get('art')
            key = f"{vid}:{art}"
            article = articles_by_key.get(key)
            if article and self._filters.get('not_abrogated') and article.is_abrogated:
                return None
            return article

    class FakeDB:
        def query(self, model):
            return FakeQuery()

    return FakeDB()


def test_validates_candidate_and_filters_abrogated():
    """Validates candidate articles, filters abrogated ones."""
    art_valid = FakeArticle(101, "73", "Art 73 text")
    art_abrogated = FakeArticle(102, "138", "Abrogat.", is_abrogated=True)

    db = _make_fake_db({"54:73": art_valid, "54:138": art_abrogated})
    chroma = FakeChromaCollection()

    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [
                {"law_key": "31/1990", "article": "73", "reason": "test"},
                {"law_key": "31/1990", "article": "138", "reason": "test"},
            ],
            "concept_descriptions": [],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)
    art_nums = [a["article_number"] for a in result]
    assert "73" in art_nums
    assert "138" not in art_nums


def test_concept_search_finds_articles():
    """Concept search within a law returns matching articles."""
    chroma = FakeChromaCollection({
        54: {
            "ids": [["art-101", "art-102"]],
            "metadatas": [[
                {"article_number": "72", "article_id": "101", "is_abrogated": "False",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
                {"article_number": "73", "article_id": "102", "is_abrogated": "False",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
            ]],
            "distances": [[0.21, 0.25]],
            "documents": [["Art 72 obligations text", "Art 73 solidarity text"]],
        }
    })

    db = _make_fake_db({})
    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [],
            "concept_descriptions": [
                {"law_key": "31/1990", "concept_general": "răspunderea administratorilor", "concept_specific": None}
            ],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)
    art_nums = [a["article_number"] for a in result]
    assert "72" in art_nums
    assert "73" in art_nums
    assert all(a.get("protected") for a in result)


def test_deduplicates_across_candidates_and_concepts():
    """Same article from candidate validation and concept search is not duplicated."""
    art = FakeArticle(102, "73", "Art 73 text")
    db = _make_fake_db({"54:73": art})

    chroma = FakeChromaCollection({
        54: {
            "ids": [["art-102"]],
            "metadatas": [[
                {"article_number": "73", "article_id": "102", "is_abrogated": "False",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
            ]],
            "distances": [[0.21]],
            "documents": [["Art 73 text"]],
        }
    })

    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [{"law_key": "31/1990", "article": "73", "reason": "test"}],
            "concept_descriptions": [
                {"law_key": "31/1990", "concept_general": "răspunderea solidară", "concept_specific": None}
            ],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)
    art_73_count = sum(1 for a in result if a["article_number"] == "73")
    assert art_73_count == 1


def test_protected_flag_set_on_all_results():
    """All returned articles have protected=True."""
    art = FakeArticle(101, "72", "Art 72 text")
    db = _make_fake_db({"54:72": art})
    chroma = FakeChromaCollection()

    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [{"law_key": "31/1990", "article": "72", "reason": "test"}],
            "concept_descriptions": [],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)
    assert len(result) >= 1
    for a in result:
        assert a["protected"] is True


def test_skips_abrogated_from_concept_search():
    """Concept search results with is_abrogated=True are filtered out."""
    chroma = FakeChromaCollection({
        54: {
            "ids": [["art-101", "art-102"]],
            "metadatas": [[
                {"article_number": "138", "article_id": "101", "is_abrogated": "True",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
                {"article_number": "73", "article_id": "102", "is_abrogated": "False",
                 "law_number": "31", "law_year": "1990", "date_in_force": "2025-12-18",
                 "law_version_id": 54},
            ]],
            "distances": [[0.20, 0.25]],
            "documents": [["Abrogat.", "Art 73 text"]],
        }
    })

    db = _make_fake_db({})
    state = _make_state(
        issues=[{
            "issue_id": "ISSUE-1",
            "applicable_laws": ["31/1990"],
            "candidate_articles": [],
            "concept_descriptions": [
                {"law_key": "31/1990", "concept_general": "test concept", "concept_specific": None}
            ],
        }],
        unique_versions={"31/1990": [54]},
    )

    result = _step1c_concept_resolution(state, db, chroma)
    art_nums = [a["article_number"] for a in result]
    assert "138" not in art_nums
    assert "73" in art_nums
