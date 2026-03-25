# Per-Issue Temporal Reasoning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the pipeline select law versions per legal issue instead of using one global date, and auto-categorize laws on import.

**Architecture:** Extend Step 1 prompt to output events + legal issues with temporal assignments. Step 3 selects versions per issue. Steps 2/2.5/import use per-law latest date. A small helper auto-categorizes imported laws from the seed mapping.

**Tech Stack:** Python/FastAPI backend, Claude API (Sonnet), PostgreSQL, Next.js frontend

**Spec:** `docs/superpowers/specs/2026-03-25-temporal-reasoning-design.md`

---

### Task 1: Extend Step 1 Prompt with Temporal Decomposition

**Files:**
- Modify: `backend/prompts/LA-S1-issue-classifier.txt`

- [ ] **Step 1: Add temporal rules and new output fields to the prompt**

After the existing rule 5 (Applicable Laws, line 44), before the RESPONSE FORMAT section (line 46), add:

```
6. Temporal Decomposition (REQUIRED for question type "B", optional for "A"):
   - Extract ALL factual events mentioned in the question, with their dates
   - For dates written as DD.MM.YYYY, convert to ISO format YYYY-MM-DD
   - For relative dates ("four months later"), compute the absolute date from context
   - If a date cannot be determined, use "unknown"
   - Identify each discrete legal issue arising from the scenario
   - Assign a "relevant_date" to each issue using these temporal rules:

   TEMPORAL RULES:
     contract_formation  — law at the date the contract was signed/concluded
     performance         — law at the date the obligation was performed or breached
     insolvency_opening  — law at the date insolvency procedure was opened
     act_date            — law at the date of the specific act/decision being assessed
     breach_date         — law at the date a continuous obligation was breached
     registration_date   — law at the date of ONRC registration or filing
     current_law         — today's date (for hypothetical, prospective, or undated questions)

   FUTURE DATE RULES:
     - If the event date is in the future or cannot be determined, use temporal_rule "current_law"
     - The per-issue "applicable_laws" array contains law keys (e.g., "31/1990") referencing entries in the top-level "applicable_laws" array

7. For question type "A" (direct questions):
   - Output a single entry in "legal_issues" with relevant_date = today or mentioned date
   - Output "events" as an empty array unless a date is explicitly mentioned
```

- [ ] **Step 2: Add events and legal_issues to the JSON response format**

Replace the RESPONSE FORMAT section (lines 46-67) with:

```
RESPONSE FORMAT — You must respond with valid JSON only, no other text:

{
  "question_type": "A" or "B",
  "legal_domain": "<domain>",
  "output_mode": "qa" or "memo" or "comparison" or "compliance" or "checklist",
  "legal_topic": "<specific topic, e.g., 'număr asociați', 'capital social minim', 'TVA', 'reziliere contract'>",
  "entity_types": ["<entity types mentioned: SRL, SA, PFA, individual, etc.>"] or [],
  "core_issue": "<one sentence reformulating the legal issue>",
  "sub_issues": ["<sub-issue 1>", "<sub-issue 2>"] or [],
  "classification_confidence": "HIGH" or "MEDIUM" or "LOW",
  "reasoning": "<brief explanation of classification>",
  "applicable_laws": [
    {
      "law_number": "<official law number, e.g. '31'>",
      "law_year": "<year, e.g. '1990'>",
      "title": "<official Romanian title>",
      "role": "PRIMARY or SECONDARY",
      "reason": "<why this law applies to the question>"
    }
  ],
  "events": [
    {
      "event": "<description of factual event>",
      "date": "<YYYY-MM-DD or 'unknown'>",
      "date_source": "explicit" or "computed" or "unknown",
      "date_reasoning": "<only if date_source is 'computed': how the date was derived>"
    }
  ],
  "legal_issues": [
    {
      "issue_id": "ISSUE-1",
      "description": "<concise description of the legal issue>",
      "relevant_date": "<YYYY-MM-DD>",
      "temporal_rule": "<one of the temporal rules above>",
      "date_reasoning": "<why this date applies to this issue>",
      "applicable_laws": ["<law_number/law_year>"]
    }
  ]
}
```

- [ ] **Step 3: Commit**

```bash
git add backend/prompts/LA-S1-issue-classifier.txt
git commit -m "feat: extend Step 1 prompt with temporal decomposition"
```

---

### Task 2: Update Step 1 Python Code to Parse Temporal Fields

