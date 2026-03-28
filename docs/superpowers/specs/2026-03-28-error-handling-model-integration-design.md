# Themis — Error Handling, Model Integration & Test Plan

**Date:** 2026-03-28
**Status:** Draft
**Scope:** Import progress tracking, error handling, multi-provider model support, model comparison, full test suite

---

## 1. Problem Statement

Themis currently has three categories of issues:

1. **No import visibility** — law imports block for up to 10 minutes with no progress indication. Users don't know if the import is working or stuck.
2. **Poor error messages** — raw SQL errors and JSON blobs are shown to users (e.g. `sqlite3.OperationalError: database is locked` with full SQL statement). The Constitution import shows "This suggestion cannot be auto-imported (no law number)" without explaining what that means.
3. **Hardcoded single-provider models** — two Claude models are hardcoded in `config.py`. No way to configure which model does what, no support for Mistral or OpenAI, no way to compare model quality.

---

## 2. Import Progress Tracking via SSE

### 2.1 New Endpoint

```
POST /api/laws/import-suggestion/{mapping_id}/stream
Body: {"import_history": true, "category_id": 5}
```

Uses POST (not GET) because this endpoint mutates state. Streams Server-Sent Events using `sse-starlette` (already a dependency). This matches the existing POST-based SSE pattern used by the chat assistant in `use-event-source.ts`.

### 2.2 Event Types

```
event: progress
data: {"phase": "metadata", "message": "Fetching law metadata from legislatie.just.ro"}

event: progress
data: {"phase": "version", "current": 3, "total": 9, "message": "Importing version 172094 (2015-10-17)"}

event: progress
data: {"phase": "indexing", "message": "Building search index (147 articles)"}

event: complete
data: {"law_id": 5, "title": "Legea 506/2004", "versions_imported": 9, "articles_indexed": 147}

event: error
data: {"code": "no_law_number", "message": "Constituția României cannot be auto-imported — it has no standard law number"}
```

### 2.3 Backend Changes

- `leropa_service.import_law()` accepts an optional `on_progress(event: dict)` callback.
- The callback is invoked at each phase: metadata fetch, each version import, indexing.
- **Threading strategy:** `import_law()` is synchronous and blocking. The SSE endpoint runs it in a thread via `asyncio.to_thread()`, using an `asyncio.Queue` to bridge progress callbacks from the worker thread to the async SSE generator. The callback puts events on the queue; the generator awaits `queue.get()`.
- **Background versions:** When `import_history=True`, version importing is currently split between inline (initial version) and background (`import_remaining_versions` via APScheduler). For SSE tracking, all versions are imported inline within the SSE-tracked flow — no background job. This gives the user full progress visibility. The background job pattern is kept for scheduled daily update checks only.
- **Client disconnect:** If the client disconnects mid-import, the import continues to completion (data integrity). Progress events are simply discarded. The SSE generator catches `asyncio.CancelledError` and lets the thread finish.
- The existing REST endpoint (`POST /api/laws/import-suggestion`) continues to work (no callback).

### 2.4 Frontend Changes

- `library-page.tsx`: use the existing `consumeSSEStream` utility (fetch + ReadableStream pattern from `use-event-source.ts`) for the POST-based SSE endpoint.
- Show a progress indicator inside the pending import card:
  - Phase label (e.g. "Fetching metadata", "Importing versions", "Building index")
  - Version counter (e.g. "3 / 9 versions")
  - Progress bar based on `current / total`
- On `complete` event: refresh library, remove from pending.
- On `error` event: show the human-readable message.

---

## 3. Error Handling Improvements

### 3.1 Structured Error Codes

New file: `backend/app/errors.py`

Maps known exceptions to structured responses:

| Exception / Condition | Code | HTTP Status | User Message |
|---|---|---|---|
| `sqlite3.OperationalError("database is locked")` | `db_locked` | 503 | "Another import is in progress. Please wait a moment and try again." |
| Missing law number (Constitution, etc.) | `no_law_number` | 400 | "This document cannot be auto-imported because it has no standard law number (e.g. Constituția)." |
| `legislatie.just.ro` unreachable | `search_failed` | 502 | "Could not reach the legislation database. Please try again later." |
| Duplicate law | `duplicate` | 409 | "This law has already been imported." |
| Generic import failure | `import_failed` | 500 | "Import failed: {brief context}. Please try again." |
| Unhandled exception | `internal` | 500 | "Something went wrong. Please try again." |

