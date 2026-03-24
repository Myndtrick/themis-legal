# Legal Accuracy Fixes — Design Spec

**Date:** 2026-03-24
**Goal:** Fix all identified risks where the system could misrepresent Romanian law, apply wrong versions, miss exceptions, or give users false confidence in incorrect answers.
**Scope:** Backend pipeline, prompts, frontend presentation. No new features — only correctness fixes.

---

## Critical Fixes

### C1. Restore date extraction in the pipeline

**Problem:** `_step1_issue_classification` hardcodes `primary_date = today`. The date extraction prompt (LA-S2) exists but is never called. Questions about past or future dates get answered with today's law version.

**Fix:** Re-enable date extraction as a substep after issue classification.
- Call Claude with the LA-S2 prompt after Step 1 completes.
- Use the extracted `primary_date` for version selection in Step 3.
- If no date is extractable, default to today (current behavior) but add a flag: "No specific date detected — using current law versions."
- Pass the extracted date context to Step 7 so the answer generation prompt can reference it.

**Files:** `pipeline_service.py` (add `_step1b_date_extraction` function, wire into pipeline)

---

### C2. Cross-law cross-reference resolution

**Problem:** `article_expander.py` only resolves `art. N` references within the same `law_version_id`. References to articles in other laws are silently ignored.

**Fix:** Extend the cross-reference parser to detect inter-law references and resolve them.

**Pattern recognition to add:**
- `art. N din Codul Civil` / `art. N din Legea nr. M/YYYY` — explicit law references
- `art. N din legea societăților` — popular-name references (use `legal_aliases.py` to resolve)
- `art. N C.civ.` / `art. N C.pen.` — abbreviated code references

