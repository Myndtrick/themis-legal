# Pipeline Repair V3 — Design Spec

## Goal

Fix 8 interrelated pipeline problems that produce wrong dates, wrong versions, missing articles, double Step 12 runs, and leaked internal terminology. Reduce cost from $0.36 to $0.15-0.22 per query and time from 238s to 100-130s without affecting accuracy.

## Architecture

The pipeline is a 15-step sequential flow in `pipeline_service.py`. This spec modifies Steps 1, 2, 3, 6, 7, 9, 14 and the context builder. No steps are added or removed — Step 2 is repurposed and Step 6 is simplified.

## Problems and Fixes

### P1 — Hypothetical Date Anchoring (LA-S1 prompt)

**Root cause:** The HYPOTHETICAL SCENARIO ANCHORING section (LA-S1 lines 113-118) is too weak. Claude sees described acts and picks `act_date` with fabricated past dates instead of anchoring to TODAY.

**Fix:** Replace lines 113-118 with a decision gate that forces Claude to classify the scenario as HYPOTHETICAL or HISTORICAL before choosing temporal rules:

```
HYPOTHETICAL vs HISTORICAL — DECISION GATE (apply BEFORE choosing temporal_rule):

Step A — Is there an explicit calendar date (e.g., "pe 15.03.2024") or reference
         to a specific historical event in the question?
  YES → The scenario is HISTORICAL. Use act_date/contract_formation/etc.
        with the stated date.
  NO  → Go to Step B.

Step B — Does the question use conditional language ("Dacă...",
         "în cazul în care...", "ce se întâmplă dacă..."), or describe
         a scenario without anchoring it to a specific past moment?
  YES → The scenario is HYPOTHETICAL. Apply Rule H below.
  NO  → Default to current_law with TODAY'S DATE.

Rule H (HYPOTHETICAL SCENARIOS):
  - The FIRST described event happens at TODAY'S DATE
  - Subsequent events are computed relative to TODAY
    Example: "~1 year later" → TODAY + 1 year
  - ALL temporal_rules use the anchored dates (not fabricated past dates)
  - Past tense does NOT make it historical — Romanian hypotheticals
    commonly use past tense ("a transferat", "a intrat")
  - For criminal issues: use act_date with the ANCHORED date (= TODAY),
    not a fabricated past date
```

**File:** `prompts/LA-S1-issue-classifier.txt` lines 113-118

**Cost impact:** Zero.

**Fixes:** P1 (directly), P2 (cascading — correct dates produce correct version selection).

---

### P2 — Wrong Version Selection

**Root cause:** Cascading from P1. The version selection logic (`_find_version_for_date`) is correct — it selects the newest version with `date_in_force <= target_date`. The input dates are wrong.

**Fix:** No code change needed. Fixing P1 fixes P2 automatically.

---

### P3+P4 — Step 2 Version Preparation + Step 6 Simplification

**Root cause (P3):** Step 2 builds `fact_version_map` with dates and temporal rules but does NOT perform DB lookups. The actual version selection (DB query for `law_version_id`) happens in Step 6, which runs after Steps 3-5.

**Root cause (P4):** Because Step 6 runs after Steps 3-5, the availability gate (Step 5) cannot report version-level availability — it only knows law-level availability.

**Fix:** Move the version selection DB queries from Step 6 into Step 2. Step 6 becomes a pure binding step.

#### Step 2 changes (`_step1b_date_extraction` → `_step1b_version_preparation`)

After building `fact_version_map` and `versions_needed` (existing code, lines 1918-1960), add DB lookups:

```python
# For each fact-law pair in fact_version_map, select the correct version
law_id_lookup = {}
for law_info in state.get("candidate_laws", []):
    if law_info.get("db_law_id"):
        key = f"{law_info['law_number']}/{law_info.get('law_year', '')}"
        law_id_lookup[key] = law_info["db_law_id"]

versions_cache = {}  # law_id -> [LawVersion objects]

for map_key, fact_info in fact_version_map.items():
    parts = map_key.split(":")
    law_key = parts[-1]  # always last part
    db_law_id = law_id_lookup.get(law_key)
    if not db_law_id:
        continue

    if db_law_id not in versions_cache:
        versions_cache[db_law_id] = (
            db.query(LawVersion)
            .filter(LawVersion.law_id == db_law_id)
            .order_by(LawVersion.date_in_force.desc().nullslast())
            .all()
        )
    versions = versions_cache[db_law_id]
    if not versions:
        continue

    fact_date = fact_info.get("relevant_date", today)
    if fact_date == "unknown":
        fact_date = today

    selected = _find_version_for_date(versions, fact_date)
    if not selected:
        selected = _fallback_version(versions)

    if selected:
        fact_info["law_version_id"] = selected.id
        fact_info["date_in_force"] = str(selected.date_in_force) if selected.date_in_force else None
        fact_info["is_current"] = selected.is_current
        fact_info["ver_id"] = selected.ver_id
```

Move `_find_version_for_date` and `_fallback_version` to module-level functions (currently nested in `_step3_version_selection` at lines ~2225-2237). Place them above `_step1b_date_extraction` so both Step 2 and Step 6 can use them.

**Dependency:** Step 2 now needs `candidate_laws` in state. Step 2 runs after Step 1, which does NOT populate `candidate_laws` — that's done by Step 3 (Law Mapping). So Step 2's DB lookups need to query Law directly:

```python
# Instead of using candidate_laws, query Law table directly
for map_key, fact_info in fact_version_map.items():
    law_key = map_key.split(":")[-1]
    law_number, law_year = law_key.split("/")
    db_law = db.query(Law).filter(
        Law.law_number == law_number,
        Law.law_year == int(law_year),
    ).first()
    if not db_law:
        fact_info["availability"] = "missing"
        continue
    # ... version selection as above ...
```

This means Step 2 can independently determine both law availability AND version availability before Step 3 runs.

#### Step 3 changes (Law Mapping)

Step 3 (`check_laws_in_db` in `law_mapping.py`) currently receives `law_date_map` and performs its own version selection. After P3+P4 fix, Step 3 can use `fact_version_map` entries that already have `law_version_id` populated. Step 3 still checks law-level availability and adds `db_law_id`, `in_library`, etc. — but version availability is already known from Step 2.

Add to each law's output: `"version_available": True/False` based on whether Step 2 found a matching version.

#### Step 6 changes (Version Binding — simplified)

Step 6 (`_step3_version_selection`) no longer performs DB queries. It reads `fact_version_map` (already enriched by Step 2) and builds:
- `issue_versions` — keyed by `"ISSUE-N:law_key"`
- `selected_versions` — backward-compat dict, keyed by `law_key`
- `unique_versions` — set of version_ids per law for retrieval

```python
def _step3_version_selection(state, db):
    """Bind version IDs from Step 2's fact_version_map into pipeline state."""
    fact_version_map = state.get("fact_version_map", {})
    issue_versions = {}
    selected_versions = {}
    unique_versions = {}

    for map_key, fact_info in fact_version_map.items():
        if not fact_info.get("law_version_id"):
            continue
        parts = map_key.split(":")
        law_key = parts[-1]
        issue_id = parts[0]

        combo_key = f"{issue_id}:{law_key}"
        issue_versions[combo_key] = {
            "law_version_id": fact_info["law_version_id"],
            "law_id": fact_info.get("law_id"),
            "issue_id": issue_id,
            "law_key": law_key,
            "relevant_date": fact_info["relevant_date"],
            "date_in_force": fact_info.get("date_in_force"),
            "is_current": fact_info.get("is_current"),
            "temporal_rule": fact_info.get("temporal_rule", ""),
            "ver_id": fact_info.get("ver_id"),
        }

        unique_versions.setdefault(law_key, set()).add(fact_info["law_version_id"])

        # Backward-compat: keep latest version per law
        existing = selected_versions.get(law_key)
        if not existing or (fact_info.get("date_in_force") and (
            not existing.get("date_in_force") or
            fact_info["date_in_force"] > existing["date_in_force"]
        )):
            selected_versions[law_key] = {
                "law_version_id": fact_info["law_version_id"],
                "date_in_force": fact_info.get("date_in_force"),
                "is_current": fact_info.get("is_current"),
                "ver_id": fact_info.get("ver_id"),
            }

    state["issue_versions"] = issue_versions
    state["selected_versions"] = selected_versions
    state["unique_versions"] = {k: list(v) for k, v in unique_versions.items()}
    return state
```

