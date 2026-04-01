"""
Pipeline V2 Step Functions — pure functions for the redesigned legal assistant pipeline.

Each step takes a state dict + SQLAlchemy Session, returns the updated state dict.
No SSE events, no logging — the orchestrator handles those concerns.

Steps:
  1.  Classification (Claude)
  2a. Version Selection (DB)
  2b. Concept Search (ChromaDB semantic)
  2c. Law Availability (rule-based)
  2d. Currency Check (online)
  2e. Availability Gate (decision)
  3.  Hybrid Retrieval per issue (BM25 + semantic)
  4.  Legal Reasoning (Claude)
  5.  Answer Generation (Claude streaming)
  5b. Citation Validation (post-processing)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Generator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.law import Article, Law, LawVersion
from app.services.chroma_service import query_articles
from app.services.claude_service import call_claude, stream_claude
from app.services.bm25_service import search_bm25
from app.services.prompt_service import load_prompt
from app.services.law_mapping import check_laws_in_db
from app.services.version_currency import check_version_currency
from app.services.pipeline_logger import save_paused_state
from app.services.pipeline_service import _extract_json, _strip_json_comments

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

# Retrieval constants
N_SEMANTIC = 10
N_BM25 = 10

# Per-issue article budgets by priority
_ARTICLE_BUDGET = {
    "PRIMARY": 12,
    "SECONDARY": 8,
    "SUPPORTING": 5,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_prompt_with_fallback(prompt_id: str, db: Session, filename: str) -> str:
    """Load prompt from DB, falling back to file on disk."""
    try:
        text, _ver = load_prompt(prompt_id, db)
        return text
    except (ValueError, Exception):
        filepath = PROMPTS_DIR / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        raise ValueError(
            f"Prompt '{prompt_id}' not found in DB and fallback file "
            f"'{filename}' does not exist"
        )


def _build_law_library_list(db: Session) -> str:
    """Query all laws and return a formatted list for the classifier prompt."""
    laws = db.execute(
        select(Law.law_number, Law.law_year, Law.title)
        .order_by(Law.law_year, Law.law_number)
    ).all()
    if not laws:
        return ""
    lines = [f"- {row.law_number}/{row.law_year}: {row.title}" for row in laws]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 1 — Classification
# ---------------------------------------------------------------------------

def step1_classify(state: dict, db: Session) -> dict:
    """Classify the user's legal question using Claude."""
    prompt_text = _load_prompt_with_fallback(
        "LA-V2-S1-classifier", db, "LA-V2-S1-classifier.txt"
    )

    # Build law library context
    laws_list = _build_law_library_list(db)
    library_context = (
        f"\n\nLAWS CURRENTLY IN LEGAL LIBRARY:\n{laws_list}"
        if laws_list else ""
    )

    # Build user message with conversation history
    session_context = state.get("session_context", [])
    user_parts = []

    if session_context:
        recent = session_context[-6:]
        history = "\n".join(
            f"[{m['role']}]: {m['content'][:500]}" for m in recent
        )
        user_parts.append(f"CONVERSATION HISTORY:\n{history}")

    user_parts.append(f"CURRENT QUESTION:\n{state['question']}")
    user_parts.append(library_context)
    user_parts.append(f"\nTODAY'S DATE: {state['today']}")

    user_message = "\n\n".join(p for p in user_parts if p)

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=4096,
    )

    parsed = _extract_json(result.get("content", ""))
    if not parsed:
        state["flags"] = state.get("flags", [])
        state["flags"].append("step1_classification_parse_failure")
        state["classification_raw"] = result.get("content", "")[:2000]
        return state

    # Populate state from classification output
    state["question_type"] = parsed.get("question_type", "A")
    state["legal_domain"] = parsed.get("legal_domain", "other")
    state["output_mode"] = parsed.get("output_mode", "qa")
    state["core_issue"] = parsed.get("core_issue", "")
    state["legal_topic"] = parsed.get("legal_topic", "")
    state["sub_issues"] = parsed.get("sub_issues", [])
    state["entity_types"] = parsed.get("entity_types", [])
    state["complexity"] = parsed.get("complexity", "STANDARD")
    state["primary_target"] = parsed.get("primary_target")
    state["applicable_laws"] = parsed.get("applicable_laws", [])
    state["legal_issues"] = parsed.get("legal_issues", [])
    state["events"] = parsed.get("events", [])
    state["facts"] = parsed.get("facts", {})
    state["classification_confidence"] = parsed.get(
        "classification_confidence", "MEDIUM"
    )

    return state