**Files:**
- Modify: `backend/app/services/pipeline_service.py:549-631` (`_step1_issue_classification`)

- [ ] **Step 1: Increase max_tokens and parse new fields**

In `_step1_issue_classification`, change line 571 from `max_tokens=1024` to `max_tokens=2048`.

After line 601 (`state["applicable_laws"] = parsed.get("applicable_laws", [])`), add:

```python
    state["events"] = parsed.get("events", [])
    state["legal_issues"] = parsed.get("legal_issues", [])
```

- [ ] **Step 2: Add law_date_map computation after applicable_laws validation**

Replace lines 616-617 (the `primary_date` default) with:

```python
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
```

- [ ] **Step 3: Add fallback defaults for events and legal_issues in the parse-failure block**

In the fallback `parsed` dict (lines 581-592), add these two keys:

```python
            "events": [],
            "legal_issues": [],
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: parse temporal fields from Step 1 and compute law_date_map"
```

---

### Task 3: Remove Step 1b from Pipeline Flow

**Files:**
- Modify: `backend/app/services/pipeline_service.py:126-132` (main pipeline flow)

- [ ] **Step 1: Remove Step 1b SSE events and call**

Delete lines 126-132 from the `run_pipeline` generator:

```python
        # Step 1b: Date Extraction (Claude)
        yield _step_event(15, "date_extraction", "running")
        t0 = time.time()
        state = _step1b_date_extraction(state, db)
        yield _step_event(15, "date_extraction", "done", {
            "primary_date": state.get("primary_date"),
        }, time.time() - t0)
```

The `_step1b_date_extraction` function definition (lines 639-667) stays in the file as dead code for now — it can be cleaned up later.

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: remove Step 1b date extraction from pipeline flow"
```

---

### Task 4: Update Law Mapping to Use Per-Law Dates

**Files:**
- Modify: `backend/app/services/law_mapping.py` (entire file, 87 lines)
- Modify: `backend/app/services/pipeline_service.py:698` (call site in `_step2_law_mapping`)

- [ ] **Step 1: Change `check_laws_in_db` signature and logic**

Replace the full content of `backend/app/services/law_mapping.py` with:

```python
# backend/app/services/law_mapping.py
"""
Check identified laws against the database for availability and version status.
"""
from __future__ import annotations
from datetime import date as date_type
from sqlalchemy.orm import Session
from app.models.law import Law, LawVersion


def check_laws_in_db(
    laws: list[dict],
    db: Session,
    law_date_map: dict[str, str] | None = None,
) -> list[dict]:
    """Enrich each law dict with DB availability and version status.

    Args:
        laws: List of law dicts from the classifier (with law_number, law_year).
        db: Database session.
        law_date_map: Optional dict mapping "law_number/law_year" to ISO date string.
                      Each law is checked against its own relevant date.

    Returns the same list with added fields:
    - db_law_id: int or None
    - in_library: bool
    - availability: "available" | "wrong_version" | "missing"
    - available_version_date: str or None (the version date actually found)
    """
    for law in laws:
        law_number = str(law["law_number"])
        law_year = str(law["law_year"])
        law_key = f"{law_number}/{law_year}"

        db_law = (
            db.query(Law)
            .filter(
                Law.law_number == law_number,
                Law.law_year == int(law_year),
            )
            .first()
        )

        if not db_law:
            law["db_law_id"] = None
            law["in_library"] = False
            law["availability"] = "missing"
            law["available_version_date"] = None
            continue

        law["db_law_id"] = db_law.id
        law["in_library"] = True
        law["title"] = law.get("title") or db_law.title

        # Look up the relevant date for this specific law
        relevant_date = law_date_map.get(law_key) if law_date_map else None

        if relevant_date:
            pd = date_type.fromisoformat(relevant_date)
            version = (
                db.query(LawVersion)
                .filter(
                    LawVersion.law_id == db_law.id,
                    LawVersion.date_in_force <= pd,
                )
                .order_by(LawVersion.date_in_force.desc())
                .first()
            )
            if version:
                law["availability"] = "available"
                law["available_version_date"] = str(version.date_in_force)
            else:
                # No version for this date — check if any version exists
                any_version = (
                    db.query(LawVersion)
                    .filter(LawVersion.law_id == db_law.id)
                    .first()
                )
                if any_version:
                    law["availability"] = "wrong_version"
                    law["available_version_date"] = str(any_version.date_in_force)
                else:
                    law["availability"] = "missing"
                    law["available_version_date"] = None
        else:
            # No date specified — just check if law has any version
            any_version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == db_law.id)
                .first()
            )
            law["availability"] = "available" if any_version else "missing"
            law["available_version_date"] = str(any_version.date_in_force) if any_version else None

    return laws
