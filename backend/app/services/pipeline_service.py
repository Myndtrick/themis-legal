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
from app.services.bm25_service import search_bm25
from app.services.prompt_service import load_prompt
from app.services.version_currency import check_version_currency

import re


def _strip_json_comments(text: str) -> str:
    """Remove // line comments from JSON-like text (not inside strings)."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        # Remove // comments that aren't inside quotes
        in_string = False
        escape = False
        for i, ch in enumerate(line):
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
            if not in_string and line[i:i+2] == "//":
                line = line[:i].rstrip()
                break
        cleaned.append(line)
    return "\n".join(cleaned)


def _try_parse_json(text: str) -> dict | None:
    """Try to parse JSON, with and without comment stripping."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try stripping // comments
    try:
        return json.loads(_strip_json_comments(text))
    except json.JSONDecodeError:
        pass
    return None


def _extract_json(text: str) -> dict | None:
    """Extract JSON from Claude's response, handling markdown wrappers and preamble text."""
    text = text.strip()

    # Try direct parse first
    result = _try_parse_json(text)
    if result is not None:
        return result

    # Try stripping markdown code blocks
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            result = _try_parse_json(match.group(1).strip())
            if result is not None:
                return result

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
                    result = _try_parse_json(text[brace_start : i + 1])
                    if result is not None:
                        return result
                    break

    return None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 12 helpers
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

    # Primary target and issue priorities
    primary_target = state.get("primary_target")
    if primary_target:
        parts.append("\nPRIMARY TARGET:")
        parts.append(f"  Actor: {primary_target.get('actor', 'unknown')}")
        parts.append(f"  Concern: {primary_target.get('concern', 'unknown')}")
        parts.append(f"  Primary issue: {primary_target.get('issue_id', 'unknown')}")

    # Per-issue article sets
    issue_articles = state.get("issue_articles", {})
    issue_versions = state.get("issue_versions", {})
    legal_issues = state.get("legal_issues", [])

    for issue in legal_issues:
        iid = issue["issue_id"]
        priority_tag = f" [{issue.get('priority', '')}]" if issue.get("priority") else ""
        parts.append(f"\n{iid}{priority_tag}: {issue.get('description', '')}")
        parts.append(f"  Relevant date: {issue.get('relevant_date', 'unknown')} ({issue.get('temporal_rule', '')})")

        for law_key in issue.get("applicable_laws", []):
            iv_key = f"{iid}:{law_key}"
            iv = issue_versions.get(iv_key, {})
            if iv:
                parts.append(f"  Version used: {law_key}, date_in_force {iv.get('date_in_force', 'unknown')}")

        # Show per-fact version info if available
        fact_version_map = state.get("fact_version_map", {})
        fact_entries = [
            (k, v) for k, v in fact_version_map.items()
            if v.get("issue_id") == iid
        ]
        if fact_entries:
            for fk, fv in fact_entries:
                if fv.get("date_in_force") and fv.get("fact_ref"):
                    parts.append(f"  Fact {fv['fact_ref']}: date={fv['relevant_date']}, "
                                 f"version={fv.get('date_in_force', 'unknown')}")
                    if fv.get("mitior_lex_newer_version"):
                        parts.append(f"    ⚠ Mitior lex: newer version exists ({fv['mitior_lex_newer_version']})")

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

    primary_target = state.get("primary_target")
    if primary_target:
        parts.append("\nPRIMARY TARGET:")
        parts.append(f"  Actor: {primary_target.get('actor', 'unknown')}")
        parts.append(f"  Concern: {primary_target.get('concern', 'unknown')}")
        parts.append(f"  Primary issue: {primary_target.get('issue_id', 'unknown')}")

    if state.get("governing_norm_incomplete"):
        parts.append("\nGOVERNING_NORM_INCOMPLETE: The governing norm for the primary issue was not found. See analysis for details.")

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

        # RL-RAP analysis — translated to Romanian for Step 14
        _STATUS_MAP = {
            "SATISFIED": "Condiție îndeplinită",
            "NOT_SATISFIED": "Condiție neîndeplinită",
            "UNKNOWN": "Informație lipsă",
        }
        _CERTAINTY_MAP = {
            "CERTAIN": "Concluzia este fermă.",
            "PROBABLE": "Concluzia este probabilă, cu rezerve minore.",
            "CONDITIONAL": "Concluzia depinde de informații lipsă.",
            "UNCERTAIN": "Analiza este incompletă — concluzie nesigură.",
        }
        _NORM_MAP = {
            "YES": "Norma se aplică",
            "NO": "Norma nu se aplică",
            "CONDITIONAL": "Aplicabilitate condiționată",
        }
        _UNCERTAINTY_TYPE_MAP = {
            "LIBRARY_GAP": "Articol indisponibil",
            "FACTUAL_GAP": "Informație lipsă din întrebare",
            "LEGAL_AMBIGUITY": "Chestiune juridică interpretabilă",
        }

        parts.append("\nLEGAL ANALYSIS (from reasoning step):")
        for issue in rl_rap.get("issues", []):
            parts.append(f"\n  {issue['issue_id']}: {issue.get('issue_label', '')}")
            certainty = issue.get("certainty_level", "UNKNOWN")
            parts.append(f"    {_CERTAINTY_MAP.get(certainty, certainty)}")

            for oa in issue.get("operative_articles", []):
                parts.append(f"    Operative article: {oa['article_ref']} — {oa.get('disposition', {}).get('modality', '')}")

            # Condition table — translated statuses
            if issue.get("condition_table"):
                parts.append("    Conditions:")
                for ct in issue["condition_table"]:
                    status_ro = _STATUS_MAP.get(ct.get("status", ""), ct.get("status", ""))
                    line = f"      {ct['condition_id']}: {ct['condition_text']} — {status_ro}"
                    if ct.get("evidence"):
                        line += f" (fapt: {ct['evidence']})"
                    if ct.get("missing_fact"):
                        line += f" [Lipsă: {ct['missing_fact']}]"
                    parts.append(line)

                summary = issue.get("subsumption_summary") or {}
                if summary:
                    norm_status = _NORM_MAP.get(summary.get("norm_applicable", "?"), summary.get("norm_applicable", "?"))
                    parts.append(
                        f"    Rezultat: {summary.get('satisfied', 0)} îndeplinite, "
                        f"{summary.get('not_satisfied', 0)} neîndeplinite, "
                        f"{summary.get('unknown', 0)} lipsă → {norm_status}"
                    )
                    if summary.get("blocking_unknowns"):
                        parts.append(f"    Condiții nerezolvate: {', '.join(summary['blocking_unknowns'])}")

            # Legacy conditions format
            elif issue.get("decomposed_conditions"):
                parts.append("    Conditions:")
                for c in issue.get("decomposed_conditions", []):
                    status_ro = _STATUS_MAP.get(c.get("condition_status", ""), c.get("condition_status", ""))
                    fact_refs = ", ".join(c.get("supporting_fact_ids", []))
                    parts.append(f"      {c['condition_id']}: {c['condition_text']} — {status_ro}" +
                               (f" ({fact_refs})" if fact_refs else ""))

            if issue.get("exceptions_checked"):
                parts.append("    Excepții verificate:")
                for ex in issue["exceptions_checked"]:
                    parts.append(f"      {ex['exception_ref']} — {ex['condition_status_summary']} — {ex.get('impact', '')}")

            if issue.get("conflicts"):
                c = issue["conflicts"]
                parts.append(f"    Conflict: {c.get('resolution_rule', 'UNRESOLVED')} — {c.get('rationale', '')}")

            ta = issue.get("temporal_applicability", {})
            if not ta.get("version_matches", True):
                parts.append("    ⚠ Versiunea legii utilizată nu corespunde exact datei evenimentului.")
            if ta.get("temporal_risks"):
                for risk in ta["temporal_risks"]:
                    parts.append(f"    Risc temporal: {risk}")

            parts.append(f"    Conclusion: {issue.get('conclusion', '')}")

            gns = issue.get("governing_norm_status", {})
            if gns.get("status") and gns["status"] != "PRESENT":
                parts.append(f"    Governing norm: {gns['status']} — {gns.get('explanation', '')}")

            # Uncertainty sources — translated
            if issue.get("uncertainty_sources"):
                parts.append("    Surse de incertitudine:")
                for us in issue["uncertainty_sources"]:
                    type_ro = _UNCERTAINTY_TYPE_MAP.get(us.get("type", ""), us.get("type", ""))
                    parts.append(f"      {type_ro}: {us['detail']} (impact: {us.get('impact', '')})")

            if issue.get("missing_facts"):
                parts.append(f"    Informații lipsă: {'; '.join(issue['missing_facts'])}")

        # Supporting article texts — operative first, then remaining
        operative_refs = set()
        for issue in rl_rap.get("issues", []):
            for oa in issue.get("operative_articles", []):
                operative_refs.add(oa.get("article_ref", ""))

        all_articles = [a for a in state.get("retrieved_articles", []) if a]
        operative_articles = []
        other_articles = []
        for art in all_articles:
            art_ref = f"art.{art.get('article_number', '')}"
            if any(art_ref in ref for ref in operative_refs):
                operative_articles.append(art)
            else:
                other_articles.append(art)

        parts.append("\nOPERATIVE ARTICLE TEXTS:")
        for art in operative_articles:
            law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
            parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}, version {art.get('date_in_force', '')}")
            parts.append(f"  {art.get('text', '')}")

        if other_articles:
            parts.append("\nADDITIONAL RETRIEVED ARTICLES (not flagged as operative by reasoning step — review for missed provisions):")
            for art in other_articles:
                law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
                parts.append(f"  [Art. {art.get('article_number', '')}] {law_ref}, version {art.get('date_in_force', '')}")
                parts.append(f"  {art.get('text', '')}")
    else:
        # Fallback: no RL-RAP output, use raw articles
        parts.append("\n⚠ FALLBACK MODE — NO STRUCTURED LEGAL ANALYSIS AVAILABLE.")
        parts.append("Step 12 (Legal Reasoning) did not produce valid output.")
        parts.append("CRITICAL OVERRIDE: Do NOT use the subsumption presentation format.")
        parts.append("Do NOT include ✅/❓ condition lists or condition-by-condition analysis.")
        parts.append("Present your analysis in NARRATIVE form based on the provided articles.")
        parts.append("State clearly in your answer that this analysis has not been validated through structured legal reasoning.")
        parts.append("")
        parts.append("\nRETRIEVED LAW ARTICLES FROM LEGAL LIBRARY:")
        for i, art in enumerate(state.get("retrieved_articles", []), 1):
            role_tag = f"[{art.get('role', 'SECONDARY')}]"
            abrogated_tag = " [ABROGATED]" if art.get("is_abrogated") else ""
            law_ref = f"{art.get('law_title', '')} ({art.get('law_number', '')}/{art.get('law_year', '')})"
            parts.append(f"[Article {i}] {role_tag}{abrogated_tag} {law_ref}, Art. {art.get('article_number', '')}")
            if art.get("date_in_force"):
                parts.append(f"  version {art['date_in_force']}")
            parts.append(f"  {art.get('text', '')}")

    # Stale version warnings for the answer generator
    stale_versions = state.get("stale_versions", [])
    if stale_versions:
        parts.append("\nVERSIUNI POTENȚIAL DEPĂȘITE:")
        for law_key in stale_versions:
            candidate = next(
                (c for c in state.get("candidate_laws", [])
                 if f"{c['law_number']}/{c['law_year']}" == law_key),
                None,
            )
            if candidate:
                parts.append(
                    f"  - Legea {law_key}: biblioteca conține versiunea din "
                    f"{candidate.get('db_latest_date', '?')}, dar pe legislatie.just.ro "
                    f"există o versiune din {candidate.get('official_latest_date', '?')}. "
                    f"Răspunsul se bazează pe versiunea din bibliotecă și poate fi incomplet sau incorect."
                )
            else:
                parts.append(f"  - Legea {law_key}: versiune potențial depășită")

    flags = state.get("flags", [])
    if flags:
        parts.append("\nFLAGS AND WARNINGS:")
        for f in flags:
            parts.append(f"  - {f}")

    parts.append(f"\nUSER QUESTION:\n{state.get('question', '')}")

    return "\n".join(parts)