All error responses follow the shape: `{"code": "<string>", "message": "<string>"}`.

### 3.2 SQLite Retry Decorator

Extracted from existing retry logic in `import_remaining_versions()`:

```python
@with_sqlite_retry(max_retries=3)
def some_db_write_operation(db, ...):
    ...
```

- Catches `sqlite3.OperationalError` where `"database is locked"` is in the message.
- Exponential backoff: 1s, 2s, 4s.
- Logs each retry with warning level.
- After exhausting retries, raises a structured `DbLockedError`.

Applied to: `import_law()`, import-suggestion endpoint DB writes, category assignment.

### 3.3 Global Exception Handler

In `main.py`, register a FastAPI exception handler:

- Catches unhandled `sqlite3.OperationalError` → 503 with `db_locked` code.
- Catches unhandled `Exception` → 500 with `internal` code, logs the traceback server-side.
- Never exposes raw SQL, stack traces, or internal details to the client.

### 3.4 Frontend Error Display

- Parse `{code, message}` from backend responses.
- Show the `message` field only — never raw JSON or SQL.
- Style by severity:
  - Yellow/warning for retryable errors (`db_locked`, `search_failed`)
  - Red/error for permanent errors (`no_law_number`, `duplicate`, `import_failed`)
- Constitution-type errors: clear message + dismiss button.

---

## 4. Provider Abstraction & Model Configuration

### 4.1 Supported Models (13 total)

| Provider | Model ID | Label | Cost | Capabilities |
|---|---|---|---|---|
| Anthropic | `claude-haiku-4-5` | Claude Haiku 4.5 | $ | chat |
| Anthropic | `claude-sonnet-4-6` | Claude Sonnet 4.6 | $$ | chat |
| Anthropic | `claude-opus-4-6` | Claude Opus 4.6 | $$$ | chat |
| Mistral | `mistral-small` | Mistral Small | $ | chat |
| Mistral | `mistral-large` | Mistral Large | $$ | chat |
| Mistral | `mistral-ocr` | Mistral OCR | $ | ocr |
| OpenAI | `gpt-4o` | GPT-4o | $$ | chat |
| OpenAI | `gpt-4o-mini` | GPT-4o Mini | $ | chat |
| OpenAI | `gpt-4.1` | GPT-4.1 | $$ | chat |
| OpenAI | `gpt-4.1-mini` | GPT-4.1 Mini | $ | chat |
| OpenAI | `gpt-4.1-nano` | GPT-4.1 Nano | $ | chat |
| OpenAI | `o3` | o3 | $$$ | chat, reasoning |
| OpenAI | `o4-mini` | o4 Mini | $$ | chat, reasoning |

### 4.2 Database Tables

**`models` table:**
```sql
CREATE TABLE models (
    id TEXT PRIMARY KEY,          -- e.g. "claude-sonnet-4-6"
    provider TEXT NOT NULL,       -- "anthropic" | "mistral" | "openai"
    api_model_id TEXT NOT NULL,   -- actual API identifier
    label TEXT NOT NULL,          -- display name
    cost_tier TEXT NOT NULL,      -- "$", "$$", "$$$"
    capabilities TEXT NOT NULL,   -- JSON array: ["chat"], ["ocr"], ["chat", "reasoning"]
    enabled INTEGER DEFAULT 1
);
```

**`model_assignments` table:**
```sql
CREATE TABLE model_assignments (
    task TEXT PRIMARY KEY,        -- e.g. "issue_classification"
    model_id TEXT NOT NULL REFERENCES models(id)
);
```

Pipeline tasks: `issue_classification`, `law_mapping`, `article_selection`, `answer_generation`, `ocr`, `diff_summary`, `fast_general`.

Default assignments:
- Fast tasks (issue_classification, law_mapping, fast_general) → `claude-haiku-4-5`
- Reasoning tasks (article_selection, answer_generation, diff_summary) → `claude-sonnet-4-6`
- OCR → `mistral-ocr`

### 4.3 Provider Abstraction

