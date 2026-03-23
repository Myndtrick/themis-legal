"""
Legal Assistant Pipeline — 7-step legal reasoning engine.

Each step is a plain function: takes state dict + db, returns updated state.
The pipeline yields SSE events as it executes, enabling real-time streaming.

Steps:
  1. Issue Classification (Claude)
  2. Date Extraction (Claude)
  3. Law Identification (Claude + DB check)
  4. Coverage Check (DB query)
  5. Import Permission (conditional pause)
  6. Version Selection (DB query)
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
      {type: "pause", run_id: str, message: str, missing_laws: [...]}
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
        # Step 1: Issue Classification
        yield _step_event(1, "issue_classification", "running")
        t0 = time.time()
        state = _step1_issue_classification(state, db)
        yield _step_event(1, "issue_classification", "done", {
            "mode": state.get("output_mode"),
            "domain": state.get("legal_domain"),
            "question_type": state.get("question_type"),
            "core_issue": state.get("core_issue"),
        }, time.time() - t0)

        # Step 2: Date Extraction
        yield _step_event(2, "date_extraction", "running")
        t0 = time.time()
        state = _step2_date_extraction(state, db)
        yield _step_event(2, "date_extraction", "done", {
            "primary_date": state.get("primary_date"),
            "date_logic": state.get("date_logic"),
        }, time.time() - t0)

        # Step 3: Law Identification
        yield _step_event(3, "law_identification", "running")
        t0 = time.time()
        state = _step3_law_identification(state, db)
        yield _step_event(3, "law_identification", "done", {
            "candidate_laws": state.get("candidate_laws"),
        }, time.time() - t0)

        # Step 4: Coverage Check
        yield _step_event(4, "coverage_check", "running")
        t0 = time.time()
        state = _step4_coverage_check(state, db)
        yield _step_event(4, "coverage_check", "done", {
            "coverage": state.get("coverage_status"),
        }, time.time() - t0)

        # Step 5: Import Permission
        yield _step_event(5, "import_permission", "running")
        t0 = time.time()
        state = _step5_import_permission(state, db)
        if state.get("needs_user_input"):
            yield _step_event(5, "import_permission", "paused", duration=time.time() - t0)
            yield {
                "type": "pause",
                "run_id": run_id,
                "message": state.get("user_prompt", ""),
                "missing_laws": state.get("missing_primary_laws", []),
            }
            save_paused_state(db, run_id, state)
            db.commit()
            return
        yield _step_event(5, "import_permission", "done", duration=time.time() - t0)

        # Step 6: Version Selection
        yield _step_event(6, "version_selection", "running")
        t0 = time.time()
        state = _step6_version_selection(state, db)
        yield _step_event(6, "version_selection", "done", {
            "selected_versions": state.get("selected_versions"),
        }, time.time() - t0)

        # Step 7: Answer Generation (streaming)
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
    """Resume a paused pipeline after user responds to import request."""
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
                # Actual import is handled by the router calling leropa_service

        # Continue from Step 6
        yield _step_event(6, "version_selection", "running")
        t0 = time.time()
        state = _step6_version_selection(state, db)
        yield _step_event(6, "version_selection", "done", {
            "selected_versions": state.get("selected_versions"),
        }, time.time() - t0)

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
# Step 1: Issue Classification
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
# Step 2: Date Extraction
# ---------------------------------------------------------------------------


def _step2_date_extraction(state: dict, db: Session) -> dict:
    prompt_text, prompt_ver = load_prompt("LA-S2", db)

    user_msg = (
        f"Today's date: {state['today']}\n\n"
        f"Question type: {state['question_type']}\n"
        f"Legal domain: {state['legal_domain']}\n"
        f"Core issue: {state['core_issue']}\n\n"
        f"ORIGINAL QUESTION:\n{state['question']}"
    )

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=1024,
    )

    log_api_call(
        db, state["run_id"], "date_extraction",
        result["tokens_in"], result["tokens_out"], result["duration"], result["model"],
    )

    parsed = _extract_json(result["content"])
    if not parsed:
        parsed = {
            "dates_found": [],
            "primary_date": state["today"],
            "date_logic": "Could not parse date extraction; using today's date as default",
            "needs_clarification": False,
        }

    state["dates_found"] = parsed.get("dates_found", [])
    state["primary_date"] = parsed.get("primary_date", state["today"])
    state["date_logic"] = parsed.get("date_logic", "")
    state["date_needs_clarification"] = parsed.get("needs_clarification", False)

    log_step(
        db, state["run_id"], "date_extraction", 2, "done",
        result["duration"],
        prompt_id="LA-S2", prompt_version=prompt_ver,
        input_summary=state["question"][:200],
        output_summary=f"Primary date: {state['primary_date']}",
        output_data=parsed,
    )

    return state


# ---------------------------------------------------------------------------
# Step 3: Law Identification
# ---------------------------------------------------------------------------


def _step3_law_identification(state: dict, db: Session) -> dict:
    prompt_text, prompt_ver = load_prompt("LA-S3", db)

    # Build the list of laws in the Library — full titles, with status
    laws_in_db = db.query(Law).all()
    library_list = []
    for i, law in enumerate(laws_in_db, 1):
        library_list.append(
            f"{i}. {law.law_number}/{law.law_year} — {law.title} "
            f"({law.document_type}, {law.status})"
        )

    # Also build a lookup for fuzzy matching later
    db_law_lookup = {}
    for law in laws_in_db:
        # Normalize: strip leading zeros, lowercase
        num_key = law.law_number.strip().lstrip("0") or law.law_number.strip()
        db_law_lookup[f"{num_key}/{law.law_year}"] = law
        db_law_lookup[f"{law.law_number}/{law.law_year}"] = law

    state["_db_law_lookup"] = db_law_lookup

    user_msg = (
        f"QUESTION TYPE: {state['question_type']}\n"
        f"LEGAL DOMAIN: {state['legal_domain']}\n"
        f"CORE ISSUE: {state['core_issue']}\n"
        f"RELEVANT DATE: {state['primary_date']}\n\n"
        f"LAWS CURRENTLY IN LEGAL LIBRARY ({len(laws_in_db)} laws):\n"
        + "\n".join(library_list) + "\n\n"
        f"ORIGINAL QUESTION:\n{state['question']}"
    )

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=2048,
    )

    log_api_call(
        db, state["run_id"], "law_identification",
        result["tokens_in"], result["tokens_out"], result["duration"], result["model"],
    )

    parsed = _extract_json(result["content"])
    if not parsed:
        parsed = {"candidate_laws": [], "reasoning": "Failed to parse law identification"}

    candidates = parsed.get("candidate_laws", [])

    # Fuzzy match: for each candidate, try to find it in the DB
    for law_info in candidates:
        num = str(law_info.get("law_number", "")).strip().lstrip("0") or str(law_info.get("law_number", "")).strip()
        year = str(law_info.get("law_year", "")).strip()
        key = f"{num}/{year}"

        matched = db_law_lookup.get(key)
        if not matched:
            # Try original number without stripping
            key2 = f"{law_info.get('law_number', '')}/{year}"
            matched = db_law_lookup.get(key2)

        if matched:
            law_info["db_law_id"] = matched.id
            law_info["source"] = "DB"
            law_info["db_title"] = matched.title
        else:
            law_info["db_law_id"] = None
            if law_info.get("source") != "Unverified":
                law_info["source"] = law_info.get("source", "General")

    state["candidate_laws"] = candidates

    log_step(
        db, state["run_id"], "law_identification", 3, "done",
        result["duration"],
        prompt_id="LA-S3", prompt_version=prompt_ver,
        input_summary=f"Domain: {state['legal_domain']}, Issue: {state['core_issue'][:100]}",
        output_summary=f"Found {len(candidates)} candidate laws, {sum(1 for c in candidates if c.get('db_law_id'))} in DB",
        output_data=parsed,
    )

    return state


# ---------------------------------------------------------------------------
# Step 4: Coverage Check (DB query — no Claude call)
# ---------------------------------------------------------------------------


def _step4_coverage_check(state: dict, db: Session) -> dict:
    t0 = time.time()
    coverage = {}
    missing_laws = []

    for law_info in state.get("candidate_laws", []):
        key = f"{law_info.get('law_number', '')}/{law_info.get('law_year', '')}"
        db_law_id = law_info.get("db_law_id")

        if db_law_id:
            # Already matched in Step 3 — just check versions exist
            has_version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == db_law_id)
                .first()
            )
            coverage[key] = "full" if has_version else "partial"
        else:
            coverage[key] = "missing"
            missing_laws.append(law_info)

    duration = time.time() - t0
    state["coverage_status"] = coverage
    state["missing_laws"] = missing_laws

    log_step(
        db, state["run_id"], "coverage_check", 4, "done",
        duration,
        input_summary=f"Checking {len(state.get('candidate_laws', []))} laws",
        output_summary=f"Coverage: {sum(1 for v in coverage.values() if v == 'full')} full, "
                       f"{sum(1 for v in coverage.values() if v == 'missing')} missing",
        output_data={"coverage": coverage},
    )

    return state


# ---------------------------------------------------------------------------
# Step 5: Import Permission
# ---------------------------------------------------------------------------


def _step5_import_permission(state: dict, db: Session) -> dict:
    missing_primary = [
        law for law in state.get("missing_laws", [])
        if law.get("role") == "PRIMARY"
    ]
    missing_secondary = [
        law for law in state.get("missing_laws", [])
        if law.get("role") in ("SECONDARY", "CONNECTED")
    ]

    if not missing_primary:
        # No primary laws missing — proceed
        state["needs_user_input"] = False
        state["missing_primary_laws"] = []

        # Flag secondary missing laws
        for law in missing_secondary:
            key = f"{law.get('law_number')}/{law.get('law_year')}"
            state["flags"].append(
                f"{key} ({law.get('title', 'unknown')}) not in Library — "
                f"answer may be incomplete on {law.get('reason', 'related aspects')}"
            )

        log_step(
            db, state["run_id"], "import_permission", 5, "done", 0.0,
            output_summary="No primary laws missing, proceeding",
        )
        return state

    # Primary laws missing — generate import request and pause
    prompt_text, prompt_ver = load_prompt("LA-S5", db)

    user_msg = (
        f"QUESTION: {state['question']}\n\n"
        f"MISSING PRIMARY LAWS:\n"
        + json.dumps(missing_primary, ensure_ascii=False, indent=2) + "\n\n"
        f"MISSING SECONDARY LAWS:\n"
        + json.dumps(missing_secondary, ensure_ascii=False, indent=2) + "\n\n"
        f"AVAILABLE LAWS IN LIBRARY:\n"
        + json.dumps(
            [f"{l['law_number']}/{l['law_year']}" for l in state.get("candidate_laws", [])
             if l.get("source") == "DB"],
            ensure_ascii=False,
        )
    )

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=1024,
    )

    log_api_call(
        db, state["run_id"], "import_permission",
        result["tokens_in"], result["tokens_out"], result["duration"], result["model"],
    )

    parsed = _extract_json(result["content"])
    if not parsed:
        parsed = {
            "should_pause": True,
            "message": f"Missing primary law(s): {', '.join(l.get('law_number', '?') + '/' + str(l.get('law_year', '?')) for l in missing_primary)}. Import to continue?",
        }

    state["needs_user_input"] = parsed.get("should_pause", True)
    state["user_prompt"] = parsed.get("message", "")
    state["missing_primary_laws"] = [
        {
            "law_number": l.get("law_number"),
            "law_year": l.get("law_year"),
            "title": l.get("title", ""),
            "reason": l.get("reason", ""),
        }
        for l in missing_primary
    ]

    log_step(
        db, state["run_id"], "import_permission", 5,
        "paused" if state["needs_user_input"] else "done",
        result["duration"],
        prompt_id="LA-S5", prompt_version=prompt_ver,
        output_summary=f"Missing {len(missing_primary)} primary laws, pause={state['needs_user_input']}",
    )

    return state


# ---------------------------------------------------------------------------
# Step 6: Version Selection (DB query — no Claude call)
# ---------------------------------------------------------------------------


def _step6_version_selection(state: dict, db: Session) -> dict:
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
        # Use the same logic as THEMIS-SHARED-v1 Section 2:
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
            # No version dated before the primary date — use the current version
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
        db, state["run_id"], "version_selection", 6, "done",
        duration,
        output_summary=f"Selected {len(selected_versions)} law versions",
        output_data={"selected_versions": selected_versions, "notes": version_notes},
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

    # RAG: retrieve relevant articles from ChromaDB
    version_ids = [
        v["law_version_id"] for v in state.get("selected_versions", {}).values()
    ]

    retrieved = []
    if version_ids:
        retrieved = query_articles(
            query_text=state["question"],
            law_version_ids=version_ids,
            n_results=20,
            db=db,
        )

    # Fallback: if filtered search returned nothing (or no versions selected),
    # do a broad search across all articles
    if not retrieved:
        retrieved = query_articles(
            query_text=state["question"],
            n_results=15,
            db=db,
        )
        if retrieved and not version_ids:
            state["flags"].append(
                "No specific law versions matched — used broad semantic search across all articles"
            )

    state["retrieved_articles"] = retrieved

    # Build the context for Claude
    articles_context = ""
    if retrieved:
        articles_context = "RETRIEVED LAW ARTICLES FROM LEGAL LIBRARY:\n\n"
        for i, art in enumerate(retrieved, 1):
            articles_context += (
                f"[Article {i}] {art['law_title']} "
                f"({art['law_number']}/{art['law_year']}), "
                f"Art. {art['article_number']}"
            )
            if art.get("date_in_force"):
                articles_context += f", version {art['date_in_force']}"
            articles_context += f"\n{art['text']}\n\n"

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
        f"  Primary date: {state.get('primary_date', 'today')}\n"
        f"  Date logic: {state.get('date_logic', '')}\n\n"
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

    if state.get("missing_laws"):
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
            "output_mode": state.get("output_mode"),
            "core_issue": state.get("core_issue"),
            "sub_issues": state.get("sub_issues", []),
        },
        "step2_dates": {
            "primary_date": state.get("primary_date"),
            "date_logic": state.get("date_logic"),
            "dates_found": state.get("dates_found", []),
        },
        "step3_laws": {
            "candidate_laws": state.get("candidate_laws", []),
        },
        "step4_coverage": {
            "coverage_status": state.get("coverage_status", {}),
        },
        "step5_imports": {
            "missing_primary": state.get("missing_primary_laws", []),
            "import_decisions": state.get("import_decisions", {}),
        },
        "step6_versions": {
            "selected_versions": state.get("selected_versions", {}),
            "version_notes": state.get("version_notes", []),
        },
        "step7_answer": {
            "articles_retrieved": len(state.get("retrieved_articles", [])),
            "confidence": state.get("confidence"),
            "flags": state.get("flags", []),
        },
    }