# ---------------------------------------------------------------------------
# Step 2a — Version Selection
# ---------------------------------------------------------------------------

def step2a_version_selection(state: dict, db: Session) -> dict:
    """Select the correct law version for each (issue, law) pair based on dates."""
    legal_issues = state.get("legal_issues", [])
    candidate_laws = state.get("candidate_laws", [])

    # Build lookup: "law_number/law_year" -> db_law_id
    law_id_lookup: dict[str, int | None] = {}
    for cl in candidate_laws:
        key = f"{cl['law_number']}/{cl['law_year']}"
        law_id_lookup[key] = cl.get("db_law_id")

    fact_version_map: dict[str, dict] = {}
    unique_versions: dict[str, list[int]] = {}

    for issue in legal_issues:
        issue_id = issue["issue_id"]
        issue_laws = issue.get("applicable_laws", [])
        fact_dates = issue.get("fact_dates", [])

        for law_key in issue_laws:
            db_law_id = law_id_lookup.get(law_key)
            if not db_law_id:
                continue

            # Determine reference dates: per-fact or per-issue fallback
            ref_dates_for_law: list[dict] = []

            # Check fact_dates for this specific law
            for fd in fact_dates:
                fd_laws = fd.get("applicable_laws", [])
                if law_key in fd_laws:
                    ref_dates_for_law.append({
                        "date": fd.get("relevant_date"),
                        "fact_ref": fd.get("fact_ref"),
                    })

            # If no fact-specific dates, use issue-level date
            if not ref_dates_for_law:
                ref_dates_for_law.append({
                    "date": issue.get("relevant_date"),
                    "fact_ref": None,
                })

            # Query all versions for this law, ordered by date_in_force DESC
            versions = db.execute(
                select(LawVersion)
                .where(LawVersion.law_id == db_law_id)
                .order_by(LawVersion.date_in_force.desc())
            ).scalars().all()

            if not versions:
                continue

            for ref_entry in ref_dates_for_law:
                reference_date = ref_entry["date"]
                fact_ref = ref_entry["fact_ref"]
                map_key = f"{issue_id}:{law_key}"
                if fact_ref:
                    map_key = f"{issue_id}:{law_key}:{fact_ref}"

                selected_version = None
                fallback_used = False

                if reference_date:
                    ref_date_str = str(reference_date)
                    for v in versions:
                        v_date_str = str(v.date_in_force) if v.date_in_force else ""
                        if v_date_str and v_date_str <= ref_date_str:
                            selected_version = v
                            break

                # Fallback: latest available version
                if not selected_version and versions:
                    selected_version = versions[0]
                    fallback_used = True

                if selected_version:
                    entry = {
                        "law_version_id": selected_version.id,
                        "date_in_force": str(selected_version.date_in_force)
                        if selected_version.date_in_force else None,
                        "reference_date": reference_date,
                        "issue_id": issue_id,
                        "law_key": law_key,
                        "fact_ref": fact_ref,
                        "fallback": fallback_used,
                    }

                    # Mitior lex check: flag if newer version exists
                    if issue.get("mitior_lex_relevant") and selected_version != versions[0]:
                        newer = versions[0]
                        entry["mitior_lex_newer_version"] = str(
                            newer.date_in_force
                        ) if newer.date_in_force else str(newer.id)

                    fact_version_map[map_key] = entry

                    # Track unique versions per law
                    if law_key not in unique_versions:
                        unique_versions[law_key] = []
                    if selected_version.id not in unique_versions[law_key]:
                        unique_versions[law_key].append(selected_version.id)

    state["fact_version_map"] = fact_version_map
    state["unique_versions"] = unique_versions
    return state