New module: `backend/app/providers/`

```
providers/
    __init__.py        # get_provider(model_id) factory
    base.py            # abstract LLMProvider class
    anthropic.py       # wraps existing claude_service
    mistral.py         # Mistral API client
    openai.py          # OpenAI API client
```

**`LLMProvider` interface:**
```python
class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages, system=None, max_tokens=4096, temperature=0.0) -> LLMResponse: ...

    @abstractmethod
    def stream(self, messages, system=None, max_tokens=4096, temperature=0.0) -> Iterator[str]: ...

    def ocr(self, document_bytes, mime_type) -> str:
        raise NotImplementedError("This model does not support OCR")
```

**Note:** The interface is synchronous to match the existing pipeline architecture. The current pipeline runs as synchronous generators yielding SSE events (`call_claude` and `stream_claude` are both sync). Each provider handles the `system` parameter according to its API convention: Anthropic uses a separate `system` field with cache control; OpenAI/Mistral embed it as the first message with `role: "system"`.

**`LLMResponse`:**
```python
@dataclass
class LLMResponse:
    content: str
    usage: TokenUsage  # input_tokens, output_tokens
    model_id: str
```

### 4.4 Pipeline Integration

- `pipeline_service.py` reads `model_assignments` table to determine which model to use per step.
- Each step calls `get_provider(model_id)` instead of directly using `claude_service`.
- Pipeline methods accept an optional `model_overrides: dict[str, str]` parameter (task → model_id) for comparison mode, allowing per-step model swapping.

### 4.5 API Key Storage

- API keys are stored in a `provider_keys` table: `provider TEXT PRIMARY KEY, encrypted_key TEXT`.
- Keys are encrypted at rest using Fernet symmetric encryption (key derived from a server secret in `.env`).
- The `GET /api/settings/provider-keys` endpoint returns masked keys only (e.g. `sk-...7f3a`).
- The existing `ANTHROPIC_API_KEY` env var is the fallback when no DB key is configured for Anthropic.
- New env vars: `MISTRAL_API_KEY`, `OPENAI_API_KEY` (optional fallbacks).

### 4.6 Capability Validation

The `capabilities` column stores a JSON array. Valid values are enforced via an enum: `"chat"`, `"ocr"`, `"reasoning"`. Validation happens in the Pydantic schema on insert/update. Assigning a model to a task that requires a capability it lacks returns 422.

### 4.7 Settings API

```
GET    /api/settings/models              — list all models with enabled status
PUT    /api/settings/models/{id}         — toggle enabled, update config
GET    /api/settings/model-assignments   — current task-to-model mapping
PUT    /api/settings/model-assignments   — update assignments
```

### 4.8 Settings UI

New section under the existing Settings page:

- **Models table:** all 13 models with provider icon, label, cost tier, capabilities badges, enable/disable toggle.
- **Task assignments:** one dropdown per pipeline task, filtered to models with the required capability.
- **API keys:** per-provider input fields (Anthropic, Mistral, OpenAI). Shows masked keys; full key only accepted on write.

---

## 5. Model Comparison Feature

### 5.1 Compare API

```
POST /api/assistant/compare
```

**Request:**
```json
{
    "question": "Ce spune legea despre protecția datelor?",
    "models": ["claude-sonnet-4-6", "gpt-4.1", "mistral-large"],
    "mode": "full"
}
```

**`mode`:**
- `"full"` — runs the complete 7-step pipeline per model, returns final answers.
- `"pipeline_steps"` — returns per-step outputs for each model (for fine-tuning assignments).

**Response:**
```json
{
    "question": "Ce spune legea despre protecția datelor?",
    "results": [
        {
            "model_id": "claude-sonnet-4-6",
            "model_label": "Claude Sonnet 4.6",
            "status": "success",
            "duration_ms": 4200,
            "usage": {"input_tokens": 3200, "output_tokens": 890},
            "cost_usd": 0.018,
            "answer": "Conform Legii nr. 506/2004...",
            "citations": [
                {"law": "506/2004", "article": "Art. 5", "version": "2022-07-10"}
            ],
            "pipeline_steps": {
                "issue_classification": {"result": "...", "duration_ms": 320},
                "law_mapping": {"result": "...", "duration_ms": 50},
                "article_selection": {"result": "...", "duration_ms": 1100},
                "answer_generation": {"result": "...", "duration_ms": 2700}
            }
        },
        {
            "model_id": "gpt-4.1",
            "model_label": "GPT-4.1",
            "status": "error",
            "duration_ms": 1200,
            "error": "API rate limit exceeded"
        }
    ]
}
```