**Files:**
- `pipeline_service.py` lines 1891-1987 (Step 2) — add DB lookups
- `pipeline_service.py` lines 2198-2419 (Step 6) — simplify to binding only
- `law_mapping.py` lines 11-135 (Step 3) — use version availability from Step 2

**Cost impact:** Zero — same DB queries moved earlier.

---

### P5+P6 — Candidate Articles + Direct Lookup in Retrieval

**Root cause (P5):** There is no candidate article lookup in Step 7. All retrieval goes through BM25 (keyword match) and ChromaDB (semantic similarity). Art. 241 (bancruta frauduloasa) and Art. 295 (delapidare) use legal terminology that doesn't match the question's surface vocabulary. Art. 297 (abuz in serviciu) matches better on keywords despite being legally inapplicable.

**Root cause (P6):** Same mechanism — Legea 31/1990 articles use specialized terminology that BM25 and semantic search don't match well against natural language questions.

**Fix — three parts:**

#### 5A. Add `candidate_articles` to Step 1 output schema

Add to each `legal_issues` entry in the LA-S1 JSON schema:

```json
"candidate_articles": [
  {"law_key": "286/2009", "article": "241", "reason": "bancruta frauduloasa"},
  {"law_key": "286/2009", "article": "295", "reason": "delapidare"}
]
```

Add prompt guidance to LA-S1:

```
CANDIDATE ARTICLES (recommended for STANDARD and COMPLEX questions):
For each legal issue, list specific articles you believe are directly
applicable based on your legal knowledge. Format: law_key and article number.
These improve retrieval precision — the system also searches broadly,
so missing an article here is not critical. List only articles you
are confident about. Omit this field for SIMPLE questions.
```

**File:** `prompts/LA-S1-issue-classifier.txt` — schema section (lines 194-214) and guidance

**Cost impact:** +50-100 output tokens in Step 1 (~$0.001).

#### 5B. Direct article lookup in Step 7

In `_step4_hybrid_retrieval`, before BM25/semantic search, fetch candidate articles by exact DB lookup:

```python
# Direct lookup for candidate articles from Step 1
candidate_articles = []
for issue in state.get("legal_issues", []):
    for ca in issue.get("candidate_articles", []):
        law_key = ca.get("law_key", "")
        article_num = ca.get("article", "")
        version_ids = unique_versions.get(law_key, [])
        if not version_ids or not article_num:
            continue
        for vid in version_ids:
            article = db.query(Article).filter(
                Article.law_version_id == vid,
                Article.article_number == article_num,
            ).first()
            if article:
                candidate_articles.append({
                    "article_id": article.id,
                    "law_version_id": vid,
                    "article_number": article.article_number,
                    "text": article.text,
                    "source": "candidate_lookup",
                    "tier": "primary",
                    "role": "PRIMARY",
                    "law_number": law_key.split("/")[0],
                    "law_year": law_key.split("/")[1],
                    # ... standard article dict fields
                })
```

These enter the retrieval pool alongside BM25/semantic results. No special scoring — the reranker evaluates them equally.

**File:** `pipeline_service.py` lines 2441-2601 (`_step4_hybrid_retrieval`)

