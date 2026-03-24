# Claude-Based Law Identification (Replace Rule-Based Mapping)

## Problem

The current Step 2 (Law Mapping) uses a static `DOMAIN_LAW_MAP` dict to map classified legal domains to applicable laws. This is fundamentally limited:

- A question about insolvency involving a corporate entity gets classified as `corporate` -> maps only to Legea 31/1990 + Codul Civil. Legea insolventei (85/2014) is completely missed.
- Every new cross-domain question reveals another gap in the static map.
- The map requires manual updates for each new legal scenario.
- When the map misses a law, the pipeline proceeds with wrong/incomplete laws, wastes tokens on retrieval + answer generation, and produces inaccurate answers.

Additionally, the pipeline proceeds even when the correct law version is unavailable, generating answers based on the wrong version of the law.

## Solution

Replace the rule-based law mapping with Claude-based law identification, merged into the existing Step 1 classifier call. Claude analyzes the question and outputs all applicable laws. The pipeline then checks each law against the DB (existence + version), and pauses with a preview if any PRIMARY law is missing or has the wrong version.

## Design

### 1. Merge Law Identification into Step 1 Classifier

**File:** `backend/prompts/LA-S1-issue-classifier.txt`

Extend the prompt to also output applicable laws. The classifier already analyzes the question deeply — identifying laws is a natural extension.

**New output fields added to the existing JSON:**
```json
{
  "question_type": "B",
  "legal_domain": "corporate",
  "output_mode": "compliance",
  "legal_topic": "raspundere administrator insolventa",
  "entity_types": ["SRL"],
  "core_issue": "...",
  "sub_issues": ["..."],
  "classification_confidence": "HIGH",
  "reasoning": "...",

  "applicable_laws": [
    {
      "law_number": "31",
      "law_year": "1990",
      "title": "Legea societăților comerciale",
      "role": "PRIMARY",
      "reason": "Reglementează răspunderea administratorilor"
    },
    {
      "law_number": "85",
      "law_year": "2014",
      "title": "Legea privind procedurile de insolvență",
      "role": "PRIMARY",
      "reason": "Reglementează actele atacabile și procedura de insolvență"
    },
    {
      "law_number": "287",
      "law_year": "2009",
      "title": "Codul Civil",
      "role": "SECONDARY",
      "reason": "Drept comun pentru obligații și răspundere civilă"
    }
  ]
}
```

**Prompt instructions for law identification:**
- Identify ALL Romanian laws that apply to this question, regardless of whether they are available in the Legal Library
- Assign each law a role: PRIMARY (directly applicable) or SECONDARY (applies subsidiarily/fills gaps)
- Only two roles exist: PRIMARY and SECONDARY. The previous CONNECTED tier is eliminated — Claude identifies all relevant laws directly, so a "connected only if cross-referenced" tier is unnecessary.
- A question can have multiple PRIMARY laws (e.g., corporate + insolvency)
- Include the law's official number, year, and Romanian title
- Include a brief reason explaining why this law applies to the question

**Context provided:** The prompt receives a list of law names/numbers currently in the Legal Library (capped at 50 entries to control token costs). Claude is explicitly told: "Do not limit your identification to available laws. Identify ALL applicable laws."

**Removed fields:**
- `secondary_domain` — no longer needed, Claude outputs all laws directly. Downstream code that reads `secondary_domain` from state will be removed/updated.

**Validation:** Before DB lookup, validate each entry in `applicable_laws`:
- Must have `law_number` (string or int) and `law_year` (string or int)
- Must have `role` that is either "PRIMARY" or "SECONDARY"
- Skip malformed entries with a warning flag

### 2. Step 2 Becomes DB Lookup + Version Check

**File:** `backend/app/services/pipeline_service.py` — `_step2_law_mapping()`

The function no longer calls `map_laws_to_question()`. The secondary-domain merge logic (line 550, iterating `tier3_connected`) is also removed — Claude identifies all applicable laws directly, so there is no secondary domain merging.

Instead:

1. Read `applicable_laws` from `state` (set by Step 1)
2. For each law, query DB:
   - Does the law exist? (`Law` table by `law_number` + `law_year`, coercing both to string for comparison)
   - If yes, does a version matching `primary_date` exist? (`LawVersion` table)
3. Build `candidate_laws` with three availability states:
   - `"available"` — law exists AND correct version found
   - `"wrong_version"` — law exists but no version for `primary_date` (only current/other versions)
   - `"missing"` — law not in DB at all
4. Build `law_mapping` dict with two tiers for downstream compatibility:
   - `tier1_primary` — laws with role "PRIMARY"
   - `tier2_secondary` — laws with role "SECONDARY"
   - `tier3_connected` is eliminated. Downstream iteration in Step 4's `tier_limits` only uses `tier1_primary` and `tier2_secondary`, so no change needed there.

**File:** `backend/app/services/law_mapping.py`

