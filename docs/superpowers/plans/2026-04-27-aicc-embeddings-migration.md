# AICC Embeddings Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Themis's in-process `sentence-transformers` embedding model with calls to AICC's `/v1/embeddings` proxy backed by `voyage-3` (1024 dims), behind an env-driven feature flag, with BM25 fallback at search time.

**Architecture:** Custom Chroma `EmbeddingFunction` subclass wraps AICC `/v1/embeddings` via httpx. Provider selected by `EMBEDDING_PROVIDER=local|aicc` env var; collection name shifts to `legal_articles_v2` when aicc is active so old + new can coexist on disk. Cutover is operator-driven: deploy code with default `local`, run reindex script to populate v2 collection, flip env var. Search-time errors fall back to BM25 which already exists.

**Tech Stack:** Python 3.12, FastAPI, Chroma 0.6, httpx, pytest, SQLAlchemy 2.x.

**Spec:** `docs/superpowers/specs/2026-04-27-aicc-embeddings-migration-design.md`

**Pre-implementation prep (NONE required before merge).** All cutover steps are post-merge operator actions; the merged code defaults to `EMBEDDING_PROVIDER=local` so production is unchanged.

---

## File map

### Backend — created
- `backend/app/services/aicc_embedding.py` — `AiccEmbeddingFunction` class
- `backend/tests/test_aicc_embedding.py` — unit tests with `httpx.MockTransport`
- `backend/scripts/reindex_with_aicc.py` — one-shot script: drops `legal_articles_v2` if present, indexes all law versions through AICC

### Backend — modified
- `backend/app/services/chroma_service.py` — provider branch in `get_embedding_function`, new collection name when provider=aicc
- `backend/app/services/pipeline_service.py` — wrap 2 `query_articles` callers with BM25 fallback (lines ~759 and ~2234)
- `backend/app/config.py` — add `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL_AICC`
- `backend/.env` — add new env vars locally (gitignored — operator updates separately)

### Docs — created
- `docs/superpowers/runbooks/2026-04-27-aicc-embeddings-cutover.md` — cutover + rollback runbook

---

## Task 0: Add config knobs

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Read current config.py to see where AICC_KEY is defined**

Run: `grep -nE "(AICC_KEY|EMBEDDING_MODEL)" backend/app/config.py`
Expected: lines for both. Will append the new vars near `EMBEDDING_MODEL`.

- [ ] **Step 2: Edit config.py**

In `backend/app/config.py`, find the line:
```python
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
```

Replace it with:
```python
# Embedding provider selection: "local" (in-process sentence-transformers,
# legacy) or "aicc" (route through AICC /v1/embeddings proxy). Default
# "local" so existing deploys are unchanged until operator flips the flag.
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "local")

# Model used when provider=local. Untouched.
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Model used when provider=aicc. voyage-3 = 1024 dims, multilingual,
# AICC-supported. See spec 2026-04-27-aicc-embeddings-migration-design.md
# for model selection rationale.
EMBEDDING_MODEL_AICC = os.environ.get("EMBEDDING_MODEL_AICC", "voyage-3")
```

- [ ] **Step 3: Verify config imports cleanly**

Run: `cd backend && uv run python -c "from app.config import EMBEDDING_PROVIDER, EMBEDDING_MODEL_AICC; print(EMBEDDING_PROVIDER, EMBEDDING_MODEL_AICC)"`
Expected: `local voyage-3`

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py
git commit -m "config(backend): add EMBEDDING_PROVIDER + EMBEDDING_MODEL_AICC knobs"
```

---

## Task 1: AiccEmbeddingFunction — happy path

**Files:**
- Create: `backend/app/services/aicc_embedding.py`
- Create: `backend/tests/test_aicc_embedding.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_aicc_embedding.py`:

```python
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