```

- [ ] **Step 2: Update the call site in `_step2_law_mapping`**

In `pipeline_service.py` line 698, change:

```python
    enriched = check_laws_in_db(applicable_laws, db, state.get("primary_date"))
```

to:

```python
    enriched = check_laws_in_db(applicable_laws, db, state.get("law_date_map"))
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/law_mapping.py backend/app/services/pipeline_service.py
git commit -m "feat: use per-law dates for version availability checks"
```

---

### Task 5: Enrich Pause Message with Temporal Context

**Files:**
- Modify: `backend/app/services/pipeline_service.py:774-809` (`_step2_5_early_relevance_gate`)
- Modify: `frontend/src/lib/api.ts:316-324` (`LawPreview` interface)
- Modify: `frontend/src/app/assistant/import-prompt.tsx:59-94` (law row rendering)

- [ ] **Step 1: Add a helper to find the date reason for a law**

Add this helper function before `_step2_5_early_relevance_gate` (before line 749):

```python
def _get_temporal_reason_for_law(law_key: str, legal_issues: list[dict]) -> str | None:
    """Find the issue that drives the date need for a specific law."""
    for issue in legal_issues:
        if law_key in issue.get("applicable_laws", []):
            date = issue.get("relevant_date", "")
            desc = issue.get("description", "")
            if date and date != "unknown":
                return f"{desc} ({date})"
    return None
```

- [ ] **Step 2: Add temporal fields to the laws_preview in the pause event**

In `_step2_5_early_relevance_gate`, inside the `if needs_pause:` block, after line 789 (`laws_preview.append(preview)`), add two fields to the `preview` dict (before `laws_preview.append`):

Replace lines 779-790:

```python
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
```

- [ ] **Step 3: Update `LawPreview` TypeScript interface**

In `frontend/src/lib/api.ts`, add two optional fields to the `LawPreview` interface (after line 323):

```typescript
export interface LawPreview {
  law_number: string;
  law_year: string;
  title: string;
  role: "PRIMARY" | "SECONDARY";
  availability: "available" | "wrong_version" | "missing";
  version_info: string | null;
  reason?: string;
  needed_for_date?: string | null;
  date_reason?: string | null;
}
```

- [ ] **Step 4: Show temporal context in ImportPrompt**

In `frontend/src/app/assistant/import-prompt.tsx`, after the `wrong_version` info div (line 83), add a line showing the date reason:

Replace lines 79-83:

```tsx
              {law.availability === "wrong_version" && law.version_info && (
                <div className="text-[10px] opacity-70 mt-0.5">
                  Available: {law.version_info} (wrong version)
                </div>
              )}
              {law.needed_for_date && (
                <div className="text-[10px] opacity-70 mt-0.5">
                  Needed for: {law.date_reason || law.needed_for_date}
                </div>
              )}
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pipeline_service.py frontend/src/lib/api.ts frontend/src/app/assistant/import-prompt.tsx
git commit -m "feat: enrich import pause message with temporal context"
```

---

### Task 6: Update Resume Pipeline to Use Per-Law Dates

**Files:**
- Modify: `backend/app/services/pipeline_service.py:326-328` (inside `resume_pipeline`)

- [ ] **Step 1: Pass per-law date to import_law_smart**

Replace line 326-328:

```python
                        result = import_law_smart(
                            db, ver_id,
                            primary_date=state.get("primary_date"),
                        )
```

with:

```python
                        relevant_date = state.get("law_date_map", {}).get(
                            law_key, state.get("primary_date")
                        )
                        result = import_law_smart(
                            db, ver_id,
                            primary_date=relevant_date,
                        )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: pass per-law date to import_law_smart on resume"
