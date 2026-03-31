# Pipeline Repair v2 — Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 10 interrelated pipeline problems to ensure legally accurate answers presented in natural language for any question domain, law, or temporal scenario — while reducing cost by ~35-40% and time by ~30%.

**Architecture:** The pipeline is a 15-step sequential flow in `pipeline_service.py` (~3000 lines). Fixes span the answer template, retrieval validation, prompt trimming, Step 12/13 restructuring, and ChromaDB indexing. No new LLM calls are added; one redundant LLM call is eliminated in most cases.

---

## Problem Inventory

| ID | Problem | Severity | Root Cause |
|----|---------|----------|------------|
| P1 | User-facing answer exposes internal pipeline terminology | CRITICAL | Answer template + context builder pass raw RL-RAP terms to Step 14 |
| P2 | Zero articles from PRIMARY law (Legea 31/1990) after reranking | CRITICAL | ChromaDB indexing gap (version 54 not indexed) + no retrieval safety net |
| P3 | Wrong criminal law articles applied (Art. 175/297 instead of 272/238) | CRITICAL | Downstream of P2 — correct articles never in context |
| P4 | ISSUE-4 (conflict of interest) disappeared from classification | HIGH | LA-S1 prompt grew ~40 lines, causing Claude to consolidate issues |
| P5 | Version MISMATCH detected by Step 12 but silently ignored | MEDIUM | No code reads `temporal_applicability.version_matches` from RL-RAP output |
| P6 | Step 2 output display unchanged despite repurposing | LOW | `output_summary` format not updated |
| P7 | Step 12 runs twice, doubling cost (~$0.12 extra per COMPLEX query) | HIGH | Step 13 re-runs Step 12 from scratch after fetching missing articles |
| P8 | ChromaDB indexing gaps are systemic (8 law versions missing) | HIGH | Import-time indexing failed silently for recent versions |
| P9 | No validation that each PRIMARY law has articles after retrieval | HIGH | Pipeline never checks per-law article counts post-retrieval |
| P10 | 85% of retrieved articles unused (17/20 not cited) | MEDIUM | All articles passed at full length regardless of relevance to analysis |

---

## P1: Answer Template Rewrite

### What changes

**Files:**
- `prompts/LA-S7-answer-template.txt` — rewrite subsumption presentation and terminology sections
- `app/services/pipeline_service.py` — modify `_build_step7_context` (lines 250-309)

### Context builder changes (`_build_step7_context`)

The function currently passes raw RL-RAP terminology directly into Step 14's input. Change the terminology translation in the RL-RAP section:

**Current (line 270-271):**
```
C1: condition_text — SATISFIED (evidence: F1: fact)
```

**New:**
```
C1: condition_text — Condiție îndeplinită (fapt: F1: fact)
```

Translation map for condition statuses passed to Step 14:
- `SATISFIED` → `Condiție îndeplinită`
- `NOT_SATISFIED` → `Condiție neîndeplinită`
- `UNKNOWN` → `Informație lipsă`

Translation map for uncertainty source types:
- `LIBRARY_GAP: detail` → `Articol indisponibil: detail`
- `FACTUAL_GAP: detail` → `Informație lipsă din întrebare: detail`
- `LEGAL_AMBIGUITY: detail` → `Chestiune juridică interpretabilă: detail`

Remove `resolvable_by` hints (ARTICLE_IMPORT, USER_INPUT, LEGAL_INTERPRETATION) — these are system-level, not for the answer.

Translation map for subsumption summary:
- `norm_applicable: YES` → `Norma se aplică`
- `norm_applicable: NO` → `Norma nu se aplică`
- `norm_applicable: CONDITIONAL` → `Aplicabilitate condiționată`
- `blocking_unknowns` → `Condiții nerezolvate`

Remove the `certainty_level` label from the context — instead pass a natural sentence:
- `CERTAIN` → `Concluzia este fermă.`
- `PROBABLE` → `Concluzia este probabilă, cu rezerve minore.`
- `CONDITIONAL` → `Concluzia depinde de informații lipsă.`
- `UNCERTAIN` → `Analiza este incompletă — concluzie nesigură.`

