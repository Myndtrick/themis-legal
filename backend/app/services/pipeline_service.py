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
# Step 6.8 helpers
# ---------------------------------------------------------------------------


def _build_step6_8_context(state: dict) -> str:
    """Build the user message for Step 6.8 from structured state."""
    parts = []

    # Facts
    facts = state.get("facts", {})
    if facts.get("stated") or facts.get("assumed") or facts.get("missing"):
        parts.append("STATED FACTS:")
        for f in facts.get("stated", []):
            date_str = f" ({f['date']})" if f.get("date") else ""
            parts.append(f"  {f['fact_id']}: {f['description']}{date_str}")

        if facts.get("assumed"):
            parts.append("\nASSUMED FACTS:")
            for f in facts["assumed"]:
                parts.append(f"  {f['fact_id']}: {f['description']} (basis: {f.get('basis', 'implied')})")

        if facts.get("missing"):
            parts.append("\nMISSING FACTS (identified by classifier):")
            for f in facts["missing"]:
                parts.append(f"  {f['fact_id']}: {f['description']} (relevance: {f.get('relevance', '')})")

    # Per-issue article sets
    issue_articles = state.get("issue_articles", {})
    issue_versions = state.get("issue_versions", {})
    legal_issues = state.get("legal_issues", [])

    for issue in legal_issues:
        iid = issue["issue_id"]
        parts.append(f"\n{iid}: {issue.get('description', '')}")
        parts.append(f"  Relevant date: {issue.get('relevant_date', 'unknown')} ({issue.get('temporal_rule', '')})")

        for law_key in issue.get("applicable_laws", []):
            iv_key = f"{iid}:{law_key}"
            iv = issue_versions.get(iv_key, {})
            if iv:
                parts.append(f"  Version used: {law_key}, date_in_force {iv.get('date_in_force', 'unknown')}")

        parts.append("  Articles:")
        for art in issue_articles.get(iid, []):
            law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
            parts.append(f"    [Art. {art.get('article_number', '')}] {law_ref}, version {art.get('date_in_force', '')}")
            parts.append(f"    {art.get('text', '')}")

    shared = state.get("shared_context", [])
    if shared:
        parts.append("\nSHARED CONTEXT (SECONDARY):")
        for art in shared:
            law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
            parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}")
            parts.append(f"  {art.get('text', '')}")

    flags = state.get("flags", [])
    if flags:
        parts.append("\nFLAGS AND WARNINGS:")
        for f in flags:
            parts.append(f"  - {f}")

    return "\n".join(parts)


def _build_step7_context(state: dict) -> str:
    """Build Step 7 user message. Uses RL-RAP output if available, falls back to raw articles."""
    parts = []

    parts.append("CLASSIFICATION:")
    parts.append(f"  Question type: {state.get('question_type', 'A')}")
    parts.append(f"  Legal domain: {state.get('legal_domain', 'unknown')}")
    parts.append(f"  Output mode: {state.get('output_mode', 'qa')}")
    parts.append(f"  Core issue: {state.get('core_issue', '')}")

    rl_rap = state.get("rl_rap_output")

    if rl_rap:
        # Structured facts
        facts = state.get("facts", {})
        if facts.get("stated") or facts.get("assumed") or facts.get("missing"):
            parts.append("\nSTRUCTURED FACTS:")
            for f in facts.get("stated", []):
                date_str = f" ({f['date']})" if f.get("date") else ""
                parts.append(f"  {f['fact_id']}: {f['description']}{date_str}")
            if facts.get("assumed"):
                parts.append("  Assumed:")
                for f in facts["assumed"]:
                    parts.append(f"    {f['fact_id']}: {f['description']} (basis: {f.get('basis', '')})")
            if facts.get("missing"):
                parts.append("  Missing:")
                for f in facts["missing"]:
                    parts.append(f"    {f['fact_id']}: {f['description']}")

        # RL-RAP analysis
        parts.append("\nLEGAL ANALYSIS (from reasoning step):")
        for issue in rl_rap.get("issues", []):
            parts.append(f"\n  {issue['issue_id']}: {issue.get('issue_label', '')}")
            parts.append(f"    Certainty: {issue.get('certainty_level', 'UNKNOWN')}")

            for oa in issue.get("operative_articles", []):
                parts.append(f"    Operative article: {oa['article_ref']} — {oa.get('disposition', {}).get('modality', '')}")

            parts.append("    Conditions:")
            for c in issue.get("decomposed_conditions", []):
                fact_refs = ", ".join(c.get("supporting_fact_ids", []))
                parts.append(f"      {c['condition_id']}: {c['condition_text']} — {c['condition_status']}" +
                           (f" ({fact_refs})" if fact_refs else ""))

            if issue.get("exceptions_checked"):
                parts.append("    Exceptions checked:")
                for ex in issue["exceptions_checked"]:
                    parts.append(f"      {ex['exception_ref']} — {ex['condition_status_summary']} — {ex.get('impact', '')}")

            if issue.get("conflicts"):
                c = issue["conflicts"]
                parts.append(f"    Conflict: {c.get('resolution_rule', 'UNRESOLVED')} — {c.get('rationale', '')}")

            ta = issue.get("temporal_applicability", {})
            if ta.get("temporal_risks"):
                parts.append(f"    Temporal risks: {', '.join(ta['temporal_risks'])}")

            parts.append(f"    Conclusion: {issue.get('conclusion', '')}")

            if issue.get("missing_facts"):
                parts.append(f"    Missing facts: {'; '.join(issue['missing_facts'])}")

        # Supporting article texts (operative only)
        operative_refs = set()
        for issue in rl_rap.get("issues", []):
            for oa in issue.get("operative_articles", []):
                operative_refs.add(oa.get("article_ref", ""))

        all_articles = state.get("retrieved_articles", [])
        parts.append("\nSUPPORTING ARTICLE TEXTS:")
        for art in all_articles:
            art_ref = f"art.{art.get('article_number', '')}"
            matched = any(art_ref in ref for ref in operative_refs)
            if matched:
                law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
                parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}, version {art.get('date_in_force', '')}")
                parts.append(f"  {art.get('text', '')}")
    else:
        # Fallback: no RL-RAP output, use raw articles
        parts.append("\nRETRIEVED LAW ARTICLES FROM LEGAL LIBRARY:")
        for i, art in enumerate(state.get("retrieved_articles", []), 1):
            role_tag = f"[{art.get('role', 'SECONDARY')}]"
            abrogated_tag = " [ABROGATED]" if art.get("is_abrogated") else ""
            law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
            parts.append(f"[Article {i}] {role_tag}{abrogated_tag} {law_ref}, Art. {art.get('article_number', '')}")
            if art.get("date_in_force"):
                parts.append(f"  version {art['date_in_force']}")
            parts.append(f"  {art.get('text', '')}")

    flags = state.get("flags", [])
    if flags:
        parts.append("\nFLAGS AND WARNINGS:")
        for f in flags:
            parts.append(f"  - {f}")

    parts.append(f"\nUSER QUESTION:\n{state.get('question', '')}")

    return "\n".join(parts)


