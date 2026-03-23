# Structured Legal Retrieval Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the failing search-only article retrieval with a 7-step structured pipeline: Classification → Rule-based law mapping → Version selection → BM25 + semantic hybrid search → Neighbor expansion → Local reranking → Answer generation. Also fix the reasoning/details panel.

**Architecture:** Deterministic law mapping (no Claude) identifies applicable laws in 3 tiers. Hybrid retrieval (FTS5 + ChromaDB) finds candidate articles. Structural expansion adds neighbors and cross-references. Local cross-encoder reranks before sending top articles to Claude for answer generation.

**Tech Stack:** SQLite FTS5 (built-in), sentence-transformers CrossEncoder (already installed), existing ChromaDB + Claude API.

**Spec:** `docs/superpowers/specs/2026-03-23-structured-retrieval-pipeline-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/app/services/law_mapping.py` | Deterministic domain → law mapping with 3 tiers |
| `backend/app/services/bm25_service.py` | SQLite FTS5 index creation, syncing, querying |
| `backend/app/services/reranker_service.py` | Cross-encoder model loading and article scoring |
| `backend/app/services/article_expander.py` | Neighbor expansion + cross-reference extraction |

### Modified Files
| File | Change |
|------|--------|
| `backend/app/services/pipeline_service.py` | Replace Steps 3-7 with new structured retrieval steps |
| `backend/app/services/chroma_service.py` | Simplify — remove `_keyword_search`, keep semantic search only |
| `backend/app/routers/assistant.py` | Fix reasoning_data storage format |
| `backend/app/main.py` | Initialize FTS5 index on startup |
| `backend/prompts/LA-S1-issue-classifier.txt` | Add `legal_topic` + `entity_types` fields |

---

## Task 1: Fix Reasoning Data Format (Quick Win)

**Files:**
- Modify: `backend/app/routers/assistant.py:184-194`
- Modify: `backend/app/routers/assistant.py:275-285`

The "Show details" button doesn't work because the router stores raw reasoning dict but the frontend expects `{structured: ..., reasoning: ..., confidence: ..., flags: []}`.

- [ ] **Step 1: Fix reasoning_data in main message endpoint**

In `routers/assistant.py`, change both `add_message` calls (lines ~184-194 and ~275-285) to store the combined format:

```python
# Replace:
reasoning_data=json.dumps(final_reasoning, ensure_ascii=False)
    if final_reasoning else None,

# With:
reasoning_data=json.dumps({
    "structured": event.get("structured"),
    "reasoning": final_reasoning,
    "confidence": event.get("confidence"),
    "flags": event.get("flags", []),
}, ensure_ascii=False) if final_reasoning else None,
```

Apply this change to BOTH the main `send_message` endpoint and the `resume_paused_pipeline` endpoint.

- [ ] **Step 2: Verify the fix**

Run: Start backend, send a question, check that the stored message has combined format:
```bash
curl -s -X POST http://localhost:8000/api/assistant/sessions -d '{}' | ...
# Then send a message and check DB
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/assistant.py
git commit -m "fix: store combined structured + reasoning data for details panel"
```

---

## Task 2: Law Mapping Service (Rule-Based)

**Files:**
- Create: `backend/app/services/law_mapping.py`

- [ ] **Step 1: Create the law mapping service**