### Answer template changes (`LA-S7-answer-template.txt`)

**Replace lines 27-49** (subsumption presentation) with:

```
PRESENTING LEGAL ANALYSIS (REQUIRED for each norm cited):
When presenting a legal provision, show how it applies to the user's specific facts.
For each norm, explain in natural language:
1. What the law requires (the conditions for applicability)
2. Which conditions are met based on the user's facts, citing the specific facts
3. Which conditions cannot be verified and what information would be needed
4. The conclusion given the condition analysis

Write as a lawyer explaining to a client. Use natural Romanian sentences, not tables
or checklists. The reader should understand the legal reasoning without any technical
or system knowledge.

Example — GOOD:
"Art. 72 din Legea 31/1990 stabilește obligația administratorului de a acționa cu
prudența unui bun administrator. În cazul dvs., transferul de fonduri către o entitate
controlată indirect, fără aprobarea asociaților, reprezintă o încălcare a acestei
obligații. Totuși, pentru a stabili răspunderea civilă, trebuie demonstrat și
prejudiciul cauzat societății — informație care nu rezultă din datele furnizate."

PROHIBITED TERMS — never use these in the answer:
SATISFIED, NOT_SATISFIED, UNKNOWN, LIBRARY_GAP, FACTUAL_GAP, ARTICLE_IMPORT,
USER_INPUT, CONDITIONAL (as a label), CERTAIN (as a label), subsumption,
condition_table, operative_articles, norm_applicable, blocking_unknowns,
LEGAL_INTERPRETATION, governing_norm_status, RISC NEDETERMINAT (as a standalone label).

Do NOT use ✅, ❓, ✓, ✗, or similar symbols in the answer.
```

**Replace lines 120-128** (risk labels) with:

```
Risk communication must be woven into the analysis narrative:
- When risk is clear and all conditions are met: state the risk directly.
  "Administratorul răspunde personal conform art. X. Riscul este major."
- When risk depends on unknown facts: state it conditionally.
  "Dacă se dovedește prejudiciul, administratorul ar putea răspunde personal,
  riscul fiind potențial major."
- When analysis is incomplete: state what cannot be determined.
  "Pe baza informațiilor disponibile, nu se poate stabili cu certitudine dacă
  există un risc de răspundere penală."

Do NOT use standalone risk labels like "**Risc: MAJOR**" or "**Risc nedeterminat**"
as section headers. Integrate risk assessment into the narrative.
```

**Keep lines 94-110** (uncertainty communication) but add at the top:

```
IMPORTANT: The uncertainty types below guide YOUR reasoning about how to present
information. The TYPE NAMES themselves (FACTUAL_GAP, LIBRARY_GAP, LEGAL_AMBIGUITY)
must NEVER appear in the answer text. Use the natural language patterns shown below.
```

**Keep lines 130-138** (status labels NECONFORM etc.) — these are valid Romanian legal terms, not pipeline jargon. But add:

```
These labels are conclusions, not formatting. Use them within sentences, not as
standalone tags. Example: "Situația este potențial contestabilă, deoarece..."
not "Status: POTENȚIAL CONTESTABIL".
```

---

## P2 + P8: ChromaDB Indexing Fix

### What changes

**Files:**
- `app/services/chroma_service.py` — add `verify_index_completeness` function
- `app/services/leropa_service.py` — add post-index validation in import flow
- New: one-time re-index script (or management command)

### Immediate re-index

Re-index all 8 missing law versions into ChromaDB:

| Law | Version ID | Articles |
|-----|-----------|----------|
| 31/1990 | 54 | 467 |
| 651/2014 | 317 | 60 |
| 679/2016 | 319 | 101 |
| 1907/2006 | 320 | 142 |
| 2065/2022 | 326 | 95 |
| 1925/2022 | 328 | 55 |
| 1689/2024 | 329 | 115 |

Run via Python script or management command calling `index_law_version(db, law_id, version_id)` for each.