# ---------------------------------------------------------------------------
# Step 2b — Concept Search
# ---------------------------------------------------------------------------

def step2b_concept_search(state: dict, db: Session) -> dict:
    """Perform concept-based semantic search for each issue's concept descriptions."""
    legal_issues = state.get("legal_issues", [])
    fact_version_map = state.get("fact_version_map", {})
    concept_candidates: dict[str, list[dict]] = {}

    for issue in legal_issues:
        issue_id = issue["issue_id"]
        seen_article_ids: set[int] = set()
        articles_for_issue: list[dict] = []

        for concept in issue.get("concept_descriptions", []):
            law_key = concept.get("law_key", "")
            concept_text = concept.get("concept_general", "")
            if concept.get("concept_specific"):
                concept_text = f"{concept_text}. {concept['concept_specific']}"

            if not concept_text:
                continue

            # Find version_id from fact_version_map
            vid = None
            # Try exact match with issue:law_key
            fvm_key = f"{issue_id}:{law_key}"
            if fvm_key in fact_version_map:
                vid = fact_version_map[fvm_key]["law_version_id"]
            else:
                # Try any fact-level key for this issue+law
                for k, v in fact_version_map.items():
                    if k.startswith(f"{issue_id}:{law_key}"):
                        vid = v["law_version_id"]
                        break

            if not vid:
                continue

            results = query_articles(
                query_text=concept_text,
                law_version_ids=[vid],
                n_results=N_SEMANTIC,
            )

            for art in results:
                # Filter abrogated (chroma returns is_abrogated as bool already)
                if art.get("is_abrogated"):
                    continue
                art_id = art.get("article_id")
                if art_id in seen_article_ids:
                    continue
                seen_article_ids.add(art_id)
                art["source"] = "concept_search"
                art["issue_id"] = issue_id
                articles_for_issue.append(art)

        concept_candidates[issue_id] = articles_for_issue

    state["concept_candidates"] = concept_candidates
    return state


# ---------------------------------------------------------------------------
# Step 2c — Law Availability
# ---------------------------------------------------------------------------

def step2c_law_availability(state: dict, db: Session) -> dict:
    """Check which applicable laws are available in the database."""
    applicable_laws = state.get("applicable_laws", [])
    enriched = check_laws_in_db(applicable_laws, db)

    # Build candidate_laws list with standard fields
    candidate_laws = []
    for law in enriched:
        candidate_laws.append({
            "law_number": law["law_number"],
            "law_year": law["law_year"],
            "role": law.get("role", "SECONDARY"),
            "source": "DB" if law.get("in_library") else "General",
            "db_law_id": law.get("db_law_id"),
            "title": law.get("title", ""),
            "reason": law.get("reason", ""),
            "tier": (
                "tier1_primary"
                if law.get("role") == "PRIMARY"
                else "tier2_secondary"
            ),
            "availability": law.get("availability", "missing"),
            "available_version_date": law.get("available_version_date"),
            "in_library": law.get("in_library", False),
        })

    state["candidate_laws"] = candidate_laws
    state["coverage_status"] = {
        "total": len(candidate_laws),
        "available": sum(1 for c in candidate_laws if c["availability"] == "available"),
        "missing": sum(1 for c in candidate_laws if c["availability"] == "missing"),
        "wrong_version": sum(
            1 for c in candidate_laws if c["availability"] == "wrong_version"
        ),
    }
    return state


# ---------------------------------------------------------------------------
# Step 2d — Currency Check
# ---------------------------------------------------------------------------

def step2d_currency_check(state: dict, db: Session) -> dict:
    """Check version currency for laws used by current_law temporal rules."""
    candidate_laws = state.get("candidate_laws", [])
    legal_issues = state.get("legal_issues", [])

    # Determine which laws need currency checking
    laws_needing_check: set[str] = set()
    for issue in legal_issues:
        if issue.get("temporal_rule") == "current_law":
            for law_key in issue.get("applicable_laws", []):
                laws_needing_check.add(law_key)

    if not laws_needing_check:
        return state

    updated = check_version_currency(
        candidate_laws=candidate_laws,
        db=db,
        today=state.get("today", ""),
        laws_needing_check=laws_needing_check,
    )

    state["candidate_laws"] = updated
    return state


