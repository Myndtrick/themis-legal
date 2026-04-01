"""
Pipeline V2 Orchestrator — 5-step legal reasoning engine.

Orchestrates the V2 pipeline steps, yielding SSE events for real-time streaming.

Steps:
  1. Classification (Claude)
  2. Resolve (law availability, version selection, concept search, currency, gate)
  3. Retrieve (hybrid per-issue retrieval)
  4. Reasoning (RL-RAP legal reasoning via Claude)  — skipped for SIMPLE
  5. Answer (streaming generation + citation validation)
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Generator

from sqlalchemy.orm import Session

from app.services.pipeline_v2_steps import (
    step1_classify,
    step2a_version_selection,
    step2b_concept_search,
    step2c_law_availability,
    step2d_currency_check,
    step2e_availability_gate,
    step3_retrieve_per_issue,
    step4_legal_reasoning,
    step5_answer_generation,
    step5b_citation_validation,
)
from app.services.pipeline_logger import (
    complete_run,
    create_run,
    log_step,
    load_paused_state,
    save_paused_state,
    update_run_mode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step_event(step: int, name: str, status: str, data: dict | None = None, duration: float = 0) -> dict:
    """Build a step SSE event."""
    return {
        "type": "step",
        "step": step,
        "name": name,
        "status": status,
        "data": data or {},
        "duration": round(duration, 2),
    }


def _derive_confidence(state: dict) -> str:
    """Derive final confidence from accumulated pipeline signals."""
    confidence = state.get("claude_confidence") or "MEDIUM"

    flags = state.get("flags", [])

    # Downgrade triggers
    downgrade_flags = {
        "step4_parse_failure",      # rl_rap_parse_failed
        "step4_truncated",          # rl_rap_truncated
        "majority_phantom_citations",
    }
    if downgrade_flags & set(flags):
        confidence = "LOW"

    # Check RL-RAP certainty levels
    rl_rap = state.get("rl_rap_output")
    if rl_rap and confidence != "LOW":
        certainties = [
            issue.get("certainty_level", "UNKNOWN")
            for issue in rl_rap.get("issues", [])
        ]
        if certainties:
            if any(c == "UNCERTAIN" for c in certainties):
                confidence = "LOW"
            elif all(c == "CERTAIN" for c in certainties):
                confidence = "HIGH"

    # Low relevance signal downgrades HIGH -> MEDIUM
    if confidence == "HIGH":
        if any(f.startswith("low_relevance_signal") for f in flags):
            confidence = "MEDIUM"

    return confidence


def _build_v2_reasoning_panel(state: dict) -> dict:
    """Build the reasoning panel dict for the frontend."""
    panel: dict = {"pipeline_version": "v2"}

    # Step 1 — Classification
    panel["step1_classification"] = {
        "question_type": state.get("question_type"),
        "legal_domain": state.get("legal_domain"),
        "legal_topic": state.get("legal_topic"),
        "entity_types": state.get("entity_types", []),
        "output_mode": state.get("output_mode"),
        "core_issue": state.get("core_issue"),
        "complexity": state.get("complexity"),
    }

    # Step 2 — Resolve
    concept_candidates = state.get("concept_candidates", {})
    panel["step2_resolve"] = {
        "fact_version_map": state.get("fact_version_map", {}),
        "concept_candidates_per_issue": {
            iid: len(arts) for iid, arts in concept_candidates.items()
        },
        "coverage_status": state.get("coverage_status", {}),
    }

    # Step 3 — Retrieve
    issue_articles = state.get("issue_articles", {})
    per_issue: dict = {}
    total_articles = 0
    for iid, arts in issue_articles.items():
        sources = {}
        for a in arts:
            src = a.get("source", "unknown")
            sources[src] = sources.get(src, 0) + 1
        per_issue[iid] = {"count": len(arts), "sources": sources}
        total_articles += len(arts)

    panel["step3_retrieve"] = {
        "per_issue": per_issue,
        "total_articles": total_articles,
    }

    # Step 4 — Reasoning (only if RL-RAP output exists)
    rl_rap = state.get("rl_rap_output")
    if rl_rap:
        issues_analyzed = []
        certainty_levels = {}
        operative_articles = []
        governing_norms = {}

        for issue in rl_rap.get("issues", []):
            iid = issue.get("issue_id", "?")
            issues_analyzed.append(iid)
            certainty_levels[iid] = issue.get("certainty_level", "UNKNOWN")
            for oa in issue.get("operative_articles", []):
                operative_articles.append(oa.get("article_ref", ""))
            gns = issue.get("governing_norm_status", {})
            if gns:
                governing_norms[iid] = gns.get("status", "")

        panel["step4_reasoning"] = {
            "issues_analyzed": issues_analyzed,
            "certainty_levels": certainty_levels,
            "operative_articles": operative_articles,
            "governing_norms": governing_norms,
        }

    # Step 5 — Answer
    panel["step5_answer"] = {
        "confidence": state.get("final_confidence", "MEDIUM"),
        "phantom_citations": "majority_phantom_citations" in state.get("flags", []),
        "flags": state.get("flags", []),
    }

    return panel


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_pipeline_v2(
    question: str,
    session_context: list[dict],
    db: Session,
) -> Generator[dict, None, None]:
    """Run the full V2 pipeline, yielding SSE events."""
    run_id: str | None = None
    try:
        # -- Init --
        run_id = create_run(db, question)
        db.commit()

        today = datetime.date.today().isoformat()
        state: dict = {
            "question": question,
            "session_context": session_context,
            "today": today,
            "run_id": run_id,
            "flags": [],
        }

        # -- Step 1: Classification --
        yield _step_event(1, "classify", "running")
        t0 = time.time()

        state = step1_classify(state, db)

        duration = time.time() - t0
        mode = state.get("output_mode", "qa")
        log_step(
            db, run_id, "classify", 1, "done", duration,
            output_summary=f"type={state.get('question_type')} domain={state.get('legal_domain')} mode={mode} complexity={state.get('complexity')}",
            output_data={
                "question_type": state.get("question_type"),
                "legal_domain": state.get("legal_domain"),
                "output_mode": mode,
                "complexity": state.get("complexity"),
                "legal_issues_count": len(state.get("legal_issues", [])),
            },
        )
        update_run_mode(db, run_id, mode)
        db.commit()

        yield _step_event(1, "classify", "done", {
            "question_type": state.get("question_type"),
            "legal_domain": state.get("legal_domain"),
            "complexity": state.get("complexity"),
            "issues": len(state.get("legal_issues", [])),
        }, duration)

        # -- Step 2: Resolve --
        yield _step_event(2, "resolve", "running")
        t0 = time.time()

        # 2c must run before 2a (provides db_law_ids via candidate_laws)
        state = step2c_law_availability(state, db)
        state = step2a_version_selection(state, db)
        state = step2b_concept_search(state, db)
        state = step2d_currency_check(state, db)

        duration = time.time() - t0
        coverage = state.get("coverage_status", {})
        log_step(
            db, run_id, "resolve", 2, "done", duration,
            output_summary=f"laws={coverage.get('total', 0)} avail={coverage.get('available', 0)} missing={coverage.get('missing', 0)} versions={len(state.get('fact_version_map', {}))}",
            output_data={
                "coverage_status": coverage,
                "fact_version_count": len(state.get("fact_version_map", {})),
                "concept_candidates_count": sum(
                    len(v) for v in state.get("concept_candidates", {}).values()
                ),
            },
        )
        db.commit()

        # 2e: gate check
        gate_result = step2e_availability_gate(state, db)
        if gate_result:
            if gate_result["type"] == "pause":
                save_paused_state(db, run_id, state)
                db.commit()
                yield _step_event(2, "resolve", "done", {"gate": "paused"}, duration)
                yield gate_result
                return
            elif gate_result["type"] == "done":
                # Clarification / stop
                complete_run(db, run_id, "clarification", None, state.get("flags"))
                db.commit()
                yield _step_event(2, "resolve", "done", {"gate": "stopped"}, duration)
                yield gate_result
                return

        yield _step_event(2, "resolve", "done", {
            "coverage": coverage,
            "versions": len(state.get("fact_version_map", {})),
        }, duration)

        # -- Step 3: Retrieve --
        yield _step_event(3, "retrieve", "running")
        t0 = time.time()

        state = step3_retrieve_per_issue(state, db)

        duration = time.time() - t0
        issue_articles = state.get("issue_articles", {})
        total_articles = sum(len(v) for v in issue_articles.values())
        log_step(
            db, run_id, "retrieve", 3, "done", duration,
            output_summary=f"issues={len(issue_articles)} total_articles={total_articles}",
            output_data={
                "issues_count": len(issue_articles),
                "total_articles": total_articles,
                "per_issue": {k: len(v) for k, v in issue_articles.items()},
            },
        )
        db.commit()

        yield _step_event(3, "retrieve", "done", {
            "total_articles": total_articles,
            "issues": len(issue_articles),
        }, duration)

        # -- Step 4: Reasoning (skip for SIMPLE) --
        complexity = state.get("complexity", "STANDARD")
        if complexity != "SIMPLE":
            yield _step_event(4, "reasoning", "running")
            t0 = time.time()

            state = step4_legal_reasoning(state, db)

            duration = time.time() - t0
            rl_rap = state.get("rl_rap_output")
            issues_count = len(rl_rap.get("issues", [])) if rl_rap else 0
            log_step(
                db, run_id, "reasoning", 4, "done", duration,
                output_summary=f"issues_analyzed={issues_count} parse_ok={rl_rap is not None}",
                output_data={
                    "issues_analyzed": issues_count,
                    "parse_ok": rl_rap is not None,
                },
            )
            db.commit()

            yield _step_event(4, "reasoning", "done", {
                "issues_analyzed": issues_count,
                "has_analysis": rl_rap is not None,
            }, duration)

        # -- Step 5: Answer --
        yield _step_event(5, "answer", "running")
        t0 = time.time()

        # step5_answer_generation is a generator — stream tokens
        for event in step5_answer_generation(state, db):
            yield event

        # Citation validation
        state = step5b_citation_validation(state, db)

        # Derive confidence
        final_confidence = _derive_confidence(state)
        state["final_confidence"] = final_confidence

        duration = time.time() - t0
        log_step(
            db, run_id, "answer", 5, "done", duration,
            output_summary=f"confidence={final_confidence} flags={state.get('flags', [])}",
            output_data={
                "confidence": final_confidence,
                "flags": state.get("flags", []),
                "answer_length": len(state.get("answer", "")),
            },
            confidence=final_confidence,
        )
        db.commit()

        yield _step_event(5, "answer", "done", {
            "confidence": final_confidence,
        }, duration)

        # -- Finalize --
        reasoning_panel = _build_v2_reasoning_panel(state)

        complete_run(db, run_id, "success", final_confidence, state.get("flags"))
        db.commit()

        yield {
            "type": "done",
            "run_id": run_id,
            "content": state.get("answer", ""),
            "structured": state.get("answer_structured"),
            "mode": state.get("output_mode", "qa"),
            "confidence": final_confidence,
            "flags": state.get("flags", []),
            "reasoning": reasoning_panel,
        }

    except GeneratorExit:
        # Client disconnected — clean up silently
        if run_id:
            try:
                complete_run(db, run_id, "cancelled", None, None)
                db.commit()
            except Exception:
                pass
    except (OSError, IOError):
        # Client disconnect (broken pipe, etc.) — silent
        if run_id:
            try:
                complete_run(db, run_id, "cancelled", None, None)
                db.commit()
            except Exception:
                pass
    except Exception as exc:
        logger.exception("Pipeline V2 error: %s", exc)
        if run_id:
            try:
                complete_run(db, run_id, "error", None, state.get("flags") if "state" in dir() else None)
                db.commit()
            except Exception:
                pass
        yield {
            "type": "error",
            "error": str(exc),
            "run_id": run_id,
        }


# ---------------------------------------------------------------------------
# Resume after pause
# ---------------------------------------------------------------------------

def resume_pipeline_v2(
    run_id: str,
    import_decisions: dict,
    db: Session,
) -> Generator[dict, None, None]:
    """Resume a paused pipeline from Step 2 onward."""
    try:
        state = load_paused_state(db, run_id)
        if not state:
            yield {
                "type": "error",
                "error": f"No paused state found for run_id={run_id}",
                "run_id": run_id,
            }
            return

        state["run_id"] = run_id
        state["import_decisions"] = import_decisions

        # -- Step 2: Resolve (re-run from 2c) --
        yield _step_event(2, "resolve", "running")
        t0 = time.time()

        state = step2c_law_availability(state, db)
        state = step2a_version_selection(state, db)
        state = step2b_concept_search(state, db)
        state = step2d_currency_check(state, db)

        duration = time.time() - t0
        coverage = state.get("coverage_status", {})
        log_step(
            db, run_id, "resolve", 2, "done", duration,
            output_summary=f"resumed laws={coverage.get('total', 0)} avail={coverage.get('available', 0)}",
            output_data={
                "coverage_status": coverage,
                "resumed": True,
            },
        )
        db.commit()

        # Re-check gate
        gate_result = step2e_availability_gate(state, db)
        if gate_result:
            if gate_result["type"] == "pause":
                save_paused_state(db, run_id, state)
                db.commit()
                yield _step_event(2, "resolve", "done", {"gate": "paused"}, duration)
                yield gate_result
                return
            elif gate_result["type"] == "done":
                complete_run(db, run_id, "clarification", None, state.get("flags"))
                db.commit()
                yield _step_event(2, "resolve", "done", {"gate": "stopped"}, duration)
                yield gate_result
                return

        yield _step_event(2, "resolve", "done", {
            "coverage": coverage,
            "versions": len(state.get("fact_version_map", {})),
        }, duration)

        # -- Step 3: Retrieve --
        yield _step_event(3, "retrieve", "running")
        t0 = time.time()

        state = step3_retrieve_per_issue(state, db)

        duration = time.time() - t0
        issue_articles = state.get("issue_articles", {})
        total_articles = sum(len(v) for v in issue_articles.values())
        log_step(
            db, run_id, "retrieve", 3, "done", duration,
            output_summary=f"issues={len(issue_articles)} total_articles={total_articles}",
            output_data={
                "issues_count": len(issue_articles),
                "total_articles": total_articles,
            },
        )
        db.commit()

        yield _step_event(3, "retrieve", "done", {
            "total_articles": total_articles,
            "issues": len(issue_articles),
        }, duration)

        # -- Step 4: Reasoning (skip for SIMPLE) --
        complexity = state.get("complexity", "STANDARD")
        if complexity != "SIMPLE":
            yield _step_event(4, "reasoning", "running")
            t0 = time.time()

            state = step4_legal_reasoning(state, db)

            duration = time.time() - t0
            rl_rap = state.get("rl_rap_output")
            issues_count = len(rl_rap.get("issues", [])) if rl_rap else 0
            log_step(
                db, run_id, "reasoning", 4, "done", duration,
                output_summary=f"issues_analyzed={issues_count} parse_ok={rl_rap is not None}",
                output_data={
                    "issues_analyzed": issues_count,
                    "parse_ok": rl_rap is not None,
                },
            )
            db.commit()

            yield _step_event(4, "reasoning", "done", {
                "issues_analyzed": issues_count,
                "has_analysis": rl_rap is not None,
            }, duration)

        # -- Step 5: Answer --
        yield _step_event(5, "answer", "running")
        t0 = time.time()

        for event in step5_answer_generation(state, db):
            yield event

        state = step5b_citation_validation(state, db)

        final_confidence = _derive_confidence(state)
        state["final_confidence"] = final_confidence

        duration = time.time() - t0
        log_step(
            db, run_id, "answer", 5, "done", duration,
            output_summary=f"confidence={final_confidence} flags={state.get('flags', [])}",
            output_data={
                "confidence": final_confidence,
                "flags": state.get("flags", []),
                "answer_length": len(state.get("answer", "")),
            },
            confidence=final_confidence,
        )
        db.commit()

        yield _step_event(5, "answer", "done", {
            "confidence": final_confidence,
        }, duration)

        # -- Finalize --
        reasoning_panel = _build_v2_reasoning_panel(state)

        complete_run(db, run_id, "success", final_confidence, state.get("flags"))
        db.commit()

        yield {
            "type": "done",
            "run_id": run_id,
            "content": state.get("answer", ""),
            "structured": state.get("answer_structured"),
            "mode": state.get("output_mode", "qa"),
            "confidence": final_confidence,
            "flags": state.get("flags", []),
            "reasoning": reasoning_panel,
        }

    except GeneratorExit:
        try:
            complete_run(db, run_id, "cancelled", None, None)
            db.commit()
        except Exception:
            pass
    except (OSError, IOError):
        try:
            complete_run(db, run_id, "cancelled", None, None)
            db.commit()
        except Exception:
            pass
    except Exception as exc:
        logger.exception("Pipeline V2 resume error: %s", exc)
        try:
            complete_run(db, run_id, "error", None, state.get("flags") if "state" in dir() else None)
            db.commit()
        except Exception:
            pass
        yield {
            "type": "error",
            "error": str(exc),
            "run_id": run_id,
        }