def test_empty_input_returns_empty_without_calling_aicc():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(500)

    fn = AiccEmbeddingFunction(
        api_key="sk-cc-fake",
        base_url="https://aicc.test/v1",
        model="voyage-3",
        transport=_mock_transport(handler),
    )
    result = fn([])
    assert result == []
    assert call_count["n"] == 0
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/test_aicc_embedding.py -v`
Expected: `ModuleNotFoundError: No module named 'app.services.aicc_embedding'`

- [ ] **Step 3: Implement AiccEmbeddingFunction**

Create `backend/app/services/aicc_embedding.py`:

```python
"""AICC-backed Chroma embedding function.

Wraps AICC's OpenAI-compatible /v1/embeddings endpoint. Used by chroma_service
when EMBEDDING_PROVIDER=aicc. Indexed embeddings live in the
legal_articles_v2 collection with 1024 dims (voyage-3 default).

NOT used at all when EMBEDDING_PROVIDER=local — the legacy
SentenceTransformerEmbeddingFunction handles that path.
"""
from __future__ import annotations

import logging
from typing import Sequence

import httpx
from chromadb import Documents, EmbeddingFunction, Embeddings

logger = logging.getLogger(__name__)

# Voyage's per-request input limit. AICC forwards directly so we batch here.
_VOYAGE_MAX_INPUTS_PER_CALL = 128