**Cost impact:** Negligible DB queries.

#### 5C. Increase per-law minimum for PRIMARY laws in reranker

In `_step6_select_articles`, pass `min_per_law=3` for PRIMARY-tier laws:

```python
ranked = rerank_articles(state["question"], raw, top_k=top_k, min_per_law=3)
```

**File:** `reranker_service.py` line 40 (default parameter), `pipeline_service.py` line 2744

**Cost impact:** Zero.

**Combined effect on P7:** With candidate articles in the retrieval pool, Step 12 won't report missing governing norms → Step 13 won't trigger → Step 12 runs once → saves ~$0.10-0.15 and ~60-90 seconds.

---

### P7 — Step 12 Runs Twice

**Root cause:** Cascading from P5+P6. Step 12 identifies missing articles because retrieval missed them. Step 13 triggers when `governing_norm_status.status == "MISSING"` and re-runs Step 12.

**Fix:** No additional code change needed beyond P5+P6. With correct articles retrieved, Step 13 should rarely trigger. The existing Step 13 logic (only re-run for MISSING governing norms) is correct as a safety net.

---

### P8 — Internal Terminology Leaks

**Root cause:** 5 bypass points in `_build_step7_context` where raw RL-RAP terms pass through without translation.

**Fix:** Add translation maps for all 5 bypass points and a defense-in-depth sanitizer.

#### New translation maps

```python
_GOVERNING_NORM_MAP = {
    "PRESENT": None,  # Don't output — norm is found, no need to flag
    "MISSING": "Norma nu a fost identificata in articolele disponibile",
    "INFERRED": "Norma a fost dedusa din cadrul legal general",
}

_EXCEPTION_STATUS_MAP = {
    "SATISFIED": "Exceptie aplicabila",
    "NOT_SATISFIED": "Exceptie inaplicabila",
    "UNKNOWN": "Exceptie — informatie insuficienta",
}

_CONFLICT_RESOLUTION_MAP = {
    "UNRESOLVED": "Conflict nerezolvat intre norme concurente",
    "lex_specialis": "Se aplica norma speciala",
    "lex_posterior": "Se aplica norma mai recenta",
    "lex_superior": "Se aplica norma superioara",
}
```

#### Apply maps at bypass points

**Line 334** (governing_norm_status):
```python
gns = issue.get("governing_norm_status", {})
translated_status = _GOVERNING_NORM_MAP.get(gns.get("status"))
if translated_status:  # None means don't output (PRESENT)
    parts.append(f"    Norma guvernanta: {translated_status}")
    if gns.get("explanation"):
        parts.append(f"      Detalii: {gns['explanation']}")
```

**Line 317** (exception condition_status_summary):
```python
for ex in issue["exceptions_checked"]:
    status = _EXCEPTION_STATUS_MAP.get(
        ex.get("condition_status_summary", ""),
        ex.get("condition_status_summary", "")
    )
    parts.append(f"      {ex['exception_ref']} — {status} — {ex.get('impact', '')}")
```

**Line 321** (conflicts resolution_rule):
```python
c = issue["conflicts"]
rule = _CONFLICT_RESOLUTION_MAP.get(
    c.get("resolution_rule", "UNRESOLVED"),
    c.get("resolution_rule", "UNRESOLVED")
)
parts.append(f"    Conflict: {rule} — {c.get('rationale', '')}")
```

**Line 303** (blocking_unknowns): Replace condition IDs with actual condition text from `condition_table`:
```python
if summary.get("blocking_unknowns"):
    # Look up condition text from condition_table
    ct_lookup = {ct["condition_id"]: ct.get("condition_text", ct["condition_id"])
                 for ct in issue.get("condition_table", []) if ct.get("condition_id")}
    blocking_texts = [ct_lookup.get(cid, cid) for cid in summary["blocking_unknowns"]]
    parts.append(f"    Conditii nerezolvate: {'; '.join(blocking_texts)}")
```

