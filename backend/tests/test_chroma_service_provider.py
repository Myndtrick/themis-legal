"""chroma_service.get_embedding_function and collection name must respect
EMBEDDING_PROVIDER. The `local` path is the legacy SentenceTransformer; the
`aicc` path is AiccEmbeddingFunction with collection `legal_articles_v2`."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_embedding_fn_cache():
	"""chroma_service caches the embedding function at module level. Reset
	after each test so order-dependent leaks don't make later tests get a
	stale provider."""
	import app.services.chroma_service as cs
	cs._embedding_fn = None
	yield
	cs._embedding_fn = None


def test_local_provider_returns_sentence_transformer_function():
    with patch("app.services.chroma_service.EMBEDDING_PROVIDER", "local"):
        # Reset the module-level cache so we get a fresh resolution
        import app.services.chroma_service as cs
        cs._embedding_fn = None
        fn = cs.get_embedding_function()
        # Look at the class name to avoid pulling sentence-transformers in tests
        assert "SentenceTransformer" in type(fn).__name__


def test_aicc_provider_returns_aicc_embedding_function():
    import app.services.chroma_service as cs
    cs._embedding_fn = None
    with patch("app.services.chroma_service.EMBEDDING_PROVIDER", "aicc"), \
         patch("app.services.chroma_service.AICC_KEY", "sk-cc-fake"), \
         patch("app.services.chroma_service.AICC_BASE_URL", "https://aicc.test/v1"):
        fn = cs.get_embedding_function()
        assert type(fn).__name__ == "AiccEmbeddingFunction"


def test_collection_name_local_is_default():
    with patch("app.services.chroma_service.EMBEDDING_PROVIDER", "local"):
        from app.services.chroma_service import get_collection_name
        assert get_collection_name() == "legal_articles"


def test_collection_name_aicc_appends_v2():
    with patch("app.services.chroma_service.EMBEDDING_PROVIDER", "aicc"):
        from app.services.chroma_service import get_collection_name
        assert get_collection_name() == "legal_articles_v2"


def test_unknown_provider_raises():
    import app.services.chroma_service as cs
    cs._embedding_fn = None
    with patch("app.services.chroma_service.EMBEDDING_PROVIDER", "bogus"):
        with pytest.raises(ValueError, match="EMBEDDING_PROVIDER"):
            cs.get_embedding_function()
