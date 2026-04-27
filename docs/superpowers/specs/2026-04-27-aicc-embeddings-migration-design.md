# AICC Embeddings Migration — Design Spec

**Date:** 2026-04-27
**Status:** Approved (brainstorm), pending implementation plan
**Scope:** Replace Themis's in-process `sentence-transformers` model + Chroma `SentenceTransformerEmbeddingFunction` with calls to AICC's `/v1/embeddings` proxy backed by Voyage `voyage-3`.

## Goals

- Remove the `sentence-transformers` library + `paraphrase-multilingual-MiniLM-L12-v2` model from the Themis backend's process.
- Drop ~600 MB of resident RAM (the model weights + tokenizer state).
- Centralize all AI calls through AICC (one source of truth for billing/observability).
- Search behavior is identical from a user's perspective; quality should be equal or better (Voyage-3 multilingual is generally stronger than MiniLM-L12-v2 on retrieval tasks).

## Non-Goals

- Replacing Chroma. Chroma stays as the local vector store; only the embedding *function* changes.
- Switching vector DB providers (e.g. to a hosted service like AICC-managed pgvector). Out of scope.
- Re-architecting search to be purely BM25 or purely semantic. The hybrid stays the same; only embedding generation moves.
- Changing the public API of `query_articles` / `index_law_version` / `remove_law_articles`. Callers in `pipeline_service.py` and `leropa_service.py` are unchanged.

## Decisions Locked In

| # | Decision | Rationale |
|---|---|---|
| Q1 | Embedding model: **`voyage-3`** (1024 dims) via AICC `/v1/embeddings` | Strong multilingual quality for Romanian + EU legal text. $0.06/1M tokens — ongoing cost <$1/mo at Themis traffic. Higher quality than `voyage-3-lite` for marginal cost increase. |
| Q2 | Migration: **Hard cutover with brief search outage** during re-index | Themis is internal admin tool with ~12K articles; full re-index runs in 5-15 min. Side-by-side collection adds complexity; outage is acceptable. |
| Q3 | Fallback: **BM25 keyword search** when AICC is unreachable | BM25 already exists (`bm25_service.py`). Graceful degradation. Search returns *some* results even if AICC is down. |

**Cost expectations (honest):**
- Themis backend RAM: ~4 GB → ~3.4 GB sustained → save ~$6/mo.
- AICC `/v1/embeddings` per-token: ~$0.10 one-time re-index, ~$0.50/mo ongoing.
- Net savings: ~$5/mo. The bigger win was already captured by the Railway memory cap (~$15/mo). This refactor is primarily about architecture cleanliness.

## Architecture

```
                   ┌─────────────────────────┐
                   │ Themis backend (FastAPI)│
                   │                         │
   ┌─indexing──────┤  chroma_service.py      │──HNSW similarity──┐
   │               │   AiccEmbeddingFunction │                   │
   │               │  search_service.py      │                   │
   │               │   (BM25 fallback)       │                   │
   │               └─────────────────────────┘                   │
   │                          │                                  │
   │                          │ httpx                            │
   │                          ▼                                  ▼
   │               ┌─────────────────────────┐    ┌──────────────────────┐
   │               │   AICC /v1/embeddings   │    │ Chroma persistent vol│
   └──────────────►│   (proxies to Voyage)   │───►│ legal_articles_v2    │
                   └─────────────────────────┘    │ (1024-dim embeddings)│
                                                  └──────────────────────┘
```

### Components

#### `AiccEmbeddingFunction` — new

A custom Chroma `EmbeddingFunction` subclass that wraps AICC `/v1/embeddings`.

```python
# Pseudocode for the interface
class AiccEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key: str, base_url: str, model: str = "voyage-3"): ...
    def __call__(self, input: list[str]) -> list[list[float]]:
        """Batches inputs, POSTs to AICC, returns 1024-dim float vectors."""
```

- One `httpx.Client` per instance (reused connection pool).
- Batching: AICC accepts up to N inputs per call (Voyage limit 128). Auto-chunk if input > 128.
- Timeout: 30s per call. AICC retry policy is its own concern.
- Errors: raise on any non-200 from AICC. Caller in `query_articles` catches and falls back to BM25.

#### `chroma_service.py` — modified