```python
# backend/app/services/law_mapping.py
"""
Deterministic mapping from legal domain + topic to applicable laws.
Three tiers: PRIMARY (directly answers), SECONDARY (subsidiarily),
CONNECTED (only if cross-referenced by primary articles).
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from app.models.law import Law


# Domain → law mapping. Each law is identified by (law_number, law_year).
# Only laws that exist in the database are included at runtime.
DOMAIN_LAW_MAP: dict[str, dict[str, list[dict]]] = {
    "corporate": {
        "primary": [
            {"law_number": "31", "law_year": 1990,
             "reason": "Legea societăților comerciale"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009,
             "reason": "Codul Civil — applies subsidiarily"},
        ],
        "connected": [],
    },
    "fiscal": {
        "primary": [
            {"law_number": "227", "law_year": 2015,
             "reason": "Codul Fiscal"},
        ],
        "secondary": [
            {"law_number": "207", "law_year": 2015,
             "reason": "Codul de Procedură Fiscală"},
        ],
        "connected": [],
    },
    "employment": {
        "primary": [
            {"law_number": "53", "law_year": 2003,
             "reason": "Codul Muncii"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009,
             "reason": "Codul Civil — applies subsidiarily"},
        ],
        "connected": [],
    },
    "contract_law": {
        "primary": [
            {"law_number": "287", "law_year": 2009,
             "reason": "Codul Civil — contract law"},
        ],
        "secondary": [],
        "connected": [],
    },
    "aml": {
        "primary": [
            {"law_number": "129", "law_year": 2019,
             "reason": "Legea AML/KYC"},
        ],
        "secondary": [],
        "connected": [],
    },
}


def map_laws_to_question(
    legal_domain: str,
    db: Session,
) -> dict[str, list[dict]]:
    """Map a classified question to applicable laws in 3 tiers.

    Returns only laws that actually exist in the database.
    If the domain has no mapping, returns empty tiers.
    """
    mapping = DOMAIN_LAW_MAP.get(legal_domain, {})
    result = {"tier1_primary": [], "tier2_secondary": [], "tier3_connected": []}

    for tier_key, result_key in [
        ("primary", "tier1_primary"),
        ("secondary", "tier2_secondary"),
        ("connected", "tier3_connected"),
    ]:
        for law_def in mapping.get(tier_key, []):
            db_law = (
                db.query(Law)
                .filter(
                    Law.law_number == law_def["law_number"],
                    Law.law_year == law_def["law_year"],
                )
                .first()
            )
            entry = {
                **law_def,
                "db_law_id": db_law.id if db_law else None,
                "in_library": db_law is not None,
                "title": db_law.title if db_law else law_def.get("reason", ""),
            }
            result[result_key].append(entry)

    return result
```

- [ ] **Step 2: Verify**

```bash
cd backend && uv run python -c "
from app.database import SessionLocal
from app.services.law_mapping import map_laws_to_question
db = SessionLocal()
result = map_laws_to_question('corporate', db)
for tier, laws in result.items():
    for l in laws:
        print(f'{tier}: {l[\"law_number\"]}/{l[\"law_year\"]} in_library={l[\"in_library\"]}')
db.close()
"
```
Expected: `tier1_primary: 31/1990 in_library=True`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/law_mapping.py
git commit -m "feat: add deterministic law mapping service (3 tiers)"
```

---

## Task 3: BM25 Search via SQLite FTS5

**Files:**
- Create: `backend/app/services/bm25_service.py`
- Modify: `backend/app/main.py` — init FTS5 on startup

- [ ] **Step 1: Create FTS5 service**

```python
# backend/app/services/bm25_service.py
"""
BM25 full-text search via SQLite FTS5.
Indexes article text + amendment notes for exact keyword matching.
BM25 naturally ranks short, focused articles higher than long articles
that happen to mention the same terms.
"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.law import Article, AmendmentNote, LawVersion

logger = logging.getLogger(__name__)


def ensure_fts_index(db: Session):
    """Create the FTS5 virtual table if it doesn't exist, then populate."""
    conn = db.get_bind().raw_connection()
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='articles_fts'"
    )
    if cursor.fetchone():
        conn.close()
        return

    logger.info("Creating FTS5 index for articles...")

    # Create the FTS5 virtual table (content-less — we store rowid only)
    cursor.execute("""
        CREATE VIRTUAL TABLE articles_fts USING fts5(
            article_text,
            law_version_id UNINDEXED,
            article_id UNINDEXED,
            tokenize='unicode61 remove_diacritics 2'
        )
    """)

    # Populate from articles table
    articles = db.query(Article).all()
    for art in articles:
        # Combine article text + amendment notes
        parts = [art.full_text or ""]
        for note in art.amendment_notes:
            if note.text:
                parts.append(note.text)
        combined = " ".join(parts)

        cursor.execute(
            "INSERT INTO articles_fts(rowid, article_text, law_version_id, article_id) VALUES (?, ?, ?, ?)",
            (art.id, combined, art.law_version_id, art.id),
        )

    conn.commit()
    conn.close()
    logger.info(f"FTS5 index created with {len(articles)} articles")