### Import-time validation

In `leropa_service.py`, after each `chroma_index(db, law.id, v.id)` call (lines 738-743, 849-851, 1000-1006), add validation:

```python
indexed_count = chroma_index(db, law.id, v.id)
expected_count = db.query(Article).filter(Article.law_version_id == v.id).count()
if indexed_count < expected_count:
    logger.error(
        f"ChromaDB indexing incomplete for {law.law_number}/{law.law_year} "
        f"v{v.id}: indexed {indexed_count}/{expected_count} articles"
    )
    # Retry once
    indexed_count = chroma_index(db, law.id, v.id)
    if indexed_count < expected_count:
        logger.error(f"ChromaDB retry also failed: {indexed_count}/{expected_count}")
```

### Startup health check

Add `verify_index_completeness(db)` to `chroma_service.py`:

```python
def verify_index_completeness(db: Session) -> list[dict]:
    """Compare current versions' DB article counts against ChromaDB counts.
    Returns list of mismatches for logging."""
    mismatches = []
    # Query all current versions with article counts
    current_versions = (
        db.query(LawVersion, func.count(Article.id))
        .join(Article)
        .filter(LawVersion.is_current == True)
        .group_by(LawVersion.id)
        .all()
    )
    collection = _get_collection()
    for version, db_count in current_versions:
        chroma_result = collection.get(where={"law_version_id": version.id})
        chroma_count = len(chroma_result["ids"])
        if chroma_count == 0 and db_count > 0:
            mismatches.append({
                "law_version_id": version.id,
                "law_id": version.law_id,
                "db_count": db_count,
                "chroma_count": 0,
                "status": "MISSING",
            })
    return mismatches
```

Call this at app startup (in `main.py` or similar) and log any mismatches as warnings. Do NOT auto-reindex at startup — just warn.

---

## P9: Post-Retrieval Article Coverage Validation

### What changes

**Files:**
- `app/services/pipeline_service.py` — extend Step 11 (article partitioning, around line 1020) with coverage check

### Logic

After article partitioning completes, check coverage:

```python
def _validate_article_coverage(state: dict, db: Session) -> dict:
    """Ensure each issue has articles from all its applicable laws.
    If a law has 0 articles for an issue, fetch directly from DB via BM25."""
    from app.services.bm25_service import search_bm25
    from collections import Counter

    issue_articles = state.get("issue_articles", {})
    issue_versions = state.get("issue_versions", {})
    coverage_fixes = []

    for issue in state.get("legal_issues", []):
        iid = issue["issue_id"]
        arts = issue_articles.get(iid, [])

        # Count articles per law for this issue
        law_counts = Counter(
            f"{a.get('law_number', '')}/{a.get('law_year', '')}" for a in arts
        )

        for law_key in issue.get("applicable_laws", []):
            if law_counts.get(law_key, 0) > 0:
                continue

            # Zero articles from this law — attempt direct DB fetch
            iv_key = f"{iid}:{law_key}"
            iv = issue_versions.get(iv_key, {})
            if not iv:
                continue

            version_id = iv["law_version_id"]
            fetched = search_bm25(db, state["question"], [version_id], limit=5)

            if fetched:
                for art in fetched:
                    art["_coverage_fix"] = True
                issue_articles.setdefault(iid, []).extend(fetched)
                coverage_fixes.append(
                    f"{iid}: {law_key} had 0 articles — fetched {len(fetched)} via BM25"
                )
                state["flags"].append(
                    f"{iid}: {law_key} lipsea din rezultatele căutării — "
                    f"s-au adăugat {len(fetched)} articole direct din baza de date"
                )

    state["issue_articles"] = issue_articles

    # Also add to retrieved_articles so Step 14 context builder can render them
    for issue in state.get("legal_issues", []):
        iid = issue["issue_id"]
        for art in issue_articles.get(iid, []):
            if art.get("_coverage_fix"):
                state.setdefault("retrieved_articles", []).append(art)

    return state
```