def _parse_step6_8_output(raw: str) -> tuple[dict | None, str | None]:
    """Parse Step 6.8 JSON output. Returns (parsed_dict, error_message)."""
    try:
        parsed = _extract_json(raw)
        if not parsed or "issues" not in parsed:
            return None, f"JSON extracted but missing 'issues' key. Keys found: {list(parsed.keys()) if parsed else 'None'}"
        # Apply backward-compatible defaults for new fields
        for issue in parsed.get("issues", []):
            if "governing_norm_status" not in issue:
                issue["governing_norm_status"] = {"status": "PRESENT"}
            if "uncertainty_sources" not in issue:
                issue["uncertainty_sources"] = []
            if "subsumption_summary" not in issue:
                issue["subsumption_summary"] = None
        return parsed, None
    except Exception as e:
        return None, f"JSON parse error: {str(e)}"


def _derive_final_confidence(
    claude_confidence: str,
    rl_rap_issues: list[dict],
    has_articles: bool,
    primary_from_db: bool,
    missing_primary: bool,
    has_stale_versions: bool,
    citation_validation: dict,
    governing_norm_incomplete: bool = False,
    uncertainty_sources: list[dict] | None = None,
) -> tuple[str, str]:
    """Derive final confidence from all pipeline signals. Returns (confidence, reason)."""

    # Rule 1: No articles
    if not has_articles:
        return "LOW", "No relevant articles found"

    # Rule 2: Majority citations unverified
    total_db = citation_validation.get("total_db", 0)
    downgraded = citation_validation.get("downgraded", 0)
    if total_db > 0 and downgraded > total_db / 2:
        return "LOW", "Most citations could not be verified against provided articles"

    # Rule 3: UNCERTAIN issues
    if rl_rap_issues:
        levels = [i.get("certainty_level", "UNCERTAIN") for i in rl_rap_issues]
        if any(l == "UNCERTAIN" for l in levels):
            return "LOW", "Legal analysis has uncertain conditions"

    # Rule 3.5: Governing norm missing for primary issue
    if governing_norm_incomplete:
        return "LOW", "Governing norm for primary issue not found"

    # Start with Claude's assessment, then cap downward
    CONF_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    confidence = claude_confidence
    reason = "Based on model assessment"

    # Rule 4: CONDITIONAL caps at MEDIUM
    if rl_rap_issues:
        levels = [i.get("certainty_level", "UNCERTAIN") for i in rl_rap_issues]
        if any(l == "CONDITIONAL" for l in levels):
            if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
                confidence = "MEDIUM"
                reason = "Legal analysis has conditional conclusions"

    # Rule 4.5: LIBRARY_GAP caps at MEDIUM
    if uncertainty_sources:
        library_gaps = [u for u in uncertainty_sources if u.get("type") == "LIBRARY_GAP"]
        if library_gaps:
            if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
                confidence = "MEDIUM"
                reason = f"Library gap: {library_gaps[0].get('detail', 'missing provision')}"

    # Rule 4.6: Majority conditions UNKNOWN caps at MEDIUM
    if rl_rap_issues:
        for issue in rl_rap_issues:
            summary = issue.get("subsumption_summary") or {}
            total = summary.get("total_conditions", 0)
            unknown = summary.get("unknown", 0)
            if total > 0 and unknown > total / 2:
                if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
                    confidence = "MEDIUM"
                    reason = "Majority of legal conditions could not be evaluated"
                break

    # Rule 5: Primary not from DB
    if not primary_from_db:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Primary law source not from verified database"

    # Rule 6: Missing primary laws
    if missing_primary:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Primary law not in library"

    # Rule 7: Stale versions
    if has_stale_versions:
        if CONF_ORDER.get(confidence, 2) > CONF_ORDER["MEDIUM"]:
            confidence = "MEDIUM"
            reason = "Law version may be outdated"

    return confidence, reason


def _validate_article_coverage(state: dict, db: Session) -> dict:
    """Ensure each issue has articles from all its applicable laws.
    If a law has 0 articles for an issue, fetch directly from DB via BM25."""
    from collections import Counter

    issue_articles = state.get("issue_articles", {})
    issue_versions = state.get("issue_versions", {})

    for issue in state.get("legal_issues", []):
        iid = issue["issue_id"]
        arts = issue_articles.get(iid, [])

        law_counts = Counter(
            f"{a.get('law_number', '')}/{a.get('law_year', '')}" for a in arts
        )

        for law_key in issue.get("applicable_laws", []):
            if law_counts.get(law_key, 0) > 0:
                continue

            iv_key = f"{iid}:{law_key}"
            iv = issue_versions.get(iv_key, {})
            if not iv:
                continue

            version_id = iv["law_version_id"]
            fetched = search_bm25(db, state["question"], [version_id], limit=5)

            if fetched:
                for art in fetched:
                    art["_coverage_fix"] = True
                issue_articles.setdefault(iid, []).extend(fetched)
                state["flags"].append(
                    f"{iid}: {law_key} lipsea din rezultatele căutării — "
                    f"s-au adăugat {len(fetched)} articole direct din baza de date"
                )

    state["issue_articles"] = issue_articles

    # Also add to retrieved_articles so Step 14 context builder can render them
    for issue in state.get("legal_issues", []):
        iid = issue["issue_id"]
        for art in issue_articles.get(iid, []):
            if art.get("_coverage_fix"):
                state.setdefault("retrieved_articles", []).append(art)

    return state