- New env-driven branch in `get_embedding_function()`:
  - `EMBEDDING_PROVIDER=local` (default for backwards compat) → existing `SentenceTransformerEmbeddingFunction`.
  - `EMBEDDING_PROVIDER=aicc` → `AiccEmbeddingFunction(model=EMBEDDING_MODEL_AICC)`.
- New collection name when provider=aicc: `legal_articles_v2` (vs current `legal_articles`). Avoids dimension-mismatch crashes if both collections coexist on disk during cutover.
- `CHROMA_COLLECTION` env still drives the local path; for aicc it appends `_v2`. Keeps the migration reversible: revert env, old collection still on disk.

#### `search_service.py` — already exists (BM25)

`pipeline_service.py:query_articles` callers wrap the call in a try/except. On any AICC failure, swallow the error and call `bm25_service.search_bm25(...)` instead. Log the fallback at WARN.

### File map

#### Created
- `backend/app/services/aicc_embedding.py` — `AiccEmbeddingFunction` class
- `backend/tests/test_aicc_embedding.py` — unit tests with `httpx.MockTransport`
- `backend/scripts/reindex_with_aicc.py` — one-shot re-index script (drops the new collection, re-runs `index_all`)

#### Modified
- `backend/app/services/chroma_service.py` — provider branch in `get_embedding_function`, new collection name
- `backend/app/services/pipeline_service.py` — wrap 2 `query_articles` callers with BM25 fallback
- `backend/app/config.py` — add `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL_AICC`
- `backend/pyproject.toml` — keep `sentence-transformers` dep until cutover proven; remove in a follow-up commit
- `backend/.env` — add new env vars locally
- `docs/superpowers/runbooks/2026-04-27-aicc-embeddings-cutover.md` — runbook (created in plan)

## Configuration

### New env vars

```
EMBEDDING_PROVIDER=local            # default; switch to "aicc" at cutover
EMBEDDING_MODEL_AICC=voyage-3       # only consulted when EMBEDDING_PROVIDER=aicc
```

### Existing env vars (already set)

```
AICC_KEY=sk-cc-...                  # virtual key, used for both proxy + embeddings
AICC_BASE_URL=https://aicommandcenter-production-d7b1.up.railway.app/v1
EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2  # used only when provider=local
CHROMA_PATH=data/chroma
CHROMA_COLLECTION=legal_articles    # voyage collection becomes legal_articles_v2
```

### Collection naming rule

```python
def get_collection_name() -> str:
    base = CHROMA_COLLECTION
    return f"{base}_v2" if EMBEDDING_PROVIDER == "aicc" else base
```

Old collection (`legal_articles`) untouched on disk during cutover. Reversible by env-var flip.

## Migration & Cutover

### Pre-cutover (in PR)

1. Land code that supports both providers behind `EMBEDDING_PROVIDER` env var. Default to `local` so the running deploy is unchanged.
2. Local + CI tests verify both code paths.
3. Deploy to prod with `EMBEDDING_PROVIDER=local` (no behavioral change yet).

### Cutover steps (operator runbook)

1. **Pre-flight (T-30 min):** Announce search downtime in #themis Slack channel (or whatever channel). Window: 30 min.
2. **Build new index (no downtime):** Run `scripts/reindex_with_aicc.py` against prod DB. Connects to AICC, generates voyage-3 embeddings for every article + annex, populates `legal_articles_v2` collection. Old `legal_articles` collection stays live; existing search keeps working during this step.
3. **Verify new index:** Spot-check `legal_articles_v2` count matches expected article + annex count. Run a couple of representative queries through the script's `--smoke-query` flag to confirm relevance is reasonable.
4. **Flip env var:** Set `EMBEDDING_PROVIDER=aicc` on Railway backend. Triggers redeploy.
5. **Verify in prod:** Run a few real searches. Confirm logs show no SentenceTransformer load (the model dependency only initializes on the local path). Confirm RAM drops.
6. **Mark cutover complete.** Update runbook with timestamp.

### Rollback

- Set `EMBEDDING_PROVIDER=local` on Railway. Backend redeploys, queries hit `legal_articles` (untouched). Search instantly back to MiniLM.
- Old collection lives until manual cleanup (`scripts/cleanup_old_chroma_collection.py`).

### Post-cutover cleanup (separate PR, ~1 week later)

- Delete `legal_articles` Chroma collection from disk to recover ~30 MB.
- Remove `sentence-transformers` from `pyproject.toml`. Saves ~470 MB from the Docker image.
- Remove `EMBEDDING_PROVIDER=local` branch from `chroma_service.py` (dead code).