class AiccEmbeddingFunction(EmbeddingFunction[Documents]):
    """Generate embeddings via AICC /v1/embeddings (proxies to Voyage)."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "voyage-3",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("AiccEmbeddingFunction: api_key is required")
        if not base_url:
            raise ValueError("AiccEmbeddingFunction: base_url is required")
        self._model = model
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            transport=transport,
        )

    def __call__(self, input: Documents) -> Embeddings:
        # Chroma sometimes hands us an empty list for empty inputs; short-circuit
        # before making any HTTP call.
        if not input:
            return []

        # Single batch path. Multi-batch handled in Task 2.
        return self._embed_batch(list(input))

    def _embed_batch(self, batch: list[str]) -> Embeddings:
        r = self._http.post(
            "/embeddings",
            json={"model": self._model, "input": batch},
        )
        r.raise_for_status()
        body = r.json()
        # Voyage/OpenAI shape: { "data": [{"index": int, "embedding": [...]}], ... }
        # Sort by index to be defensive about unordered responses.
        items = sorted(body["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]

    def close(self) -> None:
        self._http.close()
```

- [ ] **Step 4: Run, verify all 3 tests pass**

Run: `cd backend && uv run pytest tests/test_aicc_embedding.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/aicc_embedding.py backend/tests/test_aicc_embedding.py
git commit -m "feat(backend): AiccEmbeddingFunction happy path + empty input"
```

---

## Task 2: AiccEmbeddingFunction — batching

**Files:**
- Modify: `backend/app/services/aicc_embedding.py`
- Modify: `backend/tests/test_aicc_embedding.py`

- [ ] **Step 1: Add the failing test**

Append to `backend/tests/test_aicc_embedding.py`:

```python
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
    # First batch results: index 0..127 in the batch, embeddings = [0.0,...,127.0]
    # Second batch results: index 0..71 in the batch, embeddings = [0.0,...,71.0]
    # After concatenation, position 0 should have first-batch emb[0] = 0.0,
    # position 128 should have second-batch emb[0] = 0.0, position 199 should be 71.0.
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
```

- [ ] **Step 2: Run, verify they fail**

Run: `cd backend && uv run pytest tests/test_aicc_embedding.py -v`
Expected: 3 PASS (existing) + 2 FAIL (call_log shows `[200]` instead of `[128, 72]`).

- [ ] **Step 3: Add batching to `__call__`**

In `backend/app/services/aicc_embedding.py`, REPLACE the `__call__` method body:

```python
    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []
        items = list(input)
        out: Embeddings = []
        for start in range(0, len(items), _VOYAGE_MAX_INPUTS_PER_CALL):
            batch = items[start : start + _VOYAGE_MAX_INPUTS_PER_CALL]
            out.extend(self._embed_batch(batch))
        return out
```

- [ ] **Step 4: Run, verify all 5 tests pass**

Run: `cd backend && uv run pytest tests/test_aicc_embedding.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/aicc_embedding.py backend/tests/test_aicc_embedding.py
git commit -m "feat(backend): AiccEmbeddingFunction auto-chunks inputs >128"
```

---

## Task 3: AiccEmbeddingFunction — error paths

**Files:**
- Modify: `backend/tests/test_aicc_embedding.py`

- [ ] **Step 1: Add error-path tests**

Append to `backend/tests/test_aicc_embedding.py`:

```python
def test_5xx_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    fn = AiccEmbeddingFunction(
        api_key="sk-cc-fake",
        base_url="https://aicc.test/v1",
        model="voyage-3",
        transport=_mock_transport(handler),
    )
    with pytest.raises(httpx.HTTPStatusError):
        fn(["x"])


def test_401_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    fn = AiccEmbeddingFunction(
        api_key="sk-cc-fake",
        base_url="https://aicc.test/v1",
        model="voyage-3",
        transport=_mock_transport(handler),
    )
    with pytest.raises(httpx.HTTPStatusError):
        fn(["x"])


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
```

- [ ] **Step 2: Run, verify they pass without changes (impl already raises)**

Run: `cd backend && uv run pytest tests/test_aicc_embedding.py -v`
Expected: 10 PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_aicc_embedding.py
git commit -m "test(backend): cover AiccEmbeddingFunction 5xx/401/network/init errors"
```

---

## Task 4: chroma_service provider branch

**Files:**
- Modify: `backend/app/services/chroma_service.py`
- Create: `backend/tests/test_chroma_service_provider.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_chroma_service_provider.py`:

```python
"""chroma_service.get_embedding_function and collection name must respect
EMBEDDING_PROVIDER. The `local` path is the legacy SentenceTransformer; the
`aicc` path is AiccEmbeddingFunction with collection `legal_articles_v2`."""
from __future__ import annotations

from unittest.mock import patch


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


import pytest  # at bottom so test discovery still works above
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/test_chroma_service_provider.py -v`
Expected: ImportError on `get_collection_name` and/or `AICC_KEY` not in chroma_service.

- [ ] **Step 3: Edit `chroma_service.py`**

REPLACE the imports and the `_client`, `_embedding_fn`, `get_chroma_client`, `get_embedding_function`, and `get_collection` blocks (top of file through line ~44 in current code) with:

```python
from __future__ import annotations

import logging

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.utils import embedding_functions
from sqlalchemy.orm import Session

from app.config import (
    AICC_BASE_URL,
    AICC_KEY,
    CHROMA_PATH,
    CHROMA_COLLECTION,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_AICC,
    EMBEDDING_PROVIDER,
)
from app.models.law import Article, Law, LawVersion

logger = logging.getLogger(__name__)

_client: chromadb.PersistentClient | None = None
_embedding_fn = None


def get_chroma_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_collection_name() -> str:
    """Collection name varies by provider so old + new can coexist on disk."""
    if EMBEDDING_PROVIDER == "aicc":
        return f"{CHROMA_COLLECTION}_v2"
    return CHROMA_COLLECTION


def get_embedding_function():
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn

    if EMBEDDING_PROVIDER == "local":
        _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        logger.info("Embedding provider: local (model=%s)", EMBEDDING_MODEL)
    elif EMBEDDING_PROVIDER == "aicc":
        from app.services.aicc_embedding import AiccEmbeddingFunction
        _embedding_fn = AiccEmbeddingFunction(
            api_key=AICC_KEY,
            base_url=AICC_BASE_URL,
            model=EMBEDDING_MODEL_AICC,
        )
        logger.info("Embedding provider: aicc (model=%s)", EMBEDDING_MODEL_AICC)
    else:
        raise ValueError(
            f"Unknown EMBEDDING_PROVIDER={EMBEDDING_PROVIDER!r}; expected 'local' or 'aicc'"
        )

    return _embedding_fn


def get_collection():
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=get_collection_name(),
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `cd backend && uv run pytest tests/test_chroma_service_provider.py tests/test_aicc_embedding.py -v`
Expected: 5 + 10 = 15 PASS.

- [ ] **Step 5: Run full backend test suite**

Run: `cd backend && uv run pytest --no-header -q`
Expected: same baseline as before (372 pass, 10 pre-existing failures). The pre-existing failures from the AICC auth migration are unrelated.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/chroma_service.py backend/tests/test_chroma_service_provider.py
git commit -m "feat(backend): chroma_service provider branch (local|aicc) + v2 collection"
```

---

## Task 5: BM25 fallback in pipeline_service — first call site

**Files:**
- Modify: `backend/app/services/pipeline_service.py:759` (`_semantic_search_for_norm`)
- Create: `backend/tests/test_pipeline_service_fallback.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_pipeline_service_fallback.py`:

```python
"""Search must fall back to BM25 when semantic embeddings (AICC) fail."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import httpx


