"""
Pipeline V2 context builders for Steps 4 and 5.

Step 4: RL-RAP legal reasoning context
Step 5: Answer generation context
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Step 4: RL-RAP legal reasoning context
# ---------------------------------------------------------------------------


def build_step4_context(state: dict) -> str:
    """Build context for the RL-RAP legal reasoning step (Step 4).

    Includes structured facts, primary target, per-issue article blocks with
    version info, and any pipeline flags.
    """
    parts = []

    # -----------------------------------------------------------------------
    # FACTS
    # -----------------------------------------------------------------------
    facts = state.get("facts", {})
    stated = facts.get("stated", [])
    assumed = facts.get("assumed", [])
    missing = facts.get("missing", [])

    if stated or assumed or missing:
        parts.append("=" * 60)
        parts.append("FACTS")
        parts.append("=" * 60)

        if stated:
            parts.append("Stated facts:")
            for f in stated:
                date_str = f" (date: {f['date']})" if f.get("date") else ""
                parts.append(f"  {f.get('fact_id', '?')}: {f.get('description', '')}{date_str}")

        if assumed:
            parts.append("\nAssumed facts:")
            for f in assumed:
                basis = f.get("basis", "implied")
                parts.append(f"  {f.get('fact_id', '?')}: {f.get('description', '')} (basis: {basis})")

        if missing:
            parts.append("\nMissing facts (identified by classifier):")
            for f in missing:
                relevance = f.get("relevance", "")
                relevance_str = f" (relevance: {relevance})" if relevance else ""
                parts.append(f"  {f.get('fact_id', '?')}: {f.get('description', '')}{relevance_str}")

    # -----------------------------------------------------------------------
    # PRIMARY TARGET
    # -----------------------------------------------------------------------
    primary_target = state.get("primary_target")
    if primary_target:
        parts.append("\n" + "=" * 60)
        parts.append("PRIMARY TARGET")
        parts.append("=" * 60)
        parts.append(f"  Actor:   {primary_target.get('actor', 'unknown')}")
        parts.append(f"  Concern: {primary_target.get('concern', 'unknown')}")

    # -----------------------------------------------------------------------
    # PER-ISSUE ARTICLE BLOCKS
    # -----------------------------------------------------------------------
    legal_issues = state.get("legal_issues", [])
    issue_articles = state.get("issue_articles", {})
    fact_version_map = state.get("fact_version_map", {})

    parts.append("\n" + "=" * 60)
    parts.append("LEGAL ISSUES AND ARTICLES")
    parts.append("=" * 60)

    for issue in legal_issues:
        iid = issue.get("issue_id", "?")
        priority = issue.get("priority", "")
        priority_tag = f" [{priority}]" if priority else ""
        description = issue.get("description", "")

        parts.append(f"\n--- {iid}{priority_tag}: {description} ---")

        # Entity perspective
        ep = issue.get("entity_perspective")
        if ep and isinstance(ep, dict):
            actor = ep.get("actor", "")
            role = ep.get("role", "")
            counter_party = ep.get("counter_party", "")
            if actor or role:
                parts.append(f"  Entity perspective — Actor: {actor}, Role: {role}" +
                              (f", Counter-party: {counter_party}" if counter_party else ""))

        # Relevant date and temporal rule
        relevant_date = issue.get("relevant_date", "unknown")
        temporal_rule = issue.get("temporal_rule", "")
        temporal_str = f" ({temporal_rule})" if temporal_rule else ""
        parts.append(f"  Relevant date: {relevant_date}{temporal_str}")

        # Version info from fact_version_map
        fact_entries = [
            (k, v) for k, v in fact_version_map.items()
            if v.get("issue_id") == iid
        ]
        if fact_entries:
            parts.append("  Fact-specific version info:")
            for fk, fv in fact_entries:
                fact_ref = fv.get("fact_ref", fk)
                rel_date = fv.get("relevant_date", "?")
                date_in_force = fv.get("date_in_force", "unknown")
                parts.append(f"    Fact {fact_ref}: date={rel_date}, version={date_in_force}")
                if fv.get("mitior_lex_newer_version"):
                    parts.append(f"      WARNING Mitior lex: newer version exists ({fv['mitior_lex_newer_version']})")

        # Articles for this issue
        articles = issue_articles.get(iid, [])
        if articles:
            parts.append(f"  Articles ({len(articles)} retrieved):")
            for art in articles:
                law_number = art.get("law_number", "")
                law_year = art.get("law_year", "")
                law_ref = art.get("law_ref") or (f"{law_number}/{law_year}" if law_number or law_year else "unknown")
                article_number = art.get("article_number", "?")
                date_in_force = art.get("date_in_force", "")
                version_str = f", version {date_in_force}" if date_in_force else ""

                parts.append(f"    [Art. {article_number}] {law_ref}{version_str}")

                # Full article text, truncated to 3000 chars
                text = art.get("text") or art.get("full_text") or ""
                if len(text) > 3000:
                    text = text[:3000] + "... [truncated]"
                if text:
                    # Indent the text block
                    for line in text.splitlines():
                        parts.append(f"      {line}")
        else:
            parts.append(f"  NO ARTICLES RETRIEVED FOR {iid}")

    # -----------------------------------------------------------------------
    # FLAGS
    # -----------------------------------------------------------------------
    flags = state.get("flags", [])
    if flags:
        parts.append("\n" + "=" * 60)
        parts.append("FLAGS AND WARNINGS")
        parts.append("=" * 60)
        for f in flags:
            parts.append(f"  - {f}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Step 5: Answer generation context
# ---------------------------------------------------------------------------


def build_step5_context(state: dict) -> str:
    """Build context for answer generation (Step 5).

    Includes classification summary, facts, primary target, full RL-RAP legal
    analysis (or fallback notice), tiered article rendering, stale version
    warnings, and the original user question.
    """
    parts = []

    # -----------------------------------------------------------------------
    # CLASSIFICATION SUMMARY
    # -----------------------------------------------------------------------
    parts.append("=" * 60)
    parts.append("CLASSIFICATION")
    parts.append("=" * 60)
    parts.append(f"  Question type: {state.get('question_type', 'A')}")
    parts.append(f"  Legal domain:  {state.get('legal_domain', 'unknown')}")
    parts.append(f"  Output mode:   {state.get('output_mode', 'qa')}")
    parts.append(f"  Core issue:    {state.get('core_issue', '')}")

    # -----------------------------------------------------------------------
    # FACTS
    # -----------------------------------------------------------------------
    facts = state.get("facts", {})
    stated = facts.get("stated", [])

    if stated:
        parts.append("\n" + "=" * 60)
        parts.append("FACTS")
        parts.append("=" * 60)
        for f in stated:
            parts.append(f"  {f.get('fact_id', '?')}: {f.get('description', '')}")

    # -----------------------------------------------------------------------
    # PRIMARY TARGET
    # -----------------------------------------------------------------------
    primary_target = state.get("primary_target")
    if primary_target:
        parts.append("\n" + "=" * 60)
        parts.append("PRIMARY TARGET")
        parts.append("=" * 60)
        parts.append(f"  Actor:   {primary_target.get('actor', 'unknown')}")
        parts.append(f"  Concern: {primary_target.get('concern', 'unknown')}")

    # -----------------------------------------------------------------------
    # LEGAL ANALYSIS (RL-RAP output)
    # -----------------------------------------------------------------------
    rl_rap = state.get("rl_rap_output")

    parts.append("\n" + "=" * 60)
    parts.append("LEGAL ANALYSIS")
    parts.append("=" * 60)

    if rl_rap:
        for issue in rl_rap.get("issues", []):
            iid = issue.get("issue_id", "?")
            label = issue.get("issue_label", "")
            parts.append(f"\n  {iid}: {label}")

            # Governing norm status
            gns = issue.get("governing_norm_status", {})
            if gns:
                gns_status = gns.get("status", "")
                gns_explanation = gns.get("explanation", "")
                if gns_status:
                    parts.append(f"    Governing norm: {gns_status}")
                if gns_explanation:
                    parts.append(f"    Explanation: {gns_explanation}")

            # Certainty level
            certainty = issue.get("certainty_level", "UNKNOWN")
            parts.append(f"    Certainty: {certainty}")

            # Operative articles
            operative_articles = issue.get("operative_articles", [])
            if operative_articles:
                parts.append("    Operative articles:")
                for oa in operative_articles:
                    article_ref = oa.get("article_ref", "?")
                    norm_type = oa.get("norm_type", "")
                    priority = oa.get("priority", "")
                    norm_str = f", norm_type: {norm_type}" if norm_type else ""
                    priority_str = f", priority: {priority}" if priority else ""
                    parts.append(f"      {article_ref}{norm_str}{priority_str}")

            # Condition table summary
            condition_table = issue.get("condition_table", [])
            subsumption_summary = issue.get("subsumption_summary") or {}
            if condition_table or subsumption_summary:
                satisfied = subsumption_summary.get("satisfied", 0)
                not_satisfied = subsumption_summary.get("not_satisfied", 0)
                unknown = subsumption_summary.get("unknown", 0)
                norm_applicable = subsumption_summary.get("norm_applicable", "?")
                parts.append(
                    f"    Conditions: {satisfied} satisfied, {not_satisfied} not satisfied, "
                    f"{unknown} unknown — norm applicable: {norm_applicable}"
                )

            # Conclusion
            conclusion = issue.get("conclusion", "")
            if conclusion:
                parts.append(f"    Conclusion: {conclusion}")

            # Missing facts
            missing_facts = issue.get("missing_facts", [])
            if missing_facts:
                parts.append(f"    Missing facts: {'; '.join(missing_facts)}")

            # Uncertainty sources
            uncertainty_sources = issue.get("uncertainty_sources", [])
            if uncertainty_sources:
                parts.append("    Uncertainty sources:")
                for us in uncertainty_sources:
                    us_type = us.get("type", "")
                    us_detail = us.get("detail", "")
                    us_resolvable = us.get("resolvable_by", "")
                    resolvable_str = f", resolvable by: {us_resolvable}" if us_resolvable else ""
                    parts.append(f"      [{us_type}] {us_detail}{resolvable_str}")
    else:
        parts.append("  [NO STRUCTURED LEGAL ANALYSIS — direct article reasoning mode]")

    # -----------------------------------------------------------------------
    # ARTICLES SECTION
    # -----------------------------------------------------------------------
    parts.append("\n" + "=" * 60)
    parts.append("ARTICLES")
    parts.append("=" * 60)

    # Collect operative article refs from RL-RAP output
    operative_refs: set[str] = set()
    if rl_rap:
        for issue in rl_rap.get("issues", []):
            for oa in issue.get("operative_articles", []):
                ref = oa.get("article_ref", "")
                if ref:
                    operative_refs.add(ref)

    legal_issues = state.get("legal_issues", [])
    issue_articles = state.get("issue_articles", {})

    for issue in legal_issues:
        iid = issue.get("issue_id", "?")
        articles = issue_articles.get(iid, [])
        if not articles:
            continue

        parts.append(f"\n  Issue {iid}:")
        for art in articles:
            article_number = art.get("article_number", "?")
            law_number = art.get("law_number", "")
            law_year = art.get("law_year", "")
            law_ref = art.get("law_ref") or (f"{law_number}/{law_year}" if law_number or law_year else "unknown")
            date_in_force = art.get("date_in_force", "")
            version_str = f", version {date_in_force}" if date_in_force else ""

            # Determine if this is an operative article
            art_ref_key = f"art.{article_number}"
            is_operative = any(art_ref_key in ref for ref in operative_refs)

            header = f"    [Art. {article_number}] {law_ref}{version_str}"

            text = art.get("text") or art.get("full_text") or ""
            if is_operative:
                # Full text up to 2000 chars for operative articles
                if len(text) > 2000:
                    text = text[:2000] + "... [truncated]"
                parts.append(header + " [OPERATIVE]")
            else:
                # Abbreviated text up to 500 chars for non-operative articles
                if len(text) > 500:
                    text = text[:500] + "..."
                parts.append(header)

            if text:
                for line in text.splitlines():
                    parts.append(f"      {line}")

    # -----------------------------------------------------------------------
    # STALE VERSION WARNINGS
    # -----------------------------------------------------------------------
    candidate_laws = state.get("candidate_laws", [])
    stale_candidates = [c for c in candidate_laws if c.get("currency_status") == "stale"]
    if stale_candidates:
        parts.append("\n" + "=" * 60)
        parts.append("STALE VERSION WARNINGS")
        parts.append("=" * 60)
        for c in stale_candidates:
            law_number = c.get("law_number", "?")
            law_year = c.get("law_year", "?")
            db_latest = c.get("db_latest_date", "?")
            official_latest = c.get("official_latest_date", "?")
            parts.append(
                f"  WARNING: Law {law_number}/{law_year} — library contains version from "
                f"{db_latest}, but official source has a newer version from {official_latest}. "
                f"The answer may be based on outdated provisions."
            )

    # -----------------------------------------------------------------------
    # ORIGINAL QUESTION
    # -----------------------------------------------------------------------
    parts.append("\n" + "=" * 60)
    parts.append("USER QUESTION")
    parts.append("=" * 60)
    parts.append(state.get("question", ""))

    return "\n".join(parts)