def _step6_8_legal_reasoning(state: dict, db: Session) -> dict:
    """Step 6.8: RL-RAP legal reasoning. Returns state with rl_rap_output."""
    t0 = time.time()

    user_message = _build_step6_8_context(state)
    prompt_text, prompt_ver = load_prompt("LA-S6.8", db)

    num_issues = len(state.get("legal_issues", []))
    complexity = state.get("complexity", "STANDARD")
    if complexity == "COMPLEX" or num_issues >= 3:
        rl_rap_max_tokens = min(16384, 4096 + num_issues * 2048)
    else:
        rl_rap_max_tokens = 8192

    response = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": user_message}],
        max_tokens=rl_rap_max_tokens,
        temperature=0.1,
    )

    raw_text = response.get("content", "")
    stop_reason = response.get("stop_reason", "")
    if stop_reason == "max_tokens":
        logger.warning(f"Step 6.8 output truncated (max_tokens hit) for run {state['run_id']}")
        state["flags"].append("Step 6.8 output was truncated — consider increasing token budget")

    parsed, parse_error = _parse_step6_8_output(raw_text)

    duration = time.time() - t0

    if parsed:
        state["rl_rap_output"] = parsed
        # Store raw certainty levels for logging (final confidence derived after Step 7.5)
        levels = {i["issue_id"]: i["certainty_level"] for i in parsed.get("issues", [])}
        state["derived_confidence"] = (
            "LOW" if any(l == "UNCERTAIN" for l in levels.values())
            else "MEDIUM" if any(l == "CONDITIONAL" for l in levels.values())
            else "HIGH"
        )

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

        # Surface version mismatches as flags
        for issue in parsed.get("issues", []):
            ta = issue.get("temporal_applicability", {})
            if not ta.get("version_matches", True):
                risks = ta.get("temporal_risks", [])
                risk_text = (
                    "; ".join(risks) if risks
                    else "versiunea utilizată nu corespunde datei evenimentului"
                )
                state["flags"].append(
                    f"{issue['issue_id']}: Necorelare versiune — {risk_text}"
                )

        log_step(
            db, state["run_id"], "legal_reasoning", 12, "done", duration,
            prompt_id="LA-S6.8",
            prompt_version=prompt_ver,
            output_summary=f"Analyzed {len(parsed['issues'])} issues",
            output_data={
                "certainty_levels": {i["issue_id"]: i["certainty_level"] for i in parsed["issues"]},
                "rl_rap": parsed,
            },
            confidence=state["derived_confidence"],
        )
    else:
        state["rl_rap_output"] = None
        state["derived_confidence"] = None
        state["operative_articles"] = None
        state["_fallback_mode"] = True
        error_detail = parse_error or "Unknown parse error"
        if stop_reason == "max_tokens":
            error_detail = f"Output truncated (max_tokens). {error_detail}"
        state["flags"].append(f"Step 6.8 failed to produce valid analysis — falling back to direct answer generation. Detail: {error_detail}")
        logger.warning(f"Step 6.8 failed for run {state['run_id']}: {error_detail}")
        log_step(
            db, state["run_id"], "legal_reasoning", 12, "done", duration,
            prompt_id="LA-S6.8",
            prompt_version=prompt_ver,
            output_summary=f"Failed to parse — {error_detail}",
            output_data={
                "raw_response_preview": raw_text[:2000],
                "parse_error": error_detail,
                "stop_reason": stop_reason,
                "tokens_out": response.get("tokens_out", 0),
            },
            warnings=["Malformed RL-RAP output", error_detail],
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
    """Attempt to fetch missing articles from DB. Returns list of new article dicts.

    If a referenced law wasn't in the original pipeline (not in selected_versions),
    this function will look it up directly in the DB and use the best available version.
    """

    today = state.get("today", datetime.date.today().isoformat())
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

        # If the law wasn't in the pipeline, try to find it directly in the DB
        if not version_info:
            db_law = (
                db.query(Law)
                .filter(Law.law_number == law_number, Law.law_year == int(law_year))
                .first()
            )
            if not db_law:
                continue

            # Find the best version: current, or newest before today
            version = (
                db.query(LawVersion)
                .filter(
                    LawVersion.law_id == db_law.id,
                    LawVersion.date_in_force <= today,
                )
                .order_by(LawVersion.date_in_force.desc())
                .first()
            )
            if not version:
                # Fallback: any version at all
                version = (
                    db.query(LawVersion)
                    .filter(LawVersion.law_id == db_law.id)
                    .order_by(LawVersion.date_in_force.desc())
                    .first()
                )
            if not version:
                continue

            version_info = {
                "law_version_id": version.id,
                "law_id": db_law.id,
                "law_title": db_law.title or "",
                "date_in_force": str(version.date_in_force) if version.date_in_force else None,
            }
            # Register this version in the pipeline state so subsequent lookups find it
            selected[law_key] = version_info
            state.setdefault("unique_versions", {}).setdefault(law_key, set()).add(version.id)

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


def _extract_law_key(ref: str | None) -> str:
    """Extract law key (e.g., '85/2014') from an article reference string."""
    if not ref:
        return ""
    match = re.search(r"(\d+)/(\d{4})", ref)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def _semantic_search_for_norm(
    description: str,
    law_key: str,
    state: dict,
    db: Session,
) -> list[dict]:
    """Semantic search for a governing norm using ChromaDB. Returns list of article dicts."""
    if not description:
        return []

    # Find the law_version_id(s) for this law
    version_ids = []
    unique_versions = state.get("unique_versions", {})
    if law_key and law_key in unique_versions:
        version_ids = list(unique_versions[law_key])

    if not version_ids:
        # Try selected_versions
        sv = state.get("selected_versions", {}).get(law_key, {})
        vid = sv.get("law_version_id")
        if vid:
            version_ids = [vid]

    if not version_ids:
        return []

    results = query_articles(
        query_text=description,
        law_version_ids=version_ids,
        n_results=5,
    )

    # Convert ChromaDB results to pipeline article format
    fetched = []
    for r in results:
        article_id = r.get("article_id")
        if not article_id:
            continue
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            continue

        sv = state.get("selected_versions", {}).get(law_key, {})
        fetched.append({
            "article_id": article.id,
            "article_number": article.article_number,
            "law_number": law_key.split("/")[0] if "/" in law_key else "",
            "law_year": law_key.split("/")[1] if "/" in law_key else "",
            "law_version_id": article.law_version_id,
            "law_title": sv.get("law_title", ""),
            "date_in_force": sv.get("date_in_force", ""),
            "text": article.full_text or "",
            "source": "governing_norm_search",
            "tier": "reasoning_request",
            "role": "PRIMARY",
            "is_abrogated": article.is_abrogated or False,
            "doc_type": "article",
        })

    return fetched


def _fetch_governing_norm(issue: dict, state: dict, db: Session) -> list[dict]:
    """Attempt to fetch missing governing norm for an issue.

    Strategy 1: exact reference fetch (reuses _fetch_missing_articles).
    Strategy 2: semantic search using expected_norm_description (ChromaDB).
    """
    gns = issue.get("governing_norm_status", {})
    if gns.get("status") != "MISSING":
        return []

    # Strategy 1: exact reference
    ref = gns.get("missing_norm_ref")
    if ref:
        fetched = _fetch_missing_articles([ref], state, db)
        if fetched:
            return fetched

    # Strategy 2: semantic search using expected_norm_description
    description = gns.get("expected_norm_description")
    if description:
        law_key = _extract_law_key(ref)
        fetched = _semantic_search_for_norm(description, law_key, state, db)
        if fetched:
            return fetched

    return []


def _post_6_9_governing_norm_gate(state: dict) -> dict | None:
    """Check if primary issue still lacks its governing norm after conditional retrieval.

    Returns a gate event dict if hard pause is needed (law not in library),
    or None if no pause needed (either norm found, or soft warning set).
    """
    primary_target = state.get("primary_target")
    if not primary_target or not primary_target.get("issue_id"):
        return None

    primary_issue_id = primary_target["issue_id"]
    rl_rap = state.get("rl_rap_output", {})

    for issue in rl_rap.get("issues", []):
        if issue.get("issue_id") != primary_issue_id:
            continue

        gns = issue.get("governing_norm_status", {})
        if gns.get("status") != "MISSING":
            return None

        law_key = _extract_law_key(gns.get("missing_norm_ref", ""))
        law_in_library = law_key and law_key in state.get("selected_versions", {})

        if not law_in_library:
            # Hard pause — offer import
            return {
                "type": "gate",
                "gate": "governing_norm_missing",
                "issue": issue.get("issue_label", issue.get("issue_id")),
                "expected_norm": gns.get("expected_norm_description"),
                "missing_ref": gns.get("missing_norm_ref"),
                "message": (
                    f"The core legal provision for the primary issue "
                    f"({issue.get('issue_label', issue.get('issue_id'))}) was not found. "
                    f"Expected: {gns.get('expected_norm_description', 'unknown')}. "
                    f"Import the relevant law to proceed with a complete analysis."
                ),
            }
        else:
            # Soft warning — continue with disclosure
            state["flags"].append(
                f"GOVERNING_NORM_MISSING: {gns.get('expected_norm_description', 'governing norm not found')}"
            )
            state["governing_norm_incomplete"] = True
            return None

    return None


def _flag_missing_laws_from_answer(state: dict, db: Session) -> None:
    """Parse missing_info from Step 7 structured output to detect laws not in the pipeline.

    Adds actionable flags so the user knows which laws were needed but not retrieved.
    """
    structured = state.get("answer_structured")
    if not structured:
        return

    missing_info = structured.get("missing_info")
    if not missing_info:
        return

    # Extract law references like "31/1990", "286/2009", etc.
    law_refs = re.findall(r"(\d+)/(\d{4})", missing_info)
    if not law_refs:
        return

    candidate_keys = {
        f"{c['law_number']}/{c['law_year']}"
        for c in state.get("candidate_laws", [])
    }

    for law_number, law_year in law_refs:
        law_key = f"{law_number}/{law_year}"
        if law_key in candidate_keys:
            # Law was in the pipeline — already handled by other checks
            continue

        # This law was mentioned in missing_info but never entered the pipeline
        db_law = (
            db.query(Law)
            .filter(Law.law_number == law_number, Law.law_year == int(law_year))
            .first()
        )
        if db_law:
            state["flags"].append(
                f"Analiza a identificat necesitatea Legii {law_key} ({db_law.title or ''}) "
                f"care există în bibliotecă dar nu a fost inclusă în pipeline. "
                f"Repuneți întrebarea pentru a include această lege."
            )
        else:
            state["flags"].append(
                f"Analiza a identificat necesitatea Legii {law_key} "
                f"care nu este disponibilă în bibliotecă. "
                f"Importați legea și repuneți întrebarea."
            )


# ---------------------------------------------------------------------------
# Shared Steps 7-15 logic (used by both run_pipeline and resume_pipeline)
# ---------------------------------------------------------------------------


def _run_steps_4_through_7(state: dict, db: Session, run_id: str) -> Generator[dict, None, dict]:
    """Shared pipeline logic for Steps 7 through 15. Used by both run_pipeline and resume_pipeline.
    Yields SSE events. Returns final state."""

    if state.get("complexity") == "SIMPLE":
        # === FAST PATH ===
        # Step 7: Reduced retrieval (15+5 instead of 30+15)
        yield _step_event(7, "hybrid_retrieval", "running")
        t0 = time.time()
        state = _step4_hybrid_retrieval(state, db, tier_limits_override={
            "tier1_primary": 15,
            "tier2_secondary": 5,
        })
        yield _step_event(7, "hybrid_retrieval", "done", {
            "articles_found": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 9: Rerank to top 10
        yield _step_event(9, "article_selection", "running")
        t0 = time.time()
        state = _step6_select_articles(state, db, top_k_override=10)
        yield _step_event(9, "article_selection", "done", {
            "top_articles": len(state.get("retrieved_articles", [])),
        }, time.time() - t0)

        # Step 10: Late Relevance Gate
        gate_events, gate_result = _step6_5_relevance_gate(state, db)
        for evt in gate_events:
            yield evt
        if gate_result:
            complete_run(db, run_id, "clarification", None, state.get("flags"))
            db.commit()
            yield gate_result
            state["_gate_triggered"] = True
            return state

        # Step 14: Direct answer with simplified prompt
        yield _step_event(14, "answer_generation", "running")
        t0 = time.time()
        state["use_simple_prompt"] = True
        for event in _step7_answer_generation(state, db):
            yield event
        yield _step_event(14, "answer_generation", "done", duration=time.time() - t0)

        # Step 15: Citation Validation
        yield _step_event(15, "citation_validation", "running")
        t0 = time.time()
        state = _step7_5_citation_validation(state, db)
        yield _step_event(15, "citation_validation", "done", duration=time.time() - t0)

    else:
        # === FULL PATH (STANDARD/COMPLEX) ===
        # Step 7: Hybrid Retrieval
        yield _step_event(7, "hybrid_retrieval", "running")
        t0 = time.time()
        state = _step4_hybrid_retrieval(state, db)
        yield _step_event(7, "hybrid_retrieval", "done", {
            "articles_found": len(state.get("retrieved_articles_raw", [])),
        }, time.time() - t0)

        # Step 8: Graph Expansion (neighbors + cross-refs + exceptions)
        yield _step_event(8, "graph_expansion", "running")
        t0 = time.time()
        state = _step5_graph_expansion(state, db)
        yield _step_event(8, "graph_expansion", "done", duration=time.time() - t0)

        # Step 9: Reranking (dynamic top_k)
        yield _step_event(9, "article_selection", "running")
        t0 = time.time()
        state = _step6_select_articles(state, db)
        yield _step_event(9, "article_selection", "done", {
            "top_articles": len(state.get("retrieved_articles", [])),
        }, time.time() - t0)

        # Step 10: Late Relevance Gate
        gate_events, gate_result = _step6_5_relevance_gate(state, db)
        for evt in gate_events:
            yield evt
        if gate_result:
            complete_run(db, run_id, "clarification", None, state.get("flags"))
            db.commit()
            yield gate_result
            state["_gate_triggered"] = True
            return state

        # Step 11: Article-to-Issue Partitioning
        yield _step_event(11, "article_partitioning", "running")
        t0 = time.time()
        state = _step6_7_partition_articles(state, db)
        partition_duration = time.time() - t0
        partition_data = {
            "issues_with_articles": sum(1 for v in state.get("issue_articles", {}).values() if v),
            "shared_context_count": len(state.get("shared_context", [])),
            "issue_breakdown": {
                iid: [
                    {
                        "article_number": a.get("article_number"),
                        "law": f"{a.get('law_number')}/{a.get('law_year')}",
                        "score": round(a.get("reranker_score", 0), 2) if a.get("reranker_score") is not None else None,
                    }
                    for a in arts
                ]
                for iid, arts in state.get("issue_articles", {}).items()
            },
            "shared_context": [
                {
                    "article_number": a.get("article_number"),
                    "law": f"{a.get('law_number')}/{a.get('law_year')}",
                }
                for a in state.get("shared_context", [])
            ],
        }
        log_step(
            db, state["run_id"], "article_partitioning", 11, "done", partition_duration,
            output_summary=f"Partitioned articles across {partition_data['issues_with_articles']} issues, {partition_data['shared_context_count']} shared",
            output_data=partition_data,
        )
        yield _step_event(11, "article_partitioning", "done", {
            "issues_with_articles": partition_data["issues_with_articles"],
            "shared_context": partition_data["shared_context_count"],
        }, partition_duration)

        # Coverage validation: ensure each issue has articles from all applicable laws
        state = _validate_article_coverage(state, db)

        # Step 12: Legal Reasoning (RL-RAP)
        yield _step_event(12, "legal_reasoning", "running")
        state = _step6_8_legal_reasoning(state, db)
        yield _step_event(12, "legal_reasoning", "done", {
            "has_analysis": state.get("rl_rap_output") is not None,
            "derived_confidence": state.get("derived_confidence"),
        })

        # Conditional Retrieval Pass (flag-only, re-run only for governing norms)
        if state.get("rl_rap_output"):
            missing = _check_missing_articles(state["rl_rap_output"])
            governing_norm_issues = []
            governing_norm_fetched = []

            # Fetch governing norms for issues with MISSING status
            for issue in state["rl_rap_output"].get("issues", []):
                gns = issue.get("governing_norm_status", {})
                if gns.get("status") == "MISSING":
                    governing_norm_issues.append(issue["issue_id"])
                    gn_articles = _fetch_governing_norm(issue, state, db)
                    if gn_articles:
                        governing_norm_fetched.extend(gn_articles)

            # Fetch standard missing articles (non-governing)
            fetched = _fetch_missing_articles(missing, state, db) if missing else []

            all_fetched = fetched + governing_norm_fetched
            needs_step13_log = bool(missing) or bool(governing_norm_issues)

            if all_fetched:
                # Add fetched articles to issue_articles / shared_context
                for art in all_fetched:
                    added = False
                    for iid, arts in state.get("issue_articles", {}).items():
                        iv_key = f"{iid}:{art['law_number']}/{art['law_year']}"
                        if iv_key in state.get("issue_versions", {}):
                            arts.append(art)
                            added = True
                    if not added:
                        state.setdefault("shared_context", []).append(art)

            # Re-run Step 12 ONLY if a governing norm was MISSING and is now found
            should_rerun = bool(governing_norm_fetched) and bool(governing_norm_issues)

            if should_rerun:
                state = _step6_8_legal_reasoning(state, db)

            # Flag unfetched articles
            if missing:
                fetched_refs = set()
                for a in all_fetched:
                    fetched_refs.add(
                        f"{a.get('law_number', '')}/{a.get('law_year', '')} "
                        f"art.{a.get('article_number', '')}"
                    )
                unfetched = [m for m in missing if m not in fetched_refs]
                if unfetched:
                    state["flags"].append(
                        f"Articole solicitate de analiză dar nedisponibile: "
                        f"{', '.join(unfetched)}"
                    )

            if needs_step13_log:
                yield _step_event(13, "conditional_retrieval", "running")
                cond_data = {
                    "requested_refs": missing,
                    "governing_norms_searched": governing_norm_issues,
                    "fetched_articles": [
                        {
                            "article_number": a.get("article_number"),
                            "law": f"{a.get('law_number')}/{a.get('law_year')}",
                            "source": a.get("source", ""),
                        }
                        for a in all_fetched
                    ],
                    "fetched_count": len(all_fetched),
                    "requested_count": len(missing) + len(governing_norm_issues),
                    "re_ran_reasoning": should_rerun,
                }
                log_step(
                    db, state["run_id"], "conditional_retrieval", 13, "done",
                    0,
                    output_summary=(
                        f"Requested {len(missing)} missing + "
                        f"{len(governing_norm_issues)} governing norms, "
                        f"fetched {len(all_fetched)}"
                        + (", re-ran reasoning" if should_rerun else "")
                    ),
                    output_data=cond_data,
                )
                yield _step_event(13, "conditional_retrieval", "done", {
                    "requested": cond_data["requested_count"],
                    "fetched": cond_data["fetched_count"],
                    "re_ran": should_rerun,
                })

            # Post-6.9 Governing Norm Gate
            gate_result = _post_6_9_governing_norm_gate(state)
            if gate_result:
                complete_run(db, run_id, "clarification", None, state.get("flags"))
                db.commit()
                yield gate_result
                state["_gate_triggered"] = True
                return state

        # Step 14: Answer Generation
        yield _step_event(14, "answer_generation", "running")
        t0 = time.time()
        for event in _step7_answer_generation(state, db):
            yield event
        yield _step_event(14, "answer_generation", "done", duration=time.time() - t0)

        # Step 15: Citation Validation
        yield _step_event(15, "citation_validation", "running")
        t0 = time.time()
        state = _step7_5_citation_validation(state, db)
        yield _step_event(15, "citation_validation", "done", duration=time.time() - t0)

    # Check if Step 7 identified laws that weren't in the pipeline
    _flag_missing_laws_from_answer(state, db)

    # Derive final confidence from all signals
    retrieved = state.get("retrieved_articles", [])
    candidate_laws = state.get("candidate_laws", [])
    primary_from_db = all(
        l.get("source") == "DB" or l.get("db_law_id")
        for l in candidate_laws
        if l.get("role") == "PRIMARY"
    )
    missing_primary = any(
        c.get("tier") == "tier1_primary" and not c.get("db_law_id")
        for c in candidate_laws
    )
    stale_laws_in_use = [
        c for c in candidate_laws
        if c.get("version_status") == "stale" and c.get("role") == "PRIMARY"
    ]
    has_stale = bool(state.get("stale_versions") or stale_laws_in_use)

    # Aggregate uncertainty sources from RL-RAP
    rl_rap_issues = (state.get("rl_rap_output") or {}).get("issues", [])
    all_uncertainty_sources = []
    for issue in rl_rap_issues:
        all_uncertainty_sources.extend(issue.get("uncertainty_sources", []))

    state["confidence"], state["confidence_reason"] = _derive_final_confidence(
        claude_confidence=state.get("claude_confidence", "MEDIUM"),
        rl_rap_issues=rl_rap_issues,
        has_articles=bool(retrieved),
        primary_from_db=primary_from_db,
        missing_primary=missing_primary,
        has_stale_versions=has_stale,
        citation_validation=state.get("citation_validation", {"downgraded": 0, "total_db": 0}),
        governing_norm_incomplete=state.get("governing_norm_incomplete", False),
        uncertainty_sources=all_uncertainty_sources,
    )

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

        # Step 2: Date Extraction (local regex — sets date_type for currency check)
        state = _step1b_date_extraction(state, db)

        # Step 3: Law Mapping (rule-based, no Claude)
        yield _step_event(3, "law_mapping", "running")
        t0 = time.time()
        state = _step2_law_mapping(state, db)
        yield _step_event(3, "law_mapping", "done", {
            "candidate_laws": state.get("candidate_laws"),
            "coverage_status": state.get("coverage_status"),
        }, time.time() - t0)

        # Step 6: Version Selection (DB query — runs before currency check & gate
        # so that version-aware availability info is available for the gate)
        yield _step_event(6, "version_selection", "running")
        t0 = time.time()
        state = _step3_version_selection(state, db)
        yield _step_event(6, "version_selection", "done", {
            "selected_versions": state.get("selected_versions"),
        }, time.time() - t0)

        # Step 4: Version Currency Check — verify DB versions against legislatie.just.ro
        yield _step_event(4, "version_currency_check", "running")
        t0 = time.time()

        # Determine which laws need currency checking (only those used in current-law issues)
        laws_needing_check = set()
        for issue in state.get("legal_issues", []):
            if issue.get("temporal_rule") == "current_law":
                for law_key in issue.get("applicable_laws", []):
                    laws_needing_check.add(law_key)

        state["candidate_laws"] = check_version_currency(
            state.get("candidate_laws", []),
            db,
            state["today"],
            date_type=state.get("date_type"),
            primary_date=state.get("primary_date"),
            laws_needing_check=laws_needing_check if laws_needing_check else None,
        )
        currency_duration = time.time() - t0
        n_stale = sum(1 for c in state.get("candidate_laws", []) if c.get("currency_status") == "stale")
        n_current = sum(1 for c in state.get("candidate_laws", []) if c.get("currency_status") == "current")
        n_unavailable = sum(1 for c in state.get("candidate_laws", []) if c.get("currency_status") == "source_unavailable")
        log_step(
            db, state["run_id"], "version_currency_check", 4, "done",
            currency_duration,
            output_summary=f"Checked: {n_current} current, {n_stale} stale, {n_unavailable} source unavailable",
            output_data={
                "results": {
                    f"{c['law_number']}/{c['law_year']}": c.get("currency_status", "not_checked")
                    for c in state.get("candidate_laws", [])
                },
                "stale_count": n_stale,
                "law_details": [
                    {
                        "law_key": f"{c['law_number']}/{c['law_year']}",
                        "title": c.get("title", ""),
                        "currency_status": c.get("currency_status", "not_checked"),
                        "db_latest_date": c.get("available_version_date") or c.get("db_latest_date"),
                        "official_latest_date": c.get("official_latest_date"),
                        "role": c.get("role", ""),
                    }
                    for c in state.get("candidate_laws", [])
                ],
            },
        )
        yield _step_event(4, "version_currency_check", "done", {
            "stale_count": n_stale,
            "current_count": n_current,
            "unavailable_count": n_unavailable,
        }, currency_duration)

        # Step 5: Early Relevance Gate — check if primary laws exist or are stale
        # (now version-aware: version selection has already run)
        yield _step_event(5, "early_relevance_gate", "running")
        t0 = time.time()
        gate_result = _step2_5_early_relevance_gate(state, db)
        gate_duration = time.time() - t0
        if gate_result:
            candidate_laws = state.get("candidate_laws", [])
            primary_laws = [c for c in candidate_laws if c["role"] == "PRIMARY"]
            missing_primary = [c for c in primary_laws if c.get("availability") in ("missing", "wrong_version")]

            log_step(
                db, state["run_id"], "early_relevance_gate", 5, "done", gate_duration,
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
                yield _step_event(5, "early_relevance_gate", "done", {
                    "gate_triggered": True,
                    "reason": "pause_for_import",
                }, gate_duration)
                yield gate_result
                return
            else:
                # Pipeline terminates (e.g., no laws identified)
                complete_run(db, run_id, "clarification", None, state.get("flags"))
                db.commit()
                yield _step_event(5, "early_relevance_gate", "done", {
                    "gate_triggered": True,
                    "reason": gate_result.get("mode", "unknown"),
                }, gate_duration)
                yield gate_result
                return
        else:
            log_step(
                db, state["run_id"], "early_relevance_gate", 5, "done", gate_duration,
                output_summary="Gate passed — pipeline continues",
                output_data={
                    "gate_triggered": False,
                    "primary_laws_total": len([c for c in state.get("candidate_laws", []) if c.get("tier") == "tier1_primary"]),
                    "primary_laws_in_db": len([c for c in state.get("candidate_laws", []) if c.get("tier") == "tier1_primary" and c.get("db_law_id")]),
                },
            )
            yield _step_event(5, "early_relevance_gate", "done", {
                "gate_triggered": False,
            }, gate_duration)

        # Run Steps 7-15 (shared between run_pipeline and resume_pipeline)
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
        # Include original cause for API errors
        error_detail = str(e)
        if e.__cause__:
            error_detail += f" | Cause: {type(e.__cause__).__name__}: {e.__cause__}"
        try:
            complete_run(db, run_id, "error", None, [error_detail])
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
            if decision in ("import", "import_version", "update"):
                try:
                    law_number, law_year = law_key.split("/")
                    from app.services.leropa_service import import_law_smart, import_remaining_versions
                    from app.services.fetcher import search_legislatie
                    from app.scheduler import scheduler

                    # For stale updates, use the official ver_id if available
                    candidate = next(
                        (c for c in state.get("candidate_laws", [])
                         if f"{c['law_number']}/{c['law_year']}" == law_key),
                        None,
                    )
                    ver_id = None
                    if decision == "update" and candidate and candidate.get("official_latest_ver_id"):
                        ver_id = candidate["official_latest_ver_id"]
                    if not ver_id:
                        ver_id = search_legislatie(law_number, law_year)

                    if ver_id:
                        yield {"type": "step", "step": 5, "name": "importing", "status": "running",
                               "data": {"importing": law_key}}

                        dates = state.get("law_date_map", {}).get(law_key)
                        if isinstance(dates, list) and dates:
                            relevant_date = max(dates)
                        elif isinstance(dates, str):
                            relevant_date = dates
                        else:
                            relevant_date = state.get("primary_date")
                        result = import_law_smart(
                            db, ver_id,
                            primary_date=relevant_date,
                        )
                        # import_law_smart commits internally
                        action_label = "Updated" if decision == "update" else "Imported"
                        state["flags"].append(f"{action_label} {law_key} from legislatie.just.ro")

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

                        yield {"type": "step", "step": 5, "name": "importing", "status": "done",
                               "data": {"imported": law_key}}
                    else:
                        state["flags"].append(f"Could not find {law_key} on legislatie.just.ro — continuing without")
                except Exception as e:
                    logger.warning(f"Failed to import {law_key}: {e}")
                    state["flags"].append(f"Import failed for {law_key}: {str(e)[:100]}")
            elif decision == "skip":
                # Track stale laws the user chose to skip updating
                candidate = next(
                    (c for c in state.get("candidate_laws", [])
                     if f"{c['law_number']}/{c['law_year']}" == law_key),
                    None,
                )
                if candidate and candidate.get("currency_status") == "stale":
                    state.setdefault("stale_versions", []).append(law_key)
                    db_date = candidate.get("db_latest_date", "?")
                    official_date = candidate.get("official_latest_date", "?")
                    state["flags"].append(
                        f"Legea {law_key}: using version from {db_date} — "
                        f"a newer version ({official_date}) exists but was not imported"
                    )

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

        # Re-run from Step 6: Version Selection
        yield _step_event(6, "version_selection", "running")
        t0 = time.time()
        state = _step3_version_selection(state, db)
        yield _step_event(6, "version_selection", "done", {
            "selected_versions": state.get("selected_versions"),
        }, time.time() - t0)

        # Run Steps 7-15 (shared between run_pipeline and resume_pipeline)
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
    context_msg += f"\n\nTODAY'S DATE: {state['today']}"

    result = call_claude(
        system=prompt_text,
        messages=[{"role": "user", "content": context_msg}],
        max_tokens=4096,
    )

    log_api_call(
        db, state["run_id"], "issue_classification",
        result["tokens_in"], result["tokens_out"], result["duration"], result["model"],
    )

    parsed = _extract_json(result["content"])
    if not parsed:
        logger.warning("Failed to parse Step 1 JSON from %s. Raw response (first 500 chars): %s",
                       result["model"], result["content"][:500])
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
    state["primary_target"] = parsed.get("primary_target")

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

    # Build law_date_map: all relevant dates per law across all issues
    _law_dates = {}
    for issue in state.get("legal_issues", []):
        for law_key in issue.get("applicable_laws", []):
            issue_date = issue.get("relevant_date", "")
            if issue_date and issue_date != "unknown":
                _law_dates.setdefault(law_key, set()).add(issue_date)

    # Store as sorted lists (JSON-serializable)
    law_date_map = {k: sorted(v) for k, v in _law_dates.items()}
    state["law_date_map"] = law_date_map
    all_dates = [d for dates in law_date_map.values() for d in dates]
    state["primary_date"] = max(all_dates) if all_dates else state["today"]

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
# Step 2: Date Extraction (local regex)
# ---------------------------------------------------------------------------


def _step1b_date_extraction(state: dict, db: Session) -> dict:
    """Derive temporal context from Step 1 classification output.

    Sets state["date_type"] (used by version currency check to skip
    remote queries for historical questions). Replaces the legacy
    regex-based date extractor.
    """
    t0 = time.time()

    # Derive date_type from Step 1's temporal rules
    event_rules = {"contract_formation", "performance", "act_date", "breach_date",
                   "registration_date", "insolvency_opening"}
    temporal_rules = [i.get("temporal_rule") for i in state.get("legal_issues", [])]

    if any(r in event_rules for r in temporal_rules):
        # Issues reference specific events — check if any have non-today dates
        non_today = [
            i["relevant_date"] for i in state.get("legal_issues", [])
            if i.get("relevant_date")
            and i["relevant_date"] != state["today"]
            and i["relevant_date"] != "unknown"
        ]
        state["date_type"] = "explicit" if non_today else "implicit_current"
    else:
        state["date_type"] = "implicit_current"

    # Build per-fact version requirements
    versions_needed = {}  # {law_key: set of dates}
    fact_version_map = {}  # {"ISSUE-N:fact_ref:law_key": {"relevant_date": ..., "temporal_rule": ...}}

    for issue in state.get("legal_issues", []):
        issue_id = issue.get("issue_id", "ISSUE-?")
        fact_dates = issue.get("fact_dates", [])

        if fact_dates:
            # Per-fact dates available
            for fact in fact_dates:
                fact_ref = fact.get("fact_ref", "?")
                fact_date = fact.get("relevant_date", issue.get("relevant_date", state["today"]))
                if fact_date == "unknown":
                    fact_date = state["today"]
                fact_rule = fact.get("temporal_rule", issue.get("temporal_rule", "current_law"))
                fact_laws = fact.get("applicable_laws", issue.get("applicable_laws", []))

                for law_key in fact_laws:
                    versions_needed.setdefault(law_key, set()).add(fact_date)
                    map_key = f"{issue_id}:{fact_ref}:{law_key}"
                    fact_version_map[map_key] = {
                        "relevant_date": fact_date,
                        "temporal_rule": fact_rule,
                        "issue_id": issue_id,
                        "fact_ref": fact_ref,
                    }
        else:
            # No per-fact dates — use issue-level date for all applicable laws
            issue_date = issue.get("relevant_date", state["today"])
            if issue_date == "unknown":
                issue_date = state["today"]
            issue_rule = issue.get("temporal_rule", "current_law")
            for law_key in issue.get("applicable_laws", []):
                versions_needed.setdefault(law_key, set()).add(issue_date)
                map_key = f"{issue_id}:{law_key}"
                fact_version_map[map_key] = {
                    "relevant_date": issue_date,
                    "temporal_rule": issue_rule,
                    "issue_id": issue_id,
                }

    state["versions_needed"] = {k: sorted(v) for k, v in versions_needed.items()}
    state["fact_version_map"] = fact_version_map

    # Update law_date_map to include all fact-level dates (keep as sorted lists)
    law_date_map = state.get("law_date_map", {})
    for law_key, dates in versions_needed.items():
        existing = law_date_map.get(law_key, [])
        if isinstance(existing, str):
            existing = [existing]
        merged = set(existing) | dates
        law_date_map[law_key] = sorted(merged)
    state["law_date_map"] = law_date_map

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "date_extraction", 2, "done", duration,
        input_summary=state["question"][:200],
        output_summary=f"date_type={state['date_type']}, fact_mappings={len(fact_version_map)}, versions_needed={len(versions_needed)}",
        output_data={
            "date_type": state["date_type"],
            "primary_date": state.get("primary_date"),
            "temporal_rules": temporal_rules,
            "derived_from": "step1_classification",
            "versions_needed": {k: sorted(v) for k, v in versions_needed.items()},
            "fact_count": len(fact_version_map),
        },
    )

    return state


# ---------------------------------------------------------------------------
# Step 3: Law Mapping (rule-based — no Claude call)
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
            db, state["run_id"], "law_mapping", 3, "done", duration,
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
        db, state["run_id"], "law_mapping", 3, "done", duration,
        output_summary=f"Mapped {len(candidate_laws)} laws ({sum(1 for c in candidate_laws if c.get('db_law_id'))} in DB)",
        output_data={
            "mapping": mapping,
            "coverage": coverage,
            "candidate_laws": candidate_laws,
        },
    )
    return state


# ---------------------------------------------------------------------------
# Step 5: Early Relevance Gate
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

    # Check if any law (PRIMARY or SECONDARY) needs import, has wrong version, or is stale
    all_laws = candidate_laws
    needs_pause = any(
        law.get("availability") in ("missing", "wrong_version")
        or law.get("version_status") == "stale"
        or law.get("currency_status") == "stale"
        for law in all_laws
    )

    if needs_pause:
        # Save state for resume
        save_paused_state(db, state["run_id"], state)

        # Build law preview for frontend
        laws_preview = []
        law_date_map = state.get("law_date_map", {})
        issue_versions = state.get("issue_versions", {})
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
                "currency_status": law.get("currency_status", "not_checked"),
                "version_status": law.get("version_status", "not_checked"),
                "official_latest_date": law.get("official_latest_date"),
                "official_latest_ver_id": law.get("official_latest_ver_id"),
                "official_current_ver_id": law.get("official_current_ver_id"),
                "official_current_date": law.get("official_current_date"),
                "db_latest_date": law.get("db_latest_date"),
            }

            # Add version selection info if available (version selection runs before gate)
            versions_for_law = [
                iv for iv in issue_versions.values()
                if iv.get("law_key") == law_key
            ]
            if versions_for_law:
                preview["selected_versions"] = [
                    {
                        "issue_id": iv.get("issue_id"),
                        "relevant_date": iv.get("relevant_date"),
                        "date_in_force": iv.get("date_in_force"),
                        "is_current": iv.get("is_current"),
                    }
                    for iv in versions_for_law
                ]

            laws_preview.append(preview)

        # Build user-friendly message
        missing = [l for l in all_laws if l.get("availability") == "missing"]
        wrong_ver = [l for l in all_laws if l.get("availability") == "wrong_version"]
        stale = [
            l for l in all_laws
            if l.get("version_status") == "stale" or l.get("currency_status") == "stale"
        ]
        parts = []
        if missing:
            names = ", ".join(f"{l.get('title', '')} ({l['law_number']}/{l['law_year']})" for l in missing)
            parts.append(f"lipsesc din bibliotecă: {names}")
        if wrong_ver:
            names = ", ".join(f"{l.get('title', '')} ({l['law_number']}/{l['law_year']})" for l in wrong_ver)
            parts.append(f"au versiune incorectă: {names}")
        if stale:
            names = ", ".join(
                f"{l.get('title', '')} ({l['law_number']}/{l['law_year']}) — "
                f"biblioteca: {l.get('db_latest_date') or l.get('available_version_date', '?')}, "
                f"legislatie.just.ro: {l.get('official_latest_date') or l.get('official_current_date', '?')}"
                for l in stale
            )
            parts.append(f"au versiune mai nouă disponibilă: {names}")
        message = "Am identificat legile aplicabile. " + "; ".join(parts) + ". Doriți să le actualizăm?"

        return {
            "type": "pause",
            "run_id": state["run_id"],
            "message": message,
            "laws": laws_preview,
        }

    # Note: SECONDARY laws with missing/wrong_version/stale status are now
    # handled by the pause logic above (same as PRIMARY laws).

    return None


# ---------------------------------------------------------------------------
# Step 6: Version Selection (DB query — no Claude call)
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

            # Future date: use latest available version (don't override the date)
            if relevant_date > today:
                version_notes.append(
                    f"{issue_id}: Event date {relevant_date} is in the future — using latest available version"
                )
                # Do NOT override relevant_date to today.
                # _find_version_for_date will naturally return the latest enacted version
                # since it finds the newest version with date_in_force <= relevant_date,
                # and for a future date, this is the most recent enacted version.

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

    # --- Per-fact version selection (Phase 2) ---
    fact_version_map = state.get("fact_version_map", {})
    for map_key, fact_info in fact_version_map.items():
        parts = map_key.split(":")
        if len(parts) == 3:
            issue_id, fact_ref, law_key = parts
        elif len(parts) == 2:
            issue_id, law_key = parts
            fact_ref = None
        else:
            continue

        db_law_id = law_id_lookup.get(law_key)
        if not db_law_id:
            continue

        versions = _get_versions(db_law_id)
        if not versions:
            continue

        fact_date = fact_info.get("relevant_date", today)
        if fact_date == "unknown":
            fact_date = today

        # Do NOT override future dates — _find_version_for_date handles them naturally
        selected = _find_version_for_date(versions, fact_date)
        if not selected:
            selected = _fallback_version(versions)
            version_notes.append(
                f"{map_key}: No version for {fact_date}, using current"
            )

        if not selected:
            continue

        # Store the version binding in fact_version_map
        fact_info["law_version_id"] = selected.id
        fact_info["date_in_force"] = str(selected.date_in_force) if selected.date_in_force else None
        fact_info["is_current"] = selected.is_current

        # Track unique versions for retrieval
        unique_versions.setdefault(law_key, set()).add(selected.id)

        # Check for mitior lex (criminal law newer version awareness)
        if fact_info.get("temporal_rule") == "act_date":
            # Check if a newer version exists (for potential mitior lex)
            issue = next((i for i in legal_issues if i.get("issue_id") == issue_id), None)
            if issue and issue.get("mitior_lex_relevant"):
                newer = [v for v in versions if v.date_in_force and str(v.date_in_force) > fact_date]
                if newer:
                    fact_info["mitior_lex_newer_version"] = str(newer[0].date_in_force)
                    version_notes.append(
                        f"{map_key}: Newer version exists ({newer[0].date_in_force}) — mitior lex may apply"
                    )

    state["fact_version_map"] = fact_version_map

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
        db, state["run_id"], "version_selection", 6, "done",
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
# Step 7: Hybrid Retrieval (BM25 + semantic)
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
        # Search PER LAW to guarantee each law gets coverage.
        # Without this, a single dominant law (e.g., insolvency) can take all
        # retrieval slots, leaving other PRIMARY laws with zero articles.
        tier_laws = state.get("law_mapping", {}).get(tier_key, [])
        laws_with_versions = []
        for law in tier_laws:
            key = f"{law['law_number']}/{law['law_year']}"
            vids = list(state.get("unique_versions", {}).get(key, []))
            if not vids:
                v = state.get("selected_versions", {}).get(key)
                if v:
                    vids = [v["law_version_id"]]
            if vids:
                laws_with_versions.append((key, vids))

        if not laws_with_versions:
            continue

        # Distribute retrieval budget across laws in this tier
        per_law_limit = max(5, n_results // len(laws_with_versions))

        for law_key, version_ids in laws_with_versions:
            # BM25 search for this law
            bm25_results = search_bm25(db, state["question"], version_ids, limit=per_law_limit)
            bm25_count += len(bm25_results)

            # Semantic search for this law
            semantic_results = query_articles(
                state["question"], law_version_ids=version_ids, n_results=per_law_limit
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
        db, state["run_id"], "hybrid_retrieval", 7, "done", duration,
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


MAX_EXPANSION_INPUT = 30


def _cap_for_expansion(state: dict) -> dict:
    """Cap articles before expansion to prevent graph explosion."""
    articles = state.get("retrieved_articles_raw", [])
    if len(articles) <= MAX_EXPANSION_INPUT:
        return state
    articles.sort(key=lambda a: a.get("distance", 1.0))
    state["retrieved_articles_raw"] = articles[:MAX_EXPANSION_INPUT]
    return state


def _append_new_articles(state: dict, db: Session, new_ids: list[int], source: str) -> int:
    """Fetch articles by ID, build enriched dicts, append to state. Returns count added."""
    from app.models.law import Article as ArticleModel

    existing_ids = {a["article_id"] for a in state.get("retrieved_articles_raw", [])}
    unique_ids = [aid for aid in new_ids if aid not in existing_ids]

    if not unique_ids:
        return 0

    added = 0
    for art in db.query(ArticleModel).filter(ArticleModel.id.in_(unique_ids)).all():
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
            "source": source,
            "tier": source,
            "role": _derive_role(law.law_number, str(law.law_year), state),
        })
        added += 1

    return added


# ---------------------------------------------------------------------------
# Step 8: Article Expansion (neighbors + cross-refs)
# ---------------------------------------------------------------------------


def _derive_role(law_number: str, law_year: str, state: dict) -> str:
    """Determine if an article's law is PRIMARY or SECONDARY based on law mapping."""
    for law in state.get("law_mapping", {}).get("tier1_primary", []):
        if str(law["law_number"]) == str(law_number) and str(law["law_year"]) == str(law_year):
            return "PRIMARY"
    return "SECONDARY"


def _step5_graph_expansion(state: dict, db: Session) -> dict:
    """Unified graph expansion: neighbors, cross-references, and exceptions."""
    from app.services.article_expander import expand_articles, expand_with_exceptions

    t0 = time.time()

    # Cap input to prevent explosion
    state = _cap_for_expansion(state)

    # Phase 1: neighbors + cross-references
    raw_ids = [a["article_id"] for a in state.get("retrieved_articles_raw", [])]
    neighbor_ids, neighbor_details = expand_articles(
        db, raw_ids,
        selected_versions=state.get("selected_versions", {}),
        primary_date=state.get("primary_date"),
    )
    added_neighbors = _append_new_articles(state, db, neighbor_ids, source="expansion")

    # Phase 2: exception/exclusion articles
    raw = state.get("retrieved_articles_raw", [])
    if raw:
        exception_ids, exception_details = expand_with_exceptions(db, raw)
        added_exceptions = _append_new_articles(state, db, exception_ids, source="exception")
    else:
        exception_details = {"forward_count": 0, "reverse_count": 0, "forward_matches": [], "reverse_matches": []}
        added_exceptions = 0

    if added_neighbors or added_exceptions:
        logger.info(f"Graph expansion: +{added_neighbors} neighbors/crossrefs, +{added_exceptions} exceptions")

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "graph_expansion", 8, "done", duration,
        output_summary=f"Graph expansion: +{added_neighbors} neighbors/crossrefs, +{added_exceptions} exceptions",
        output_data={
            "articles_before": len(raw_ids),
            "articles_after": len(state.get("retrieved_articles_raw", [])),
            "neighbors_added": neighbor_details.get("neighbors_added", 0),
            "crossrefs_added": neighbor_details.get("crossrefs_added", 0),
            "exceptions_added": added_exceptions,
            "forward_matches": exception_details.get("forward_count", 0),
            "reverse_matches": exception_details.get("reverse_count", 0),
            "expansion_triggers": neighbor_details.get("expansion_triggers", []),
            "added_articles": [
                {
                    "article_number": a.get("article_number"),
                    "law": f"{a.get('law_number')}/{a.get('law_year')}",
                    "source": a.get("source"),
                }
                for a in state.get("retrieved_articles_raw", [])
                if a.get("article_id") not in raw_ids
            ],
        },
    )
    return state


