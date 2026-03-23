"""
Legal Assistant Pipeline — 7-step legal reasoning engine.

Each step is a plain function: takes state dict + db, returns updated state.
The pipeline yields SSE events as it executes, enabling real-time streaming.

Steps:
  1. Issue Classification (Claude)
  2. Law Mapping (rule-based)
  3. Version Selection (DB query)
  4. Hybrid Retrieval (BM25 + semantic)
  5. Article Expansion (neighbors + cross-refs)
  6. Reranking (local cross-encoder)
  7. Answer Generation (RAG + Claude streaming)
"""

from __future__ import annotations

import datetime
import json
import logging
import time
from typing import Generator

from sqlalchemy.orm import Session

from app.models.law import Article, Law, LawVersion
from app.services.chroma_service import query_articles
from app.services.claude_service import call_claude, stream_claude
from app.services.pipeline_logger import (
    complete_run,
    create_run,
    log_api_call,
    log_step,
    load_paused_state,
    save_paused_state,
    update_run_mode,
)
from app.services.prompt_service import load_prompt

import re


def _extract_json(text: str) -> dict | None:
    """Extract JSON from Claude's response, handling markdown wrappers and preamble text."""
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try stripping markdown code blocks
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

    # Try finding the first { ... } block
    brace_start = text.find("{")
    if brace_start >= 0:
        # Find matching closing brace
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start : i + 1])
                    except json.JSONDecodeError:
                        break

    return None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline entry points
# ---------------------------------------------------------------------------