# ---------------------------------------------------------------------------
# Step 2e — Availability Gate
# ---------------------------------------------------------------------------

def step2e_availability_gate(state: dict, db: Session) -> dict | None:
    """Decide whether the pipeline should continue, pause, or stop.

    Returns None if pipeline should continue.
    Returns a gate event dict if pipeline should pause or stop.
    """
    candidate_laws = state.get("candidate_laws", [])

    # No laws identified at all — stop with clarification
    if not candidate_laws:
        return {
            "type": "done",
            "mode": "clarification",
            "content": (
                "Nu am putut identifica legislația aplicabilă pentru această "
                "întrebare. Vă rugăm să reformulați sau să precizați domeniul "
                "juridic relevant."
            ),
        }

    # Check for missing or stale primary laws
    missing_primary = [
        c for c in candidate_laws
        if c.get("tier") == "tier1_primary"
        and c.get("availability") == "missing"
    ]
    stale_primary = [
        c for c in candidate_laws
        if c.get("tier") == "tier1_primary"
        and c.get("availability") == "wrong_version"
    ]

    needs_pause = missing_primary or stale_primary
    if not needs_pause:
        return None

    # Pause: save state and return pause event
    run_id = state.get("run_id")
    if run_id:
        save_paused_state(db, run_id, state)
        db.flush()

    pause_laws = []
    for c in missing_primary:
        pause_laws.append({
            "law_number": c["law_number"],
            "law_year": c["law_year"],
            "title": c.get("title", ""),
            "status": "missing",
        })
    for c in stale_primary:
        pause_laws.append({
            "law_number": c["law_number"],
            "law_year": c["law_year"],
            "title": c.get("title", ""),
            "status": "wrong_version",
        })

    return {
        "type": "pause",
        "run_id": run_id,
        "laws": pause_laws,
    }


# ---------------------------------------------------------------------------
# Step 3 — Hybrid Retrieval per Issue
# ---------------------------------------------------------------------------

