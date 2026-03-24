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
  6. Article Selection (Claude-based, with local reranker fallback)
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

        # Step 1b: Date Extraction (Claude)
        yield _step_event(15, "date_extraction", "running")
        t0 = time.time()
        state = _step1b_date_extraction(state, db)
        yield _step_event(15, "date_extraction", "done", {
            "primary_date": state.get("primary_date"),
        }, time.time() - t0)

        # Step 2: Law Mapping (rule-based, no Claude)
        yield _step_event(2, "law_mapping", "running")
        t0 = time.time()
        state = _step2_law_mapping(state, db)
        yield _step_event(2, "law_mapping", "done", {
            "candidate_laws": state.get("candidate_laws"),
            "coverage_status": state.get("coverage_status"),
        }, time.time() - t0)

        # Step 2.5: Early Relevance Gate — check if primary laws exist
        yield _step_event(25, "early_relevance_gate", "running")
        t0 = time.time()
        gate_result = _step2_5_early_relevance_gate(state, db)
        gate_duration = time.time() - t0
        if gate_result:
            # Log the gate decision before short-circuiting
            candidate_laws = state.get("candidate_laws", [])
            primary_laws = [c for c in candidate_laws if c.get("tier") == "tier1_primary"]
            missing_primary = [c for c in primary_laws if not c.get("db_law_id")]
            log_step(
                db, state["run_id"], "early_relevance_gate", 25, "done", gate_duration,
                output_summary=f"Gate triggered: pipeline short-circuited ({gate_result.get('mode', 'unknown')})",
                output_data={
                    "gate_triggered": True,
                    "trigger_reason": gate_result.get("mode", "unknown"),
                    "primary_laws_total": len(primary_laws),
                    "primary_laws_missing": len(missing_primary),
                    "missing_laws": [
                        {"law_number": l["law_number"], "law_year": l["law_year"],
                         "reason": l.get("reason", "")}
                        for l in missing_primary
                    ],
                    "clarification_round": _count_clarification_rounds(state.get("session_context", [])),
                },
                warnings=["Pipeline stopped early — insufficient law coverage"],
            )
            yield _step_event(25, "early_relevance_gate", "done", {
                "gate_triggered": True,
                "reason": gate_result.get("mode", "unknown"),
            }, gate_duration)
            # Pipeline short-circuits: yield the gate result and stop
            complete_run(db, run_id, "clarification", None, state.get("flags"))
            db.commit()
            yield gate_result
            return
        else:
            log_step(
                db, state["run_id"], "early_relevance_gate", 25, "done", gate_duration,
                output_summary="Gate passed — pipeline continues",
                output_data={
                    "gate_triggered": False,
                    "primary_laws_total": len([c for c in state.get("candidate_laws", []) if c.get("tier") == "tier1_primary"]),
                    "primary_laws_in_db": len([c for c in state.get("candidate_laws", []) if c.get("tier") == "tier1_primary" and c.get("db_law_id")]),
                },
            )
            yield _step_event(25, "early_relevance_gate", "done", {
                "gate_triggered": False,
            }, gate_duration)

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
        before_expansion = len(state.get("retrieved_articles_raw", []))
        state = _step5_expand(state, db)
        yield _step_event(5, "expansion", "done", {
            "articles_before": before_expansion,
            "articles_after_expansion": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 5.5: Exception Retrieval
        yield _step_event(55, "exception_retrieval", "running")
        t0 = time.time()
        before_exceptions = len(state.get("retrieved_articles_raw", []))
        state = _step5_5_exception_retrieval(state, db)
        exceptions_added = len(state.get("retrieved_articles_raw", [])) - before_exceptions
        yield _step_event(55, "exception_retrieval", "done", {
            "exceptions_added": exceptions_added,
        }, time.time() - t0)

        # Step 6: Article Selection (Claude-based)
        yield _step_event(6, "article_selection", "running")
        t0 = time.time()
        state = _step6_select_articles(state, db)
        yield _step_event(6, "article_selection", "done", {
            "top_articles": len(state.get("retrieved_articles", [])),
        }, time.time() - t0)

        # Step 6.5: Late Relevance Gate — check if selected articles match the question
        gate_events, gate_result = _step6_5_relevance_gate(state, db)
        for evt in gate_events:
            yield evt
        if gate_result:
            complete_run(db, run_id, "clarification", None, state.get("flags"))
            db.commit()
            yield gate_result
            return

        # Step 7: Answer Generation (Claude streaming)
        yield _step_event(8, "answer_generation", "running")
        t0 = time.time()
        for event in _step7_answer_generation(state, db):
            yield event
        yield _step_event(8, "answer_generation", "done", duration=time.time() - t0)

        # Step 7.5: Citation Validation (code-based, no Claude)
        yield _step_event(85, "citation_validation", "running")
        t0 = time.time()
        state = _step7_5_citation_validation(state, db)
        yield _step_event(85, "citation_validation", "done", duration=time.time() - t0)

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
        before_expansion = len(state.get("retrieved_articles_raw", []))
        state = _step5_expand(state, db)
        yield _step_event(5, "expansion", "done", {
            "articles_before": before_expansion,
            "articles_after_expansion": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 5.5: Exception Retrieval
        yield _step_event(55, "exception_retrieval", "running")
        t0 = time.time()
        before_exceptions = len(state.get("retrieved_articles_raw", []))
        state = _step5_5_exception_retrieval(state, db)
        exceptions_added = len(state.get("retrieved_articles_raw", [])) - before_exceptions
        yield _step_event(55, "exception_retrieval", "done", {
            "exceptions_added": exceptions_added,
        }, time.time() - t0)

        # Step 6: Article Selection (Claude-based)
        yield _step_event(6, "article_selection", "running")
        t0 = time.time()
        state = _step6_select_articles(state, db)
        yield _step_event(6, "article_selection", "done", {
            "top_articles": len(state.get("retrieved_articles", [])),
        }, time.time() - t0)

        # Step 6.5: Late Relevance Gate
        gate_events, gate_result = _step6_5_relevance_gate(state, db)
        for evt in gate_events:
            yield evt
        if gate_result:
            complete_run(db, run_id, "clarification", None, state.get("flags"))
            db.commit()
            yield gate_result
            return

        # Step 7: Answer Generation
        yield _step_event(8, "answer_generation", "running")
        t0 = time.time()
        for event in _step7_answer_generation(state, db):
            yield event
        yield _step_event(8, "answer_generation", "done", duration=time.time() - t0)

        # Step 7.5: Citation Validation
        yield _step_event(85, "citation_validation", "running")
        t0 = time.time()
        state = _step7_5_citation_validation(state, db)
        yield _step_event(85, "citation_validation", "done", duration=time.time() - t0)

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

    from app.models.law import Law as LawModel
    available_laws = db.query(LawModel).limit(50).all()
    laws_list = "\n".join(
        f"- {l.law_number}/{l.law_year}: {l.title}" for l in available_laws
    )
    library_context = f"\n\nLAWS CURRENTLY IN LEGAL LIBRARY:\n{laws_list}" if available_laws else ""

    context_msg = state["question"]
    if state["session_context"]:
        history = "\n".join(
            f"[{m['role']}]: {m['content'][:500]}" for m in state["session_context"][-5:]
        )
        context_msg = f"CONVERSATION HISTORY:\n{history}\n\nCURRENT QUESTION:\n{state['question']}"

    context_msg += library_context

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
            "applicable_laws": [],
        }

    state["question_type"] = parsed.get("question_type", "A")
    state["legal_domain"] = parsed.get("legal_domain", "other")
    state["output_mode"] = parsed.get("output_mode", "qa")
    state["core_issue"] = parsed.get("core_issue", state["question"][:200])
    state["sub_issues"] = parsed.get("sub_issues", [])
    state["legal_topic"] = parsed.get("legal_topic", "")
    state["entity_types"] = parsed.get("entity_types", [])
    state["applicable_laws"] = parsed.get("applicable_laws", [])

    # Validate applicable_laws entries
    valid_laws = []
    for law_entry in state["applicable_laws"]:
        if not law_entry.get("law_number") or not law_entry.get("law_year"):
            state["flags"].append(f"Skipping malformed law entry: {law_entry}")
            continue
        law_entry["law_number"] = str(law_entry["law_number"])
        law_entry["law_year"] = str(law_entry["law_year"])
        if law_entry.get("role") not in ("PRIMARY", "SECONDARY"):
            law_entry["role"] = "SECONDARY"
        valid_laws.append(law_entry)
    state["applicable_laws"] = valid_laws

    # Default to today — will be overridden by Step 1b date extraction
    state["primary_date"] = state["today"]

    update_run_mode(db, state["run_id"], state["output_mode"])

    log_step(
        db, state["run_id"], "issue_classification", 1, "done",
        result["duration"],
        prompt_id="LA-S1", prompt_version=prompt_ver,
        input_summary=state["question"][:200],
        output_summary=f"Type={state['question_type']}, Domain={state['legal_domain']}, Mode={state['output_mode']}",
        output_data=parsed,
        confidence=parsed.get("classification_confidence"),
    )

    return state


# ---------------------------------------------------------------------------
# Step 1b: Date Extraction (Claude)
# ---------------------------------------------------------------------------


def _step1b_date_extraction(state: dict, db: Session) -> dict:
    """Extract temporal context — local regex, no Claude call."""
    from app.services.date_extractor import extract_date_local

    t0 = time.time()
    parsed = extract_date_local(state["question"], state["today"])

    if parsed and parsed.get("primary_date"):
        state["primary_date"] = parsed["primary_date"]
        state["date_logic"] = parsed.get("date_logic", "")
        state["dates_found"] = parsed.get("dates_found", [])

        if parsed.get("needs_clarification"):
            state["flags"].append(
                f"Date ambiguous: {parsed.get('date_logic', 'unclear temporal context')} "
                f"— using {state['primary_date']} as best estimate"
            )
    else:
        state["flags"].append("No specific date detected — using current law versions")

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "date_extraction", 15, "done", duration,
        input_summary=state["question"][:200],
        output_summary=f"primary_date={state.get('primary_date')}",
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

    # If classifier returned a secondary domain, merge its laws too
    secondary_domain = state.get("secondary_domain")
    if secondary_domain and secondary_domain != state.get("legal_domain"):
        secondary_mapping = map_laws_to_question(secondary_domain, db)
        existing_keys = set()
        for tier_laws in mapping.values():
            for law in tier_laws:
                existing_keys.add((law["law_number"], law["law_year"]))

        for tier_key in ["tier1_primary", "tier2_secondary", "tier3_connected"]:
            for law in secondary_mapping.get(tier_key, []):
                if (law["law_number"], law["law_year"]) not in existing_keys:
                    target_tier = "tier2_secondary" if tier_key == "tier1_primary" else tier_key
                    mapping.setdefault(target_tier, []).append(law)
                    existing_keys.add((law["law_number"], law["law_year"]))

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
        output_data={
            "mapping": mapping,
            "coverage": coverage,
            "candidate_laws": candidate_laws,
            "missing_laws": [
                {"law_number": l["law_number"], "law_year": l["law_year"],
                 "title": l.get("title", ""), "reason": l.get("reason", ""), "tier": l["tier"]}
                for l in candidate_laws if not l.get("db_law_id")
            ],
        },
    )
    return state


# ---------------------------------------------------------------------------
# Step 2.5: Early Relevance Gate
# ---------------------------------------------------------------------------


def _step2_5_early_relevance_gate(state: dict, db: Session) -> dict | None:
    """Check if the primary laws needed for this question exist in the database.

    Returns None if the pipeline should continue, or a 'done' event dict
    if the pipeline should short-circuit with a clarification/import message.
    """
    candidate_laws = state.get("candidate_laws", [])
    primary_laws = [c for c in candidate_laws if c.get("tier") == "tier1_primary"]
    missing_primary = [c for c in primary_laws if not c.get("db_law_id")]
    has_any_primary_in_db = any(c.get("db_law_id") for c in primary_laws)

    # Count how many clarification rounds have happened in this session
    clarification_round = _count_clarification_rounds(state.get("session_context", []))

    if not primary_laws:
        # Domain mapped to nothing (e.g., "other") — no laws identified at all
        if clarification_round >= 1:
            # Already asked once — don't loop. Suggest import or give up.
            return _build_cannot_answer_event(state, missing_primary)

        clarification = _generate_clarification_question(state, db)
        if clarification:
            return {
                "type": "done",
                "run_id": state["run_id"],
                "content": clarification["clarification_question"],
                "structured": None,
                "mode": "clarification",
                "output_mode": "clarification",
                "confidence": "LOW",
                "flags": state.get("flags", []),
                "reasoning": _build_reasoning_panel(state),
                "clarification_type": "missing_context",
                "missing_laws": [],
            }

    elif missing_primary and not has_any_primary_in_db:
        # ALL primary laws are missing — refuse and suggest import
        return _build_needs_import_event(state, missing_primary)

    elif missing_primary:
        # SOME primary laws missing — flag but continue (partial coverage)
        state["flags"].append(
            "Partial coverage: some primary laws are not in the Legal Library"
        )

    return None


def _count_clarification_rounds(session_context: list[dict]) -> int:
    """Count how many clarification rounds have happened in this session.

    Looks for assistant messages that were clarification/needs_import responses.
    Uses multiple signals since the mode field may not be preserved in stored messages.
    """
    count = 0
    for msg in session_context[-10:]:
        if msg.get("role") == "assistant":
            mode = msg.get("mode", "")
            content = msg.get("content", "")
            # Check mode field if available
            if mode in ("clarification", "needs_import"):
                count += 1
            # Heuristic: assistant messages that end with "?" and are under 600 chars
            # are likely clarification questions (not full legal answers)
            elif content.strip().endswith("?") and len(content) < 600:
                count += 1
    return count


def _generate_clarification_question(state: dict, db: Session) -> dict | None:
    """Use Claude to generate a targeted follow-up question."""
    try:
        prompt_text, _ = load_prompt("LA-S2.5", db)
    except ValueError:
        # Prompt not yet seeded — use a simple fallback
        return {
            "clarification_question": (
                "Nu am putut identifica legea relevantă pentru întrebarea dumneavoastră. "
                "Puteți preciza despre ce lege sau domeniu juridic este vorba?"
            ),
            "reasoning": "Fallback — LA-S2.5 prompt not available",
        }

    # Build context about what laws are available
    from app.models.law import Law
    available_laws = db.query(Law).limit(20).all()
    available_list = ", ".join(f"{l.title} ({l.law_number}/{l.law_year})" for l in available_laws)

    user_msg = (
        f"USER QUESTION: {state['question']}\n"
        f"CLASSIFIED DOMAIN: {state.get('legal_domain', 'other')}\n"
        f"AVAILABLE LAWS IN LIBRARY: {available_list}\n"
        f"MISSING LAWS: None identified\n"
    )

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=512,
    )

    log_api_call(
        db, state["run_id"], "clarification_generation",
        result["tokens_in"], result["tokens_out"], result["duration"], result["model"],
    )

    parsed = _extract_json(result["content"])
    return parsed


def _build_needs_import_event(state: dict, missing_laws: list[dict]) -> dict:
    """Build a 'done' event that tells the frontend to offer law import."""
    law_names = ", ".join(
        f"{l.get('reason', '')} ({l['law_number']}/{l['law_year']})"
        for l in missing_laws
    )
    content = (
        f"Nu pot răspunde corect la această întrebare deoarece nu am în biblioteca juridică "
        f"legea necesară: {law_names}. "
        f"Doriți să o importăm din legislatie.just.ro?"
    )
    return {
        "type": "done",
        "run_id": state["run_id"],
        "content": content,
        "structured": None,
        "mode": "needs_import",
        "output_mode": "needs_import",
        "confidence": "LOW",
        "flags": state.get("flags", []),
        "reasoning": _build_reasoning_panel(state),
        "clarification_type": "missing_law",
        "missing_laws": [
            {
                "law_number": l["law_number"],
                "law_year": l["law_year"],
                "title": l.get("title", l.get("reason", "")),
                "reason": l.get("reason", ""),
            }
            for l in missing_laws
        ],
    }


def _build_cannot_answer_event(state: dict, missing_laws: list[dict]) -> dict:
    """Build a 'done' event when we've exhausted clarification attempts."""
    content = (
        "Din păcate, nu am putut identifica legea relevantă pentru întrebarea dumneavoastră. "
        "Vă rog să verificați dacă legea necesară este disponibilă în Biblioteca Juridică "
        "sau să o importați de pe legislatie.just.ro."
    )
    return {
        "type": "done",
        "run_id": state["run_id"],
        "content": content,
        "structured": None,
        "mode": "needs_import",
        "output_mode": "needs_import",
        "confidence": "LOW",
        "flags": state.get("flags", []) + ["Exhausted clarification attempts"],
        "reasoning": _build_reasoning_panel(state),
        "clarification_type": "missing_law",
        "missing_laws": [
            {
                "law_number": l["law_number"],
                "law_year": l["law_year"],
                "title": l.get("title", l.get("reason", "")),
                "reason": l.get("reason", ""),
            }
            for l in missing_laws
        ],
    }


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

    # Build amendment flags: mark laws where the selected version is not current
    amendment_flags = []
    for key, v in selected_versions.items():
        if not v.get("is_current"):
            amendment_flags.append(f"{key}: using historical version from {v.get('date_in_force', 'unknown')}")

    log_step(
        db, state["run_id"], "version_selection", 3, "done",
        duration,
        output_summary=f"Selected {len(selected_versions)} law versions",
        output_data={
            "selected_versions": selected_versions,
            "notes": version_notes,
            "amendment_flags": amendment_flags,
            "primary_date": primary_date,
        },
    )

    return state


_ENTITY_KEYWORDS: dict[str, list[str]] = {
    "SRL": ["raspundere limitata", "asociati", "parte sociala", "parti sociale"],
    "SA": ["actiuni", "actionar", "societate pe actiuni", "capital social", "adunarea generala"],
    "PFA": ["persoana fizica autorizata", "activitate independenta"],
    "SCS": ["comandita simpla", "comanditar", "comanditat"],
    "SNC": ["nume colectiv", "raspundere nelimitata", "solidara"],
    "SCA": ["comandita pe actiuni", "comanditari", "actionari comandita"],
    "ONG": ["asociatie", "organizatie neguvernamentala", "scop nepatrimonial", "act constitutiv asociatie"],
    "ASOCIATIE": ["asociatie", "asociatii", "scop nepatrimonial", "membri asociatie"],
    "FUNDATIE": ["fundatie", "fundatii", "patrimoniu afectat", "scop nepatrimonial fundatie"],
    "COOPERATIVA": ["cooperativa", "cooperative", "membri cooperatori", "parti sociale cooperativa"],
}


# ---------------------------------------------------------------------------
# Step 4: Hybrid Retrieval (BM25 + semantic)
# ---------------------------------------------------------------------------


def _step4_hybrid_retrieval(state: dict, db: Session) -> dict:
    """BM25 + semantic search, per tier."""
    from app.services.bm25_service import search_bm25

    t0 = time.time()
    all_articles = []
    seen_ids = set()
    bm25_count = 0
    semantic_count = 0
    duplicates_removed = 0

    tier_limits = {
        "tier1_primary": 30,
        "tier2_secondary": 15,
    }

    TIER_TO_ROLE = {
        "tier1_primary": "PRIMARY",
        "tier2_secondary": "SECONDARY",
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
        bm25_count += len(bm25_results)

        # Semantic search (ChromaDB)
        semantic_results = query_articles(
            state["question"], law_version_ids=version_ids, n_results=n_results
        )
        semantic_count += len(semantic_results)

        # Merge and deduplicate
        for art in bm25_results + semantic_results:
            aid = art["article_id"]
            if aid not in seen_ids:
                seen_ids.add(aid)
                art["tier"] = tier_key
                art["role"] = TIER_TO_ROLE.get(tier_key, "SECONDARY")
                all_articles.append(art)
            else:
                duplicates_removed += 1

    # Entity-aware targeted retrieval
    entity_count = 0
    entity_types = state.get("entity_types", [])
    if entity_types:
        # Get all version IDs from primary tier
        primary_version_ids = []
        for law in state.get("law_mapping", {}).get("tier1_primary", []):
            key = f"{law['law_number']}/{law['law_year']}"
            v = state.get("selected_versions", {}).get(key)
            if v:
                primary_version_ids.append(v["law_version_id"])

        if primary_version_ids:
            for entity in entity_types:
                keywords = _ENTITY_KEYWORDS.get(entity.upper(), [])
                for kw in keywords:
                    entity_results = search_bm25(db, kw, primary_version_ids, limit=10)
                    for art in entity_results:
                        aid = art["article_id"]
                        if aid not in seen_ids:
                            seen_ids.add(aid)
                            art["tier"] = "entity_targeted"
                            art["role"] = "PRIMARY"
                            art["source"] = f"entity:{entity}"
                            all_articles.append(art)
                            entity_count += 1
                        else:
                            duplicates_removed += 1

    # Enrich semantic-only articles with amendment notes from DB
    # (BM25 results already include amendments; ChromaDB stores only full_text)
    from app.models.law import Article as ArticleModel
    semantic_only_ids = [
        a["article_id"] for a in all_articles
        if a.get("source") != "bm25" and "[Amendment:" not in a.get("text", "")
    ]
    if semantic_only_ids:
        arts_with_notes = (
            db.query(ArticleModel)
            .filter(ArticleModel.id.in_(semantic_only_ids))
            .all()
        )
        notes_by_id = {}
        for art in arts_with_notes:
            notes = [
                f"[Amendment: {n.text.strip()}]"
                for n in art.amendment_notes
                if n.text and n.text.strip()
            ]
            if notes:
                notes_by_id[art.id] = notes
        for art_dict in all_articles:
            if art_dict["article_id"] in notes_by_id:
                art_dict["text"] = art_dict["text"] + "\n" + "\n".join(notes_by_id[art_dict["article_id"]])

    state["retrieved_articles_raw"] = all_articles

    # Build top 10 articles by score for logging
    def _article_score(art):
        return art.get("reranker_score") or art.get("bm25_rank") or art.get("distance") or 0
    sorted_for_log = sorted(all_articles, key=_article_score, reverse=True)
    top_articles_log = [
        {
            "article_id": a["article_id"],
            "article_number": a.get("article_number"),
            "law": f"{a.get('law_number', '')}/{a.get('law_year', '')}",
            "tier": a.get("tier"),
            "source": a.get("source", "bm25" if a.get("bm25_rank") else "semantic"),
            "bm25_rank": a.get("bm25_rank"),
            "distance": round(a["distance"], 4) if a.get("distance") is not None else None,
        }
        for a in sorted_for_log[:10]
    ]

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "hybrid_retrieval", 4, "done", duration,
        output_summary=f"Retrieved {len(all_articles)} articles (BM25: {bm25_count}, semantic: {semantic_count}, entity: {entity_count}, dupes removed: {duplicates_removed})",
        output_data={
            "article_count": len(all_articles),
            "bm25_count": bm25_count,
            "semantic_count": semantic_count,
            "entity_count": entity_count,
            "duplicates_removed": duplicates_removed,
            "top_articles": top_articles_log,
        },
    )
    return state


# ---------------------------------------------------------------------------
# Step 5: Article Expansion (neighbors + cross-refs)
# ---------------------------------------------------------------------------


def _derive_role(law_number: str, law_year: str, state: dict) -> str:
    """Determine if an article's law is PRIMARY or SECONDARY based on law mapping."""
    for law in state.get("law_mapping", {}).get("tier1_primary", []):
        if str(law["law_number"]) == str(law_number) and str(law["law_year"]) == str(law_year):
            return "PRIMARY"
    return "SECONDARY"


def _step5_expand(state: dict, db: Session) -> dict:
    """Expand with neighbors and cross-references."""
    from app.services.article_expander import expand_articles
    from app.models.law import Article as ArticleModel

    t0 = time.time()
    raw_ids = [a["article_id"] for a in state.get("retrieved_articles_raw", [])]
    expanded_ids, expansion_details = expand_articles(
        db, raw_ids,
        selected_versions=state.get("selected_versions", {}),
        primary_date=state.get("primary_date"),
    )

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
                "law_version_id": version.id,
                "law_number": law.law_number,
                "law_year": str(law.law_year),
                "law_title": law.title[:200],
                "date_in_force": str(version.date_in_force) if version.date_in_force else "",
                "text": "\n".join(text_parts),
                "source": "expansion",
                "tier": "expansion",
                "role": _derive_role(law.law_number, str(law.law_year), state),
            })
            added += 1

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "expansion", 5, "done", duration,
        output_summary=f"Expanded: {len(raw_ids)} -> {len(raw_ids) + added} articles (+{added} from neighbors/cross-refs)",
        output_data={
            "articles_before": len(raw_ids),
            "articles_after": len(raw_ids) + added,
            "added": added,
            "neighbors_added": expansion_details.get("neighbors_added", 0),
            "crossrefs_added": expansion_details.get("crossrefs_added", 0),
            "expansion_triggers": expansion_details.get("expansion_triggers", []),
        },
    )
    return state