def run_pipeline(
    question: str,
    session_context: list[dict],
    db: Session,
) -> Generator[dict, None, None]:
    """
    Run the full 7-step pipeline. Yields SSE-compatible event dicts.

    Event types:
      {type: "step",  step: N, name: str, status: "running"|"done", data: {}}
      {type: "token", text: str}
      {type: "done",  run_id: str, content: str, reasoning: {...}, confidence: str, flags: [...]}
      {type: "error", error: str, run_id: str}
    """
    run_id = create_run(db, question)
    state = {
        "question": question,
        "session_context": session_context,
        "run_id": run_id,
        "flags": [],
        "today": datetime.date.today().isoformat(),
    }

    try:
        # Step 1: Issue Classification (Claude)
        yield _step_event(1, "issue_classification", "running")
        t0 = time.time()
        state = _step1_issue_classification(state, db)
        yield _step_event(1, "issue_classification", "done", {
            "mode": state.get("output_mode"),
            "domain": state.get("legal_domain"),
            "question_type": state.get("question_type"),
            "core_issue": state.get("core_issue"),
            "legal_topic": state.get("legal_topic"),
            "entity_types": state.get("entity_types", []),
        }, time.time() - t0)

        # Step 2: Law Mapping (rule-based, no Claude)
        yield _step_event(2, "law_mapping", "running")
        t0 = time.time()
        state = _step2_law_mapping(state, db)
        yield _step_event(2, "law_mapping", "done", {
            "candidate_laws": state.get("candidate_laws"),
            "coverage_status": state.get("coverage_status"),
        }, time.time() - t0)

        # Step 3: Version Selection (DB query)
        yield _step_event(3, "version_selection", "running")
        t0 = time.time()
        state = _step3_version_selection(state, db)
        yield _step_event(3, "version_selection", "done", {
            "selected_versions": state.get("selected_versions"),
        }, time.time() - t0)

        # Step 4: Hybrid Retrieval (BM25 + semantic)
        yield _step_event(4, "hybrid_retrieval", "running")
        t0 = time.time()
        state = _step4_hybrid_retrieval(state, db)
        yield _step_event(4, "hybrid_retrieval", "done", {
            "articles_found": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 5: Article Expansion (neighbors + cross-refs)
        yield _step_event(5, "expansion", "running")
        t0 = time.time()
        state = _step5_expand(state, db)
        yield _step_event(5, "expansion", "done", {
            "articles_after_expansion": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 6: Reranking (local cross-encoder)
        yield _step_event(6, "reranking", "running")
        t0 = time.time()
        state = _step6_rerank(state, db)
        yield _step_event(6, "reranking", "done", {
            "top_articles": len(state.get("retrieved_articles", [])),
        }, time.time() - t0)

        # Step 7: Answer Generation (Claude streaming)
        yield _step_event(7, "answer_generation", "running")
        t0 = time.time()
        for event in _step7_answer_generation(state, db):
            yield event
        yield _step_event(7, "answer_generation", "done", duration=time.time() - t0)

        # Finalize
        complete_run(db, run_id, "ok", state.get("confidence"), state.get("flags"))
        db.commit()

        yield {
            "type": "done",
            "run_id": run_id,
            "content": state.get("answer", ""),
            "structured": state.get("answer_structured"),
            "mode": state.get("output_mode", "qa"),
            "confidence": state.get("confidence", "MEDIUM"),
            "flags": state.get("flags", []),
            "reasoning": _build_reasoning_panel(state),
        }

    except GeneratorExit:
        logger.info(f"Pipeline {run_id} interrupted by client disconnect")
    except (OSError, IOError) as e:
        logger.info(f"Pipeline {run_id} connection lost: {e}")
    except Exception as e:
        logger.exception(f"Pipeline error in run {run_id}")
        try:
            complete_run(db, run_id, "error", None, [str(e)])
            db.commit()
        except Exception:
            pass
        yield {"type": "error", "error": str(e), "run_id": run_id}


def resume_pipeline(
    run_id: str,
    import_decisions: dict[str, str],
    db: Session,
) -> Generator[dict, None, None]:
    """Resume a paused pipeline — re-run from Step 3 (version selection) onwards.

    The import-pause flow is deprecated in the new pipeline (missing laws are
    flagged but don't pause). This function is kept for backward compatibility.
    """
    state = load_paused_state(db, run_id)
    if not state:
        yield {"type": "error", "error": "No paused state found", "run_id": run_id}
        return

    state["import_decisions"] = import_decisions
    state["needs_user_input"] = False

    try:
        # Handle imports if user approved
        for law_key, decision in import_decisions.items():
            if decision == "import":
                state["flags"].append(f"User approved import of {law_key}")

        # Re-run from Step 3: Version Selection
        yield _step_event(3, "version_selection", "running")
        t0 = time.time()
        state = _step3_version_selection(state, db)
        yield _step_event(3, "version_selection", "done", {
            "selected_versions": state.get("selected_versions"),
        }, time.time() - t0)

        # Step 4: Hybrid Retrieval
        yield _step_event(4, "hybrid_retrieval", "running")
        t0 = time.time()
        state = _step4_hybrid_retrieval(state, db)
        yield _step_event(4, "hybrid_retrieval", "done", {
            "articles_found": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 5: Article Expansion
        yield _step_event(5, "expansion", "running")
        t0 = time.time()
        state = _step5_expand(state, db)
        yield _step_event(5, "expansion", "done", {
            "articles_after_expansion": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 6: Reranking
        yield _step_event(6, "reranking", "running")
        t0 = time.time()
        state = _step6_rerank(state, db)
        yield _step_event(6, "reranking", "done", {
            "top_articles": len(state.get("retrieved_articles", [])),
        }, time.time() - t0)

        # Step 7: Answer Generation
        yield _step_event(7, "answer_generation", "running")
        t0 = time.time()
        for event in _step7_answer_generation(state, db):
            yield event
        yield _step_event(7, "answer_generation", "done", duration=time.time() - t0)

        status = "ok" if not state.get("is_partial") else "partial"
        complete_run(db, run_id, status, state.get("confidence"), state.get("flags"))
        db.commit()

        yield {
            "type": "done",
            "run_id": run_id,
            "content": state.get("answer", ""),
            "structured": state.get("answer_structured"),
            "mode": state.get("output_mode", "qa"),
            "confidence": state.get("confidence", "MEDIUM"),
            "flags": state.get("flags", []),
            "reasoning": _build_reasoning_panel(state),
        }

    except GeneratorExit:
        logger.info(f"Pipeline resume {run_id} interrupted by client disconnect")
    except (OSError, IOError) as e:
        logger.info(f"Pipeline resume {run_id} connection lost: {e}")
    except Exception as e:
        logger.exception(f"Pipeline resume error in run {run_id}")
        try:
            complete_run(db, run_id, "error", None, [str(e)])
            db.commit()
        except Exception:
            pass
        yield {"type": "error", "error": str(e), "run_id": run_id}


# ---------------------------------------------------------------------------
# Helper: SSE event builder
# ---------------------------------------------------------------------------


def _step_event(
    step: int, name: str, status: str, data: dict | None = None, duration: float | None = None
) -> dict:
    event = {"type": "step", "step": step, "name": name, "status": status}
    if data:
        event["data"] = data
    if duration is not None:
        event["duration"] = round(duration, 2)
    return event


# ---------------------------------------------------------------------------
# Step 1: Issue Classification (Claude)
# ---------------------------------------------------------------------------


def _step1_issue_classification(state: dict, db: Session) -> dict:
    prompt_text, prompt_ver = load_prompt("LA-S1", db)

    context_msg = state["question"]
    if state["session_context"]:
        history = "\n".join(
            f"[{m['role']}]: {m['content'][:200]}" for m in state["session_context"][-5:]
        )
        context_msg = f"CONVERSATION HISTORY:\n{history}\n\nCURRENT QUESTION:\n{state['question']}"

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": context_msg}],
        max_tokens=1024,
    )

    log_api_call(
        db, state["run_id"], "issue_classification",
        result["tokens_in"], result["tokens_out"], result["duration"], result["model"],
    )

    parsed = _extract_json(result["content"])
    if not parsed:
        parsed = {
            "question_type": "A",
            "legal_domain": "other",
            "output_mode": "qa",
            "legal_topic": "",
            "entity_types": [],
            "core_issue": state["question"][:200],
            "sub_issues": [],
            "classification_confidence": "LOW",
            "reasoning": "Failed to parse classification response",
        }

    state["question_type"] = parsed.get("question_type", "A")
    state["legal_domain"] = parsed.get("legal_domain", "other")
    state["output_mode"] = parsed.get("output_mode", "qa")
    state["core_issue"] = parsed.get("core_issue", state["question"][:200])
    state["sub_issues"] = parsed.get("sub_issues", [])
    state["legal_topic"] = parsed.get("legal_topic", "")
    state["entity_types"] = parsed.get("entity_types", [])

    # Use today as the primary date (date extraction removed as separate step)
    state["primary_date"] = state["today"]

    update_run_mode(db, state["run_id"], state["output_mode"])

    log_step(
        db, state["run_id"], "issue_classification", 1, "done",
        result["duration"],
        prompt_id="LA-S1", prompt_version=prompt_ver,
        input_summary=state["question"][:200],
        output_summary=f"Type={state['question_type']}, Domain={state['legal_domain']}, Mode={state['output_mode']}",
        output_data=parsed,
    )

    return state


# ---------------------------------------------------------------------------
# Step 2: Law Mapping (rule-based — no Claude call)
# ---------------------------------------------------------------------------


def _step2_law_mapping(state: dict, db: Session) -> dict:
    """Rule-based law mapping — no Claude call."""
    from app.services.law_mapping import map_laws_to_question

    t0 = time.time()
    mapping = map_laws_to_question(state.get("legal_domain", "other"), db)
    state["law_mapping"] = mapping

    # Build candidate_laws for backward compatibility + reasoning panel
    candidate_laws = []
    missing_primary = []
    for tier_key, tier_laws in mapping.items():
        role = tier_key.replace("tier1_", "").replace("tier2_", "").replace("tier3_", "").upper()
        for law in tier_laws:
            entry = {
                "law_number": law["law_number"],
                "law_year": law["law_year"],
                "role": role,
                "source": "DB" if law["in_library"] else "General",
                "db_law_id": law.get("db_law_id"),
                "title": law.get("title", ""),
                "reason": law.get("reason", ""),
                "tier": tier_key,
            }
            candidate_laws.append(entry)
            if tier_key == "tier1_primary" and not law["in_library"]:
                missing_primary.append(entry)

    state["candidate_laws"] = candidate_laws

    # If primary laws are missing, add flags (but don't pause -- just warn)
    if missing_primary:
        for law in missing_primary:
            state["flags"].append(
                f"PRIMARY law {law['law_number']}/{law['law_year']} ({law['reason']}) "
                f"not in Legal Library -- answer may be incomplete"
            )

    # Build coverage status
    coverage = {}
    for law in candidate_laws:
        key = f"{law['law_number']}/{law['law_year']}"
        if law["db_law_id"]:
            coverage[key] = "full"
        else:
            coverage[key] = "missing"
    state["coverage_status"] = coverage

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "law_mapping", 2, "done", duration,
        output_summary=f"Mapped {len(candidate_laws)} laws ({sum(1 for c in candidate_laws if c['db_law_id'])} in DB)",
        output_data={"mapping": mapping, "coverage": coverage},
    )
    return state


# ---------------------------------------------------------------------------
# Step 3: Version Selection (DB query — no Claude call)
# ---------------------------------------------------------------------------


def _step3_version_selection(state: dict, db: Session) -> dict:
    t0 = time.time()
    selected_versions = {}
    version_notes = []

    primary_date = state.get("primary_date", datetime.date.today().isoformat())

    for law_info in state.get("candidate_laws", []):
        db_law_id = law_info.get("db_law_id")
        if not db_law_id:
            continue

        key = f"{law_info['law_number']}/{law_info.get('law_year', '')}"

        # Select the version in force at the primary date
        # date_in_force <= relevant_date, ordered by date_in_force DESC
        versions = (
            db.query(LawVersion)
            .filter(LawVersion.law_id == db_law_id)
            .order_by(LawVersion.date_in_force.desc().nullslast())
            .all()
        )

        if not versions:
            continue

        # Find version in force at primary_date
        selected = None
        for v in versions:
            if v.date_in_force and str(v.date_in_force) <= primary_date:
                selected = v
                break

        if not selected:
            # No version dated before the primary date -- use the current version
            current_versions = [v for v in versions if v.is_current]
            selected = current_versions[0] if current_versions else versions[0]
            version_notes.append(
                f"{key}: No version found for {primary_date}, using current version"
            )

        selected_versions[key] = {
            "law_version_id": selected.id,
            "law_id": db_law_id,
            "date_in_force": str(selected.date_in_force) if selected.date_in_force else None,
            "is_current": selected.is_current,
            "ver_id": selected.ver_id,
        }

        # Check if law was amended between dates (for multi-date scenarios)
        if selected.date_in_force and not selected.is_current:
            version_notes.append(
                f"{key}: Using version from {selected.date_in_force} (not the current version)"
            )

    duration = time.time() - t0
    state["selected_versions"] = selected_versions
    state["version_notes"] = version_notes

    if version_notes:
        state["flags"].extend(version_notes)

    log_step(
        db, state["run_id"], "version_selection", 3, "done",
        duration,
        output_summary=f"Selected {len(selected_versions)} law versions",
        output_data={"selected_versions": selected_versions, "notes": version_notes},
    )

    return state


# ---------------------------------------------------------------------------
# Step 4: Hybrid Retrieval (BM25 + semantic)
# ---------------------------------------------------------------------------


def _step4_hybrid_retrieval(state: dict, db: Session) -> dict:
    """BM25 + semantic search, per tier."""
    from app.services.bm25_service import search_bm25

    t0 = time.time()
    all_articles = []
    seen_ids = set()

    tier_limits = {
        "tier1_primary": 30,
        "tier2_secondary": 15,
    }

    for tier_key, n_results in tier_limits.items():
        # Collect version IDs for this tier's laws
        version_ids = []
        for law in state.get("law_mapping", {}).get(tier_key, []):
            key = f"{law['law_number']}/{law['law_year']}"
            v = state.get("selected_versions", {}).get(key)
            if v:
                version_ids.append(v["law_version_id"])

        if not version_ids:
            continue

        # BM25 search
        bm25_results = search_bm25(db, state["question"], version_ids, limit=n_results)

        # Semantic search (ChromaDB)
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

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "hybrid_retrieval", 4, "done", duration,
        output_summary=f"Retrieved {len(all_articles)} articles (BM25 + semantic)",
        output_data={"article_count": len(all_articles)},
    )
    return state


# ---------------------------------------------------------------------------
# Step 5: Article Expansion (neighbors + cross-refs)
# ---------------------------------------------------------------------------


def _step5_expand(state: dict, db: Session) -> dict:
    """Expand with neighbors and cross-references."""
    from app.services.article_expander import expand_articles
    from app.models.law import Article as ArticleModel

    t0 = time.time()
    raw_ids = [a["article_id"] for a in state.get("retrieved_articles_raw", [])]
    expanded_ids = expand_articles(db, raw_ids)

    existing_ids = {a["article_id"] for a in state["retrieved_articles_raw"]}
    new_ids = [aid for aid in expanded_ids if aid not in existing_ids]

    added = 0
    if new_ids:
        for art in db.query(ArticleModel).filter(ArticleModel.id.in_(new_ids)).all():
            law = art.law_version.law
            version = art.law_version
            text_parts = [art.full_text]
            for note in art.amendment_notes:
                if note.text and note.text.strip():
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
            added += 1

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "expansion", 5, "done", duration,
        output_summary=f"Expanded: {len(raw_ids)} -> {len(raw_ids) + added} articles (+{added} from neighbors/cross-refs)",
    )
    return state


# ---------------------------------------------------------------------------
# Step 6: Reranking (local cross-encoder)
# ---------------------------------------------------------------------------


def _step6_rerank(state: dict, db: Session) -> dict:
    """Rerank articles using local cross-encoder."""
    from app.services.reranker_service import rerank_articles

    t0 = time.time()
    raw = state.get("retrieved_articles_raw", [])
    ranked = rerank_articles(state["question"], raw, top_k=25)
    state["retrieved_articles"] = ranked

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "reranking", 6, "done", duration,
        output_summary=f"Reranked {len(raw)} -> top {len(ranked)} articles",
        output_data={"top_articles": [
            {"article_number": a.get("article_number"), "score": a.get("reranker_score", 0)}
            for a in ranked[:5]
        ]},
    )
    return state


# ---------------------------------------------------------------------------
# Step 7: Answer Generation (RAG + Claude streaming)
# ---------------------------------------------------------------------------


def _step7_answer_generation(state: dict, db: Session) -> Generator[dict, None, None]:
    # Determine which prompt to use based on output mode
    mode = state.get("output_mode", "qa")
    prompt_map = {
        "qa": "LA-S7",
        "memo": "LA-S7-M2",
        "comparison": "LA-S7-M3",
        "compliance": "LA-S7-M4",
        "checklist": "LA-S7-M5",
    }
    prompt_id = prompt_map.get(mode, "LA-S7")
    prompt_text, prompt_ver = load_prompt(prompt_id, db)

    # Use reranked articles from the pipeline (already in state["retrieved_articles"])
    retrieved = state.get("retrieved_articles", [])

    # Fallback: if no articles from the pipeline, try a broad semantic search
    if not retrieved:
        retrieved = query_articles(
            query_text=state["question"],
            n_results=15,
        )
        if retrieved:
            state["flags"].append(
                "No articles from structured retrieval -- used broad semantic search as fallback"
            )
        state["retrieved_articles"] = retrieved

    # Build the context for Claude
    articles_context = ""
    if retrieved:
        articles_context = "RETRIEVED LAW ARTICLES FROM LEGAL LIBRARY:\n\n"
        for i, art in enumerate(retrieved, 1):
            articles_context += (
                f"[Article {i}] {art.get('law_title', '')} "
                f"({art.get('law_number', '')}/{art.get('law_year', '')}), "
                f"Art. {art.get('article_number', '')}"
            )
            if art.get("date_in_force"):
                articles_context += f", version {art['date_in_force']}"
            if art.get("reranker_score") is not None:
                articles_context += f" [relevance: {art['reranker_score']:.2f}]"
            articles_context += f"\n{art.get('text', '')}\n\n"

    # Build version selection context
    version_context = ""
    if state.get("selected_versions"):
        version_context = "SELECTED LAW VERSIONS:\n"
        for key, v in state["selected_versions"].items():
            version_context += f"  {key}: version {v.get('date_in_force', 'unknown')} "
            version_context += "(current)" if v.get("is_current") else "(historical)"
            version_context += "\n"

    # Build flags context
    flags_context = ""
    if state.get("flags"):
        flags_context = "FLAGS AND WARNINGS:\n" + "\n".join(f"  - {f}" for f in state["flags"]) + "\n"

    # Build conversation history for session memory
    history_msgs = []
    for msg in state.get("session_context", [])[-10:]:
        history_msgs.append({"role": msg["role"], "content": msg["content"]})

    user_msg = (
        f"CLASSIFICATION:\n"
        f"  Question type: {state.get('question_type', 'A')}\n"
        f"  Legal domain: {state.get('legal_domain', 'other')}\n"
        f"  Output mode: {mode}\n"
        f"  Core issue: {state.get('core_issue', '')}\n\n"
        f"DATE CONTEXT:\n"
        f"  Primary date: {state.get('primary_date', 'today')}\n\n"
        f"{version_context}\n"
        f"{articles_context}\n"
        f"{flags_context}\n"
        f"USER QUESTION:\n{state['question']}"
    )

    messages = history_msgs + [{"role": "user", "content": user_msg}]

    # Stream the answer
    full_text = ""
    total_tokens_in = 0
    total_tokens_out = 0
    total_duration = 0.0

    for chunk in stream_claude(
        system=prompt_text,
        messages=messages,
        max_tokens=4096,
        temperature=0.2,
    ):
        if chunk["type"] == "token":
            full_text += chunk["text"]
            yield {"type": "token", "text": chunk["text"]}
        elif chunk["type"] == "done":
            total_tokens_in = chunk["tokens_in"]
            total_tokens_out = chunk["tokens_out"]
            total_duration = chunk["duration"]

    # Parse the structured JSON response
    structured = _extract_json(full_text)
    if not structured:
        logger.warning(f"Failed to parse Step 7 JSON, using raw text. First 200 chars: {full_text[:200]}")

    if structured:
        state["answer"] = structured.get("short_answer", full_text)
        state["answer_structured"] = structured
    else:
        state["answer"] = full_text
        state["answer_structured"] = None

    log_api_call(
        db, state["run_id"], "answer_generation",
        total_tokens_in, total_tokens_out, total_duration, state.get("model", ""),
    )

    # Use confidence from Claude's structured response if available
    if structured and structured.get("confidence"):
        state["confidence"] = structured["confidence"]
    elif not retrieved:
        state["confidence"] = "LOW"
        state["flags"].append("No articles retrieved from Legal Library")
    elif any(l.get("role") == "PRIMARY" and l.get("source") != "DB"
             for l in state.get("candidate_laws", [])):
        state["confidence"] = "MEDIUM"
    else:
        state["confidence"] = "HIGH"

    # Check for missing primary laws
    missing_primary = [
        c for c in state.get("candidate_laws", [])
        if c.get("tier") == "tier1_primary" and not c.get("db_law_id")
    ]
    if missing_primary:
        if state["confidence"] == "HIGH":
            state["confidence"] = "MEDIUM"
        state["is_partial"] = True

    log_step(
        db, state["run_id"], "answer_generation", 7, "done",
        total_duration,
        prompt_id=prompt_id, prompt_version=prompt_ver,
        input_summary=f"Retrieved {len(retrieved)} articles, mode={mode}",
        output_summary=f"Generated {len(full_text)} chars, confidence={state.get('confidence')}",
        confidence=state.get("confidence"),
    )


# ---------------------------------------------------------------------------
# Reasoning Panel Builder
# ---------------------------------------------------------------------------


def _build_reasoning_panel(state: dict) -> dict:
    """Build the structured reasoning data for the frontend panel."""
    return {
        "step1_classification": {
            "question_type": state.get("question_type"),
            "legal_domain": state.get("legal_domain"),
            "legal_topic": state.get("legal_topic"),
            "entity_types": state.get("entity_types", []),
            "output_mode": state.get("output_mode"),
            "core_issue": state.get("core_issue"),
        },
        "step2_law_mapping": {
            "candidate_laws": state.get("candidate_laws", []),
            "coverage_status": state.get("coverage_status", {}),
        },
        "step3_versions": {
            "selected_versions": state.get("selected_versions", {}),
        },
        "step4_retrieval": {
            "articles_found": len(state.get("retrieved_articles_raw", [])),
        },
        "step5_expansion": {
            "articles_after_expansion": len(state.get("retrieved_articles_raw", [])),
        },
        "step6_reranking": {
            "top_articles": [
                {"article_number": a.get("article_number"), "score": round(a.get("reranker_score", 0), 3), "law": f"{a.get('law_number')}/{a.get('law_year')}"}
                for a in state.get("retrieved_articles", [])[:10]
            ],
        },
        "step7_answer": {
            "articles_used": len(state.get("retrieved_articles", [])),
            "confidence": state.get("confidence"),
            "flags": state.get("flags", []),
        },
    }
