"""chroma_service.get_embedding_function and collection name.

The provider branching (local vs aicc) was removed after the post-cutover
cleanup — embeddings now always go through AiccEmbeddingFunction and the
active collection is `legal_articles_v2`.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_embedding_fn_cache():
    """chroma_service caches the embedding function at module level."""
    import app.services.chroma_service as cs
    cs._embedding_fn = None
    yield
    cs._embedding_fn = None


def test_collection_name_is_v2():
    from app.services.chroma_service import get_collection_name
    assert get_collection_name() == "legal_articles_v2"


def test_embedding_function_is_aicc():
    import app.services.chroma_service as cs
    with patch("app.services.chroma_service.AICC_KEY", "sk-cc-fake"), \
         patch("app.services.chroma_service.AICC_BASE_URL", "https://aicc.test/v1"):
        fn = cs.get_embedding_function()
        assert type(fn).__name__ == "AiccEmbeddingFunction"


def test_embedding_function_caches():
    import app.services.chroma_service as cs
    with patch("app.services.chroma_service.AICC_KEY", "sk-cc-fake"), \
         patch("app.services.chroma_service.AICC_BASE_URL", "https://aicc.test/v1"):
        a = cs.get_embedding_function()
        b = cs.get_embedding_function()
        assert a is b
