# Version Currency Verification (Step 2.5b)

## Problem

The pipeline currently treats the latest version stored in the local database as the latest version that exists. This is a silent, unverifiable assumption that can produce confidently wrong legal answers.

Consider: a user asks "what is the minimum share capital for an SRL?" The pipeline finds Legea 31/1990 with `date_in_force = 2024-12-06` in the DB, selects it, retrieves articles, and generates an answer. If the legislature amended this law in 2025 and the DB was never updated, the answer is wrong — and nothing in the pipeline flags this.

**Three distinct concepts are currently collapsed into one:**

| Concept | Definition | Source of truth |
|---|---|---|
| **DB version** | Latest version imported into local library | `LawVersion` table |
| **Official version** | Latest version published by the legislature | legislatie.just.ro |
| **Applicable version** | Version that legally governs the question | Temporal analysis + legal rules |

The pipeline currently equates DB version = official version = applicable version. This is only correct when the DB is perfectly up to date, which cannot be assumed.

### Why this matters for a legal product

- A missing law produces a visible "I can't answer" — a stale version produces a plausible but wrong answer
- Legal professionals relying on the tool may not independently verify version currency
- The tool's value proposition depends on correctness; silent staleness undermines trust
- A wrong answer based on outdated law is worse than no answer at all

## Solution

Add a **Version Currency Check** between the existing Step 2 (Law Mapping / Availability) and Step 2.5 (Early Relevance Gate). For each law identified as relevant, the pipeline queries legislatie.just.ro to determine whether the local DB has the latest officially published version. If not, the pipeline flags the discrepancy and can pause for import — using the same pause mechanism already in place for missing laws.

## Design

### Overview

```
Existing Step 2:  Law Mapping (check_laws_in_db)
                      ↓
NEW Step 2a:      Version Currency Check        ← this spec
                      ↓
Existing Step 2.5: Early Relevance Gate (pause if missing/stale)
                      ↓
Existing Step 3:   Version Selection
```

### Step 2a: Version Currency Check

**File:** `backend/app/services/version_currency.py` (new)

**Called from:** `backend/app/services/pipeline_service.py`, after `_step2_law_mapping` and before `_step2_5_early_relevance_gate`

**Applies to:** All laws in `candidate_laws` that have `availability = "available"` (laws already flagged as `"missing"` are handled by the existing gate)

**Skipped when:**
- The question contains an explicit past date (user is asking about historical law — the DB version may be intentionally historical)
- `date_type == "explicit"` and `primary_date < today` → skip currency check, the user wants a past version

#### Algorithm

```python
def check_version_currency(candidate_laws: list, db: Session, today: str) -> list:
    """
    For each available law, check if legislatie.just.ro has a newer version
    than what's in the local DB. Returns enriched candidate_laws with
    currency_status field.
    """
    for law in candidate_laws:
        if law["availability"] != "available":
            # Already flagged as missing/wrong_version — skip
            law["currency_status"] = "not_checked"
            continue

        if not law.get("db_law_id"):
            law["currency_status"] = "not_checked"
            continue

        # 1. Get current version from DB
        current_version = get_current_db_version(db, law["db_law_id"])
        if not current_version:
            law["currency_status"] = "no_current_version"
            continue

        # 2. Fetch fresh metadata from legislatie.just.ro
        try:
            official_latest = fetch_latest_version_metadata(current_version.ver_id)
        except SourceUnavailableError:
            law["currency_status"] = "source_unavailable"
            law["currency_note"] = "Could not reach legislatie.just.ro to verify version currency"
            continue

        # 3. Compare
        if official_latest is None:
            # No newer version found — DB is current
            law["currency_status"] = "current"
        else:
            law["currency_status"] = "stale"
            law["official_latest_ver_id"] = official_latest["ver_id"]
            law["official_latest_date"] = official_latest["date"]
            law["db_latest_date"] = str(current_version.date_in_force)

    return candidate_laws
```

#### `fetch_latest_version_metadata(ver_id)` — lightweight check

This function determines whether a newer version exists **without importing anything**. It reuses the existing infrastructure in `fetcher.py` and `update_checker.py`.