### 5.2 Backend Execution

- **Optimization:** Steps 1-5 of the pipeline (issue classification, law mapping, version selection, hybrid retrieval, article expansion) are run once since they produce identical results regardless of the answer-generation model. Only steps 6-7 (article selection + answer generation) fan out across selected models in parallel.
- Parallel execution via `asyncio.gather()` with `return_exceptions=True`, each model running steps 6-7 in its own thread.
- Each run gets its own provider via `get_provider(model_id)`.
- Pipeline accepts `model_overrides: dict[str, str]` (task → model_id) to swap models per step.
- **Dry run:** No database writes during comparison. Pipeline logger calls (`create_run`, `log_step`, `log_api_call`, `complete_run`) are suppressed via a `dry_run=True` flag threaded through the pipeline.
- **Cost controls:** Maximum 5 models per comparison request. An optional `max_cost_usd` parameter aborts remaining models if running total exceeds the limit. Estimated cost preview available via `GET /api/assistant/compare/estimate?models=x,y,z`.
- Cost calculated via `services/pricing.py` using per-model token rates.

### 5.3 Migration Strategy

New tables (`models`, `model_assignments`, `provider_keys`) are created via `Base.metadata.create_all()` (consistent with existing approach). Seed data is inserted in `lifespan()` alongside existing `seed_defaults()` and `seed_categories()` calls. A new `seed_models()` function populates the 13 models and default assignments.

### 5.4 Pricing Module

New file: `backend/app/services/pricing.py`

- Per-model pricing: input rate + output rate per 1M tokens.
- Page-based pricing for Mistral OCR.
- `calculate_cost(model_id: str, usage: TokenUsage) -> float` function.

### 5.5 Frontend — Compare Tab

New tab in the Legal Assistant page:

- **Input:** textarea for the legal question.
- **Model selection:** toggle buttons for each enabled model. Select 2-5 for comparison.
- **Mode toggle:** "Full answer" vs "Pipeline steps".
- **Results grid:** responsive columns (2-5) based on selected model count.
- **Model cards** (color-coded per model, same palette as Exodus Live):
  - Header: model name, cost tier badge, execution time.
  - Body: full answer with citations (in "full" mode).
  - Footer: token usage (input/output), estimated cost in USD.
  - Expandable "Pipeline steps" section: per-step output and timing.
- **Error handling:** if a model fails, its card shows the error message while others show results.
- **Loading state:** skeleton cards during comparison.

**Color palette per provider:**
- Claude: Purple shades (Haiku light, Sonnet medium, Opus dark)
- Mistral: Orange/Amber shades
- OpenAI: Green/Teal shades

---

## 6. Test Plan

### 6.1 Backend Unit Tests

**`tests/test_providers.py`**
- Each provider correctly formats API calls
- `get_provider()` factory returns correct provider per model
- Provider handles API errors (rate limits, auth failures, timeouts)
- OCR method raises `NotImplementedError` on non-OCR models

**`tests/test_errors.py`**
- SQLite locked → `db_locked` response with 503
- No law number → `no_law_number` with 400
- Search failure → `search_failed` with 502
- Duplicate → `duplicate` with 409
- Unknown error → `internal` with 500, no raw traceback

**`tests/test_sqlite_retry.py`**
- Success on first attempt → no retry
- Fail once then succeed → one retry with correct backoff
- Fail 3 times → raises after exhausting retries
- Non-lock OperationalError → immediate raise, no retry

**`tests/test_model_assignments.py`**
- Default assignments seeded correctly on startup
- Pipeline reads assignment from DB
- Changing assignment changes which model is used
- Assigning incapable model → validation error

**`tests/test_pricing.py`**
- Token-based cost calculation per provider
- Page-based cost for Mistral OCR
- Zero usage → zero cost

### 6.2 Backend Integration Tests (HTTP)