Reduce to a utility with:
- `check_laws_in_db(laws: list[dict], db: Session, primary_date: str | None) -> list[dict]` — enriches each law dict with `db_law_id`, `in_library`, `availability`, `available_version_date`
- Remove `DOMAIN_LAW_MAP` and `map_laws_to_question()`

### 3. Step 2.5 Becomes Pause-with-Preview

**File:** `backend/app/services/pipeline_service.py` — `_step2_5_early_relevance_gate()`

Rewrite to use the existing pause mechanism. Currently the gate returns a `done` event (terminates pipeline). Change it to:

1. Check if any PRIMARY law has `availability` of `"missing"` or `"wrong_version"`
2. If yes: save pipeline state with `save_paused_state()`, then return a `pause` event (not `done`)
3. If no: return `None` (continue)

```python
needs_pause = any(
    law["availability"] in ("missing", "wrong_version")
    for law in candidate_laws
    if law["role"] == "PRIMARY"
)

if needs_pause:
    save_paused_state(db, state["run_id"], state)
    return {
        "type": "pause",
        "run_id": state["run_id"],
        "message": "Am identificat legile aplicabile. Unele necesită import.",
        "laws": [build law preview list with availability status]
    }
```

**The pause event includes ALL laws** (not just missing ones):
```json
{
  "type": "pause",
  "run_id": "...",
  "message": "Am identificat legile aplicabile. Unele necesită import.",
  "laws": [
    {
      "law_number": "31",
      "law_year": "1990",
      "title": "Legea societăților comerciale",
      "role": "PRIMARY",
      "availability": "available",
      "version_info": "version 2025-12-18 (current)"
    },
    {
      "law_number": "85",
      "law_year": "2014",
      "title": "Legea privind procedurile de insolvență",
      "role": "PRIMARY",
      "availability": "missing",
      "version_info": null
    },
    {
      "law_number": "287",
      "law_year": "2009",
      "title": "Codul Civil",
      "role": "SECONDARY",
      "availability": "wrong_version",
      "version_info": "Only current version available, not 2025-01-01"
    }
  ]
}
```

**What gets removed:**
- `_generate_clarification_question()` — no longer needed
- `_build_needs_import_event()` — replaced by the pause event builder
- `_build_cannot_answer_event()` — replaced by a simpler "no laws identified" message
- `_count_clarification_rounds()` — clarification loop removed
- `LA-S2.5-clarification.txt` — deleted

**Fallback for "no laws identified":** If Claude returns an empty `applicable_laws`, the pipeline yields a `done` event (not `pause`) with a static message: "Nu am putut identifica legile aplicabile. Vă rog să reformulați întrebarea cu mai multe detalii." This is a regression from the current Claude-generated clarification question, but it's simpler and the new law identification makes this case much rarer — Claude identifying laws is more robust than the old domain→map approach.

### 4. Resume Pipeline with Actual Import

**File:** `backend/app/services/pipeline_service.py` — `resume_pipeline()`

Currently `resume_pipeline` is a stub that only appends a flag when user clicks "import." Update it to actually trigger the import:

```python
for law_key, decision in import_decisions.items():
    if decision in ("import", "import_version"):
        law_number, law_year = law_key.split("/")
        # Search legislatie.just.ro for this law
        ver_id = search_law_on_legislatie(law_number, law_year)
        if ver_id:
            from app.services.leropa_service import import_law
            import_law(db, ver_id, import_history=True)
            state["flags"].append(f"Imported {law_key} from legislatie.just.ro")
        else:
            state["flags"].append(f"Could not find {law_key} on legislatie.just.ro")
```

**The `search_law_on_legislatie()` function:** New utility that searches legislatie.just.ro for a law by number/year and returns the `ver_id`. This uses the existing leropa scraper to find the law. If the law cannot be found, the pipeline continues without it (with a flag).

**Import is synchronous within the SSE stream.** The frontend shows "Importing..." while waiting. This can take 5-30 seconds depending on the law size. The SSE connection stays open. Progress could be streamed as step events if needed (future enhancement).

**Decision values from frontend:**
- `"import"` — law is missing, import it
- `"import_version"` — law exists but wrong version, import the needed version
- `"skip"` — continue without this law

### 5. Frontend Changes

**File:** `frontend/src/app/assistant/import-prompt.tsx`

Update the ImportPrompt component to handle the new `laws` array (replaces `missing_laws`):

- **Green checkmark** — `availability: "available"`. No action.
- **Amber warning + import button** — `availability: "wrong_version"`. Button sends `"import_version"`.
- **Red X + import button** — `availability: "missing"`. Button sends `"import"`.

Show all laws (not just missing ones) for full transparency.

Two buttons at bottom:
- "Import and continue" — sends import/import_version for all non-available laws
- "Continue without" — sends skip for all non-available laws

**File:** `frontend/src/app/assistant/use-chat.ts`