```python
def fetch_latest_version_metadata(ver_id: str) -> dict | None:
    """
    Fetch the document page from legislatie.just.ro (bypass cache),
    extract the history list, and check if there are versions newer
    than the one we have.

    Returns:
        None if no newer version exists.
        {"ver_id": str, "date": str} if a newer version is found.
    """
    result = fetch_document(ver_id, use_cache=False)
    doc = result["document"]

    # Check next_ver pointer (direct successor)
    if doc.get("next_ver"):
        return {"ver_id": doc["next_ver"], "date": None}

    # Check history list for versions newer than ours
    history = doc.get("history", [])
    if not history:
        return None

    our_date = doc.get("date_in_force") or _parse_doc_date(doc)

    # History is ordered newest-first by legislatie.just.ro
    # Cross-reference newest history entry to discover even newer versions
    newest_entry = history[0]
    if newest_entry["ver_id"] != ver_id:
        # There's a version in the history we don't have
        return {"ver_id": newest_entry["ver_id"], "date": newest_entry.get("date")}

    # Also cross-reference from the newest history entry's own page
    # (same pattern used in leropa_service._fetch_law_metadata)
    try:
        cross_result = fetch_document(newest_entry["ver_id"], use_cache=False)
        cross_history = cross_result["document"].get("history", [])
        for entry in cross_history:
            if entry["ver_id"] != ver_id and entry["ver_id"] != newest_entry["ver_id"]:
                entry_date = entry.get("date")
                if entry_date and our_date and entry_date > our_date:
                    return {"ver_id": entry["ver_id"], "date": entry_date}
    except Exception:
        pass  # Cross-reference is best-effort

    return None
```

**Performance note:** This makes 1-2 HTTP requests per law (not per version). For a typical question involving 1-3 laws, this adds 2-6 seconds. This is acceptable for a legal correctness guarantee. See Performance section for optimization strategies.

### Integration with Early Relevance Gate (Step 2.5)

The existing `_step2_5_early_relevance_gate` already pauses when PRIMARY laws have `availability in ("missing", "wrong_version")`. Extend it to also pause on `currency_status == "stale"`.

**Modified pause logic:**

```python
needs_pause = any(
    law.get("availability") in ("missing", "wrong_version")
    or law.get("currency_status") == "stale"
    for law in primary_laws
)
```

**Pause event payload — new fields per law:**

```python
{
    # ... existing fields ...
    "currency_status": "current" | "stale" | "source_unavailable" | "not_checked",
    "official_latest_date": "2025-09-15",  # if stale
    "db_latest_date": "2024-12-06",        # if stale
    "official_latest_ver_id": "289123",    # if stale, for import
}
```

**Pause message (Romanian):**

```
"Am verificat versiunile legilor aplicabile. Legea {law_number}/{law_year} are o versiune
mai nouă pe legislatie.just.ro (din {official_latest_date}) față de cea din biblioteca
dumneavoastră (din {db_latest_date}). Doriți să actualizăm?"
```

### User decisions on pause

The import-prompt UI already supports "Import and continue" and "Continue without". For stale versions, the same options apply:

| Decision | Behavior |
|---|---|
| **Import** | Import the newer version from legislatie.just.ro (reuse existing `import_law_smart` flow), rebuild FTS index, re-run from Step 2 |
| **Continue anyway** | Proceed with stale version, but flag in reasoning and cap confidence |

When the user chooses "Continue anyway" with a stale version:

```python
# In resume_pipeline, after user decides to skip import:
if decision == "skip" and law.get("currency_status") == "stale":
    state["flags"].append(
        f"Legea {law_key}: using version from {law['db_latest_date']} — "
        f"a newer version ({law['official_latest_date']}) exists but was not imported"
    )
    state["stale_versions"] = state.get("stale_versions", [])
    state["stale_versions"].append(law_key)
```

### Impact on confidence scoring

**File:** `backend/app/services/pipeline_service.py` (confidence assessment section)