**Line 328** (temporal_risks): Check structure and translate:
```python
if ta.get("temporal_risks"):
    for risk in ta["temporal_risks"]:
        if isinstance(risk, dict):
            parts.append(f"    Risc temporal: {risk.get('description', str(risk))}")
        else:
            parts.append(f"    Risc temporal: {risk}")
```

#### Defense-in-depth sanitizer

Add a check function called after `_build_step7_context` returns:

```python
_FORBIDDEN_TERMS = {
    "SATISFIED", "NOT_SATISFIED", "LIBRARY_GAP", "FACTUAL_GAP",
    "ARTICLE_IMPORT", "USER_INPUT", "GOVERNING_NORM_INCOMPLETE",
    "GOVERNING_NORM_MISSING", "UNRESOLVED", "RISC NEDETERMINAT",
}

def _warn_untranslated_terms(ctx: str) -> None:
    for term in _FORBIDDEN_TERMS:
        if term in ctx:
            logger.warning(f"Untranslated pipeline term '{term}' in Step 14 context")
```

**Files:**
- `pipeline_service.py` lines 211-271 (add maps), 303 (blocking_unknowns), 317 (exceptions), 321 (conflicts), 328 (temporal_risks), 334 (governing_norm_status)

**Cost impact:** Zero.

---

## Cost Optimization

### Dynamic max_tokens for Step 12

```python
if state.get("complexity") == "COMPLEX":
    max_tokens = 12288
else:
    max_tokens = 8192
```

**File:** `pipeline_service.py` line 483 (Step 12 `call_claude`)

### Projected savings

| Source | Current | After fix | Savings |
|--------|---------|-----------|---------|
| Step 12 runs twice | ~$0.15 | $0 | ~$0.15 |
| Step 12 output tokens (STANDARD) | 4096+ | Scaled | ~$0.01-0.02 |
| Better retrieval = less noise | Variable | Reduced | ~$0.01-0.02 |
| **Total projected cost** | **$0.36** | **$0.15-0.22** | **$0.14-0.21** |
| **Total projected time** | **238s** | **100-130s** | **~110s** |

---

## Implementation Order

```
Batch 1 (parallel — no dependencies between them):
  P1:    LA-S1 prompt rewrite (hypothetical anchoring decision gate)
  P5+P6: Candidate articles in Step 1 schema + direct lookup in Step 7
         + min_per_law=3 in reranker
  P8:    Translation map completion (5 bypass points + sanitizer)

Batch 2 (depends on P1 being done — correct dates required):
  P3+P4: Move version selection into Step 2, simplify Step 6 to binding
         + update Step 3 to use version availability from Step 2

Cost optimization (can be in either batch):
  Dynamic max_tokens for Step 12
```

**P2 and P7 have no implementation tasks** — they are fixed by P1 and P5+P6 respectively.

---

## Files Modified

| File | Changes |
|------|---------|
| `prompts/LA-S1-issue-classifier.txt` | P1: rewrite anchoring section; P5A: add candidate_articles to schema |
| `pipeline_service.py` | P3: add DB lookups to Step 2; P4: simplify Step 6; P5B: direct lookup in Step 7; P8: translation maps + sanitizer; cost: dynamic max_tokens |
| `reranker_service.py` | P5C: min_per_law=3 default |
| `law_mapping.py` | P3: accept version availability from Step 2 |

## Verification

After all fixes, run the same test question. Expected:
- Step 1: all dates = TODAY or TODAY+1yr, temporal_rules correct
- Step 2: all versions = current (hypothetical question)
- Step 7: candidate articles (Art. 241, 295, 238, 72, 73, 144, 169) in retrieval pool
- Step 9: each PRIMARY law has 3+ articles
- Step 12: runs ONCE, all issues have operative articles
- Step 13: NOT triggered
- Step 14: no internal terminology in answer
- Cost: $0.15-0.22
- Time: 100-130s