Note: articles added by the coverage check must be marked with `art["_coverage_fix"] = True` before appending to `issue_articles`, so we can identify them and avoid duplicating articles that were already in `retrieved_articles`.

Call this immediately after the existing partitioning logic (after line 1023), before Step 12 starts.

### Why BM25 and not ChromaDB

BM25/FTS5 is confirmed to have all articles for all versions (including version 54 of 31/1990). ChromaDB may have indexing gaps (P8). Using BM25 as the fallback ensures the coverage check works even when ChromaDB is incomplete.

---

## P3: Wrong Criminal Articles

### What changes

No code changes needed beyond P2+P8+P9.

### Why

The wrong articles (Art. 175, 297 — public servant provisions) were retrieved because the correct articles (Art. 272, 238 — private sector provisions) were never in the candidate pool. With P8 fixing ChromaDB indexing and P9 ensuring coverage, the correct articles will be available for retrieval and reranking.

Step 12 already correctly identified that Art. 175 doesn't apply ("NOT SATISFIED: Administrator al unui SRL privat nu îndeplinește condițiile din art. 175"). The reasoning was correct — the input was wrong.

---

## P4: LA-S1 Prompt Trim

### What changes

**Files:**
- `prompts/LA-S1-issue-classifier.txt`

### Trim sections

**HYPOTHETICAL SCENARIO ANCHORING (lines 109-120)** — reduce from 12 lines to 5:

```
HYPOTHETICAL SCENARIO ANCHORING (CRITICAL):
When the question uses conditional language ("Dacă...", "în cazul în care...")
or describes a scenario without specific past dates, anchor the first event
to TODAY'S DATE and compute subsequent events relative to it.
Past tense alone does NOT make a scenario historical — only explicit calendar
dates or historical references do.
```

