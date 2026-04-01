"""Integration test for Pipeline V2 — runs against real DB and ChromaDB."""
import pytest
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "themis.db")
pytestmark = pytest.mark.skipif(
    not os.path.exists(DB_PATH),
    reason="No test database available"
)


def _get_db():
    """Get a DB session with proper model imports."""
    from app.models.category import Category, CategoryGroup  # must import first
    from app.database import SessionLocal
    return SessionLocal()


def test_simple_query_v2():
    """SIMPLE query should skip Step 4 (reasoning) and return an answer."""
    from app.services.pipeline_v2_service import run_pipeline_v2

    db = _get_db()
    try:
        events = list(run_pipeline_v2(
            question="Care este capitalul social minim pentru un SRL?",
            session_context=[],
            db=db,
        ))

        # Check step events
        step_events = [e for e in events if e.get("type") == "step"]
        done_step_names = [e["name"] for e in step_events if e.get("status") == "done"]

        assert "classify" in done_step_names, f"Missing classify step. Got: {done_step_names}"
        assert "resolve" in done_step_names, f"Missing resolve step. Got: {done_step_names}"
        assert "retrieve" in done_step_names, f"Missing retrieve step. Got: {done_step_names}"
        assert "answer" in done_step_names, f"Missing answer step. Got: {done_step_names}"
        # Step 4 (reasoning) should NOT appear for SIMPLE
        assert "reasoning" not in done_step_names, f"reasoning should be skipped for SIMPLE. Got: {done_step_names}"

        # Check for done event
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) == 1, f"Expected 1 done event, got {len(done_events)}"
        done = done_events[0]
        assert done.get("content"), "Done event should have content (answer)"
        assert done.get("confidence") in ("LOW", "MEDIUM", "HIGH"), f"Bad confidence: {done.get('confidence')}"
        assert done.get("reasoning", {}).get("pipeline_version") == "v2"

        # Check no errors
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) == 0, f"Got errors: {error_events}"

    finally:
        db.close()


def test_complex_query_v2():
    """COMPLEX/STANDARD query should run all 5 steps including reasoning."""
    from app.services.pipeline_v2_service import run_pipeline_v2

    db = _get_db()
    try:
        events = list(run_pipeline_v2(
            question="Dacă un administrator al unui SRL transferă bani din firmă către o altă firmă pe care o controlează indirect, fără aprobarea asociaților, iar firma intră în insolvență după un an, poate răspunde personal?",
            session_context=[],
            db=db,
        ))

        step_events = [e for e in events if e.get("type") == "step"]
        done_step_names = [e["name"] for e in step_events if e.get("status") == "done"]

        assert "classify" in done_step_names
        assert "resolve" in done_step_names
        assert "retrieve" in done_step_names
        assert "reasoning" in done_step_names, f"reasoning should run for complex query. Got: {done_step_names}"
        assert "answer" in done_step_names

        # Check done event
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) == 1
        done = done_events[0]
        assert done.get("content")
        assert done.get("reasoning", {}).get("pipeline_version") == "v2"

        # Reasoning panel should have step4 data
        reasoning = done.get("reasoning", {})
        assert "step4_reasoning" in reasoning, f"Missing step4_reasoning in panel. Keys: {list(reasoning.keys())}"

        # Check no errors
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) == 0, f"Got errors: {error_events}"

    finally:
        db.close()