def _parse_step6_8_output(raw: str) -> dict | None:
    """Parse Step 6.8 JSON output. Returns None if malformed."""
    try:
        parsed = _extract_json(raw)
        if parsed and "issues" in parsed:
            return parsed
        return None
    except Exception:
        return None


def _derive_confidence(issues: list[dict]) -> str:
    """Derive overall confidence from per-issue certainty levels."""
    if not issues:
        return "LOW"
    levels = [i.get("certainty_level", "UNCERTAIN") for i in issues]
    if any(l == "UNCERTAIN" for l in levels):
        return "LOW"
    if any(l == "CONDITIONAL" for l in levels):
        return "MEDIUM"
    return "HIGH"


def _cap_confidence(state: dict) -> None:
    """Cap Step 7's confidence to not exceed Step 6.8's derived confidence."""
    derived = state.get("derived_confidence")
    if not derived:
        return
    CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    derived_rank = CONF_ORDER.get(derived, 0)
    actual_rank = CONF_ORDER.get(state.get("confidence", "HIGH"), 2)
    if actual_rank > derived_rank:
        state["confidence"] = derived


def _step6_8_legal_reasoning(state: dict, db: Session) -> dict:
    """Step 6.8: RL-RAP legal reasoning. Returns state with rl_rap_output."""
    t0 = time.time()

    user_message = _build_step6_8_context(state)
    prompt_text, prompt_ver = load_prompt("LA-S6.8", db)

    response = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=4096,
        temperature=0.1,
    )

    raw_text = response.get("content", "")
    parsed = _parse_step6_8_output(raw_text)

    duration = time.time() - t0

    if parsed:
        state["rl_rap_output"] = parsed
        state["derived_confidence"] = _derive_confidence(parsed.get("issues", []))

        operative = []
        for issue in parsed.get("issues", []):
            for oa in issue.get("operative_articles", []):
                operative.append(oa)
        state["operative_articles"] = operative

        expected_ids = {i["issue_id"] for i in state.get("legal_issues", [])}
        returned_ids = {i["issue_id"] for i in parsed.get("issues", [])}
        missing_ids = expected_ids - returned_ids
        for mid in missing_ids:
            state["flags"].append(f"{mid}: not analyzed by reasoning step")

        log_step(
            db, state["run_id"], "legal_reasoning", 68, "done", duration,
            prompt_id="LA-S6.8",
            prompt_version=prompt_ver,
            output_summary=f"Analyzed {len(parsed['issues'])} issues",
            output_data={"certainty_levels": {i["issue_id"]: i["certainty_level"] for i in parsed["issues"]}},
            confidence=state["derived_confidence"],
        )
    else:
        state["rl_rap_output"] = None
        state["derived_confidence"] = None
        state["operative_articles"] = None
        state["flags"].append("Step 6.8 failed to produce valid analysis — falling back to direct answer generation")
        logger.warning(f"Step 6.8 failed to parse output for run {state['run_id']}")
        log_step(
            db, state["run_id"], "legal_reasoning", 68, "done", duration,
            output_summary="Failed to parse — fallback mode",
            warnings=["Malformed RL-RAP output"],
        )

    log_api_call(
        db, state["run_id"], "legal_reasoning",
        response.get("tokens_in", 0), response.get("tokens_out", 0),
        duration, model=response.get("model", "unknown"),
    )

    return state


def _check_missing_articles(rl_rap_output: dict) -> list[str]:
    """Extract missing article references from RL-RAP output. Cap at 5."""
    missing = []
    for issue in rl_rap_output.get("issues", []):
        for ref in issue.get("missing_articles_needed", []):
            if ref not in missing:
                missing.append(ref)
            if len(missing) >= 5:
                return missing
    return missing