```

---

### Task 7: Redesign Step 3 for Per-Issue Version Selection

**Files:**
- Modify: `backend/app/services/pipeline_service.py:830-910` (`_step3_version_selection`)

- [ ] **Step 1: Rewrite `_step3_version_selection`**

Replace the entire function (lines 830-910) with:

```python
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
```

- [ ] **Step 2: Verify the app starts without errors**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.pipeline_service import run_pipeline; print('OK')"`

Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: per-issue version selection in Step 3"
```

---

### Task 8: Update Step 4 Retrieval to Use Unique Versions

**Files:**
- Modify: `backend/app/services/pipeline_service.py:953-963` (inside `_step4_hybrid_retrieval`)

- [ ] **Step 1: Use unique_versions instead of selected_versions for version ID collection**

Replace lines 954-960:

```python
        # Collect version IDs for this tier's laws
        version_ids = []
        for law in state.get("law_mapping", {}).get(tier_key, []):
            key = f"{law['law_number']}/{law['law_year']}"
            v = state.get("selected_versions", {}).get(key)
            if v:
                version_ids.append(v["law_version_id"])
```

with:

```python
        # Collect version IDs for this tier's laws (all versions needed across issues)
        version_ids = []
        for law in state.get("law_mapping", {}).get(tier_key, []):
            key = f"{law['law_number']}/{law['law_year']}"
            vids = state.get("unique_versions", {}).get(key, set())
            if vids:
                version_ids.extend(vids)
            else:
                # Fallback to selected_versions for backward compat
                v = state.get("selected_versions", {}).get(key)
                if v:
                    version_ids.append(v["law_version_id"])
```

- [ ] **Step 2: Do the same for the entity-aware retrieval block**

Replace lines 991-997:

```python
        primary_version_ids = []
        for law in state.get("law_mapping", {}).get("tier1_primary", []):
            key = f"{law['law_number']}/{law['law_year']}"
            v = state.get("selected_versions", {}).get(key)
            if v:
                primary_version_ids.append(v["law_version_id"])
```

with:

```python
        primary_version_ids = []
        for law in state.get("law_mapping", {}).get("tier1_primary", []):
            key = f"{law['law_number']}/{law['law_year']}"
            vids = state.get("unique_versions", {}).get(key, set())
            if vids:
                primary_version_ids.extend(vids)
            else:
                v = state.get("selected_versions", {}).get(key)
                if v:
                    primary_version_ids.append(v["law_version_id"])
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: retrieve articles from all per-issue versions in Step 4"
```

---

### Task 9: Update Step 7 Answer Context with Temporal Analysis

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1435-1466` (inside `_step7_answer` or the answer function)
- Modify: `backend/prompts/LA-S7-answer-qa.txt`

- [ ] **Step 1: Replace the version context block in the answer function**

Replace lines 1435-1466 (from `# Build version selection context` through the end of the `user_msg` assignment):

```python
    # Build temporal analysis context
    temporal_context = ""
    if state.get("events") or state.get("issue_versions"):
        temporal_context = "TEMPORAL ANALYSIS:\n"

        # Events
        events = state.get("events", [])
        if events:
            temporal_context += "  Events:\n"
            for i, evt in enumerate(events, 1):
                line = f"    {i}. {evt.get('date', '?')} — {evt.get('event', '?')}"
                if evt.get("date_reasoning"):
                    line += f" ({evt['date_reasoning']})"
                temporal_context += line + "\n"
            temporal_context += "\n"

        # Legal issues with versions
        issue_versions = state.get("issue_versions", {})
        legal_issues = state.get("legal_issues", [])
        if legal_issues:
            temporal_context += "  Legal Issues & Applicable Versions:\n"
            for issue in legal_issues:
                iid = issue.get("issue_id", "?")
                temporal_context += (
                    f"    {iid}: {issue.get('description', '?')}\n"
                    f"      Relevant date: {issue.get('relevant_date', '?')} "
                    f"({issue.get('temporal_rule', '?')})\n"
                )
                for law_key in issue.get("applicable_laws", []):
                    combo = f"{iid}:{law_key}"
                    iv = issue_versions.get(combo, {})
                    date_in_force = iv.get("date_in_force", "?")
                    temporal_context += f"      -> {law_key} version {date_in_force}\n"
            temporal_context += "\n"
    else:
        # Fallback: simple version context (for Type A questions or missing decomposition)
        if state.get("selected_versions"):
            temporal_context = "SELECTED LAW VERSIONS:\n"
            for key, v in state["selected_versions"].items():
                temporal_context += f"  {key}: version {v.get('date_in_force', 'unknown')} "
                temporal_context += "(current)" if v.get("is_current") else "(historical)"
                temporal_context += "\n"

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
        f"{temporal_context}\n"
        f"{articles_context}\n"
        f"{flags_context}\n"
        f"USER QUESTION:\n{state['question']}"
    )
```