def test_semantic_search_falls_back_to_bm25_on_aicc_5xx():
    """When query_articles raises (AICC down), _semantic_search_for_norm must
    return BM25 results instead of crashing or returning []."""
    from app.services.pipeline_service import _semantic_search_for_norm

    db = MagicMock()
    state = {
        "unique_versions": {"31/1990": [42]},  # law key -> [law_version_id]
    }

    bm25_hits = [
        {
            "article_id": 100, "article_number": "1",
            "law_number": "31", "law_year": 1990,
            "law_title": "Test", "text": "matched by BM25",
            "is_abrogated": False, "doc_type": "article",
            "annex_title": "", "date_in_force": "", "is_current": "True",
        }
    ]

    with patch(
        "app.services.pipeline_service.query_articles",
        side_effect=httpx.HTTPStatusError(
            "503", request=httpx.Request("POST", "http://x/v1/embeddings"),
            response=httpx.Response(503),
        ),
    ), patch(
        "app.services.bm25_service.search_bm25",
        return_value=bm25_hits,
    ) as mock_bm25:
        result = _semantic_search_for_norm(
            description="contract de munca",
            law_key="31/1990",
            state=state,
            db=db,
        )

    assert mock_bm25.called
    # Result should pass through BM25 hits with the same conversion the
    # function applies to ChromaDB results
    assert len(result) == 1
    assert result[0]["article_id"] == 100


def test_semantic_search_returns_empty_when_both_fail():
    from app.services.pipeline_service import _semantic_search_for_norm

    db = MagicMock()
    state = {"unique_versions": {"31/1990": [42]}}

    with patch(
        "app.services.pipeline_service.query_articles",
        side_effect=httpx.HTTPStatusError(
            "503", request=httpx.Request("POST", "http://x/v1/embeddings"),
            response=httpx.Response(503),
        ),
    ), patch(
        "app.services.bm25_service.search_bm25",
        side_effect=Exception("FTS broken"),
    ):
        result = _semantic_search_for_norm(
            description="x",
            law_key="31/1990",
            state=state,
            db=db,
        )

    assert result == []


def test_semantic_search_no_fallback_on_happy_path():
    from app.services.pipeline_service import _semantic_search_for_norm

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock(
        id=100, article_number="1",
    )
    state = {"unique_versions": {"31/1990": [42]}}

    semantic_hits = [
        {
            "article_id": 100, "article_number": "1",
            "law_number": "31", "law_year": "1990",
            "law_title": "Test", "text": "semantic match",
            "is_abrogated": False, "doc_type": "article",
            "annex_title": "", "date_in_force": "", "is_current": "True",
            "distance": 0.1,
        }
    ]

    with patch(
        "app.services.pipeline_service.query_articles",
        return_value=semantic_hits,
    ), patch(
        "app.services.bm25_service.search_bm25",
    ) as mock_bm25:
        _semantic_search_for_norm(
            description="contract",
            law_key="31/1990",
            state=state,
            db=db,
        )

    assert not mock_bm25.called, "BM25 should not be called on happy path"
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/test_pipeline_service_fallback.py -v`
Expected: FAIL — current code has no fallback; the side_effect raises and propagates out.

- [ ] **Step 3: Add fallback to `_semantic_search_for_norm`**

In `backend/app/services/pipeline_service.py`, find the function `_semantic_search_for_norm` (~line 733). REPLACE the block:

```python
    if not version_ids:
        return []

    results = query_articles(
        query_text=description,
        law_version_ids=version_ids,
        n_results=5,
    )