def step3_retrieve_per_issue(state: dict, db: Session) -> dict:
    """Perform hybrid retrieval (concept + BM25 + semantic) for each issue."""
    legal_issues = state.get("legal_issues", [])
    concept_candidates = state.get("concept_candidates", {})
    fact_version_map = state.get("fact_version_map", {})
    unique_versions = state.get("unique_versions", {})

    issue_articles: dict[str, list[dict]] = {}
    flags = state.get("flags", [])

    for issue in legal_issues:
        issue_id = issue["issue_id"]
        priority = issue.get("priority", "SECONDARY")
        budget = _ARTICLE_BUDGET.get(priority, 8)

        seen_ids: set[int] = set()
        all_articles: list[dict] = []

        # 1. Start with concept_candidates from step2b
        for art in concept_candidates.get(issue_id, []):
            art_id = art.get("article_id")
            if art_id and art_id not in seen_ids:
                seen_ids.add(art_id)
                all_articles.append(art)

        # Collect version_ids for this issue
        issue_version_ids: list[int] = []
        for law_key in issue.get("applicable_laws", []):
            fvm_key = f"{issue_id}:{law_key}"
            if fvm_key in fact_version_map:
                vid = fact_version_map[fvm_key]["law_version_id"]
                if vid not in issue_version_ids:
                    issue_version_ids.append(vid)
            else:
                # Try fact-level keys
                for k, v in fact_version_map.items():
                    if k.startswith(f"{issue_id}:{law_key}"):
                        vid = v["law_version_id"]
                        if vid not in issue_version_ids:
                            issue_version_ids.append(vid)

        if not issue_version_ids:
            issue_articles[issue_id] = all_articles[:budget]
            continue

        # 2. BM25 search per law, scoped to issue's version_ids
        entity_actor = ""
        entity_persp = issue.get("entity_perspective", {})
        if entity_persp:
            entity_actor = entity_persp.get("actor", "")

        bm25_query = issue.get("description", "")
        if entity_actor:
            bm25_query = f"{bm25_query} {entity_actor}"

        bm25_results = search_bm25(
            db,
            bm25_query,
            law_version_ids=issue_version_ids,
            limit=N_BM25,
        )

        for art in bm25_results:
            art_id = art.get("article_id")
            if art.get("is_abrogated"):
                continue
            if art_id and art_id not in seen_ids:
                seen_ids.add(art_id)
                art["source"] = "bm25"
                art["issue_id"] = issue_id
                all_articles.append(art)

        # 3. Semantic search with issue description
        semantic_results = query_articles(
            query_text=issue.get("description", ""),
            law_version_ids=issue_version_ids,
            n_results=N_SEMANTIC,
        )

        for art in semantic_results:
            if art.get("is_abrogated"):
                continue
            art_id = art.get("article_id")
            if art_id and art_id not in seen_ids:
                seen_ids.add(art_id)
                art["source"] = "semantic"
                art["issue_id"] = issue_id
                all_articles.append(art)

        # 4. Sort: prefer concept_search source, then lowest distance
        def _sort_key(a: dict) -> tuple[int, float]:
            source_rank = 0 if a.get("source") == "concept_search" else 1
            distance = a.get("distance", 1.0)
            return (source_rank, distance)

        all_articles.sort(key=_sort_key)

        # 5. Trim to budget
        issue_articles[issue_id] = all_articles[:budget]

        # Lightweight relevance check for PRIMARY issues
        if priority == "PRIMARY" and semantic_results:
            best_distance = min(
                (a.get("distance", 1.0) for a in semantic_results),
                default=1.0,
            )
            if best_distance > 0.7:
                flags.append(f"low_relevance_signal:{issue_id}")

    state["issue_articles"] = issue_articles
    state["flags"] = flags
    return state


# ---------------------------------------------------------------------------
# Step 4 — Legal Reasoning
# ---------------------------------------------------------------------------

def step4_legal_reasoning(state: dict, db: Session) -> dict:
    """Run structured legal reasoning via Claude."""
    # Lazy import — module created separately
    from app.services.pipeline_v2_context import build_step4_context

    legal_issues = state.get("legal_issues", [])
    complexity = state.get("complexity", "STANDARD")
    num_issues = len(legal_issues)

    # Dynamic token budget
    if complexity == "COMPLEX" or num_issues >= 3:
        max_tokens = min(16384, 4096 + num_issues * 2048)
    else:
        max_tokens = 8192

    prompt_text = _load_prompt_with_fallback(
        "LA-V2-S4-reasoning", db, "LA-V2-S4-reasoning.txt"
    )

    user_message = build_step4_context(state)

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=max_tokens,
        temperature=0.1,
    )

    content = result.get("content", "")
    flags = state.get("flags", [])

    # Check for truncation
    stop_reason = result.get("stop_reason", "")
    if stop_reason == "max_tokens" or (
        result.get("tokens_out", 0) >= max_tokens - 10
    ):
        flags.append("step4_truncated")

    parsed = _extract_json(content)
    if parsed:
        state["rl_rap_output"] = parsed
        # Extract operative articles for citation validation
        operative = []
        for issue_data in parsed.get("issues", []):
            for oa in issue_data.get("operative_articles", []):
                operative.append(oa)
        state["operative_articles"] = operative
    else:
        logger.warning(
            "Step 4 JSON parse failure. Raw prefix: %s", content[:500]
        )
        state["rl_rap_output"] = None
        state["operative_articles"] = []
        flags.append("step4_parse_failure")

    state["flags"] = flags
    return state


# ---------------------------------------------------------------------------
# Step 5 — Answer Generation (streaming)
# ---------------------------------------------------------------------------