# ---------------------------------------------------------------------------
# Step 5.5: Exception Retrieval
# ---------------------------------------------------------------------------


def _step5_5_exception_retrieval(state: dict, db: Session) -> dict:
    """Expand retrieved articles with exception/exclusion articles."""
    from app.services.article_expander import expand_with_exceptions
    from app.models.law import Article as ArticleModel

    t0 = time.time()
    raw = state.get("retrieved_articles_raw", [])

    if not raw:
        return state

    exception_ids, exception_details = expand_with_exceptions(db, raw)
    existing_ids = {a["article_id"] for a in raw}
    new_ids = [aid for aid in exception_ids if aid not in existing_ids]

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
                "law_version_id": version.id,
                "law_number": law.law_number,
                "law_year": str(law.law_year),
                "law_title": law.title[:200],
                "date_in_force": str(version.date_in_force) if version.date_in_force else "",
                "text": "\n".join(text_parts),
                "source": "exception",
                "tier": "exception",
                "role": _derive_role(law.law_number, str(law.law_year), state),
            })
            added += 1

    if added:
        logger.info(f"Exception retrieval added {added} articles")

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "exception_retrieval", 55, "done", duration,
        output_summary=f"Exception retrieval: +{added} articles (forward: {exception_details['forward_count']}, reverse: {exception_details['reverse_count']})",
        output_data={
            "added": added,
            "forward_matches": exception_details.get("forward_matches", []),
            "reverse_matches": exception_details.get("reverse_matches", []),
            "forward_count": exception_details.get("forward_count", 0),
            "reverse_count": exception_details.get("reverse_count", 0),
        },
    )
    return state