Update the `PauseData` interface:
```typescript
export interface PauseData {
  run_id: string;
  message: string;
  laws: LawPreview[];  // Changed from missing_laws: MissingLaw[]
}

export interface LawPreview {
  law_number: string;
  law_year: string;
  title: string;
  role: "PRIMARY" | "SECONDARY";
  availability: "available" | "wrong_version" | "missing";
  version_info: string | null;
}
```

The `onPause` handler and `handleImportDecision` function already work with the pause/resume pattern — they just need the updated type.

**File:** `frontend/src/lib/api.ts`

Update `MissingLaw` type or replace with `LawPreview`. Update any references.

### 6. Step 1 Receives Library Context

**File:** `backend/app/services/pipeline_service.py` — `_step1_issue_classification()`

Before calling Claude, query the DB for available laws and pass them as context:

```python
from app.models.law import Law
available_laws = db.query(Law).limit(50).all()
laws_context = "LAWS CURRENTLY IN LEGAL LIBRARY:\n"
for law in available_laws:
    laws_context += f"- {law.law_number}/{law.law_year}: {law.title}\n"
```

This is appended to the user message. Capped at 50 laws to control token cost. The prompt tells Claude this list is for reference only — it should identify all applicable laws regardless.

## Edge Cases

- **Claude hallucinates a law number:** The DB lookup returns `missing`. User sees it in the preview with an import button. If they click import and the law doesn't exist on legislatie.just.ro, the import fails gracefully with a flag.
- **Very vague question ("ce drepturi am?"):** Claude outputs generic laws. Pipeline proceeds with what's available.
- **No applicable laws identified:** Claude returns empty `applicable_laws`. Pipeline yields a `done` event with a static message asking the user to be more specific. No tokens wasted on retrieval.
- **All laws available, correct versions:** Pipeline continues silently. No pause, no delay. User sees the identified laws in the pipeline debug panel.
- **SECONDARY law missing:** Pipeline does NOT pause for missing SECONDARY laws — only PRIMARY. Missing SECONDARY laws get a flag.
- **Malformed Claude output:** Entries missing `law_number` or `law_year` are skipped with a warning. If all entries are malformed, treated as "no laws identified."
- **Import fails during resume:** Flag added, pipeline continues with available laws. Answer will have lower confidence.
- **`law_year` type mismatch:** Both Claude's output and DB values are coerced to `str()` before comparison.

## Files Changed

| File | Change |
|------|--------|
| `prompts/LA-S1-issue-classifier.txt` | Add `applicable_laws` output format + identification instructions |
| `pipeline_service.py` — `_step1_issue_classification()` | Parse `applicable_laws`, pass library context, remove `secondary_domain` handling |
| `pipeline_service.py` — `_step2_law_mapping()` | Replace rule-based mapping with DB lookup + version check |
| `pipeline_service.py` — `_step2_5_early_relevance_gate()` | Rewrite: save state + pause if any PRIMARY law missing/wrong version |
| `pipeline_service.py` — `resume_pipeline()` | Add actual import via leropa_service before resuming |
| `pipeline_service.py` — remove functions | Delete `_generate_clarification_question()`, `_build_needs_import_event()`, `_build_cannot_answer_event()`, `_count_clarification_rounds()` |
| `law_mapping.py` | Remove DOMAIN_LAW_MAP + map_laws_to_question(), add `check_laws_in_db()` |
| `prompts/LA-S2.5-clarification.txt` | Delete |
| `frontend/src/app/assistant/import-prompt.tsx` | Show three-state law preview (available/wrong_version/missing) |
| `frontend/src/app/assistant/use-chat.ts` | Update `PauseData` interface to use `laws: LawPreview[]` |
| `frontend/src/lib/api.ts` | Add `LawPreview` type, update/replace `MissingLaw` |

## Not Changed

- Steps 3-7 (version selection, retrieval, expansion, reranking, answer generation)
- BM25, ChromaDB, reranker services
- Answer prompts (LA-S7-*)
- Frontend message-bubble.tsx (no changes)
- The `streamResume()` function in use-event-source.ts (already handles pause/resume)

## Verification

1. Ask "daca un actionar... compania intra in insolventa" — Claude should identify Legea 85/2014 as PRIMARY. If not in library, pause with import button.
2. Ask "ce capital social minim pentru SRL" — Claude should identify Legea 31/1990 as PRIMARY. If available with correct version, no pause. Verify result is identical to before (regression test).
3. Ask a question with a historical date (e.g., "in 2020") — verify version check catches wrong-version laws and pauses with import button.
4. Ask a vague question — verify Claude outputs sensible laws or empty array, pipeline doesn't waste tokens.
5. Ask a cross-domain question (e.g., criminal + corporate) — verify Claude identifies multiple PRIMARY laws.
6. Click "Import and continue" — verify the law is actually imported from legislatie.just.ro and the pipeline resumes with it available.
7. Click "Continue without" — verify pipeline proceeds with available laws only and flags the gap.