```python
# Existing confidence logic + new rules:

# Rule: Stale version used → cap at MEDIUM
if state.get("stale_versions"):
    confidence = min(confidence, "MEDIUM")
    confidence_flags.append(
        "Version currency: answer based on potentially outdated law version"
    )

# Rule: Source unreachable → flag uncertainty but don't cap
if any(law.get("currency_status") == "source_unavailable" for law in candidate_laws):
    confidence_flags.append(
        "Version currency: could not verify against official source"
    )
```

### Impact on answer generation (Step 7)

**File:** `backend/prompts/LA-S7-answer-qa.txt`

Add to the prompt context when stale versions are in play:

```
VERSIUNI POTENȚIAL DEPĂȘITE:
{{#stale_versions}}
- Legea {{law_number}}/{{law_year}}: biblioteca conține versiunea din {{db_latest_date}},
  dar pe legislatie.just.ro există o versiune din {{official_latest_date}}.
  Răspunsul se bazează pe versiunea din bibliotecă și poate fi incomplet sau incorect.
{{/stale_versions}}
```

The answer generator must include a disclaimer when stale versions are used:

> **Notă:** Acest răspuns se bazează pe versiunea din {db_latest_date} a Legii {law_number}/{law_year}. O versiune mai recentă (din {official_latest_date}) este disponibilă pe legislatie.just.ro dar nu a fost importată în bibliotecă. Recomandăm verificarea cu versiunea actualizată.

### Handling `source_unavailable`

When legislatie.just.ro cannot be reached (timeout, DNS failure, HTTP error):

1. **Do not block the pipeline** — the user asked a question and deserves an answer
2. **Flag the uncertainty** in `version_notes` and `flags`
3. **Do not cap confidence** solely for this — the DB version may well be current
4. **Show in reasoning panel:** "Version currency: UNVERIFIED — could not reach legislatie.just.ro"
5. **Retry policy:** Single attempt with 10-second timeout. No retries during pipeline execution.

### Frontend changes

**File:** `frontend/src/app/assistant/import-prompt.tsx`

Extend the import prompt to distinguish between three states per law:

| Status | Icon | Label | Action |
|---|---|---|---|
| `missing` | :x: | Lipsește din bibliotecă | Import |
| `wrong_version` | :warning: | Versiune incorectă | Import version |
| `stale` | :arrows_counterclockwise: | Versiune mai nouă disponibilă (din {date}) | Update |
| `current` | :white_check_mark: | Versiune actuală | — |
| `source_unavailable` | :grey_question: | Nu s-a putut verifica | — |

**File:** `frontend/src/app/assistant/reasoning-panel.tsx` (or equivalent)

Add a "Version Currency" row to the reasoning panel:

```
Versiuni Verificate
  ✅ 31/1990: versiunea din 2025-09-15 (actuală)
  🔄 85/2014: versiunea din 2024-12-06 (disponibilă versiune din 2025-03-01) — neactualizată
  ❓ 287/2009: nu s-a putut verifica
```

## Performance

### Latency budget

The currency check adds 1-2 HTTP requests per law (fetch document page + optional cross-reference). With legislatie.just.ro typical response times of 1-3 seconds:

- 1 law: +2-6 seconds
- 3 laws: +6-18 seconds (sequential) or +2-6 seconds (parallel)

### Optimization: parallel requests

Check all laws concurrently using `asyncio.gather` or `concurrent.futures.ThreadPoolExecutor`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def check_version_currency(candidate_laws, db, today):
    laws_to_check = [l for l in candidate_laws if l["availability"] == "available" and l.get("db_law_id")]

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_check_single_law, law, db): law
            for law in laws_to_check
        }
        for future in as_completed(futures, timeout=15):
            law = futures[future]
            try:
                result = future.result()
                law.update(result)
            except Exception:
                law["currency_status"] = "source_unavailable"
```

With parallel execution, the check adds ~3-6 seconds regardless of how many laws are involved.

### Optimization: caching with short TTL

For laws checked recently (within the same session or within the last hour), skip re-checking:

```python
# In-memory cache with 1-hour TTL
_currency_cache: dict[str, tuple[str, float]] = {}  # ver_id -> (status, timestamp)
CACHE_TTL = 3600  # 1 hour