## Error Handling / Fallback

| Failure | Handler | User experience |
|---|---|---|
| AICC `/v1/embeddings` returns 5xx | `query_articles` catches, logs `[search] AICC embedding failed, falling back to BM25`, returns BM25 results | User gets keyword-matched results instead of semantic. Slightly less relevant but works. |
| AICC `/v1/embeddings` returns 401 (bad virtual key) | Same — fallback to BM25, but log at ERROR | Same as above; ops alert on repeated 401s |
| AICC `/v1/embeddings` returns 429 (rate limit) | Same — fallback to BM25, log at WARN | Same as above; rare at Themis scale |
| AICC unreachable (network/DNS) | httpx.RequestError caught, fallback to BM25 | Same |
| Voyage returns valid response but mismatched dimensions | Log at ERROR, raise — Chroma upsert/query crashes are unrecoverable | Search broken; ops investigates immediately |
| Indexing fails mid-batch (during `index_law_version`) | Existing batch error path; partial indexing is logged. Caller (leropa import) decides retry policy | Existing behavior unchanged |

**Fallback scope:** Only `query_articles` (search-time) falls back. `index_law_version` (write-time) does NOT fall back — if AICC is down during a law import, the import fails loudly and the caller decides whether to retry. Indexing is rare and tolerates retries; search is constant and must always return *something*.

## Testing Strategy

### Backend unit tests

`tests/test_aicc_embedding.py`:
- happy path: AICC returns 1024-dim vectors → `AiccEmbeddingFunction` returns same shape
- batching: input > 128 → multiple AICC calls, results concatenated in input order
- empty input list → returns empty list, no AICC call
- AICC 5xx → raises (caller decides fallback)
- AICC 401 → raises (caller decides fallback)
- AICC network error → raises (caller decides fallback)
- model name override: `EMBEDDING_MODEL_AICC=voyage-3-lite` is forwarded in request body

`tests/test_chroma_service_provider_branch.py`:
- `EMBEDDING_PROVIDER=local` → returns `SentenceTransformerEmbeddingFunction`, collection name `legal_articles`
- `EMBEDDING_PROVIDER=aicc` → returns `AiccEmbeddingFunction`, collection name `legal_articles_v2`

`tests/test_pipeline_service_fallback.py`:
- patch `query_articles` to raise → caller falls back to BM25, returns BM25 results
- BM25 also fails → return empty, log error
- normal path → semantic results returned, no BM25 call

### Out of scope for tests

- Real AICC roundtrip (verified manually during cutover smoke check).
- Real Voyage embedding quality on Romanian legal text (manual eval in step 3 of cutover runbook).

## Implementation Notes

- **One-shot reindex script timing:** for ~12K articles × ~500 tokens each = ~6M tokens, voyage-3 at $0.06/1M = $0.36 one-time. AICC's rate limit on Voyage may bottleneck total time; expect 10-15 min walltime.
- **HTTP client lifecycle:** `AiccEmbeddingFunction` holds an `httpx.Client`. Module-level singleton in `aicc_embedding.py`, lazily created. Closed on FastAPI lifespan shutdown.
- **No process-level model warmup:** `voyage-3` lives in AICC's process. Themis no longer warms up an embedding model at boot. Backend startup gets ~5-10 sec faster.
- **Volume size impact:** 384-dim → 1024-dim means raw embedding bytes grow ~2.7x. For 12K articles: ~18 MB → ~50 MB. Plus HNSW index overhead. Net: maybe +50 MB on a 17.5 GB volume. Negligible.
- **HNSW recall after model swap:** The HNSW parameter `hnsw:space=cosine` stays unchanged. New embeddings live in the new collection with the same parameters. No tuning needed.

## Done Criteria

- All backend tests pass.
- Code paths under both `EMBEDDING_PROVIDER=local` and `EMBEDDING_PROVIDER=aicc` exercise without errors.
- After cutover: `[aicc-auth]`-style log line `Using AICC embedding provider (model=voyage-3)` appears at startup; no `SentenceTransformer` model load in logs; Themis backend RAM drops by ~600 MB.
- Search functional in prod (representative legal queries return relevant articles).
- BM25 fallback proven (turn off AICC virtual key in dev, run a search, confirm BM25 results returned + warn log).
- Cost: $0/no spike on AICC dashboard during steady-state queries (~$1/mo expected).
