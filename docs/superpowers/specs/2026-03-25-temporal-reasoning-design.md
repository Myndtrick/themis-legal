# Per-Issue Temporal Reasoning & Auto-Categorization

**Date:** 2026-03-25
**Status:** Approved
**Scope:** Pipeline temporal logic, version selection, import flow, auto-categorization

## Problem

The Legal Assistant pipeline uses a single `primary_date` (extracted via regex as the first date found in the question) to select law versions for all legal issues. This is legally incorrect for scenario questions involving multiple events at different dates.

**Example:** A shareholder loans a company money on 01.01.2025, the company repays on 01.03.2026, and enters insolvency four months later. The system selects law versions based on 01.01.2025 (first date found) for all issues, even though insolvency and liability analysis should use 2026 versions.

**Additional issues identified:**
- Laws imported via the chat pipeline are not auto-categorized even when they exist in the seed category mapping.
- The import pause message lacks temporal context (doesn't explain why a specific version is needed).

## Design

### Approach

1. **Merge issue decomposition into Step 1** — extend the existing classifier prompt to also output events, legal issues with temporal assignments. Zero extra Claude calls.
2. **Per-law latest date for availability/import** — use `max(relevant_dates)` per law for Steps 2/2.5/import. Correct because if a version exists for a later date, earlier versions are already available.
3. **Per-issue version selection in Step 3** — each legal issue gets the exact law version for its relevant date.
4. **Auto-categorization on import** — check seed `LawMapping` table after importing any law.

### Section 1: Step 1 Prompt Extension

Extend `LA-S1-issue-classifier.txt` to output two new fields in the JSON response:

**`events`** — all factual events with dates:
```json
{
  "events": [
    {
      "event": "Shareholder loans 100,000 EUR to company",
      "date": "2025-01-01",
      "date_source": "explicit"
    },
    {
      "event": "Company enters insolvency",
      "date": "2026-07-01",
      "date_source": "computed",
      "date_reasoning": "4 months after 01.03.2026"
    }
  ]
}
```

**`legal_issues`** — each discrete legal issue with its temporal assignment:
```json
{
  "legal_issues": [
    {
      "issue_id": "ISSUE-1",
      "description": "Validity of related-party loan",
      "relevant_date": "2025-01-01",
      "temporal_rule": "contract_formation",
      "date_reasoning": "Law at contract signing date applies",
      "applicable_laws": ["31/1990"]
    }
  ]
}
```

**Temporal rules included in the prompt:**

| Rule | Meaning | Date used |
|------|---------|-----------|
| `contract_formation` | Contract validity | Signing date |
| `performance` | Obligation performed/breached | Performance date |
| `insolvency_opening` | Insolvency analysis | Opening date |
| `act_date` | Liability for a specific act | Date of the act |
| `breach_date` | Continuous obligation breach | Breach date |
| `registration_date` | ONRC/filing matters | Filing date |
| `current_law` | Hypothetical/prospective questions | Today |

**Future date rule:** If event date is in the future or cannot be determined, use `current_law`.

**Relationship to top-level `applicable_laws`:** The per-issue `applicable_laws` arrays contain law keys (e.g., `"31/1990"`) that reference entries in the existing top-level `applicable_laws` array. The top-level array continues to carry the full metadata (number, year, title, role, reason). The per-issue arrays are subset references, not duplicates.

**For Type A (direct) questions:** Single issue in `legal_issues` with `relevant_date` set to today or the mentioned date.

**`max_tokens` increase:** from 1024 to 2048.

### Section 2: Step 1b Removal

`_step1b_date_extraction` is removed from the pipeline flow. Date extraction is now done by Claude inside Step 1.

After Step 1 returns, the pipeline computes:

```python
# law_date_map — latest relevant date per law (for Steps 2/2.5/import)
law_date_map = {}
for issue in parsed.get("legal_issues", []):
    for law_key in issue.get("applicable_laws", []):
        existing = law_date_map.get(law_key)
        if not existing or issue["relevant_date"] > existing:
            law_date_map[law_key] = issue["relevant_date"]

# primary_date — kept for backward compat, set to max across all issues
state["primary_date"] = max(law_date_map.values()) if law_date_map else state["today"]
state["law_date_map"] = law_date_map
state["legal_issues"] = parsed.get("legal_issues", [])
state["events"] = parsed.get("events", [])
```

**Fallback:** If Claude returns no `legal_issues`, fall back to `primary_date = today`, no per-issue decomposition.

The `date_extractor.py` file stays in the codebase but is no longer called.

The SSE event for Step 1b (`step 15, date_extraction`) is removed from the stream. The frontend progress display should gracefully ignore missing steps (it already does — unknown steps are simply not rendered).

### Section 3: Step 2 & 2.5 Changes

**`check_laws_in_db`** signature changes:

```python
# From:
def check_laws_in_db(laws, db, primary_date: str | None = None)
# To:
def check_laws_in_db(laws, db, law_date_map: dict[str, str] | None = None)
```

Inside, looks up the relevant date per law:
```python
law_key = f"{law_number}/{law_year}"
relevant_date = law_date_map.get(law_key) if law_date_map else None
```

**Pause message enrichment** — `laws_preview` gets:
```python
preview = {
    # ... existing fields ...
    "needed_for_date": law_date_map.get(law_key),
    "date_reason": "Needed for insolvency analysis (01.07.2026)"
}
```

**`resume_pipeline`** passes per-law date to import:
```python
law_key = f"{law_number}/{law_year}"
relevant_date = state.get("law_date_map", {}).get(law_key, state.get("primary_date"))
result = import_law_smart(db, ver_id, primary_date=relevant_date)
```

`import_law_smart` itself does not change.

### Section 4: Step 3 Redesign

Loop over `legal_issues` instead of `candidate_laws`. Select a version per issue-law pair.

**Two output dicts:**

1. **`issue_versions`** — per-issue detail, keyed by `issue_id:law_key`:
```python
{
    "ISSUE-2:85/2014": {
        "law_version_id": int,
        "law_id": int,
        "issue_id": str,
        "law_key": str,
        "relevant_date": str,        # the issue's date
        "date_in_force": str,        # the version's actual date
        "is_current": bool,
        "temporal_rule": str,
        "date_reasoning": str,
    }
}
```

2. **`selected_versions`** — backward-compatible dict keyed by law only, using the **latest** version per law (for Step 5 expander and cross-law reference resolution):
```python
{
    "85/2014": {"law_version_id": 123, "law_id": 5, "date_in_force": "2026-01-15", ...},
    "31/1990": {"law_version_id": 78, "law_id": 3, "date_in_force": "2026-02-20", ...},
}
```
This preserves the existing `selected_versions` shape that Step 5 (`expand_articles`), the reasoning panel (`_build_reasoning_panel`), and other downstream consumers expect.

**Future date handling:** If `relevant_date > today`, use today and add a version note.

**`unique_versions` dict** built for Step 4 retrieval (all version IDs per law, deduplicated):
```python
# {"85/2014": {123}, "31/1990": {45, 78}}
```

### Section 5: Step 4 Changes

Use `unique_versions` (set of version IDs per law) instead of single version ID:

```python
for law in state.get("law_mapping", {}).get(tier_key, []):
    key = f"{law['law_number']}/{law['law_year']}"
    vids = state.get("unique_versions", {}).get(key, set())
    version_ids.extend(vids)
```

Articles already carry `law_version_id` metadata. Each article is tagged with its version date for Step 7 context.

No changes to BM25 search, ChromaDB search, Step 5.5, Step 6.

Step 5 (`expand_articles` / `_extract_cross_law_references`) is **not changed** — it continues to use `selected_versions` in the existing `"law_number/law_year"` key format, which Step 3 still produces alongside the new `issue_versions` dict.

### Section 6: Step 7 Answer Generation

**New temporal context block** replaces the simple date/version context:

```
TEMPORAL ANALYSIS:
  Events:
    1. 01.01.2025 — Shareholder loans 100,000 EUR to company
    2. 01.03.2026 — Company repays loan to shareholder
    3. 01.07.2026 — Company enters insolvency

  Legal Issues & Applicable Versions:
    ISSUE-1: Validity of related-party loan
      Relevant date: 01.01.2025 (contract_formation)
      -> L. 31/1990 version 2024-12-06

    ISSUE-2: Legality of loan repayment before insolvency
      Relevant date: 01.03.2026 (performance)
      -> L. 85/2014 version 2026-01-15
      -> L. 31/1990 version 2026-02-20
    ...
```

**Prompt instructions added to `LA-S7-answer-qa.txt`:**
1. Structure answer by legal issue
2. For each issue, state which law version applies and why
3. If the same law has different versions for different issues, explain explicitly
4. Cite articles with version date: "Art. 117 din Legea 85/2014 (versiunea din 15.01.2026)"
5. End with a temporal summary table: Issue -> Date -> Law -> Version

### Section 7: Auto-Categorization on Import

Shared helper called from both `import_law_smart()` and `import_law()`:

```python
def _auto_categorize(db: Session, law: Law) -> None:
    """Assign category from seed mapping if law has no category."""
    if law.category_id is not None:
        return
    if not law.law_number:
        return
    from app.models.category import LawMapping as CategoryMapping
    mapping = (
        db.query(CategoryMapping)
        .filter(
            CategoryMapping.law_number == law.law_number,
            CategoryMapping.law_year == law.law_year,
        )
        .first()
    )
    if mapping and mapping.category_id:
        law.category_id = mapping.category_id
        law.category_confidence = "auto"
```

Called before the commit in both import functions. Only sets category if the law doesn't already have one. Filters on both `law_number` and `law_year` to avoid mismatches (e.g., Legea 85/2014 vs Legea 85/2006). Skips laws with no `law_number`.

## Files Changed

| File | Change | Size |
|------|--------|------|
| `prompts/LA-S1-issue-classifier.txt` | Add events, legal_issues, temporal rules to prompt + output schema | ~60 lines added |
| `pipeline_service.py` — `_step1_issue_classification` | Parse new fields, compute `law_date_map`, `legal_issues`, `events`. Increase `max_tokens` to 2048 | ~25 lines |
| `pipeline_service.py` — pipeline flow | Remove Step 1b call and SSE event | ~10 lines removed |
| `pipeline_service.py` — `_step2_law_mapping` | Pass `law_date_map` instead of `primary_date` | 1 line |
| `law_mapping.py` — `check_laws_in_db` | Accept `law_date_map` dict, look up per-law date | ~8 lines changed |
| `pipeline_service.py` — `_step2_5_early_relevance_gate` | Add `needed_for_date` and `date_reason` to pause message | ~10 lines |
| `pipeline_service.py` — `resume_pipeline` | Pass per-law date to `import_law_smart` | 2 lines |
| `pipeline_service.py` — `_step3_version_selection` | Loop over `legal_issues`. Produce `issue_versions` (per-issue), `selected_versions` (backward-compat per-law), and `unique_versions` (for retrieval). Handle future dates. | ~50 lines rewritten |
| `pipeline_service.py` — `_step4_hybrid_retrieval` | Use `unique_versions` set instead of single version | ~5 lines changed |
| `pipeline_service.py` — `_step7_answer` | Build temporal context block from `issue_versions` | ~20 lines changed |
| `prompts/LA-S7-answer-qa.txt` | Add per-issue version citation instructions | ~15 lines added |
| `leropa_service.py` | Add `_auto_categorize` helper, call from both import functions | ~15 lines |
| `frontend/import-prompt.tsx` | Show `needed_for_date` and `date_reason` in pause UI | ~5 lines |

**Total: ~200 lines changed/added across 8 files. Zero new endpoints. Zero new Claude calls. Zero new dependencies.**

## Not Changed

- BM25 search, ChromaDB search
- Step 5 (expansion — uses backward-compatible `selected_versions`), Step 5.5 (exceptions), Step 6 (article selection)
- `article_expander.py` (uses `selected_versions` in existing format)
- Citation validation (Step 7.5)
- Database schema / models
- `date_extractor.py` (kept as unused fallback)
- `_build_reasoning_panel` (uses `selected_versions` in existing format)

## Cost Impact

- Zero additional Claude API calls
- Step 1 output ~300 tokens larger (~$0.005)
- Step 7 input ~1,500 tokens larger (~$0.005)
- Total: ~$0.01 per question increase