# ---------------------------------------------------------------------------
# Step 9: Article Selection (Claude-based, with local reranker fallback)
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
        log_step(db, state["run_id"], "article_selection", 9, "done", 0,
                 output_summary="No articles to select from")
        return state

    ranked = rerank_articles(state["question"], raw, top_k=top_k)
    state["retrieved_articles"] = ranked

    kept_ids = {a["article_id"] for a in ranked}
    dropped = [a for a in raw if a["article_id"] not in kept_ids]

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "article_selection", 9, "done", duration,
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
# Step 10: Late Relevance Gate
# ---------------------------------------------------------------------------


def _step6_5_relevance_gate(state: dict, db: Session) -> tuple[list[dict], dict | None]:
    """Check if selected articles are relevant using reranker scores (no Claude call).

    Called from both run_pipeline and resume_pipeline.
    """
    t0 = time.time()
    retrieved = state.get("retrieved_articles", [])
    events = []

    if not retrieved:
        events.append(_step_event(10, "relevance_check", "done", {"skipped": True}, 0))
        log_step(db, state["run_id"], "relevance_check", 10, "done", 0,
                 output_summary="Skipped — no articles to check",
                 output_data={"skipped": True})
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
    relevance_output = {
        "relevance_score": round(relevance_score, 3),
        "top_reranker_score": round(top_score, 3),
        "avg_reranker_score": round(avg_score, 3),
        "gate_triggered": gate_will_trigger,
        "gate_warning": gate_will_warn,
        "method": "reranker_scores",
    }
    events.append(_step_event(10, "relevance_check", "done", relevance_output, duration))

    log_step(
        db, state["run_id"], "relevance_check", 10, "done", duration,
        output_summary=f"Relevance score: {relevance_score:.2f}" + (
            " — gate triggered" if gate_will_trigger else
            " — warning" if gate_will_warn else " — OK"
        ),
        output_data=relevance_output,
        warnings=["Low article relevance"] if gate_will_warn else None,
    )

    if gate_will_warn:
        state["flags"].append(
            f"Low article relevance (score: {relevance_score:.2f}) — answer may be incomplete"
        )

    if gate_will_trigger:
        # Try to identify missing laws from the candidate list
        candidate_laws = state.get("candidate_laws", [])
        primary_missing = [
            c for c in candidate_laws
            if c.get("tier") == "tier1_primary" and not c.get("db_law_id")
        ]

        # If all primary laws ARE in the library, proceed anyway — the reranker
        # may score Romanian text low but the articles are there.
        primary_in_db = [
            c for c in candidate_laws
            if c.get("tier") == "tier1_primary" and c.get("db_law_id")
        ]
        if primary_in_db and not primary_missing:
            state["flags"].append(
                f"Low reranker relevance (score: {relevance_score:.2f}) but primary laws "
                f"are in library — proceeding with available articles"
            )
            state["confidence"] = "MEDIUM"
            return events, None

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

        # No primary laws at all — ask for clarification
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
# Step 14: Answer Generation (RAG + Claude streaming)
# ---------------------------------------------------------------------------