**`tests/test_import_endpoints.py`**
- SSE stream returns progress events in correct order (metadata → versions → indexing → complete)
- Duplicate import → error event with `duplicate` code
- No law number → error event with `no_law_number` code
- DB lock with retries exhausted → error event with `db_locked` code

**`tests/test_settings_endpoints.py`**
- `GET /api/settings/models` returns all 13 models
- Toggle model enabled/disabled persists
- Update task assignment persists
- Assign model without required capability → 422

**`tests/test_compare_endpoint.py`**
- Full mode returns answer per model
- Pipeline steps mode returns per-step outputs
- One model fails, others succeed → partial results with error on failed model
- No models selected → 422
- Cost and usage included per model result

### 6.3 Frontend Tests

**`frontend/__tests__/api.test.ts`**
- `apiFetch` throws structured error with code/message on non-200
- Network failure → "Cannot reach backend" error
- Successful response parsed correctly

**`frontend/__tests__/import-progress.test.ts`**
- SSE progress events (via fetch + ReadableStream) update UI (phase label, version counter)
- Progress bar reflects `current / total`
- Complete event clears pending state and refreshes library
- Error event shows human-readable message

**`frontend/__tests__/model-compare.test.ts`**
- Toggle model selection on/off
- Submit comparison → renders result cards per model
- Expand/collapse pipeline steps
- Failed model shows error in its card
- Grid columns scale with model count

**`frontend/__tests__/error-display.test.ts`**
- `db_locked` → yellow warning styling
- `no_law_number` → red error styling with clear message
- Unknown error code → generic fallback message
- No raw JSON or SQL ever visible

### 6.4 Test Infrastructure

- **Backend:** pytest + `httpx.AsyncClient` (TestClient) for endpoint tests, in-memory SQLite, mocked provider API calls via `unittest.mock`
- **Frontend:** Vitest + React Testing Library (aligned with Next.js 16), MSW (Mock Service Worker) for API mocking including SSE streams (fetch + ReadableStream mocking)

---

## 7. Files Changed / Created

### New Files
```
backend/app/errors.py                    — structured error codes + mapping
backend/app/providers/__init__.py        — get_provider() factory
backend/app/providers/base.py            — abstract LLMProvider
backend/app/providers/anthropic.py       — Anthropic provider
backend/app/providers/mistral.py         — Mistral provider
backend/app/providers/openai.py          — OpenAI provider
backend/app/services/pricing.py          — cost calculation
backend/app/models/model_config.py       — Model + ModelAssignment SQLAlchemy models
backend/app/routers/settings_models.py   — model settings endpoints
backend/app/schemas/model_config.py      — Pydantic schemas for model settings
backend/tests/test_providers.py
backend/tests/test_errors.py
backend/tests/test_sqlite_retry.py
backend/tests/test_model_assignments.py
backend/tests/test_pricing.py
backend/tests/test_import_endpoints.py
backend/tests/test_settings_endpoints.py
backend/tests/test_compare_endpoint.py
frontend/__tests__/api.test.ts
frontend/__tests__/import-progress.test.ts
frontend/__tests__/model-compare.test.ts
frontend/__tests__/error-display.test.ts
frontend/src/app/assistant/compare-tab.tsx
frontend/src/app/settings/models/        — model settings UI components
```

### Modified Files
```
backend/app/main.py                      — global exception handler, new routers
backend/app/config.py                    — provider API keys from env/db
backend/app/database.py                  — new tables
backend/app/routers/laws.py              — SSE import endpoint, retry decorator
backend/app/routers/assistant.py         — compare endpoint
backend/app/services/leropa_service.py   — on_progress callback in import_law()
backend/app/services/pipeline_service.py — model_override, read assignments from DB
backend/app/services/claude_service.py   — refactored into anthropic provider
backend/pyproject.toml                   — mistralai, openai dependencies
frontend/src/app/laws/library-page.tsx   — SSE import, structured error display
frontend/src/app/laws/search-import-form.tsx — structured error display
frontend/src/lib/api.ts                  — parse structured errors
frontend/src/app/assistant/page.tsx      — compare tab
frontend/src/app/settings/page.tsx       — model settings section
frontend/package.json                    — vitest, testing-library, msw
```