# ---------------------------------------------------------------------------
# Step 6: Article Selection (Claude-based, with local reranker fallback)
# ---------------------------------------------------------------------------


def _step6_select_articles(state: dict, db: Session) -> dict:
    """Select top articles using local cross-encoder reranker."""
    from app.services.reranker_service import rerank_articles

    t0 = time.time()
    raw = state.get("retrieved_articles_raw", [])
    if not raw:
        state["retrieved_articles"] = []
        log_step(db, state["run_id"], "article_selection", 6, "done", 0,
                 output_summary="No articles to select from")
        return state

    ranked = rerank_articles(state["question"], raw, top_k=20)
    state["retrieved_articles"] = ranked

    kept_ids = {a["article_id"] for a in ranked}
    dropped = [a for a in raw if a["article_id"] not in kept_ids]

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "article_selection", 6, "done", duration,
        output_summary=f"Reranker: {len(raw)} -> top {len(ranked)} articles",
        output_data={
            "method": "reranker",
            "kept_articles": [
                {
                    "article_id": a["article_id"],
                    "article_number": a.get("article_number"),
                    "law": f"{a.get('law_number')}/{a.get('law_year')}",
                    "score": round(a.get("reranker_score", 0), 3),
                }
                for a in ranked
            ],
            "dropped_count": len(dropped),
            "total_candidates": len(raw),
        },
    )
    return state