```

with:

```python
    if not version_ids:
        return []

    # Try semantic search first; on AICC failure (5xx, 401, network), fall back
    # to BM25 so the user still gets some results.
    try:
        results = query_articles(
            query_text=description,
            law_version_ids=version_ids,
            n_results=5,
        )
    except Exception as e:
        logger.warning(
            "[search] AICC embedding failed in _semantic_search_for_norm: %s; falling back to BM25",
            e,
        )
        try:
            from app.services.bm25_service import search_bm25
            results = search_bm25(db, description, version_ids, limit=5)
        except Exception as bm25_err:
            logger.error("[search] BM25 fallback also failed: %s", bm25_err)
            results = []
```

- [ ] **Step 4: Confirm `logger` is imported in pipeline_service.py**

Run: `grep -nE "^import logging|^logger" backend/app/services/pipeline_service.py | head -5`
Expected: a `logger = logging.getLogger(__name__)` line near the top. If absent, add `import logging` and `logger = logging.getLogger(__name__)` near the existing imports.

- [ ] **Step 5: Run tests, verify they pass**

Run: `cd backend && uv run pytest tests/test_pipeline_service_fallback.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/tests/test_pipeline_service_fallback.py
git commit -m "feat(backend): BM25 fallback in _semantic_search_for_norm when AICC fails"
```

---

## Task 6: BM25 fallback at second call site

**Files:**
- Modify: `backend/app/services/pipeline_service.py:2234` (semantic search inside the per-law tier loop)

- [ ] **Step 1: Add a test for the second call site**

Append to `backend/tests/test_pipeline_service_fallback.py`:

```python
def test_tier_search_semantic_failure_doesnt_break_loop():
    """If the per-law semantic call raises mid-loop, we should log and use
    only BM25 results for that law (BM25 was already called separately),
    not abort the whole tier."""
    # This is integration-shaped; we verify by patching query_articles to raise
    # and ensuring no exception propagates out of the search assembly path.
    # We don't try to exercise the full state machine — just verify the wrapper.
    from app.services.pipeline_service import _safe_semantic_search

    with patch(
        "app.services.pipeline_service.query_articles",
        side_effect=httpx.HTTPStatusError(
            "503", request=httpx.Request("POST", "http://x"),
            response=httpx.Response(503),
        ),
    ):
        result = _safe_semantic_search("question", [42], n_results=5)
    assert result == []
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/test_pipeline_service_fallback.py::test_tier_search_semantic_failure_doesnt_break_loop -v`
Expected: ImportError — `_safe_semantic_search` doesn't exist.

- [ ] **Step 3: Extract a helper + use it at line ~2234**

In `backend/app/services/pipeline_service.py`, ADD this helper near the other private helpers (e.g., right after `_extract_law_key`):

```python
def _safe_semantic_search(
    question: str,
    law_version_ids: list[int],
    n_results: int,
) -> list[dict]:
    """Wrap query_articles with logging on failure. Returns [] on AICC errors.

    Used in tier search (caller already has BM25 results separately, so
    returning [] here loses semantic but BM25 still contributes).
    """
    try:
        return query_articles(
            query_text=question,
            law_version_ids=law_version_ids,
            n_results=n_results,
        )
    except Exception as e:
        logger.warning(
            "[search] semantic search failed for versions=%s: %s; tier continues with BM25 only",
            law_version_ids, e,
        )
        return []
```

Then at the call site (~line 2234), REPLACE:

```python
            # Semantic search for this law
            semantic_results = query_articles(
                state["question"], law_version_ids=version_ids, n_results=per_law_limit
            )
            semantic_count += len(semantic_results)
```

with:

```python
            # Semantic search for this law (with AICC-failure tolerance)
            semantic_results = _safe_semantic_search(
                state["question"], version_ids, n_results=per_law_limit,
            )
            semantic_count += len(semantic_results)