def _fetch_missing_articles(missing_refs: list[str], state: dict, db: Session) -> list[dict]:
    """Attempt to fetch missing articles from DB. Returns list of new article dicts."""
    from app.models.law import Article
    import re

    fetched = []
    for ref in missing_refs:
        art_match = re.search(r"art\.?\s*(\d+(?:\^\d+)?)", ref)
        law_match = re.search(r"(\d+)/(\d{4})", ref)

        if not art_match:
            continue

        art_num = art_match.group(1)

        if law_match:
            law_number = law_match.group(1)
            law_year = law_match.group(2)
            law_key = f"{law_number}/{law_year}"
        else:
            continue

        selected = state.get("selected_versions", {})
        version_info = selected.get(law_key)
        if not version_info:
            continue

        law_version_id = version_info.get("law_version_id")
        if not law_version_id:
            continue

        article = (
            db.query(Article)
            .filter(Article.law_version_id == law_version_id, Article.article_number == art_num)
            .first()
        )
        if article:
            fetched.append({
                "article_id": article.id,
                "article_number": article.article_number,
                "law_number": law_number,
                "law_year": law_year,
                "law_version_id": law_version_id,
                "law_title": version_info.get("law_title", ""),
                "date_in_force": version_info.get("date_in_force", ""),
                "text": article.full_text or "",
                "source": "reasoning_request",
                "tier": "reasoning_request",
                "role": "PRIMARY",
                "is_abrogated": article.is_abrogated or False,
                "doc_type": "article",
            })

    return fetched


# ---------------------------------------------------------------------------
# Shared Steps 4-7.5 logic (used by both run_pipeline and resume_pipeline)
# ---------------------------------------------------------------------------