def step5_answer_generation(state: dict, db: Session) -> Generator[dict, None, None]:
    """Generate the final answer via Claude streaming."""
    # Lazy import — module created separately
    from app.services.pipeline_v2_context import build_step5_context

    output_mode = state.get("output_mode", "qa")
    rl_rap_output = state.get("rl_rap_output")

    # For SIMPLE questions with no rl_rap_output, use simple mode
    if state.get("complexity") == "SIMPLE" and not rl_rap_output:
        effective_mode = "simple"
    else:
        effective_mode = output_mode

    # Load base prompt
    prompt_text = _load_prompt_with_fallback(
        "LA-V2-S5-answer", db, "LA-V2-S5-answer.txt"
    )

    # Load mode-specific prompt
    mode_prompt_id = f"LA-S7-mode-{effective_mode}"
    mode_filename = f"LA-S7-mode-{effective_mode}.txt"
    try:
        mode_text = _load_prompt_with_fallback(mode_prompt_id, db, mode_filename)
        prompt_text = f"{prompt_text}\n\n{mode_text}"
    except ValueError:
        logger.warning("Mode prompt '%s' not found, using base only", mode_prompt_id)

    user_message = build_step5_context(state)

    full_text = ""
    for chunk in stream_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=8192,
        temperature=0.2,
    ):
        if chunk.get("type") == "token":
            full_text += chunk["text"]
            yield {"type": "token", "text": chunk["text"]}
        elif chunk.get("type") == "done":
            # Final message from stream
            pass
        elif chunk.get("type") == "error":
            state["flags"] = state.get("flags", [])
            state["flags"].append(f"step5_stream_error:{chunk.get('error', '')}")
            break

    state["answer"] = full_text

    # Try to extract structured answer (JSON block within the response)
    structured = _extract_json(full_text)
    state["answer_structured"] = structured

    # Extract confidence from structured output if available
    if structured:
        state["claude_confidence"] = structured.get("confidence", None)
    else:
        state["claude_confidence"] = None


# ---------------------------------------------------------------------------
# Step 5b — Citation Validation
# ---------------------------------------------------------------------------

def step5b_citation_validation(state: dict, db: Session) -> dict:
    """Validate citations in the answer against retrieved articles."""
    answer_structured = state.get("answer_structured")
    issue_articles = state.get("issue_articles", {})
    flags = state.get("flags", [])

    if not answer_structured:
        return state

    # Build set of known article IDs from all issue_articles
    known_article_ids: set[int] = set()
    known_article_refs: set[str] = set()
    for _issue_id, articles in issue_articles.items():
        for art in articles:
            art_id = art.get("article_id")
            if art_id:
                known_article_ids.add(art_id)
            # Also track by reference string for fuzzy matching
            art_num = art.get("article_number", "")
            law_num = art.get("law_number", "")
            law_year = art.get("law_year", "")
            if art_num and law_num:
                known_article_refs.add(f"{art_num}:{law_num}/{law_year}")

    # Check sources in the structured answer
    sources = answer_structured.get("sources", [])
    if not sources:
        sources = answer_structured.get("citations", [])
    if not sources:
        return state

    total_sources = len(sources)
    phantom_count = 0

    for source in sources:
        source_type = source.get("source_type", source.get("type", ""))
        if source_type != "DB":
            continue

        # Check if this source matches a known article
        art_id = source.get("article_id")
        art_num = source.get("article_number", source.get("article", ""))
        law_num = source.get("law_number", source.get("law", ""))
        law_year = source.get("law_year", "")

        matched = False
        if art_id and art_id in known_article_ids:
            matched = True
        elif art_num and law_num:
            ref = f"{art_num}:{law_num}/{law_year}"
            if ref in known_article_refs:
                matched = True

        if not matched:
            source["source_type"] = "Unverified"
            if "type" in source:
                source["type"] = "Unverified"
            phantom_count += 1

    if total_sources > 0 and phantom_count / total_sources > 0.5:
        flags.append("majority_phantom_citations")

    state["answer_structured"] = answer_structured
    state["flags"] = flags
    return state