**Resolution logic:**
1. Parse the referenced law identifier from the text.
2. Look up the law in the database (by number/year or alias).
3. Use the version selected in Step 3 for that law (if available), or the current version.
4. Fetch the referenced article from that version.
5. If the referenced law is not in the database, skip silently (don't break the pipeline).

**Constraint:** Only follow one level of cross-references (no recursive expansion) to avoid explosion.

**Files:** `article_expander.py` (new function `_extract_cross_law_references`), `legal_aliases.py` (use for popular-name resolution)

---

### C3. Expand domain-to-law mapping and handle unknown domains

**Problem:** `law_mapping.py` has no entries for `real_estate`, `data_protection`, `eu_law`, `procedural`, or `other`. Unknown domains return empty mapping, so zero laws are searched.

**Fix:**

Add missing domain mappings:
- `real_estate`: Primary = Codul Civil 287/2009 (Book III — property rights). Secondary = Legea 7/1996 (cadastre).
- `data_protection`: Primary = Legea 190/2018 (GDPR implementation). Secondary = Codul Civil 287/2009.
- `procedural`: Primary = Codul de Procedură Civilă 134/2010. Secondary = Codul Civil 287/2009.
- `eu_law`: Primary = none (EU law questions are too varied). Secondary = Codul Civil 287/2009. Flag: "EU law questions may require importing specific transposition laws."
- `other`: Primary = Codul Civil 287/2009 (gap-filler). Flag: "Domain not specifically mapped — using Civil Code as general framework."

Also add multi-domain support: allow Step 1 (issue classification) to return a secondary domain. Step 2 merges the law sets from both domains, deduplicating. This requires a small prompt change to LA-S1 to output `secondary_domain` field.

**Files:** `law_mapping.py` (add new domain entries, add `merge_domains` helper), `pipeline_service.py` (call mapping for secondary domain if present), LA-S1 prompt (add `secondary_domain` output field)

---

### C4. Reranker: use full article text (not 512-char truncation)

**Problem:** The reranker fallback truncates articles to 512 characters, losing content in longer articles.

**Fix:** Remove the hard truncation. The `cross-encoder/ms-marco-MiniLM-L-6-v2` model has a 512-token input limit (not character limit), and the tokenizer handles truncation internally. Pass full text and let the model's tokenizer handle it — this way at least the model sees the full first ~512 tokens rather than ~512 characters (which is fewer tokens).

Alternatively, if performance is a concern: chunk long articles into overlapping 512-token segments, score each, and use the max score. This ensures the reranker sees all parts of the article.

**Recommended approach:** Simple fix first — pass full text, let tokenizer truncate. Monitor if this is sufficient. The chunking approach is a follow-up if needed.

**Files:** `reranker_service.py` (remove `[:512]` truncation)

---

## High-Priority Fixes

### H1. Flag abrogated articles in retrieval results

**Problem:** Articles marked "Abrogat" in their text are retrieved and cited like valid articles. No semantic flag distinguishes them.

**Fix:**
1. During law import (in `leropa_service.py` or `pipeline_service.py`), detect abrogated articles by checking if `full_text` starts with "Abrogat" or "(Abrogat)" or if article has an amendment note indicating abrogation.
2. Add an `is_abrogated` boolean field to the `Article` model.
3. In Step 4 (retrieval), include abrogated articles in results but mark them with `is_abrogated: true`.
4. In Step 6 (article selection), include abrogation status in the article summary sent to Claude: `[ABROGATED]` prefix.
5. In Step 7 (answer generation), Claude's context should mark abrogated articles clearly so it knows not to cite them as current law.
6. Migration: backfill `is_abrogated` for all existing articles by scanning `full_text` for abrogation patterns.

**Files:** `models/law.py` (add field), `leropa_service.py` (detect on import), `pipeline_service.py` (Steps 4, 6, 7 — pass flag), migration script

---

### H2. Stop conflating amendment notes with article text in embeddings

**Problem:** Amendment metadata is embedded alongside article text, causing retrieval to match on amendment metadata rather than article content.

**Fix:**
1. In `chroma_service.py`, index only `article.full_text` — do NOT append amendment notes.
2. In `bm25_service.py`, index only article text — do NOT append amendment notes.
3. Store amendment metadata in ChromaDB's metadata fields instead (e.g., `amendment_laws`, `amendment_dates`) so it can be used for filtering but doesn't pollute semantic search.
4. Re-index all existing articles after this change.

**Files:** `chroma_service.py` (remove amendment concatenation), `bm25_service.py` (remove amendment concatenation), re-indexing script

---

### H3. Surface version fallback warnings in the main answer

**Problem:** When Step 3 can't find a version for the requested date and falls back to the current version, the warning only appears in the reasoning panel, not in the answer.

**Fix:**
1. In Step 7 context building, if `version_notes` contains fallback warnings, prepend them to the FLAGS AND WARNINGS section (already exists).
2. In the LA-S7 answer prompts, add instruction: "If FLAGS contain version fallback warnings, you MUST mention this in the `version_logic` field — explain that the system used a different version than the user's date implied, and what this means for the answer's reliability."
3. In the frontend, if `version_logic` contains a fallback mention, render it prominently (not just in details).

**Files:** `pipeline_service.py` (ensure flags flow to Step 7), LA-S7 prompts (add instruction), frontend `answer-detail.tsx` (surface version_logic prominently when it contains warnings)

---

### H4. Strengthen the `[General]` source label handling

**Problem:** `[General]` sources look similar to `[DB]` sources in the UI, creating false equivalence.

**Fix:**
1. In the frontend sources table, add a visual warning icon next to `[General]` sources and a tooltip: "This information comes from AI training data, not from verified law text. It may be outdated or incorrect."
2. In the frontend sources table, add a stronger visual warning for `[Unverified]` sources.
3. In the answer prompts (LA-S7 variants), add: "When you cite [General] sources, always include a qualifier like 'Based on general legal knowledge (not verified against current law text)' in the statement."

**Files:** Frontend sources display component, LA-S7 prompt variants

---

## Moderate Fixes

### M1. Expand BM25 synonym groups

**Problem:** Only 13 expansion groups. Many common Romanian legal terms are missing.

**Fix:** Add synonym expansions for:
- `concediu` → types of leave
- `reziliere` / `rezolutiune` → termination concepts
- `locatar` / `chirias` → tenant terms
- `angajat` / `salariat` → employee terms
- `patronat` / `angajator` → employer terms
- `dobanda` → interest terms
- `ipoteca` / `garantie` → security interest terms
- `mostenire` / `succesiune` → inheritance terms
- `procura` / `imputernicire` → power of attorney terms
- `cauzalitate` / `raspundere` → liability terms

Target: ~30 expansion groups covering the most common legal terminology variations.

**Files:** `bm25_service.py` (_BM25_EXPANSIONS dict)

---

### M2. Add more entity types to targeted search

**Problem:** Only SRL, SA, PFA covered. Missing SCS, SNC, SCA, ONG, cooperative, etc.

**Fix:** Add entity keywords for:
- `SCS` (societate in comandita simpla)
- `SNC` (societate in nume colectiv)
- `SCA` (societate in comandita pe actiuni)
- `ONG` / `asociatie` (non-profit association)
- `fundatie` (foundation)
- `cooperativa` (cooperative)

Update the `_ENTITY_KEYWORDS` dict in `pipeline_service.py` and the LA-S1 prompt to recognize these entity types.

**Files:** `pipeline_service.py` (_ENTITY_KEYWORDS), LA-S1 prompt

---

### M3. Make the disclaimer more visible

**Problem:** Disclaimer is 10px light gray — nearly invisible.

**Fix:** Increase to `text-xs` (12px), change color to `text-gray-600`, add a subtle border or background. The disclaimer should be readable without effort while not dominating the UI.

**Files:** Frontend `message-bubble.tsx`

---

### M4. Increase conversation history context

**Problem:** History is truncated to 200 chars per message in Step 1, losing facts the user already provided.

**Fix:**
- Increase truncation limit to 500 characters per message in Step 1.
- Keep the 5-message window for Step 1 (classification doesn't need full history).
- In Step 7 (answer generation), ensure full message content is passed (already the case — just verify).

**Files:** `pipeline_service.py` (_step1_issue_classification, line 322)

---

## Design-Level Items (deferred — noted for future work)

These require significant architectural changes and are out of scope for this fix batch:

- **Norme metodologice** (implementation norms) — requires a "paired document" concept in the data model
- **CCR decisions** — requires a new data source and annotation system
- **ICCJ RIL/HP decisions** — requires binding interpretation overlay on articles
- **Forma republicata vs. forma consolidata** — requires version type distinction in the data model

---

## Implementation Order

1. **C1** (date extraction) — highest impact, self-contained
2. **C3** (domain mapping + unknown domain fallback) — prevents zero-retrieval scenarios
3. **C4** (reranker truncation) — one-line fix
4. **H2** (stop conflating amendments in embeddings) — requires re-indexing
5. **H1** (flag abrogated articles) — requires migration + pipeline changes
6. **C2** (cross-law cross-references) — complex parser work
7. **H3** (surface version warnings) — prompt + frontend changes
8. **H4** (strengthen General label) — prompt + frontend changes
9. **M1-M4** (moderate fixes) — incremental improvements

## Testing Strategy

- Each fix should be tested with specific Romanian law questions that exercise the fixed path.
- C1: Test with "In 2018, was X legal?" — verify the 2018 version is selected.
- C2: Test with a question about Legea 31/1990 Art. 196 (which references Civil Code) — verify Civil Code articles are fetched.
- C3: Test with a real estate question — verify retrieval is not empty.
- H1: Test with a law containing abrogated articles — verify they're flagged in the answer.