def _step7_answer_generation(state: dict, db: Session) -> Generator[dict, None, None]:
    # Determine which prompt to use based on output mode
    mode = state.get("output_mode", "qa")
    mode_key = "simple" if state.get("use_simple_prompt") else mode

    # Load template + mode, assemble prompt
    template_text, template_ver = load_prompt("LA-S7-template", db)
    mode_text, mode_ver = load_prompt(f"LA-S7-mode-{mode_key}", db)
    prompt_text = template_text.replace("{MODE_SECTION}", mode_text)
    prompt_ver = template_ver
    prompt_id = f"LA-S7-template+{mode_key}"

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

    # Append fallback disclaimer when RL-RAP was unavailable
    if state.get("_fallback_mode"):
        disclaimer = "\n\n⚠ Această analiză se bazează pe citirea directă a articolelor de lege, fără raționament juridic structurat. Se recomandă reverificarea concluziilor."
        state["answer"] = state.get("answer", "") + disclaimer
        if state.get("answer_structured") and isinstance(state["answer_structured"], dict):
            existing_answer = state["answer_structured"].get("answer", "")
            state["answer_structured"]["answer"] = existing_answer + disclaimer

    log_api_call(
        db, state["run_id"], "answer_generation",
        total_tokens_in, total_tokens_out, total_duration, state.get("model", ""),
    )

    # Store Claude's raw confidence — final confidence derived after Step 7.5.
    state["claude_confidence"] = (structured.get("confidence") if structured else None) or "MEDIUM"

    # Track partial coverage for downstream use
    missing_primary = [
        c for c in state.get("candidate_laws", [])
        if c.get("tier") == "tier1_primary" and not c.get("db_law_id")
    ]
    if missing_primary:
        state["is_partial"] = True

    # Track stale versions for flags (confidence handled by _derive_final_confidence)
    stale_laws_in_use = [
        c for c in state.get("candidate_laws", [])
        if c.get("version_status") == "stale" and c.get("role") == "PRIMARY"
    ]
    if state.get("stale_versions") or stale_laws_in_use:
        stale_names = state.get("stale_versions", []) or [
            f"{c['law_number']}/{c['law_year']}" for c in stale_laws_in_use
        ]
        state["flags"].append(
            "Version currency: answer based on potentially outdated law version(s): "
            + ", ".join(stale_names)
        )

    # Build output_data with answer details
    answer_output_data = {
        "articles_provided": len(retrieved),
        "confidence": state.get("confidence"),
        "is_partial": state.get("is_partial", False),
        "output_mode": mode,
        "reasoning_mode": "fallback" if state.get("_fallback_mode") else "structured",
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
        if structured.get("caveats"):
            answer_output_data["caveats"] = structured["caveats"]

    log_step(
        db, state["run_id"], "answer_generation", 14, "done",
        total_duration,
        prompt_id=prompt_id, prompt_version=prompt_ver,
        input_summary=f"Retrieved {len(retrieved)} articles, mode={mode}",
        output_summary=f"Generated {len(full_text)} chars, confidence={state.get('confidence')}",
        output_data=answer_output_data,
        confidence=state.get("confidence"),
    )


# ---------------------------------------------------------------------------
# Step 15: Citation Validation (code-based, no Claude)
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
            db, state["run_id"], "citation_validation", 15, "done", time.time() - t0,
            output_summary="Skipped — no structured answer to validate",
            output_data={"skipped": True, "reason": "no_structured_answer"},
        )
        return state

    sources = structured.get("sources", [])
    if not sources:
        log_step(
            db, state["run_id"], "citation_validation", 15, "done", time.time() - t0,
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

    total_db = sum(1 for s in sources if s.get("label") in ("DB", "Unverified"))
    confidence_downgraded = total_db > 0 and downgraded > total_db / 2

    if downgraded > 0:
        logger.info(f"Citation validation: downgraded {downgraded} citations to Unverified")

    # Store validation results for _derive_final_confidence
    state["citation_validation"] = {
        "downgraded": downgraded,
        "total_db": total_db,
    }

    duration = time.time() - t0
    log_step(
        db, state["run_id"], "citation_validation", 15, "done", duration,
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

    panel = {
        "step1_classification": {
            "question_type": state.get("question_type"),
            "legal_domain": state.get("legal_domain"),
            "legal_topic": state.get("legal_topic"),
            "entity_types": state.get("entity_types", []),
            "output_mode": state.get("output_mode"),
            "core_issue": state.get("core_issue"),
            "sub_issues": state.get("sub_issues", []),
        },
        "step3_law_mapping": {
            "candidate_laws": state.get("candidate_laws", []),
            "coverage_status": state.get("coverage_status", {}),
        },
        "step4_version_currency": {
            "results": {
                f"{c['law_number']}/{c['law_year']}": {
                    "currency_status": c.get("currency_status", "not_checked"),
                    "official_latest_date": c.get("official_latest_date"),
                    "db_latest_date": c.get("db_latest_date"),
                }
                for c in state.get("candidate_laws", [])
            },
            "stale_versions": state.get("stale_versions", []),
        },
        "step6_versions": {
            "selected_versions": state.get("selected_versions", {}),
            "version_notes": state.get("version_notes", []),
        },
        "step7_retrieval": {
            "articles_found": len(raw),
            "bm25_count": len(bm25_articles),
            "semantic_count": len(semantic_articles),
            "entity_count": len(entity_articles),
        },
        "step8_expansion": {
            "articles_after_expansion": len(raw),
            "expansion_added": len(expansion_articles),
            "exceptions_added": len(exception_articles),
        },
        "step9_selection": {
            "total_candidates": len(raw),
            "selected_count": len(state.get("retrieved_articles", [])),
            "top_articles": [
                {"article_number": a.get("article_number"), "score": round(a.get("reranker_score", 0), 3), "law": f"{a.get('law_number')}/{a.get('law_year')}"}
                for a in state.get("retrieved_articles", [])[:10]
            ],
        },
        "step10_relevance": {
            "relevance_score": state.get("relevance_score"),
        },
        "step14_answer": {
            "articles_used": len(state.get("retrieved_articles", [])),
            "confidence": state.get("confidence"),
            "flags": state.get("flags", []),
        },
    }

    # Step 11: Partitioning
    if state.get("issue_articles"):
        panel["step11_partitioning"] = {
            "issues_with_articles": {
                iid: len(arts) for iid, arts in state.get("issue_articles", {}).items()
            },
            "shared_context_count": len(state.get("shared_context", [])),
        }

    # Step 12: Legal Reasoning (RL-RAP)
    if state.get("rl_rap_output"):
        rl_rap = state["rl_rap_output"]
        panel["step12_reasoning"] = {
            "issues_analyzed": len(rl_rap.get("issues", [])),
            "certainty_levels": {
                i["issue_id"]: i.get("certainty_level", "UNKNOWN")
                for i in rl_rap.get("issues", [])
            },
            "operative_articles": [
                oa.get("article_ref", "")
                for issue in rl_rap.get("issues", [])
                for oa in issue.get("operative_articles", [])
            ],
            "missing_facts": [
                fact
                for issue in rl_rap.get("issues", [])
                for fact in issue.get("missing_facts", [])
            ],
            "derived_confidence": state.get("derived_confidence"),
        }

    # Conditional retrieval
    if state.get("rl_rap_output"):
        missing_requested = []
        for issue in state["rl_rap_output"].get("issues", []):
            missing_requested.extend(issue.get("missing_articles_needed", []))
        if missing_requested:
            panel["conditional_retrieval"] = {
                "articles_requested": missing_requested,
            }

    return panel