# ---------------------------------------------------------------------------
# Step 6.5: Late Relevance Gate
# ---------------------------------------------------------------------------


def _step6_5_relevance_gate(state: dict, db: Session) -> tuple[list[dict], dict | None]:
    """Check if selected articles are relevant using reranker scores (no Claude call).

    Called from both run_pipeline and resume_pipeline.
    """
    t0 = time.time()
    retrieved = state.get("retrieved_articles", [])
    events = []

    if not retrieved:
        events.append(_step_event(7, "relevance_check", "done", {"skipped": True}, 0))
        return events, None

    # Use the top reranker score as a relevance proxy
    # Cross-encoder ms-marco-MiniLM-L-6-v2 scores range roughly -10 to +10
    top_score = max((a.get("reranker_score", 0) for a in retrieved), default=0)
    avg_score = sum(a.get("reranker_score", 0) for a in retrieved) / len(retrieved)

    # Normalize to 0-1: score of -5 → 0.0, score of +10 → 1.0
    relevance_score = min(1.0, max(0.0, (top_score + 5) / 15))
    state["relevance_score"] = relevance_score

    gate_will_trigger = relevance_score < 0.2  # ~top_score < -2 (clearly irrelevant)
    gate_will_warn = 0.2 <= relevance_score < 0.4  # ~top_score < 1

    duration = time.time() - t0
    events.append(_step_event(7, "relevance_check", "done", {
        "relevance_score": round(relevance_score, 3),
        "top_reranker_score": round(top_score, 3),
        "avg_reranker_score": round(avg_score, 3),
        "gate_triggered": gate_will_trigger,
        "gate_warning": gate_will_warn,
        "method": "reranker_scores",
    }, duration))

    if gate_will_warn:
        state["flags"].append(
            f"Low article relevance (score: {relevance_score:.2f}) — answer may be incomplete"
        )

    if gate_will_trigger:
        clarification_round = _count_clarification_rounds(state.get("session_context", []))

        # Try to identify missing laws from the domain mapping
        candidate_laws = state.get("candidate_laws", [])
        primary_missing = [
            c for c in candidate_laws
            if c.get("tier") == "tier1_primary" and not c.get("db_law_id")
        ]

        if primary_missing:
            # We know which laws are needed → offer import
            law_names = ", ".join(
                f"{l.get('title', '')} ({l['law_number']}/{l['law_year']})"
                for l in primary_missing
            )
            content = (
                f"Pentru a răspunde corect la această întrebare, am nevoie de articole din: "
                f"{law_names}. "
                f"Aceste legi nu sunt în biblioteca juridică. "
                f"Doriți să le importați din legislatie.just.ro?"
            )
            return events, {
                "type": "done",
                "run_id": state["run_id"],
                "content": content,
                "structured": None,
                "mode": "needs_import",
                "output_mode": "needs_import",
                "confidence": "LOW",
                "flags": state.get("flags", []),
                "reasoning": _build_reasoning_panel(state),
                "clarification_type": "missing_law",
                "missing_laws": [
                    {
                        "law_number": l["law_number"],
                        "law_year": l["law_year"],
                        "title": l.get("title", ""),
                        "reason": l.get("reason", ""),
                    }
                    for l in primary_missing
                ],
            }

        if clarification_round >= 1:
            state["flags"].append(
                f"Low relevance (score: {relevance_score:.2f}) but proceeding after "
                f"{clarification_round} clarification round(s)"
            )
            state["confidence"] = "MEDIUM"
            return events, None

        # First time: trigger clarification
        state["confidence"] = "LOW"
        clarification_msg = (
            "Nu am putut identifica articole suficient de relevante pentru "
            "întrebarea dumneavoastră. Puteți preciza despre ce lege sau "
            "domeniu juridic este vorba?"
        )
        return events, {
            "type": "done",
            "run_id": state["run_id"],
            "content": clarification_msg,
            "structured": None,
            "mode": "clarification",
            "output_mode": "clarification",
            "confidence": "LOW",
            "flags": state.get("flags", []),
            "reasoning": _build_reasoning_panel(state),
            "clarification_type": "missing_context",
            "missing_laws": [],
        }

    return events, None


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

    # No fallback to broad semantic search — if structured retrieval found
    # nothing relevant, we should not grab random articles from other laws.
    # The answer prompt will handle the empty-articles case by refusing.
    if not retrieved:
        state["flags"].append("No relevant articles found in Legal Library")
        state["confidence"] = "LOW"

    # Build the context for Claude
    articles_context = ""
    if retrieved:
        articles_context = "RETRIEVED LAW ARTICLES FROM LEGAL LIBRARY:\n\n"
        for i, art in enumerate(retrieved, 1):
            role_tag = f"[{art.get('role', 'SECONDARY')}] " if art.get("role") else ""
            abrogated_tag = " [ABROGATED — this article has been repealed]" if art.get("is_abrogated") else ""
            articles_context += (
                f"[Article {i}] {role_tag}{abrogated_tag}{art.get('law_title', '')} "
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
    for msg in state.get("session_context", [])[-5:]:
        history_msgs.append({"role": msg["role"], "content": msg["content"][:500]})

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

    # Build output_data with answer details
    answer_output_data = {
        "articles_provided": len(retrieved),
        "confidence": state.get("confidence"),
        "is_partial": state.get("is_partial", False),
        "output_mode": mode,
    }
    if structured:
        # Extract sources info without the full answer text
        sources = structured.get("sources", [])
        answer_output_data["sources_count"] = len(sources)
        answer_output_data["sources"] = [
            {
                "law": s.get("law", ""),
                "article": s.get("article", ""),
                "label": s.get("label", ""),
            }
            for s in sources
        ]
        # Track which retrieved articles were cited vs not
        cited_articles = set()
        for s in sources:
            if s.get("label") == "DB":
                cited_articles.add(str(s.get("article", "")))
        answer_output_data["articles_cited"] = len(cited_articles)
        answer_output_data["articles_not_cited"] = len(retrieved) - len(cited_articles)
        if structured.get("confidence_reasoning"):
            answer_output_data["confidence_reasoning"] = structured["confidence_reasoning"]

    log_step(
        db, state["run_id"], "answer_generation", 8, "done",
        total_duration,
        prompt_id=prompt_id, prompt_version=prompt_ver,
        input_summary=f"Retrieved {len(retrieved)} articles, mode={mode}",
        output_summary=f"Generated {len(full_text)} chars, confidence={state.get('confidence')}",
        output_data=answer_output_data,
        confidence=state.get("confidence"),
    )


# ---------------------------------------------------------------------------
# Step 7.5: Citation Validation (code-based, no Claude)
# ---------------------------------------------------------------------------


def _step7_5_citation_validation(state: dict, db: Session) -> dict:
    """Verify that every DB-labeled citation was actually in the provided context.

    This is a code-based post-generation check — no Claude call needed.
    Downgrades phantom citations from 'DB' to 'Unverified' and adjusts confidence.
    """
    t0 = time.time()
    structured = state.get("answer_structured")
    if not structured:
        log_step(
            db, state["run_id"], "citation_validation", 85, "done", time.time() - t0,
            output_summary="Skipped — no structured answer to validate",
            output_data={"skipped": True, "reason": "no_structured_answer"},
        )
        return state

    sources = structured.get("sources", [])
    if not sources:
        log_step(
            db, state["run_id"], "citation_validation", 85, "done", time.time() - t0,
            output_summary="Skipped — no sources to validate",
            output_data={"skipped": True, "reason": "no_sources"},
        )
        return state

    # Build a set of (law_number/year, article_number) tuples from provided articles
    provided = set()
    for art in state.get("retrieved_articles", []):
        law_key = f"{art.get('law_number', '')}/{art.get('law_year', '')}"
        art_num = str(art.get("article_number", "")).strip()
        provided.add((law_key, art_num))

    # Also build a set of just article numbers per law for fuzzy matching
    provided_by_law_num = {}
    for art in state.get("retrieved_articles", []):
        law_num = str(art.get("law_number", "")).strip()
        art_num = str(art.get("article_number", "")).strip()
        provided_by_law_num.setdefault(law_num, set()).add(art_num)

    downgraded = 0
    validated = 0
    downgraded_citations = []
    validated_citations = []
    for source in sources:
        if source.get("label") != "DB":
            continue
        law_ref = str(source.get("law", "")).strip()
        art_ref = str(source.get("article", "")).strip()

        # Normalize: strip "Art." prefix, whitespace
        art_ref_clean = re.sub(r"^art\.?\s*", "", art_ref, flags=re.IGNORECASE).strip()

        # Normalize law reference: extract just "number/year" from formats like
        # "Legea 31/1990", "Codul Civil 287/2009", "31/1990", etc.
        law_ref_normalized = law_ref
        law_match = re.search(r"(\d+)\s*/\s*(\d+)", law_ref)
        if law_match:
            law_ref_normalized = f"{law_match.group(1)}/{law_match.group(2)}"

        # Also try matching just by law number (for cases like "287" without year)
        law_num_only = re.search(r"(\d+)", law_ref)
        law_num_str = law_num_only.group(1) if law_num_only else ""

        # Check if this citation exists in provided articles
        found = (
            (law_ref_normalized, art_ref_clean) in provided
            or (law_num_str in provided_by_law_num
                and art_ref_clean in provided_by_law_num[law_num_str])
        )

        if not found:
            source["label"] = "Unverified"
            state["flags"].append(
                f"Citation Art. {art_ref_clean} from {law_ref} not in provided context — "
                f"downgraded to Unverified"
            )
            downgraded += 1
            downgraded_citations.append({
                "law": law_ref,
                "article": art_ref_clean,
                "original_label": "DB",
                "new_label": "Unverified",
            })
        else:
            validated += 1
            validated_citations.append({
                "law": law_ref,
                "article": art_ref_clean,
            })

    confidence_downgraded = False
    if downgraded > 0:
        logger.info(f"Citation validation: downgraded {downgraded} citations to Unverified")

        # If majority are unverified, downgrade confidence
        total_db = sum(1 for s in sources if s.get("label") in ("DB", "Unverified"))
        if total_db > 0 and downgraded > total_db / 2:
            state["confidence"] = "LOW"
            state["flags"].append(
                "Majority of citations could not be verified against provided articles"
            )
            confidence_downgraded = True

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "citation_validation", 85, "done", duration,
        output_summary=f"Validated {validated}, downgraded {downgraded} citations" + (" — confidence lowered to LOW" if confidence_downgraded else ""),
        output_data={
            "skipped": False,
            "total_db_citations": validated + downgraded,
            "validated": validated,
            "downgraded": downgraded,
            "confidence_downgraded": confidence_downgraded,
            "downgraded_citations": downgraded_citations,
            "validated_citations": validated_citations,
        },
        warnings=(
            [f"Downgraded {downgraded} citations to Unverified"]
            if downgraded > 0 else None
        ),
    )

    return state