```

Note: `query_articles` takes the query as `query_text=...` per its signature; the existing call at line 2234 passes it positionally. The helper above uses the keyword form; it accepts the same query string.

- [ ] **Step 4: Run tests, verify all pass**

Run: `cd backend && uv run pytest tests/test_pipeline_service_fallback.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `cd backend && uv run pytest --no-header -q`
Expected: pass count up by 4 from baseline. Pre-existing failure count unchanged.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/tests/test_pipeline_service_fallback.py
git commit -m "feat(backend): _safe_semantic_search wrapper for tier-level search"
```

---

## Task 7: Reindex script

**Files:**
- Create: `backend/scripts/reindex_with_aicc.py`

- [ ] **Step 1: Implement the script**

Create `backend/scripts/reindex_with_aicc.py`:

```python
"""One-shot reindex: drop and rebuild the Chroma collection used when
EMBEDDING_PROVIDER=aicc.

Forces EMBEDDING_PROVIDER=aicc in this process regardless of the actual env,
so the operator can run it before flipping the prod env var. Connects to the
production DB + AICC and rebuilds legal_articles_v2 from scratch.

Usage (from backend/):
  AICC_KEY=sk-cc-... \\
  AICC_BASE_URL=https://aicommandcenter-production-d7b1.up.railway.app/v1 \\
  EMBEDDING_MODEL_AICC=voyage-3 \\
  PYTHONPATH=. uv run python scripts/reindex_with_aicc.py

Idempotent: run again, it drops and rebuilds.
"""
from __future__ import annotations

import logging
import os
import sys

# Force aicc provider for this process before any chroma_service imports.
os.environ["EMBEDDING_PROVIDER"] = "aicc"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reindex-aicc")