def _is_cached_current(ver_id: str) -> bool | None:
    entry = _currency_cache.get(ver_id)
    if entry and time.time() - entry[1] < CACHE_TTL:
        return entry[0]
    return None
```

### Optimization: skip check when DB was recently updated

If the law's most recent version was imported within the last 24 hours (based on `LawVersion.date_imported`), skip the currency check and mark as `"current"` — the DB is fresh enough.

```python
if current_version.date_imported and (datetime.now() - current_version.date_imported).total_seconds() < 86400:
    law["currency_status"] = "current"
    law["currency_note"] = "Version imported within last 24h — skipping remote check"
    continue
```

## State changes

### New fields in `candidate_laws` entries

| Field | Type | Values |
|---|---|---|
| `currency_status` | str | `"current"`, `"stale"`, `"source_unavailable"`, `"not_checked"`, `"no_current_version"` |
| `currency_note` | str? | Human-readable explanation |
| `official_latest_ver_id` | str? | ver_id of newer version on legislatie.just.ro |
| `official_latest_date` | str? | date_in_force of newer version |
| `db_latest_date` | str? | date_in_force of current DB version |

### New fields in pipeline `state`

| Field | Type | Purpose |
|---|---|---|
| `stale_versions` | list[str] | law_keys where user chose to continue with stale version |
| `currency_check_skipped` | bool | True if check was skipped (historical question) |

### Pipeline log entry

```python
log_step(
    db, state["run_id"], "version_currency_check", step_number, "done",
    duration,
    output_summary=f"Checked {n_checked} laws: {n_current} current, {n_stale} stale, {n_unavailable} source unavailable",
    output_data={
        "results": {law_key: currency_status for each law},
        "stale_laws": [...],
        "skipped": currency_check_skipped,
    },
)
```

### SSE step label

Add to the step labels sent to frontend:

```python
"version_currency_check": "Verificare versiuni actuale..."
```

## Edge cases

### 1. Law has no `ver_id` (manually added)
- `currency_status = "not_checked"`
- Cannot verify against legislatie.just.ro without a ver_id

### 2. Law exists on legislatie.just.ro but history list is empty
- Treat as `"current"` — if the official source shows no other versions, the one we have is the only one

### 3. Multiple primary laws, some stale and some current
- Pause for the stale ones; show current ones as verified
- User can selectively import or skip each

### 4. Official source returns a version older than what's in DB
- This can happen if `date_in_force` was corrected in a re-import
- Treat as `"current"` — our version is at least as recent

### 5. Question about historical law (explicit past date)
- Skip currency check entirely — the user wants the version applicable at that past date, not the current one
- The existing version selection logic handles this correctly

### 6. Rate limiting by legislatie.just.ro
- If the site returns 429 or connection is throttled, treat as `source_unavailable`
- Do not retry during pipeline execution
- Log for monitoring

## Migration / backward compatibility

- No database schema changes required
- New fields in `candidate_laws` are additive — existing code ignores unknown keys
- The pause event gains new fields but existing frontend handles unknown fields gracefully
- Feature can be toggled via a pipeline config flag during rollout:
  ```python
  ENABLE_CURRENCY_CHECK = os.getenv("ENABLE_CURRENCY_CHECK", "true").lower() == "true"
  ```

## Summary of changes by file

| File | Change |
|---|---|
| `backend/app/services/version_currency.py` | **NEW** — `check_version_currency()` and `fetch_latest_version_metadata()` |
| `backend/app/services/pipeline_service.py` | Call `check_version_currency()` after Step 2, extend pause logic in Step 2.5, extend confidence scoring, pass stale info to Step 7 |
| `backend/app/services/pipeline_service.py` | Extend `resume_pipeline()` to handle "skip" for stale laws |
| `backend/prompts/LA-S7-answer-qa.txt` | Add stale version disclaimer instructions |
| `frontend/src/app/assistant/import-prompt.tsx` | Add "stale" and "source_unavailable" display states |
| `frontend/src/app/assistant/reasoning-panel.tsx` | Add version currency row |
| `frontend/src/lib/use-event-source.ts` | Handle new `currency_status` fields in pause event (minimal) |