# ---------------------------------------------------------------------------
# Reasoning Panel Builder
# ---------------------------------------------------------------------------


def _build_reasoning_panel(state: dict) -> dict:
    """Build the structured reasoning data for the frontend panel."""
    # Build retrieval breakdown from raw articles
    raw = state.get("retrieved_articles_raw", [])
    bm25_articles = [a for a in raw if a.get("source") == "bm25" or a.get("bm25_rank")]
    semantic_articles = [a for a in raw if a.get("distance") is not None and not a.get("bm25_rank")]
    entity_articles = [a for a in raw if a.get("tier") == "entity_targeted"]
    expansion_articles = [a for a in raw if a.get("source") == "expansion"]
    exception_articles = [a for a in raw if a.get("source") == "exception"]

    return {
        "step1_classification": {
            "question_type": state.get("question_type"),
            "legal_domain": state.get("legal_domain"),
            "legal_topic": state.get("legal_topic"),
            "entity_types": state.get("entity_types", []),
            "output_mode": state.get("output_mode"),
            "core_issue": state.get("core_issue"),
            "sub_issues": state.get("sub_issues", []),
        },
        "step2_law_mapping": {
            "candidate_laws": state.get("candidate_laws", []),
            "coverage_status": state.get("coverage_status", {}),
        },
        "step3_versions": {
            "selected_versions": state.get("selected_versions", {}),
            "version_notes": state.get("version_notes", []),
        },
        "step4_retrieval": {
            "articles_found": len(raw),
            "bm25_count": len(bm25_articles),
            "semantic_count": len(semantic_articles),
            "entity_count": len(entity_articles),
        },
        "step5_expansion": {
            "articles_after_expansion": len(raw),
            "expansion_added": len(expansion_articles),
            "exceptions_added": len(exception_articles),
        },
        "step6_selection": {
            "total_candidates": len(raw),
            "selected_count": len(state.get("retrieved_articles", [])),
            "top_articles": [
                {"article_number": a.get("article_number"), "score": round(a.get("reranker_score", 0), 3), "law": f"{a.get('law_number')}/{a.get('law_year')}"}
                for a in state.get("retrieved_articles", [])[:10]
            ],
        },
        "step6_5_relevance": {
            "relevance_score": state.get("relevance_score"),
        },
        "step7_answer": {
            "articles_used": len(state.get("retrieved_articles", [])),
            "confidence": state.get("confidence"),
            "flags": state.get("flags", []),
        },
    }
