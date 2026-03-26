"""Tests for revised Step 7 context construction."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline_service import _build_step7_context


def test_context_includes_rl_rap_analysis(mock_state_standard, mock_rl_rap_output, mock_articles):
    """When RL-RAP output exists, context includes structured analysis."""
    mock_state_standard["rl_rap_output"] = mock_rl_rap_output
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "LEGAL ANALYSIS" in ctx
    assert "ISSUE-1" in ctx
    assert "CONDITIONAL" in ctx


def test_context_includes_operative_articles_only(mock_state_standard, mock_rl_rap_output, mock_articles):
    """Only operative articles from RL-RAP should appear in SUPPORTING ARTICLE TEXTS."""
    mock_state_standard["rl_rap_output"] = mock_rl_rap_output
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "SUPPORTING ARTICLE TEXTS" in ctx
    assert "art.197" in ctx.lower() or "Art. 197" in ctx


def test_context_fallback_without_rl_rap(mock_state_standard, mock_articles):
    """Without RL-RAP output, falls back to all retrieved articles."""
    mock_state_standard["rl_rap_output"] = None
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "RETRIEVED LAW ARTICLES" in ctx


def test_context_includes_facts(mock_state_standard, mock_rl_rap_output, mock_articles):
    """Facts should appear in the context."""
    mock_state_standard["rl_rap_output"] = mock_rl_rap_output
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "STRUCTURED FACTS" in ctx
    assert "F1:" in ctx


def test_context_includes_classification(mock_state_standard, mock_articles):
    """Classification section should always be present."""
    mock_state_standard["rl_rap_output"] = None
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "CLASSIFICATION:" in ctx
    assert "corporate" in ctx


def test_context_includes_user_question(mock_state_standard, mock_articles):
    """User question should always be at the end."""
    mock_state_standard["rl_rap_output"] = None
    mock_state_standard["retrieved_articles"] = mock_articles
    ctx = _build_step7_context(mock_state_standard)
    assert "USER QUESTION:" in ctx
    assert mock_state_standard["question"] in ctx