def _run_steps_4_through_7(state: dict, db: Session, run_id: str) -> Generator[dict, None, dict]:
    """Shared pipeline logic for Steps 4 through 7.5. Used by both run_pipeline and resume_pipeline.
    Yields SSE events. Returns final state."""

    if state.get("complexity") == "SIMPLE":
        # === FAST PATH ===
        # Step 4: Reduced retrieval (5+5 instead of 30+30)
        yield _step_event(4, "hybrid_retrieval", "running")
        t0 = time.time()
        state = _step4_hybrid_retrieval(state, db, tier_limits_override={
            "tier1_primary": 5,
            "tier2_secondary": 5,
        }, skip_entity_retrieval=True)
        yield _step_event(4, "hybrid_retrieval", "done", {
            "articles_found": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 6: Rerank to top 3
        yield _step_event(6, "article_selection", "running")
        t0 = time.time()
        state = _step6_select_articles(state, db, top_k_override=3)
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
            state["_gate_triggered"] = True
            return state

        # Step 7: Direct answer with simplified prompt
        yield _step_event(8, "answer_generation", "running")
        t0 = time.time()
        state["use_simple_prompt"] = True
        for event in _step7_answer_generation(state, db):
            yield event
        yield _step_event(8, "answer_generation", "done", duration=time.time() - t0)

        # Step 7.5: Citation Validation
        yield _step_event(85, "citation_validation", "running")
        t0 = time.time()
        state = _step7_5_citation_validation(state, db)
        yield _step_event(85, "citation_validation", "done", duration=time.time() - t0)

    else:
        # === FULL PATH (STANDARD/COMPLEX) ===
        # Step 4: Hybrid Retrieval
        yield _step_event(4, "hybrid_retrieval", "running")
        t0 = time.time()
        state = _step4_hybrid_retrieval(state, db)
        yield _step_event(4, "hybrid_retrieval", "done", {
            "articles_found": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 4.5: Pre-Expansion Relevance Filter
        yield _step_event(45, "pre_expansion_filter", "running")
        t0 = time.time()
        before_filter = len(state.get("retrieved_articles_raw", []))
        state = _step4_5_pre_expansion_filter(state)
        yield _step_event(45, "pre_expansion_filter", "done", {
            "before": before_filter,
            "after": len(state.get("retrieved_articles_raw", [])),
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
        yield _step_event(55, "exception_retrieval", "done", {
            "exceptions_added": len(state.get("retrieved_articles_raw", [])) - before_exceptions,
        }, time.time() - t0)

        # Step 6: Reranking (dynamic top_k)
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
            state["_gate_triggered"] = True
            return state

        # Step 6.7: Article-to-Issue Partitioning
        yield _step_event(67, "article_partitioning", "running")
        t0 = time.time()
        state = _step6_7_partition_articles(state, db)
        yield _step_event(67, "article_partitioning", "done", {
            "issues_with_articles": sum(1 for v in state.get("issue_articles", {}).values() if v),
            "shared_context": len(state.get("shared_context", [])),
        }, time.time() - t0)

        # Step 6.8: Legal Reasoning (RL-RAP)
        yield _step_event(68, "legal_reasoning", "running")
        state = _step6_8_legal_reasoning(state, db)
        yield _step_event(68, "legal_reasoning", "done", {
            "has_analysis": state.get("rl_rap_output") is not None,
            "derived_confidence": state.get("derived_confidence"),
        })

        # Conditional Retrieval Pass
        if state.get("rl_rap_output"):
            missing = _check_missing_articles(state["rl_rap_output"])
            if missing:
                yield _step_event(69, "conditional_retrieval", "running")
                t0 = time.time()
                fetched = _fetch_missing_articles(missing, state, db)
                if fetched:
                    for art in fetched:
                        added = False
                        for iid, arts in state.get("issue_articles", {}).items():
                            iv_key = f"{iid}:{art['law_number']}/{art['law_year']}"
                            if iv_key in state.get("issue_versions", {}):
                                arts.append(art)
                                added = True
                        if not added:
                            state.setdefault("shared_context", []).append(art)
                    state = _step6_8_legal_reasoning(state, db)
                else:
                    state["flags"].append(f"Missing provisions not in library: {', '.join(missing)}")
                yield _step_event(69, "conditional_retrieval", "done", {
                    "requested": len(missing),
                    "fetched": len(fetched) if fetched else 0,
                }, time.time() - t0)

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

    # Cap confidence (runs on both paths, no-ops if derived_confidence is None)
    _cap_confidence(state)

    return state


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

        # Step 2.5: Early Relevance Gate — check if primary laws exist
        yield _step_event(25, "early_relevance_gate", "running")
        t0 = time.time()
        gate_result = _step2_5_early_relevance_gate(state, db)
        gate_duration = time.time() - t0
        if gate_result:
            candidate_laws = state.get("candidate_laws", [])
            primary_laws = [c for c in candidate_laws if c["role"] == "PRIMARY"]
            missing_primary = [c for c in primary_laws if c.get("availability") in ("missing", "wrong_version")]

            log_step(
                db, state["run_id"], "early_relevance_gate", 25, "done", gate_duration,
                output_summary=f"Gate triggered: {gate_result.get('type', 'unknown')}",
                output_data={
                    "gate_triggered": True,
                    "trigger_type": gate_result.get("type"),
                    "primary_laws_total": len(primary_laws),
                    "primary_laws_missing": len(missing_primary),
                },
                warnings=["Pipeline stopped — law coverage issue"],
            )

            if gate_result.get("type") == "pause":
                # Pipeline pauses — frontend will show import prompt
                yield _step_event(25, "early_relevance_gate", "done", {
                    "gate_triggered": True,
                    "reason": "pause_for_import",
                }, gate_duration)
                yield gate_result
                return
            else:
                # Pipeline terminates (e.g., no laws identified)
                complete_run(db, run_id, "clarification", None, state.get("flags"))
                db.commit()
                yield _step_event(25, "early_relevance_gate", "done", {
                    "gate_triggered": True,
                    "reason": gate_result.get("mode", "unknown"),
                }, gate_duration)
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

        # Run Steps 4-7.5 (shared between run_pipeline and resume_pipeline)
        path_gen = _run_steps_4_through_7(state, db, run_id)
        try:
            event = next(path_gen)
            while True:
                yield event
                event = next(path_gen)
        except StopIteration as e:
            if e.value:
                state = e.value

        if state.get("_gate_triggered"):
            return

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
    """Resume a paused pipeline after user import decisions.

    Imports requested laws, re-runs law mapping to pick up new data,
    then continues from Step 3 (version selection) onwards.
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
            if decision in ("import", "import_version"):
                try:
                    law_number, law_year = law_key.split("/")
                    from app.services.leropa_service import import_law_smart, import_remaining_versions
                    from app.services.fetcher import search_legislatie
                    from app.scheduler import scheduler

                    ver_id = search_legislatie(law_number, law_year)
                    if ver_id:
                        yield {"type": "step", "step": 25, "name": "importing", "status": "running",
                               "data": {"importing": law_key}}

                        relevant_date = state.get("law_date_map", {}).get(
                            law_key, state.get("primary_date")
                        )
                        result = import_law_smart(
                            db, ver_id,
                            primary_date=relevant_date,
                        )
                        # import_law_smart commits internally
                        state["flags"].append(f"Imported {law_key} from legislatie.just.ro")

                        # Rebuild FTS5 so hybrid retrieval finds the just-imported articles
                        try:
                            from app.services.bm25_service import rebuild_fts_index
                            rebuild_fts_index(db)
                        except Exception as e:
                            logger.warning(f"FTS5 rebuild failed (non-fatal): {e}")

                        # Schedule background import of remaining versions
                        if result.get("remaining_ver_ids"):
                            scheduler.add_job(
                                import_remaining_versions,
                                args=[
                                    result["law_id"],
                                    result["remaining_ver_ids"],
                                    result["date_lookup"],
                                ],
                                trigger="date",
                                id=f"bg_import_{law_key}",
                                replace_existing=True,
                            )
                            state["flags"].append(
                                f"Background: importing {len(result['remaining_ver_ids'])} "
                                f"remaining versions of {law_key}"
                            )

                        yield {"type": "step", "step": 25, "name": "importing", "status": "done",
                               "data": {"imported": law_key}}
                    else:
                        state["flags"].append(f"Could not find {law_key} on legislatie.just.ro — continuing without")
                except Exception as e:
                    logger.warning(f"Failed to import {law_key}: {e}")
                    state["flags"].append(f"Import failed for {law_key}: {str(e)[:100]}")

        # Re-run law mapping to pick up newly imported laws
        state = _step2_law_mapping(state, db)

        # Re-check gate: if PRIMARY laws are still unavailable, stop
        candidate_laws = state.get("candidate_laws", [])
        primary_laws = [c for c in candidate_laws if c["role"] == "PRIMARY"]
        still_missing = [
            c for c in primary_laws
            if c.get("availability") == "missing"
        ]
        still_wrong_version = [
            c for c in primary_laws
            if c.get("availability") == "wrong_version"
        ]

        if still_missing:
            names = ", ".join(
                f"{l.get('title', '')} ({l['law_number']}/{l['law_year']})"
                for l in still_missing
            )
            content = (
                f"Importul nu a reușit pentru: {names}. "
                f"Nu pot genera un răspuns fiabil fără aceste legi. "
                f"Vă rugăm să le importați manual din Biblioteca Juridică."
            )
            complete_run(db, run_id, "error", None, state.get("flags"))
            db.commit()
            yield {
                "type": "done",
                "run_id": run_id,
                "content": content,
                "structured": None,
                "mode": "error",
                "output_mode": "error",
                "confidence": "LOW",
                "flags": state.get("flags", []),
                "reasoning": _build_reasoning_panel(state),
            }
            return

        if still_wrong_version:
            names = ", ".join(
                f"{l.get('title', '')} ({l['law_number']}/{l['law_year']})"
                for l in still_wrong_version
            )
            content = (
                f"Legile au fost importate, dar versiunile corecte pentru data solicitată "
                f"nu sunt disponibile: {names}. "
                f"Răspunsul nu poate fi generat cu versiunea corectă a legii. "
                f"Puteți reformula întrebarea fără o dată specifică pentru a folosi versiunea curentă."
            )
            complete_run(db, run_id, "error", None, state.get("flags"))
            db.commit()
            yield {
                "type": "done",
                "run_id": run_id,
                "content": content,
                "structured": None,
                "mode": "error",
                "output_mode": "error",
                "confidence": "LOW",
                "flags": state.get("flags", []),
                "reasoning": _build_reasoning_panel(state),
            }
            return

        # Re-run from Step 3: Version Selection
        yield _step_event(3, "version_selection", "running")
        t0 = time.time()
        state = _step3_version_selection(state, db)
        yield _step_event(3, "version_selection", "done", {
            "selected_versions": state.get("selected_versions"),
        }, time.time() - t0)

        # Run Steps 4-7.5 (shared between run_pipeline and resume_pipeline)
        path_gen = _run_steps_4_through_7(state, db, run_id)
        try:
            event = next(path_gen)
            while True:
                yield event
                event = next(path_gen)
        except StopIteration as e:
            if e.value:
                state = e.value

        if state.get("_gate_triggered"):
            return

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
        max_tokens=2048,
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
            "events": [],
            "legal_issues": [],
        }

    state["question_type"] = parsed.get("question_type", "A")
    state["legal_domain"] = parsed.get("legal_domain", "other")
    state["output_mode"] = parsed.get("output_mode", "qa")
    state["core_issue"] = parsed.get("core_issue", state["question"][:200])
    state["sub_issues"] = parsed.get("sub_issues", [])
    state["legal_topic"] = parsed.get("legal_topic", "")
    state["entity_types"] = parsed.get("entity_types", [])
    state["applicable_laws"] = parsed.get("applicable_laws", [])
    state["events"] = parsed.get("events", [])
    state["legal_issues"] = parsed.get("legal_issues", [])

    # Parse complexity (default to STANDARD if missing)
    state["complexity"] = parsed.get("complexity", "STANDARD")

    # Parse structured facts (STANDARD/COMPLEX only)
    if state["complexity"] != "SIMPLE":
        state["facts"] = parsed.get("facts", {"stated": [], "assumed": [], "missing": []})
    else:
        state["facts"] = {"stated": [], "assumed": [], "missing": []}

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

    # Build law_date_map: latest relevant date per law across all issues
    law_date_map = {}
    for issue in state.get("legal_issues", []):
        for law_key in issue.get("applicable_laws", []):
            existing = law_date_map.get(law_key)
            issue_date = issue.get("relevant_date", "")
            if issue_date and issue_date != "unknown":
                if not existing or issue_date > existing:
                    law_date_map[law_key] = issue_date

    state["law_date_map"] = law_date_map
    state["primary_date"] = (
        max(law_date_map.values()) if law_date_map else state["today"]
    )

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
    """Check identified laws against DB — no Claude call, no static map."""
    from app.services.law_mapping import check_laws_in_db

    t0 = time.time()

    # Get laws identified by Step 1 classifier
    applicable_laws = state.get("applicable_laws", [])

    if not applicable_laws:
        # Claude didn't identify any laws — can't proceed
        state["law_mapping"] = {"tier1_primary": [], "tier2_secondary": []}
        state["candidate_laws"] = []
        state["coverage_status"] = {}
        duration = time.time() - t0
        log_step(
            db, state["run_id"], "law_mapping", 2, "done", duration,
            output_summary="No applicable laws identified by classifier",
            output_data={"candidate_laws": [], "coverage": {}},
        )
        return state

    # Check each law against DB + version availability
    enriched = check_laws_in_db(applicable_laws, db, state.get("law_date_map"))

    # Build law_mapping for downstream compatibility (tier1/tier2)
    mapping = {"tier1_primary": [], "tier2_secondary": []}
    for law in enriched:
        tier_key = "tier1_primary" if law["role"] == "PRIMARY" else "tier2_secondary"
        mapping[tier_key].append(law)
    state["law_mapping"] = mapping

    # Build candidate_laws for reasoning panel
    candidate_laws = []
    for law in enriched:
        candidate_laws.append({
            "law_number": law["law_number"],
            "law_year": law["law_year"],
            "role": law["role"],
            "source": "DB" if law["in_library"] else "General",
            "db_law_id": law.get("db_law_id"),
            "title": law.get("title", ""),
            "reason": law.get("reason", ""),
            "tier": "tier1_primary" if law["role"] == "PRIMARY" else "tier2_secondary",
            "availability": law.get("availability", "missing"),
            "available_version_date": law.get("available_version_date"),
        })
    state["candidate_laws"] = candidate_laws

    # Build coverage status
    coverage = {}
    for law in candidate_laws:
        key = f"{law['law_number']}/{law['law_year']}"
        coverage[key] = law["availability"]
    state["coverage_status"] = coverage

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "law_mapping", 2, "done", duration,
        output_summary=f"Mapped {len(candidate_laws)} laws ({sum(1 for c in candidate_laws if c.get('db_law_id'))} in DB)",
        output_data={
            "mapping": mapping,
            "coverage": coverage,
            "candidate_laws": candidate_laws,
        },
    )
    return state


# ---------------------------------------------------------------------------
# Step 2.5: Early Relevance Gate
# ---------------------------------------------------------------------------


def _get_temporal_reason_for_law(law_key: str, legal_issues: list[dict]) -> str | None:
    """Find the issue that drives the date need for a specific law."""
    for issue in legal_issues:
        if law_key in issue.get("applicable_laws", []):
            date = issue.get("relevant_date", "")
            desc = issue.get("description", "")
            if date and date != "unknown":
                return f"{desc} ({date})"
    return None


def _step2_5_early_relevance_gate(state: dict, db: Session) -> dict | None:
    """Check law availability. Returns None to continue, or a pause/done event dict."""
    candidate_laws = state.get("candidate_laws", [])

    if not candidate_laws:
        # No laws identified at all — return a done event
        return {
            "type": "done",
            "run_id": state["run_id"],
            "content": "Nu am putut identifica legile aplicabile pentru această întrebare. Vă rog să reformulați întrebarea cu mai multe detalii.",
            "structured": None,
            "mode": "clarification",
            "output_mode": "clarification",
            "confidence": "LOW",
            "flags": state.get("flags", []),
            "reasoning": _build_reasoning_panel(state),
        }

    # Check if any PRIMARY law needs import or has wrong version
    primary_laws = [c for c in candidate_laws if c["role"] == "PRIMARY"]
    needs_pause = any(
        law.get("availability") in ("missing", "wrong_version")
        for law in primary_laws
    )

    if needs_pause:
        # Save state for resume
        save_paused_state(db, state["run_id"], state)

        # Build law preview for frontend
        laws_preview = []
        law_date_map = state.get("law_date_map", {})
        for law in candidate_laws:
            law_key = f"{law['law_number']}/{law['law_year']}"
            preview = {
                "law_number": law["law_number"],
                "law_year": law["law_year"],
                "title": law.get("title", ""),
                "role": law["role"],
                "availability": law.get("availability", "missing"),
                "version_info": law.get("available_version_date"),
                "reason": law.get("reason", ""),
                "needed_for_date": law_date_map.get(law_key),
                "date_reason": _get_temporal_reason_for_law(
                    law_key, state.get("legal_issues", [])
                ),
            }
            laws_preview.append(preview)

        # Build user-friendly message
        missing = [l for l in primary_laws if l.get("availability") == "missing"]
        wrong_ver = [l for l in primary_laws if l.get("availability") == "wrong_version"]
        parts = []
        if missing:
            names = ", ".join(f"{l.get('title', '')} ({l['law_number']}/{l['law_year']})" for l in missing)
            parts.append(f"lipsesc din bibliotecă: {names}")
        if wrong_ver:
            names = ", ".join(f"{l.get('title', '')} ({l['law_number']}/{l['law_year']})" for l in wrong_ver)
            parts.append(f"au versiune incorectă: {names}")
        message = "Am identificat legile aplicabile. " + "; ".join(parts) + ". Doriți să le importăm?"

        return {
            "type": "pause",
            "run_id": state["run_id"],
            "message": message,
            "laws": laws_preview,
        }

    # Flag missing SECONDARY laws but don't pause
    secondary_missing = [
        c for c in candidate_laws
        if c["role"] == "SECONDARY" and c.get("availability") in ("missing", "wrong_version")
    ]
    for law in secondary_missing:
        state["flags"].append(
            f"SECONDARY law {law['law_number']}/{law['law_year']} ({law.get('title', '')}) "
            f"not available — answer may be incomplete"
        )

    return None


# ---------------------------------------------------------------------------
# Step 3: Version Selection (DB query — no Claude call)
# ---------------------------------------------------------------------------


def _step3_version_selection(state: dict, db: Session) -> dict:
    """Select law versions per legal issue, plus backward-compatible per-law dict."""
    t0 = time.time()
    today = state.get("today", datetime.date.today().isoformat())
    issue_versions = {}      # keyed by "ISSUE-N:law_number/law_year"
    selected_versions = {}   # backward-compat: keyed by "law_number/law_year" (latest version per law)
    unique_versions = {}     # keyed by "law_number/law_year" -> set of law_version_ids
    version_notes = []

    # Build a lookup: law_key -> db_law_id from candidate_laws
    law_id_lookup = {}
    for law_info in state.get("candidate_laws", []):
        if law_info.get("db_law_id"):
            key = f"{law_info['law_number']}/{law_info.get('law_year', '')}"
            law_id_lookup[key] = law_info["db_law_id"]

    # Cache: law_id -> list of versions (avoid repeated queries)
    versions_cache = {}

    def _get_versions(db_law_id):
        if db_law_id not in versions_cache:
            versions_cache[db_law_id] = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == db_law_id)
                .order_by(LawVersion.date_in_force.desc().nullslast())
                .all()
            )
        return versions_cache[db_law_id]

    def _find_version_for_date(versions, target_date):
        """Find the newest version with date_in_force <= target_date."""
        for v in versions:
            if v.date_in_force and str(v.date_in_force) <= target_date:
                return v
        return None

    def _fallback_version(versions):
        """Return current version, or first available."""
        current = [v for v in versions if v.is_current]
        return current[0] if current else versions[0] if versions else None

    legal_issues = state.get("legal_issues", [])

    if not legal_issues:
        # Fallback: no issue decomposition — behave like before with primary_date
        primary_date = state.get("primary_date", today)
        for law_key, db_law_id in law_id_lookup.items():
            versions = _get_versions(db_law_id)
            if not versions:
                continue
            selected = _find_version_for_date(versions, primary_date)
            if not selected:
                selected = _fallback_version(versions)
                version_notes.append(
                    f"{law_key}: No version found for {primary_date}, using current version"
                )
            if selected:
                selected_versions[law_key] = {
                    "law_version_id": selected.id,
                    "law_id": db_law_id,
                    "date_in_force": str(selected.date_in_force) if selected.date_in_force else None,
                    "is_current": selected.is_current,
                    "ver_id": selected.ver_id,
                }
                unique_versions.setdefault(law_key, set()).add(selected.id)
    else:
        # Per-issue version selection
        for issue in legal_issues:
            issue_id = issue.get("issue_id", "ISSUE-?")
            relevant_date = issue.get("relevant_date", today)

            # Handle "unknown" dates explicitly
            if relevant_date == "unknown":
                relevant_date = today

            # Future date rule
            if relevant_date > today:
                version_notes.append(
                    f"{issue_id}: Event date {relevant_date} is in the future — using current law"
                )
                relevant_date = today

            for law_key in issue.get("applicable_laws", []):
                db_law_id = law_id_lookup.get(law_key)
                if not db_law_id:
                    continue

                versions = _get_versions(db_law_id)
                if not versions:
                    continue

                selected = _find_version_for_date(versions, relevant_date)
                if not selected:
                    selected = _fallback_version(versions)
                    version_notes.append(
                        f"{issue_id}:{law_key}: No version for {relevant_date}, using current"
                    )

                if not selected:
                    continue

                combo_key = f"{issue_id}:{law_key}"
                issue_versions[combo_key] = {
                    "law_version_id": selected.id,
                    "law_id": db_law_id,
                    "issue_id": issue_id,
                    "law_key": law_key,
                    "relevant_date": relevant_date,
                    "date_in_force": str(selected.date_in_force) if selected.date_in_force else None,
                    "is_current": selected.is_current,
                    "temporal_rule": issue.get("temporal_rule", ""),
                    "date_reasoning": issue.get("date_reasoning", ""),
                    "ver_id": selected.ver_id,
                }

                # Track unique versions per law for retrieval
                unique_versions.setdefault(law_key, set()).add(selected.id)

                # Backward-compat: keep latest version per law in selected_versions
                existing = selected_versions.get(law_key)
                if not existing or (selected.date_in_force and (
                    not existing.get("date_in_force") or
                    str(selected.date_in_force) > existing["date_in_force"]
                )):
                    selected_versions[law_key] = {
                        "law_version_id": selected.id,
                        "law_id": db_law_id,
                        "date_in_force": str(selected.date_in_force) if selected.date_in_force else None,
                        "is_current": selected.is_current,
                        "ver_id": selected.ver_id,
                    }

    # Check for historical versions
    for key, v in selected_versions.items():
        if v.get("date_in_force") and not v.get("is_current"):
            version_notes.append(
                f"{key}: Using version from {v['date_in_force']} (not the current version)"
            )

    duration = time.time() - t0
    state["issue_versions"] = issue_versions
    state["selected_versions"] = selected_versions
    # Store as lists (not sets) so state is JSON-serializable for pause/resume
    state["unique_versions"] = {k: list(v) for k, v in unique_versions.items()}
    state["version_notes"] = version_notes

    if version_notes:
        state["flags"].extend(version_notes)

    log_step(
        db, state["run_id"], "version_selection", 3, "done",
        duration,
        output_summary=f"Selected {len(selected_versions)} law versions for {len(issue_versions)} issue-law pairs",
        output_data={
            "selected_versions": selected_versions,
            "issue_versions": {k: {kk: vv for kk, vv in v.items() if kk != "ver_id"} for k, v in issue_versions.items()},
            "notes": version_notes,
            "unique_version_count": sum(len(s) for s in unique_versions.values()),
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


def _step4_hybrid_retrieval(state: dict, db: Session, tier_limits_override: dict | None = None, skip_entity_retrieval: bool = False) -> dict:
    """BM25 + semantic search, per tier."""
    from app.services.bm25_service import search_bm25

    t0 = time.time()
    all_articles = []
    seen_ids = set()
    bm25_count = 0
    semantic_count = 0
    duplicates_removed = 0

    tier_limits = tier_limits_override or {
        "tier1_primary": 30,
        "tier2_secondary": 15,
    }

    TIER_TO_ROLE = {
        "tier1_primary": "PRIMARY",
        "tier2_secondary": "SECONDARY",
    }

    for tier_key, n_results in tier_limits.items():
        # Collect version IDs for this tier's laws (all versions needed across issues)
        version_ids = []
        for law in state.get("law_mapping", {}).get(tier_key, []):
            key = f"{law['law_number']}/{law['law_year']}"
            vids = state.get("unique_versions", {}).get(key, [])
            if vids:
                version_ids.extend(vids)
            else:
                # Fallback to selected_versions for backward compat
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
            doc_type = art.get("doc_type", "article")
            aid = f"{doc_type}:{art['article_id']}"
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
    if entity_types and not skip_entity_retrieval:
        # Get all version IDs from primary tier
        primary_version_ids = []
        for law in state.get("law_mapping", {}).get("tier1_primary", []):
            key = f"{law['law_number']}/{law['law_year']}"
            vids = state.get("unique_versions", {}).get(key, [])
            if vids:
                primary_version_ids.extend(vids)
            else:
                v = state.get("selected_versions", {}).get(key)
                if v:
                    primary_version_ids.append(v["law_version_id"])

        if primary_version_ids:
            for entity in entity_types:
                keywords = _ENTITY_KEYWORDS.get(entity.upper(), [])
                for kw in keywords:
                    entity_results = search_bm25(db, kw, primary_version_ids, limit=10)
                    for art in entity_results:
                        doc_type = art.get("doc_type", "article")
                        aid = f"{doc_type}:{art['article_id']}"
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
        if a.get("source") != "bm25"
        and "[Amendment:" not in a.get("text", "")
        and a.get("doc_type", "article") == "article"
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


def _step4_5_pre_expansion_filter(state: dict) -> dict:
    """Drop bottom-tier articles before expansion to reduce noise."""
    articles = state.get("retrieved_articles_raw", [])
    if len(articles) <= 10:
        return state

    # Compute BM25 median per tier
    tier_bm25_scores = {}
    for art in articles:
        if "bm25_rank" in art:
            tier = art.get("tier", "unknown")
            tier_bm25_scores.setdefault(tier, []).append(art["bm25_rank"])

    tier_bm25_medians = {}
    for tier, scores in tier_bm25_scores.items():
        sorted_scores = sorted(scores)
        mid = len(sorted_scores) // 2
        tier_bm25_medians[tier] = sorted_scores[mid]

    kept = []
    for art in articles:
        if art.get("source", "").startswith("entity:"):
            kept.append(art)
            continue

        bm25_ok = False
        if "bm25_rank" in art:
            tier = art.get("tier", "unknown")
            median = tier_bm25_medians.get(tier)
            if median is not None and art["bm25_rank"] <= median:
                bm25_ok = True

        semantic_ok = False
        if "distance" in art:
            if art["distance"] < 0.7:
                semantic_ok = True

        if bm25_ok or semantic_ok:
            kept.append(art)

    state["retrieved_articles_raw"] = kept
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


def _step6_select_articles(state: dict, db: Session, top_k_override: int | None = None) -> dict:
    """Rerank articles using cross-encoder, select top-k."""
    from app.services.reranker_service import rerank_articles

    num_issues = len(state.get("legal_issues", []))
    top_k = top_k_override or min(20, 5 + (num_issues * 5))

    t0 = time.time()
    raw = state.get("retrieved_articles_raw", [])
    if not raw:
        state["retrieved_articles"] = []
        log_step(db, state["run_id"], "article_selection", 6, "done", 0,
                 output_summary="No articles to select from")
        return state

    ranked = rerank_articles(state["question"], raw, top_k=top_k)
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


def _step6_7_partition_articles(state: dict, db: Session = None) -> dict:
    """Partition reranked articles by issue using issue_versions mapping."""
    articles = state.get("retrieved_articles", [])
    issue_versions = state.get("issue_versions", {})
    legal_issues = state.get("legal_issues", [])

    # Batch lookup law_version_id for articles that don't have it
    if db:
        from app.models.law import Article as ArticleModel
        missing_vid_ids = [a["article_id"] for a in articles if a.get("law_version_id") is None and a.get("article_id")]
        if missing_vid_ids:
            rows = db.query(ArticleModel.id, ArticleModel.law_version_id).filter(
                ArticleModel.id.in_(missing_vid_ids)
            ).all()
            vid_map = {r.id: r.law_version_id for r in rows}
            for art in articles:
                if art.get("law_version_id") is None and art.get("article_id") in vid_map:
                    art["law_version_id"] = vid_map[art["article_id"]]

    issue_articles: dict[str, list[dict]] = {
        issue["issue_id"]: [] for issue in legal_issues
    }
    shared_context: list[dict] = []

    # Build reverse map: law_version_id -> set of issue_ids
    version_to_issues: dict[int, set[str]] = {}
    for key, iv in issue_versions.items():
        vid = iv["law_version_id"]
        iid = iv["issue_id"]
        version_to_issues.setdefault(vid, set()).add(iid)

    for art in articles:
        art_version_id = art.get("law_version_id")
        if art_version_id is None:
            shared_context.append(art)
            continue

        matched_issues = version_to_issues.get(art_version_id, set())
        if matched_issues:
            for iid in matched_issues:
                if iid in issue_articles:
                    issue_articles[iid].append(art)
        else:
            shared_context.append(art)

    # Flag issues with zero articles
    flags = state.get("flags", [])
    for issue_id, arts in issue_articles.items():
        if len(arts) == 0:
            flags.append(f"ISSUE {issue_id}: no articles matched after partitioning")

    state["issue_articles"] = issue_articles
    state["shared_context"] = shared_context
    state["flags"] = flags
    return state


# ---------------------------------------------------------------------------
# Step 7: Answer Generation (RAG + Claude streaming)
# ---------------------------------------------------------------------------


def _step7_answer_generation(state: dict, db: Session) -> Generator[dict, None, None]:
    # Determine which prompt to use based on output mode
    mode = state.get("output_mode", "qa")
    if state.get("use_simple_prompt"):
        prompt_id = "LA-S7-simple"
    else:
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

    # Build user message using centralized context builder
    user_message = _build_step7_context(state)

    # Build conversation history for session memory
    history_msgs = []
    for msg in state.get("session_context", [])[-5:]:
        history_msgs.append({"role": msg["role"], "content": msg["content"][:500]})

    messages = history_msgs + [{"role": "user", "content": user_message}]

    # Stream the answer
    full_text = ""
    total_tokens_in = 0
    total_tokens_out = 0
    total_duration = 0.0

    for chunk in stream_claude(
        system=prompt_text,
        messages=messages,
        max_tokens=8192,
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
        state["answer"] = structured.get("answer", structured.get("short_answer", full_text))
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

    # Use operative articles from RL-RAP if available (stricter validation)
    if state.get("operative_articles"):
        provided = set()
        for oa in state["operative_articles"]:
            ref = oa.get("article_ref", "")
            # Parse "Legea 31/1990 art.197 alin.(3)" into components
            law_match = re.search(r"(\d+)/(\d{4})", ref)
            art_match = re.search(r"art\.?\s*(\d+(?:\^\d+)?)", ref)
            if law_match and art_match:
                law_key = f"{law_match.group(1)}/{law_match.group(2)}"
                art_num = art_match.group(1)
                provided.add((law_key, art_num))
    else:
        # Fallback: build from retrieved_articles (existing behavior)
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