def main() -> int:
    from app.database import SessionLocal
    from app.models.law import LawVersion
    from app.services.chroma_service import (
        get_chroma_client,
        get_collection_name,
        get_collection,
        index_law_version,
    )

    client = get_chroma_client()
    name = get_collection_name()
    if name == "legal_articles":
        logger.error(
            "Refusing to operate on the local-provider collection 'legal_articles'."
            " Check EMBEDDING_PROVIDER is 'aicc'."
        )
        return 2

    logger.info("Dropping existing collection if present: %s", name)
    try:
        client.delete_collection(name)
    except Exception as e:
        # Already absent — fine.
        logger.info("(no existing collection to drop: %s)", e)

    logger.info("Creating fresh collection: %s", name)
    get_collection()  # creates on first access

    db = SessionLocal()
    total = 0
    try:
        versions = db.query(LawVersion).all()
        logger.info("Re-indexing %d law versions through AICC...", len(versions))
        for i, v in enumerate(versions, start=1):
            count = index_law_version(db, v.law_id, v.id)
            total += count
            if i % 10 == 0:
                logger.info("  ...%d/%d versions, %d docs indexed so far", i, len(versions), total)
    finally:
        db.close()

    logger.info("Reindex complete: %d documents indexed into %s", total, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test the script's import path locally**

Run: `cd backend && PYTHONPATH=. uv run python -c "import scripts.reindex_with_aicc; print('ok')"`
Expected: `ok`. (We don't actually run the reindex — that hits AICC and burns tokens.)

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/reindex_with_aicc.py
git commit -m "scripts(backend): one-shot reindex through AICC voyage-3"
```

---

## Task 8: Cutover runbook

**Files:**
- Create: `docs/superpowers/runbooks/2026-04-27-aicc-embeddings-cutover.md`

- [ ] **Step 1: Write the runbook**

Create `docs/superpowers/runbooks/2026-04-27-aicc-embeddings-cutover.md`:

```markdown
# AICC Embeddings Cutover Runbook

**Date written:** 2026-04-27
**Spec:** `docs/superpowers/specs/2026-04-27-aicc-embeddings-migration-design.md`
**Plan:** `docs/superpowers/plans/2026-04-27-aicc-embeddings-migration.md`

## What this does

Switches Themis search from in-process `sentence-transformers` (MiniLM-L12-v2,
384 dims) to AICC `/v1/embeddings` proxied to Voyage `voyage-3` (1024 dims).
Drops ~600 MB resident RAM. Old collection (`legal_articles`) stays on disk
through cutover for instant rollback.

## T-1 day — verify code is shipped

1. `git log origin/main` should include the AICC embeddings PR merge commit.
2. Confirm Railway redeploy succeeded after merge.
3. Confirm `EMBEDDING_PROVIDER` is **NOT** set in Railway env (default `local`
   keeps current behavior). The PR ships the code only.

## T-0 — cutover (operator-driven, ~30 min)

### Step 1: Announce window
Post in #themis (or wherever): "Themis search briefly degraded for next 30 min while we re-index against a new embedding model. BM25 keyword fallback active during the swap."

### Step 2: Build new collection (no downtime)

From a developer machine with Railway CLI auth:

```bash
cd /path/to/themis/backend
railway run --service Themis-legal -- bash -c '
  cd /app
  EMBEDDING_PROVIDER=aicc \
  EMBEDDING_MODEL_AICC=voyage-3 \
  PYTHONPATH=. uv run python scripts/reindex_with_aicc.py
'
```

This runs the reindex script inside the prod backend container with prod env.
Expected: log lines like `Re-indexing N law versions through AICC...`,
followed by `Reindex complete: M documents indexed into legal_articles_v2`.
Walltime: 5-15 min depending on Voyage rate limits.

### Step 3: Verify v2 collection populated

Still via `railway run`:

```bash
railway run --service Themis-legal -- bash -c '
  cd /app
  PYTHONPATH=. uv run python -c "
import os
os.environ[\"EMBEDDING_PROVIDER\"] = \"aicc\"
from app.services.chroma_service import get_collection
c = get_collection()
print(\"collection:\", c.name, \"count:\", c.count())
print(\"sample:\", c.peek(2))
"
'
```

Expected: `collection: legal_articles_v2 count: ~12000` (your real article count).
Sample should show ID format `art-XXX` or `anx-XXX`. If count is 0, reindex
failed — investigate before proceeding.

### Step 4: Flip env var
On Railway dashboard for the `Themis-legal` service:
- Add variable: `EMBEDDING_PROVIDER=aicc`
- Save. Railway redeploys (~1 min).

### Step 5: Verify in prod

After redeploy completes, watch backend logs:

```bash
railway logs --service Themis-legal --lines 50
```

Look for: `Embedding provider: aicc (model=voyage-3)`. **Confirm absence
of any `Loading sentence-transformer model` line** (that means the old
path is still being hit).

Run a real search through the UI. Click into an assistant session, ask a
question that exercises retrieval, and confirm the response surfaces
relevant articles.

### Step 6: Verify RAM dropped

In Railway dashboard → `Themis-legal` → metrics. Backend RSS should drop
from ~3 GB to ~2.5 GB within 5 min of redeploy. The 600 MB that was
SentenceTransformer is gone.

### Step 7: Mark complete
Update this runbook (timestamp at the top) and post in #themis: cutover done.

## Rollback

Instant rollback: in Railway, set `EMBEDDING_PROVIDER=local` (or remove the
var entirely; default is `local`). Backend redeploys, queries hit the old
`legal_articles` collection again. Old embeddings are still on disk.

## Post-cutover cleanup (separate PR, 1-2 weeks later)

Once new path is proven stable:

1. Delete the old `legal_articles` collection from disk to recover ~30 MB:
   ```bash
   railway run --service Themis-legal -- bash -c '
     cd /app
     PYTHONPATH=. uv run python -c "
   from app.services.chroma_service import get_chroma_client
   client = get_chroma_client()
   client.delete_collection(\"legal_articles\")
   print(\"deleted\")
   "
   '
   ```
2. Remove `sentence-transformers` from `backend/pyproject.toml`. Saves ~470 MB
   in the Docker image.
3. Remove the `EMBEDDING_PROVIDER=local` branch from `chroma_service.py`.
4. Remove `EMBEDDING_MODEL` env var from Railway (used only by the local path).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/runbooks/2026-04-27-aicc-embeddings-cutover.md
git commit -m "docs: cutover runbook for AICC embeddings migration"
```

---

## Task 9: Final verification

**Files:** none

- [ ] **Step 1: Full backend test suite**

Run: `cd backend && uv run pytest --no-header -q`
Expected: all green (modulo 10 pre-existing failures from before this PR).

- [ ] **Step 2: Verify default behavior unchanged**

Run: `cd backend && uv run python -c "
from app.config import EMBEDDING_PROVIDER
import app.services.chroma_service as cs
cs._embedding_fn = None
fn = cs.get_embedding_function()
print(f'provider={EMBEDDING_PROVIDER} fn_type={type(fn).__name__}')
print(f'collection={cs.get_collection_name()}')
"`
Expected: `provider=local fn_type=SentenceTransformerEmbeddingFunction collection=legal_articles`. (No env override → default behavior preserved.)

- [ ] **Step 3: Verify aicc branch loads cleanly with the right env**

Run: `cd backend && EMBEDDING_PROVIDER=aicc AICC_KEY=fake AICC_BASE_URL=https://aicc.test/v1 uv run python -c "
import app.services.chroma_service as cs
cs._embedding_fn = None
fn = cs.get_embedding_function()
print(f'fn_type={type(fn).__name__}')
print(f'collection={cs.get_collection_name()}')
"`
Expected: `fn_type=AiccEmbeddingFunction collection=legal_articles_v2`.

- [ ] **Step 4: Boot the full app under both modes (smoke check)**

Run: `cd backend && timeout 8 uv run uvicorn app.main:app --port 8765 2>&1 | grep -iE "(Embedding provider|Application startup|error)" | head -10`
Expected: `Embedding provider: local (model=paraphrase-multilingual-MiniLM-L12-v2)` and `Application startup complete`. No errors.

Note: under `EMBEDDING_PROVIDER=aicc` the boot won't index anything new (Chroma's PersistentClient lazy-loads), but `get_embedding_function` should not be called at boot until the first search/index. That's fine — we don't smoke-boot the aicc path at this step.

- [ ] **Step 5: Push branch and open PR**

```bash
git push -u myndtrick feature/aicc-embeddings-migration
gh pr create --repo Myndtrick/themis-legal --base main \
  --head feature/aicc-embeddings-migration \
  --title "feat: migrate embeddings to AICC voyage-3 (behind feature flag)" \
  --body-file <(cat <<'EOF'
## Summary

Replace in-process sentence-transformers with AICC /v1/embeddings backed by Voyage voyage-3 (1024 dims), behind `EMBEDDING_PROVIDER` env flag (default `local` → no behavior change at merge). Cutover happens post-merge per the runbook.

- New `AiccEmbeddingFunction` (Chroma EmbeddingFunction subclass) wrapping AICC's OpenAI-compatible /v1/embeddings.
- `chroma_service.py` provider branch: `local` (legacy) or `aicc` (new). Collection name shifts to `legal_articles_v2` when aicc is active so old + new can coexist on disk.
- BM25 fallback added to both `query_articles` callers in `pipeline_service.py` — search degrades gracefully if AICC is unreachable.
- Reindex script: `backend/scripts/reindex_with_aicc.py` drops + rebuilds the v2 collection.
- Runbook: `docs/superpowers/runbooks/2026-04-27-aicc-embeddings-cutover.md`.

15 new unit tests + integration tests for fallback behavior.

Spec: `docs/superpowers/specs/2026-04-27-aicc-embeddings-migration-design.md`
Plan: `docs/superpowers/plans/2026-04-27-aicc-embeddings-migration.md`

## Cost expectations

- Themis backend RAM: ~4 GB → ~3.4 GB sustained → save ~$6/mo.
- AICC voyage-3 ongoing query cost: <$1/mo at Themis traffic.
- One-time reindex: ~$0.10.
- Net savings: ~$5/mo. Architectural cleanliness (one source of truth for AI calls) is the bigger win.

## Test plan

- [x] Backend: `uv run pytest` (full suite passes; only pre-existing 10 failures unchanged).
- [x] Default-path boot: `EMBEDDING_PROVIDER` unset → loads SentenceTransformer, collection `legal_articles`.
- [x] AICC-path resolution: `EMBEDDING_PROVIDER=aicc` → loads AiccEmbeddingFunction, collection `legal_articles_v2`.
- [ ] Post-merge cutover per runbook: reindex via `scripts/reindex_with_aicc.py`, flip env var, verify RAM drops + search returns relevant results.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)
```

- [ ] **Step 6: Done**

Confirm PR opened with link in CLI output. Hand off to operator for merge + cutover.

## Done criteria

- All backend tests pass.
- Default behavior (no env override) unchanged.
- `EMBEDDING_PROVIDER=aicc` resolves to `AiccEmbeddingFunction` + `legal_articles_v2`.
- BM25 fallback exercised by tests.
- Runbook covers reindex, flip, verify, rollback.
- PR open against main.