def rebuild_fts_index(db: Session):
    """Drop and recreate the FTS5 index."""
    conn = db.get_bind().raw_connection()
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS articles_fts")
    conn.commit()
    conn.close()
    ensure_fts_index(db)


def search_bm25(
    db: Session,
    query: str,
    law_version_ids: list[int] | None = None,
    limit: int = 15,
) -> list[dict]:
    """Search articles using BM25 ranking.

    FTS5 with 'remove_diacritics 2' handles ă/â/î/ș/ț automatically.
    BM25 naturally ranks short, focused articles higher.
    """
    conn = db.get_bind().raw_connection()
    cursor = conn.cursor()

    # Build the FTS5 query — split words and join with OR
    import re
    words = re.findall(r"[a-zA-ZăîâșțĂÎÂȘȚ]{3,}", query)
    if not words:
        conn.close()
        return []

    fts_query = " OR ".join(words)

    if law_version_ids:
        placeholders = ",".join("?" * len(law_version_ids))
        sql = f"""
            SELECT article_id, law_version_id, rank
            FROM articles_fts
            WHERE articles_fts MATCH ?
            AND law_version_id IN ({placeholders})
            ORDER BY rank
            LIMIT ?
        """
        params = [fts_query] + law_version_ids + [limit]
    else:
        sql = """
            SELECT article_id, law_version_id, rank
            FROM articles_fts
            WHERE articles_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        params = [fts_query, limit]

    try:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    except Exception as e:
        logger.warning(f"FTS5 search failed: {e}")
        rows = []
    finally:
        conn.close()

    # Fetch full article data
    results = []
    for article_id, law_version_id, rank in rows:
        art = db.query(Article).filter(Article.id == article_id).first()
        if not art:
            continue
        law = art.law_version.law
        version = art.law_version

        # Build text with amendments
        text_parts = [art.full_text]
        for note in art.amendment_notes:
            if note.text and note.text.strip():
                text_parts.append(f"[Amendment: {note.text.strip()}]")

        results.append({
            "article_id": art.id,
            "law_number": law.law_number,
            "law_year": str(law.law_year),
            "law_title": law.title[:200],
            "article_number": art.article_number,
            "date_in_force": str(version.date_in_force) if version.date_in_force else "",
            "is_current": str(version.is_current),
            "text": "\n".join(text_parts),
            "bm25_rank": rank,
            "source": "bm25",
        })

    return results
```

- [ ] **Step 2: Add FTS5 initialization to main.py startup**

In `main.py` lifespan, after `seed_defaults(db)`:
```python
from app.services.bm25_service import ensure_fts_index
ensure_fts_index(db)
```

- [ ] **Step 3: Verify BM25 finds Art. 4 and Art. 12**

```bash
cd backend && uv run python -c "
from app.database import SessionLocal
from app.services.bm25_service import ensure_fts_index, search_bm25
db = SessionLocal()
ensure_fts_index(db)
results = search_bm25(db, 'asociati numar limita SRL', law_version_ids=[2], limit=10)
for r in results:
    print(f'Art.{r[\"article_number\"]} (rank={r[\"bm25_rank\"]:.1f}) — {r[\"text\"][:80]}')
db.close()
"
```
Expected: Art. 4 and Art. 12 should appear in top 10 (BM25 favors short docs with search terms).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/bm25_service.py backend/app/main.py
git commit -m "feat: add BM25 search via SQLite FTS5 with diacritic support"
```

---

## Task 4: Article Expander (Neighbors + Cross-References)

**Files:**
- Create: `backend/app/services/article_expander.py`

- [ ] **Step 1: Create the article expander**

```python
# backend/app/services/article_expander.py
"""
Structural article expansion:
- Add neighbor articles from the same chapter (N-2 to N+2)
- Extract and fetch cross-referenced articles
- Add definition articles from the same section
"""
from __future__ import annotations
import re
import logging
from sqlalchemy.orm import Session
from app.models.law import Article, Law, LawVersion, StructuralElement

logger = logging.getLogger(__name__)


def expand_articles(
    db: Session,
    article_ids: list[int],
    neighbor_range: int = 2,
) -> list[int]:
    """Expand a set of article IDs with neighbors and cross-references.

    Returns a deduplicated list of article IDs including the originals.
    """
    expanded = set(article_ids)

    for art_id in article_ids:
        article = db.query(Article).filter(Article.id == art_id).first()
        if not article:
            continue

        # Add neighbors from the same structural section
        neighbors = _get_neighbors(db, article, neighbor_range)
        expanded.update(n.id for n in neighbors)

        # Extract cross-referenced articles
        xrefs = _extract_cross_references(db, article)
        expanded.update(xrefs)

    return list(expanded)


def _get_neighbors(
    db: Session,
    article: Article,
    range_: int = 2,
) -> list[Article]:
    """Get neighboring articles within the same structural section."""
    if article.structural_element_id:
        # Get articles in the same structural element, within order_index range
        return (
            db.query(Article)
            .filter(
                Article.law_version_id == article.law_version_id,
                Article.structural_element_id == article.structural_element_id,
                Article.order_index.between(
                    article.order_index - range_,
                    article.order_index + range_,
                ),
                Article.id != article.id,
            )
            .all()
        )
    else:
        # No structural element — get by order_index globally within the version
        return (
            db.query(Article)
            .filter(
                Article.law_version_id == article.law_version_id,
                Article.order_index.between(
                    article.order_index - range_,
                    article.order_index + range_,
                ),
                Article.id != article.id,
            )
            .all()
        )


def _extract_cross_references(
    db: Session,
    article: Article,
) -> list[int]:
    """Parse article text for cross-references and return referenced article IDs."""
    text = article.full_text or ""
    # Also check amendment notes
    for note in article.amendment_notes:
        if note.text:
            text += " " + note.text

    article_ids = []

    # Pattern: "art. 123" or "art. 123^1" — same law
    for match in re.finditer(r"art\.\s*(\d+(?:\^\d+)?)", text, re.IGNORECASE):
        ref_number = match.group(1)
        ref_art = (
            db.query(Article)
            .filter(
                Article.law_version_id == article.law_version_id,
                Article.article_number == ref_number,
            )
            .first()
        )
        if ref_art:
            article_ids.append(ref_art.id)

    return article_ids
```

- [ ] **Step 2: Verify neighbor expansion**

```bash
cd backend && uv run python -c "
from app.database import SessionLocal
from app.services.article_expander import expand_articles
from app.models.law import Article, LawVersion
db = SessionLocal()
# Get Art. 5 and see if expansion pulls in Art. 4
art5 = db.query(Article).join(LawVersion).filter(
    LawVersion.law_id == 1, LawVersion.is_current == True,
    Article.article_number == '5'
).first()
if art5:
    expanded = expand_articles(db, [art5.id])
    arts = db.query(Article).filter(Article.id.in_(expanded)).all()
    for a in sorted(arts, key=lambda x: x.order_index):
        print(f'Art.{a.article_number} (order={a.order_index})')
db.close()
"
```
Expected: Art. 3, 4, 5, 6, 7 should appear (neighbors of Art. 5).

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/article_expander.py
git commit -m "feat: add article expansion with neighbors and cross-references"
```

---

## Task 5: Reranker Service (Local Cross-Encoder)

**Files:**
- Create: `backend/app/services/reranker_service.py`

- [ ] **Step 1: Create the reranker service**

```python
# backend/app/services/reranker_service.py
"""
Local cross-encoder reranking using sentence-transformers.
Scores each article against the question for relevance.
Free, runs locally, ~80MB model, ~5ms per article.
"""
from __future__ import annotations
import logging
from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)

_model: CrossEncoder | None = None
MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def get_reranker() -> CrossEncoder:
    global _model
    if _model is None:
        logger.info(f"Loading cross-encoder model: {MODEL_NAME}")
        _model = CrossEncoder(MODEL_NAME)
        logger.info("Cross-encoder model loaded")
    return _model


def rerank_articles(
    question: str,
    articles: list[dict],
    top_k: int = 15,
) -> list[dict]:
    """Rerank articles by relevance to the question.

    Uses a cross-encoder model to score each (question, article) pair.
    Returns top_k articles sorted by score, with score added to each dict.
    """
    if not articles:
        return []

    model = get_reranker()

    # Build pairs for the model
    pairs = [(question, art["text"][:512]) for art in articles]  # truncate long articles

    # Score all pairs
    scores = model.predict(pairs)

    # Add scores to articles
    for art, score in zip(articles, scores):
        art["reranker_score"] = float(score)

    # Sort by score descending, take top_k
    articles.sort(key=lambda x: x["reranker_score"], reverse=True)
    return articles[:top_k]
```

- [ ] **Step 2: Verify reranker scores Art. 4 and Art. 12 highly**

```bash
cd backend && uv run python -c "
from app.services.reranker_service import rerank_articles
articles = [
    {'article_number': '4', 'text': 'Societatea cu personalitate juridică va avea cel puțin 2 asociați, în afară de cazul în care legea prevede altfel.'},
    {'article_number': '12', 'text': 'În societatea cu răspundere limitată, numărul asociaților nu poate fi mai mare de 50.'},
    {'article_number': '261', 'text': 'După aprobarea socotelilor și terminarea repartiției, registrele și actele societății în nume colectiv, în comandită simplă sau cu răspundere limitată vor fi depuse la oficiul registrului comerțului.'},
    {'article_number': '216', 'text': 'Acțiunile emise pentru majorarea capitalului social vor fi oferite spre subscriere, în primul rând acționarilor existenți.'},
]
question = 'intr-un SRL si intr-un SA, exista vreo limita minima sau maxima in ceea ce priveste nr de asociati/actionari?'
ranked = rerank_articles(question, articles, top_k=4)
for r in ranked:
    print(f'Art.{r[\"article_number\"]} score={r[\"reranker_score\"]:.4f} — {r[\"text\"][:60]}')
"
```
Expected: Art. 4 and Art. 12 should score highest.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/reranker_service.py
git commit -m "feat: add local cross-encoder reranker for article relevance scoring"
```

---

## Task 6: Rewire Pipeline — New Structured Retrieval Steps

**Files:**
- Modify: `backend/app/services/pipeline_service.py` — replace Steps 3-6 with new steps
- Modify: `backend/app/services/chroma_service.py` — simplify (remove `_keyword_search`)
- Modify: `backend/prompts/LA-S1-issue-classifier.txt` — add `legal_topic`, `entity_types`

This is the largest task. Replace the current Steps 3 (Claude law identification), 4 (coverage check), 5 (import permission), 6 (version selection) with the new structured retrieval.

- [ ] **Step 1: Update LA-S1 prompt to extract legal_topic and entity_types**

Add to the JSON output format in `LA-S1-issue-classifier.txt`:
```json
{
  "question_type": "A or B",
  "legal_domain": "<domain>",
  "legal_topic": "<specific topic, e.g., 'număr asociați', 'capital social minim', 'TVA'>",
  "entity_types": ["SRL", "SA"],
  "output_mode": "qa",
  "core_issue": "<reformulated>",
  "sub_issues": [],
  "classification_confidence": "HIGH",
  "reasoning": "<brief>"
}
```

- [ ] **Step 2: Create new pipeline step functions**

In `pipeline_service.py`, add these new functions (don't remove old ones yet):

```python
def _step2_law_mapping(state: dict, db: Session) -> dict:
    """Rule-based law mapping — no Claude call."""
    from app.services.law_mapping import map_laws_to_question
    mapping = map_laws_to_question(state["legal_domain"], db)
    state["law_mapping"] = mapping
    state["candidate_laws"] = []  # Build for backward compat
    for tier, laws in mapping.items():
        for law in laws:
            state["candidate_laws"].append({
                "law_number": law["law_number"],
                "law_year": law["law_year"],
                "role": tier.replace("tier1_", "").replace("tier2_", "").replace("tier3_", "").upper(),
                "source": "DB" if law["in_library"] else "General",
                "db_law_id": law.get("db_law_id"),
                "title": law.get("title", ""),
                "reason": law.get("reason", ""),
            })
    # ... log step, check missing primary laws, handle import ...
    return state


def _step4_hybrid_retrieval(state: dict, db: Session) -> dict:
    """BM25 + semantic search, per tier."""
    from app.services.bm25_service import search_bm25
    from app.services.chroma_service import query_articles

    all_articles = []
    seen_ids = set()

    for tier_key, n_results in [
        ("tier1_primary", 15),
        ("tier2_secondary", 10),
    ]:
        version_ids = []  # collect version IDs for this tier's laws
        for law in state["law_mapping"].get(tier_key, []):
            v = state.get("selected_versions", {}).get(
                f"{law['law_number']}/{law['law_year']}"
            )
            if v:
                version_ids.append(v["law_version_id"])

        if not version_ids:
            continue

        # BM25 search
        bm25_results = search_bm25(db, state["question"], version_ids, limit=n_results)

        # Semantic search
        semantic_results = query_articles(
            state["question"], law_version_ids=version_ids, n_results=n_results
        )

        # Merge and deduplicate
        for art in bm25_results + semantic_results:
            aid = art["article_id"]
            if aid not in seen_ids:
                seen_ids.add(aid)
                art["tier"] = tier_key
                all_articles.append(art)

    state["retrieved_articles_raw"] = all_articles
    return state


def _step5_expand(state: dict, db: Session) -> dict:
    """Expand with neighbors and cross-references."""
    from app.services.article_expander import expand_articles

    raw_ids = [a["article_id"] for a in state.get("retrieved_articles_raw", [])]
    expanded_ids = expand_articles(db, raw_ids)

    # Fetch any new articles not already in the raw results
    existing_ids = {a["article_id"] for a in state["retrieved_articles_raw"]}
    new_ids = [aid for aid in expanded_ids if aid not in existing_ids]

    if new_ids:
        from app.models.law import Article
        for art in db.query(Article).filter(Article.id.in_(new_ids)).all():
            law = art.law_version.law
            version = art.law_version
            text_parts = [art.full_text]
            for note in art.amendment_notes:
                if note.text:
                    text_parts.append(f"[Amendment: {note.text.strip()}]")

            state["retrieved_articles_raw"].append({
                "article_id": art.id,
                "article_number": art.article_number,
                "law_number": law.law_number,
                "law_year": str(law.law_year),
                "law_title": law.title[:200],
                "date_in_force": str(version.date_in_force) if version.date_in_force else "",
                "text": "\n".join(text_parts),
                "source": "expansion",
                "tier": "expansion",
            })

    return state


def _step6_rerank(state: dict, db: Session) -> dict:
    """Rerank articles using local cross-encoder."""
    from app.services.reranker_service import rerank_articles

    raw = state.get("retrieved_articles_raw", [])
    ranked = rerank_articles(state["question"], raw, top_k=15)
    state["retrieved_articles"] = ranked
    return state
```

- [ ] **Step 3: Rewire `run_pipeline` to use new steps**

Replace the step sequence in `run_pipeline()`:
- Step 1: `_step1_issue_classification` (keep, add legal_topic/entity_types parsing)
- Step 2: `_step2_law_mapping` (NEW — replaces old Step 3 Claude law identification)
- Step 3: `_step3_version_selection` (rename from old Step 6 — reuse as-is)
- Step 4: `_step4_hybrid_retrieval` (NEW — BM25 + semantic)
- Step 5: `_step5_expand` (NEW — neighbors + cross-refs)
- Step 6: `_step6_rerank` (NEW — local cross-encoder)
- Step 7: `_step7_answer_generation` (keep — uses state["retrieved_articles"])

Remove old Steps 3 (Claude law ID), 4 (coverage check), 5 (import permission).
Keep import permission logic inside Step 2 (law_mapping) — if a PRIMARY law is not in DB, flag it.

- [ ] **Step 4: Update `_build_reasoning_panel` for new steps**

The reasoning panel should reflect the new pipeline steps with the data from each step.

- [ ] **Step 5: Simplify chroma_service.py**

Remove `_keyword_search()` function and all its helpers (diacritic normalization, keyword expansion, scoring). Keep only:
- `get_collection()`, `index_law_version()`, `index_all()`, `remove_law_articles()`
- `query_articles()` — simplified to semantic search only (no `db` parameter, no keyword merge)

- [ ] **Step 6: Test end-to-end**

Send both test questions:
1. "Ce capital social trebuie un SRL la înființare?" → Should find 500 lei from amendment
2. "Într-un SRL și într-un SA, există vreo limită în ceea ce privește nr de asociați?" → Should cite Art. 4 (min 2), Art. 12 (max 50)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/app/services/chroma_service.py backend/prompts/LA-S1-issue-classifier.txt
git commit -m "feat: rewire pipeline with structured retrieval (BM25 + expand + rerank)"
```

---

## Task 7: Final Integration Test + Cleanup

- [ ] **Step 1: Test the details panel**

Send a question, then check the UI:
- "Show details" link should appear
- Click it → should show: Legal Basis, Version Logic, Sources, Pipeline Reasoning
- Pipeline Reasoning should show: laws identified (with tiers), coverage, versions selected

- [ ] **Step 2: Test with multiple questions**

Verify all test cases from the spec:
1. "Ce capital social trebuie un SRL la înființare?" → 500 lei
2. "Într-un SRL și SA, limita de asociați?" → Art. 4, Art. 12, Art. 13
3. "Care sunt obligațiile unui administrator de SRL?" → Art. 197, Art. 194
4. Follow-up "Dar într-un SA?" → reuses context

- [ ] **Step 3: Commit and tag**

```bash
git add -A
git commit -m "feat: complete structured retrieval pipeline v2"
```

---

## Verification

After all tasks complete, verify:

1. **Answer quality:** Both test questions get correct, cited answers
2. **Details panel:** "Show details" works and shows Legal Basis, Sources, Pipeline Reasoning
3. **Cost:** Check pipeline logs — should be ~$0.06 per question (2 Claude calls)
4. **Speed:** Pipeline should complete in 15-25 seconds
5. **No regressions:** Capital social question still works correctly

## Key Files Reference

- Spec: `docs/superpowers/specs/2026-03-23-structured-retrieval-pipeline-design.md`
- Pipeline: `backend/app/services/pipeline_service.py`
- Router: `backend/app/routers/assistant.py`
- Law models: `backend/app/models/law.py` (StructuralElement, Article relationships)
- Frontend details: `frontend/src/app/assistant/answer-detail.tsx`