- [ ] **Step 2: Add per-issue version citation instructions to the answer prompt**

In `backend/prompts/LA-S7-answer-qa.txt`, after line 11 (`- Classification data (domain, type, sub-issues)`), add:

```
- Temporal analysis: events, legal issues, and the law version selected per issue

TEMPORAL REASONING — when a TEMPORAL ANALYSIS section is provided:
- Structure your answer BY LEGAL ISSUE, following the issue decomposition
- For each issue, state which law version applies and why (e.g., "Legea 85/2014 in versiunea din 15.01.2026 se aplica deoarece data deschiderii procedurii de insolventa este momentul juridic relevant")
- If the SAME LAW has DIFFERENT VERSIONS for different issues, explain this explicitly
- When citing articles, include the version date: "Art. 117 din Legea 85/2014 (versiunea din 15.01.2026)"
- End complex answers (Type B) with a temporal summary table:
  | Problemă juridică | Dată relevantă | Lege | Versiune utilizată |
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py backend/prompts/LA-S7-answer-qa.txt
git commit -m "feat: temporal analysis context in answer generation"
```

---

### Task 10: Auto-Categorize Laws on Import

**Files:**
- Modify: `backend/app/services/leropa_service.py:688-713` (in `import_law_smart`) and `backend/app/services/leropa_service.py:956-974` (in `import_law`)

- [ ] **Step 1: Add the `_auto_categorize` helper**

Add this function after the imports at the top of `leropa_service.py` (after the existing helper functions, before `fetch_and_store_version`):

```python
def _auto_categorize(db: Session, law) -> None:
    """Assign category from seed mapping if law has no category."""
    if law.category_id is not None:
        return
    if not law.law_number:
        return
    from app.models.category import LawMapping as CategoryMapping
    mapping = (
        db.query(CategoryMapping)
        .filter(
            CategoryMapping.law_number == law.law_number,
            CategoryMapping.law_year == law.law_year,
        )
        .first()
    )
    if mapping and mapping.category_id:
        law.category_id = mapping.category_id
        law.category_confidence = "auto"
```

- [ ] **Step 2: Call `_auto_categorize` in `import_law_smart`**

In `import_law_smart`, after line 689 (`_apply_law_metadata(db, law, doc)`), add:

```python
    _auto_categorize(db, law)
```

- [ ] **Step 3: Call `_auto_categorize` in `import_law`**

In `import_law`, after line 956 (`_apply_law_metadata(db, law, doc)`), add:

```python
    _auto_categorize(db, law)
```

- [ ] **Step 4: Verify the app starts without errors**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.services.leropa_service import import_law_smart, import_law; print('OK')"`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/leropa_service.py
git commit -m "feat: auto-categorize laws on import from seed mapping"
```

---

### Task 11: Manual Integration Test

**Files:** None (manual verification)

- [ ] **Step 1: Start the backend**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m uvicorn app.main:app --reload`

Verify: Server starts without import errors.

- [ ] **Step 2: Test with the shareholder scenario**

In the chat UI, ask:

> Un asociat care deține 40% dintr-un SRL împrumută societatea cu 100.000 EUR pe 01.01.2025. Societatea rambursează împrumutul pe 01.03.2026. Patru luni mai târziu societatea intră în insolvență. Administratorul este afectat legal și care sunt riscurile?

Verify in the reasoning panel:
- Step 1 output contains `events` with 3 dates (2025-01-01, 2026-03-01, ~2026-07-01)
- Step 1 output contains `legal_issues` with 3-4 issues, each with different `relevant_date`
- Step 3 shows different version selections per issue
- The answer is structured by legal issue with per-issue version citations

- [ ] **Step 3: Test with a simple Type A question**

Ask: "Care este capitalul social minim pentru un SRL?"

Verify:
- Step 1 output has a single entry in `legal_issues` with `temporal_rule: "current_law"`
- Pipeline completes normally with no regressions

- [ ] **Step 4: Test import flow (if a required law is missing)**

Ask a question that references a law not in the library to trigger the import pause.

Verify:
- The pause message shows `needed_for_date` and `date_reason`
- After clicking "Import and continue", the law appears in the Legal Library with a category assigned (if it exists in the seed mapping)