Remove the worked example (it's redundant with the existing examples at lines 113-115 that demonstrate the same anchoring for this specific question).

**CRIMINAL LAW — TEMPUS REGIT ACTUM (lines 122-124)** — keep as-is (already 3 lines).

**FACT-LEVEL DATE DECOMPOSITION (lines 221-231)** — reduce from 11 lines to 4:

```
FACT-LEVEL DATE DECOMPOSITION:
Use "fact_dates" when a single issue involves multiple facts with different
relevant dates (e.g., a transfer on one date and insolvency opening on another).
If all facts share the same date, leave fact_dates as an empty array [].
```

**MITIOR LEX FLAG (lines 233-236)** — reduce from 5 lines to 2:

```
MITIOR LEX FLAG: For criminal issues referencing Codul Penal, set
"mitior_lex_relevant": true to flag potential applicability of a more favorable law.
```

### Add conflict of interest example

In ISSUE SEPARATION (after line 87), add one line to the example:

```
   - ISSUE-4: Conflict of interest obligations (governing norm: disclosure/approval requirements)
```

And add to the general separations list (after line 81):

```
   - Direct liability (breach of duty) vs Conflict of interest (violation of disclosure obligations)
```

### Net effect

Approximately -20 lines, +3 lines = net reduction of ~17 lines. Restores the prompt to a length where Claude can fully process the issue separation rules.

---

## P5: Version Mismatch Handling

### What changes

**Files:**
- `app/services/pipeline_service.py` — add check after Step 12 parse (around line 540)
- `app/services/pipeline_service.py` — update `_build_step7_context` temporal section

### After Step 12 parse

After `state["rl_rap_output"] = parsed` (line 526), add:

```python
# Surface version mismatches as flags
for issue in parsed.get("issues", []):
    ta = issue.get("temporal_applicability", {})
    if not ta.get("version_matches", True):
        risks = ta.get("temporal_risks", [])
        risk_text = "; ".join(risks) if risks else "versiunea utilizată nu corespunde datei evenimentului"
        state["flags"].append(f"{issue['issue_id']}: Necorelare versiune — {risk_text}")
```

### In `_build_step7_context`

When passing temporal info for an issue (around line 291-292), translate version mismatch into a caveat for Step 14:

```python
ta = issue.get("temporal_applicability", {})
if not ta.get("version_matches", True):
    parts.append(f"    ⚠ Versiunea legii utilizată nu corespunde exact datei evenimentului.")
    if ta.get("temporal_risks"):
        for risk in ta["temporal_risks"]:
            parts.append(f"    Risc temporal: {risk}")
```

---

## P6: Step 2 Display Update

### What changes

**Files:**
- `app/services/pipeline_service.py` line 1830

### Change

Replace:
```python
output_summary=f"primary_date={state.get('primary_date')}, date_type={state.get('date_type')}",
```

With:
```python
output_summary=f"date_type={state['date_type']}, fact_mappings={len(fact_version_map)}, versions_needed={len(versions_needed)}",
```

---

## P7: Eliminate Double Step 12

### What changes

**Files:**
- `app/services/pipeline_service.py` — restructure Step 13 logic (lines 1033-1099)

### New Step 13 logic

```python
# Step 13: Conditional Retrieval (flag-only, re-run only for governing norms)
if state.get("rl_rap_output"):
    missing = _check_missing_articles(state["rl_rap_output"])
    governing_norm_issues = []
    governing_norm_fetched = []

    # Identify issues with MISSING governing norms
    for issue in state["rl_rap_output"].get("issues", []):
        gns = issue.get("governing_norm_status", {})
        if gns.get("status") == "MISSING":
            governing_norm_issues.append(issue["issue_id"])
            gn_articles = _fetch_governing_norm(issue, state, db)
            if gn_articles:
                governing_norm_fetched.extend(gn_articles)

    # Fetch standard missing articles (non-governing)
    fetched = _fetch_missing_articles(missing, state, db) if missing else []

    all_fetched = fetched + governing_norm_fetched

    if all_fetched:
        # Add fetched articles to issue_articles / shared_context
        for art in all_fetched:
            added = False
            for iid, arts in state.get("issue_articles", {}).items():
                iv_key = f"{iid}:{art['law_number']}/{art['law_year']}"
                if iv_key in state.get("issue_versions", {}):
                    arts.append(art)
                    added = True
            if not added:
                state.setdefault("shared_context", []).append(art)

    # Re-run Step 12 ONLY if a governing norm was missing and is now found
    should_rerun = bool(governing_norm_fetched) and bool(governing_norm_issues)

    if should_rerun:
        state = _step6_8_legal_reasoning(state, db)
    # Flag any missing articles that were NOT successfully fetched
    if missing:
        fetched_refs = set()
        for a in all_fetched:
            fetched_refs.add(f"{a.get('law_number', '')}/{a.get('law_year', '')} art.{a.get('article_number', '')}")
        unfetched = [m for m in missing if m not in fetched_refs]
        if unfetched:
            state["flags"].append(
                f"Articole solicitate de analiză dar nedisponibile: {', '.join(unfetched)}"
            )

    # Log Step 13
    # ... (existing logging logic, update re_ran_reasoning to use should_rerun)
```

### Key behavior change

| Scenario | Before | After |
|----------|--------|-------|
| Step 12 finds LIBRARY_GAPs, articles in DB | Re-run Step 12 (full cost) | Fetch articles, add to Step 14 context only |
| Step 12 finds MISSING governing norm, found in DB | Re-run Step 12 (full cost) | Re-run Step 12 (justified — analysis changes) |
| Step 12 finds gaps, articles NOT in DB | Re-run Step 12 (wasted) | Flag for user, no re-run |
| No gaps | No Step 13 | No Step 13 |

### Expected impact

- Most COMPLEX queries: Step 12 runs once (P9 coverage check fills gaps beforehand)
- Governing norm missing: Step 12 runs twice (justified, rare with P9)
- Current test query: would run once (31/1990 articles filled by P9)
- Cost savings: ~$0.10-0.12 per COMPLEX query

---

## P10: Reduce Wasted Context in Step 14

### What changes

**Files:**
- `app/services/pipeline_service.py` — modify `_build_step7_context` article presentation (lines 310-337)

### Tiered article presentation

After Step 12, articles fall into three categories based on the RL-RAP output:

**Tier 1 — Operative articles** (identified by Step 12 as legally operative):
Full article text with law reference and version date. These are the articles Step 12 actually analyzed.

**Tier 2 — Related articles** (in issue_articles but not operative):
Abbreviated: article number, law reference, version date, and first 200 characters of text. Enough for Step 14 to decide if it wants to cite them, without consuming full context.

**Tier 3 — Remaining articles** (shared_context or very low score):
One line each: `[Art. N] Law X/Y` — reference only for citation verification.

### Implementation

Replace the current article rendering in `_build_step7_context` (lines 310-337) with:

```python
# Identify operative article IDs from RL-RAP
operative_refs = set()
for issue in rl_rap.get("issues", []):
    for oa in issue.get("operative_articles", []):
        operative_refs.add(oa.get("article_ref", ""))

all_articles = [a for a in state.get("retrieved_articles", []) if a]

tier1 = []  # operative
tier2 = []  # related (in issue_articles but not operative)
tier3 = []  # remaining

# Collect all articles assigned to issues
issue_article_ids = set()
for arts in state.get("issue_articles", {}).values():
    for a in arts:
        issue_article_ids.add(a.get("article_id"))

for art in all_articles:
    art_ref = f"art.{art.get('article_number', '')}"
    if any(art_ref in ref for ref in operative_refs):
        tier1.append(art)
    elif art.get("article_id") in issue_article_ids:
        tier2.append(art)
    else:
        tier3.append(art)

# Render Tier 1 — full text
parts.append("\nARTICOLE RELEVANTE (analizate juridic):")
for art in tier1:
    law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
    parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}, versiune {art.get('date_in_force', '')}")
    parts.append(f"  {art.get('text', '')}")

# Render Tier 2 — abbreviated
if tier2:
    parts.append("\nARTICOLE SUPLIMENTARE (disponibile pentru citare):")
    for art in tier2:
        law_ref = f"{art.get('law_number', '')}/{art.get('law_year', '')}"
        text_preview = art.get("text", "")[:200].rsplit(" ", 1)[0] + "..." if len(art.get("text", "")) > 200 else art.get("text", "")
        parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}: {text_preview}")

# Render Tier 3 — reference only
if tier3:
    parts.append("\nALTE ARTICOLE RECUPERATE (referință):")
    refs = [f"Art. {a.get('article_number', '')} ({a.get('law_number', '')}/{a.get('law_year', '')})" for a in tier3]
    parts.append(f"  {', '.join(refs)}")
```

### Expected impact

For the test query (20 articles, 3 operative):
- Tier 1: 3 articles at full text (~3000 tokens)
- Tier 2: ~7 articles abbreviated (~700 tokens)
- Tier 3: ~10 articles as references (~100 tokens)
- Total: ~3800 tokens vs current ~8000 tokens
- **~50% reduction in Step 14 article context**

---

## Pipeline Step Summary (After All Fixes)

```
 1. Issue Classification (Claude)     — P4: trimmed prompt (-17 lines)
 2. Date Extraction (local)           — P6: updated display format
 3. Law Mapping (DB)                  — unchanged
 4. Version Currency Check (remote)   — unchanged
 5. Early Relevance Gate (local)      — unchanged
 6. Version Selection (DB)            — unchanged
 7. Hybrid Retrieval (BM25+semantic)  — P8: ChromaDB now fully indexed
 8. Graph Expansion (DB)              — unchanged
 9. Article Selection / Reranking     — unchanged (per-law guarantee active)
10. Relevance Check (local)           — unchanged
11. Article Partitioning (local+DB)   — P9: coverage validation added
12. Legal Reasoning (Claude)          — P5: version mismatch surfaced
13. Conditional Retrieval (DB)        — P7: flag-only, re-run only for governing norms
14. Answer Generation (Claude)        — P1: rewritten template; P10: tiered context
15. Citation Validation (local)       — unchanged
```

---

## Cost and Time Impact

### Current (COMPLEX query with library gaps)

| Step | Tokens In | Tokens Out | Time |
|------|-----------|------------|------|
| Step 1 (Classification) | 1,221 | 2,021 | 30.4s |
| Step 12 (Reasoning #1) | 13,083 | 3,865 | 58.4s |
| Step 13 (Re-run #2) | 16,827 | 3,260 | 46.3s |
| Step 14 (Answer) | 14,424 | 2,051 | 39.0s |
| **Total** | **45,555** | **11,197** | **~216s** |
| **Cost** | | | **~$0.30** |

### After fixes (same query)

| Step | Tokens In | Tokens Out | Time |
|------|-----------|------------|------|
| Step 1 (Classification) | ~1,100 | ~2,000 | ~28s |
| Step 12 (Reasoning, single) | ~14,000 | ~4,000 | ~60s |
| Step 13 (Flag only) | 0 | 0 | <1s |
| Step 14 (Answer, reduced) | ~9,000 | ~2,000 | ~30s |
| **Total** | **~24,100** | **~8,000** | **~120s** |
| **Cost** | | | **~$0.17** |

**Savings: ~43% cost, ~44% time**

### For SIMPLE queries (no change in Step 12/13)

Cost and time unchanged — SIMPLE queries already use the fast path with reduced retrieval and skip Step 12/13 re-runs.

---

## Verification Plan

### P1 verification
Run the test query. The answer must:
- Be in natural Romanian, readable by a non-lawyer
- Contain no internal terminology (grep for SATISFIED, LIBRARY_GAP, etc.)
- Explain conditions in sentences, not tables
- Integrate risk assessment into narrative

### P2 + P8 verification
```bash
python3 -c "
import chromadb
client = chromadb.PersistentClient(path='data/chroma')
col = client.get_or_create_collection(name='legal_articles')
for vid in [54, 317, 319, 320, 326, 328, 329]:
    count = len(col.get(where={'law_version_id': vid})['ids'])
    print(f'  Version {vid}: {count} articles')
"
```
All counts should match DB article counts.

### P9 verification
Run the test query. Step 11 output should show:
- Articles from ALL applicable laws for each issue
- If any law had 0 articles from retrieval, a flag explaining the direct DB fetch

### P4 verification
Run the test query. Step 1 should identify 4 issues:
- ISSUE-1: Civil liability (31/1990)
- ISSUE-2: Insolvency annulment (85/2014)
- ISSUE-3: Criminal exposure (286/2009)
- ISSUE-4: Conflict of interest (31/1990)

### P7 verification
Run the test query. Claude API Calls section should show:
- `legal reasoning`: 1 call (not 2)
- Exception: if governing norm was MISSING and found, 2 calls is acceptable

### P10 verification
Step 14 input should show:
- Operative articles at full text
- Related articles abbreviated
- Remaining articles as references only
- Total Step 14 input tokens should be ~9,000 (down from ~14,000)

### Full regression
Run 3 additional queries of different types:
1. SIMPLE query ("Care este capitalul social minim pentru un SRL?")
2. STANDARD query with explicit date
3. COMPLEX query in a different domain (e.g., employment + fiscal)

Verify all produce natural-language answers without internal terminology.

---

## Implementation Order

```
Batch 1 — Independent fixes (parallel):
  ├── P2+P8: ChromaDB re-index + import validation
  ├── P4: LA-S1 prompt trim
  └── P6: Step 2 display update

Batch 2 — Retrieval safety net:
  └── P9: Article coverage validation in Step 11

Batch 3 — Step 12/13 restructuring:
  ├── P7: Single Step 12 (conditional re-run only for governing norms)
  └── P5: Version mismatch surfacing

Batch 4 — Answer quality:
  ├── P1: Answer template rewrite + context builder translation
  └── P10: Tiered article context for Step 14
```

**Rationale:** Batch 1 fixes data issues (indexing, prompt, display). Batch 2 adds the safety net that Batch 3 depends on (P7 assumes P9 fills gaps before Step 12). Batch 4 is the answer quality layer that depends on everything else working correctly.
