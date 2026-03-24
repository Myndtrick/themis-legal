# Claude-Based Law Identification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static DOMAIN_LAW_MAP with Claude-based law identification merged into Step 1, so the pipeline correctly identifies all applicable laws (including cross-domain) and pauses with import buttons when laws are missing or have wrong versions.

**Architecture:** Extend the Step 1 classifier prompt to output `applicable_laws`. Rewrite Step 2 as a DB lookup + version check. Rewrite Step 2.5 to use the existing pause/resume mechanism with a law preview showing available/missing/wrong-version states. Update `resume_pipeline()` to trigger actual imports via leropa_service. Update frontend ImportPrompt to show three-state law preview.

**Tech Stack:** Python (pipeline_service.py, law_mapping.py, leropa_service.py), Claude API prompts, React/TypeScript (import-prompt.tsx, use-chat.ts, api.ts)

**Spec:** `docs/superpowers/specs/2026-03-24-claude-law-identification-design.md`

---

### Task 1: Extend Step 1 classifier prompt with law identification

**Files:**
- Modify: `backend/prompts/LA-S1-issue-classifier.txt`

- [ ] **Step 1: Add applicable_laws to the prompt output format**

Add the `applicable_laws` field to the JSON response format in `LA-S1-issue-classifier.txt`. After the existing `"reasoning"` field (line 47), add:

```
  "applicable_laws": [
    {
      "law_number": "<official law number, e.g. '31'>",
      "law_year": "<year, e.g. '1990'>",
      "title": "<official Romanian title>",
      "role": "PRIMARY or SECONDARY",
      "reason": "<why this law applies to the question>"
    }
  ]
```

Also add instructions before the RESPONSE FORMAT section (after line 33, before line 35):

```
5. Applicable Laws:
   - Identify ALL Romanian laws that apply to this question
   - Do NOT limit yourself to laws in the Legal Library — identify all applicable laws
   - Assign each law a role:
     - "PRIMARY" = directly applicable law (lex specialis for this question)
     - "SECONDARY" = applies subsidiarily or fills gaps
   - A question can have MULTIPLE PRIMARY laws (e.g., corporate + insolvency)
   - Include the law's official number, year, and Romanian title
   - Include a brief reason explaining why this law applies
   - If the Legal Library list is provided, use it as reference but do NOT restrict your identification to it
```

Remove the `secondary_domain` field from the JSON format (line 43). Remove line 43 entirely.

- [ ] **Step 2: Commit**

```bash
git add backend/prompts/LA-S1-issue-classifier.txt
git commit -m "feat: extend Step 1 classifier prompt with applicable_laws identification"
```

---

### Task 2: Update Step 1 to parse applicable_laws and pass library context

**Files:**
- Modify: `backend/app/services/pipeline_service.py:430-489`

- [ ] **Step 1: Add library context to Step 1 Claude call**

In `_step1_issue_classification()`, before building the `context_msg` (line 433), query the DB for available laws and append to the message:

```python
# After line 431 (prompt load), before line 433:
from app.models.law import Law as LawModel
available_laws = db.query(LawModel).limit(50).all()
laws_list = "\n".join(
    f"- {l.law_number}/{l.law_year}: {l.title}" for l in available_laws
)
library_context = f"\n\nLAWS CURRENTLY IN LEGAL LIBRARY:\n{laws_list}" if available_laws else ""
```

Then append `library_context` to `context_msg` (after line 438):

```python
context_msg += library_context
```

- [ ] **Step 2: Parse applicable_laws from response**

After the existing parsed fields (lines 465-472), add:

```python
# Replace line 472 (secondary_domain) with:
state["applicable_laws"] = parsed.get("applicable_laws", [])
```

Remove the `secondary_domain` line entirely. Validate the applicable_laws entries:

```python
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
```

- [ ] **Step 3: Add applicable_laws fallback when parsing fails**

In the fallback parsed dict (lines 453-463), add:

```python
"applicable_laws": [],
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: parse applicable_laws from Step 1 classifier, pass library context"
```

---

### Task 3: Rewrite law_mapping.py as DB lookup utility

**Files:**
- Modify: `backend/app/services/law_mapping.py` (full rewrite)

- [ ] **Step 1: Replace entire file contents**

Replace the whole file with a new `check_laws_in_db()` function:

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
    primary_date: str | None = None,
) -> list[dict]:
    """Enrich each law dict with DB availability and version status.

    Returns the same list with added fields:
    - db_law_id: int or None
    - in_library: bool
    - availability: "available" | "wrong_version" | "missing"
    - available_version_date: str or None (the version date actually found)
    """
    for law in laws:
        law_number = str(law["law_number"])
        law_year = str(law["law_year"])

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

        # Check if the correct version exists
        if primary_date:
            pd = date_type.fromisoformat(primary_date)
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

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/law_mapping.py
git commit -m "feat: rewrite law_mapping.py as DB lookup utility (remove static DOMAIN_LAW_MAP)"
```

---

### Task 4: Rewrite _step2_law_mapping() to use DB lookup

**Files:**
- Modify: `backend/app/services/pipeline_service.py:533-612`

- [ ] **Step 1: Replace the function body**

Replace `_step2_law_mapping()` (lines 533-612) with:

```python
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
    enriched = check_laws_in_db(applicable_laws, db, state.get("primary_date"))

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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: rewrite Step 2 law mapping as DB lookup using Claude-identified laws"
```

---

### Task 5: Rewrite Step 2.5 early relevance gate with pause mechanism

**Files:**
- Modify: `backend/app/services/pipeline_service.py:620-792` (gate + helper functions)

- [ ] **Step 1: Replace _step2_5_early_relevance_gate()**

Replace the function (lines 620-666) with:

```python
def _step2_5_early_relevance_gate(state: dict, db: Session) -> dict | None:
    """Check law availability. Returns None to continue, or a pause event dict."""
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
        for law in candidate_laws:
            preview = {
                "law_number": law["law_number"],
                "law_year": law["law_year"],
                "title": law.get("title", ""),
                "role": law["role"],
                "availability": law.get("availability", "missing"),
                "version_info": law.get("available_version_date"),
                "reason": law.get("reason", ""),
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
```

- [ ] **Step 2: Remove old helper functions**

Delete these functions (they are no longer called):
- `_count_clarification_rounds()` (lines 669-687)
- `_generate_clarification_question()` (lines 690-728)
- `_build_needs_import_event()` (lines 731-762)
- `_build_cannot_answer_event()` (lines 765-792)

- [ ] **Step 3: Update run_pipeline() gate handling**

In `run_pipeline()`, replace the entire `if gate_result:` block (lines 148-178) with code that handles both `pause` and `done` events. Note: do NOT reference `_count_clarification_rounds()` — it is deleted in Step 2.

```python
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
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: rewrite Step 2.5 gate with pause mechanism for missing/wrong-version laws"
```

---

### Task 6: Add search_legislatie() utility to fetcher

**Files:**
- Modify: `backend/app/services/fetcher.py`

- [ ] **Step 1: Check existing fetcher for search capability**

Read `backend/app/services/fetcher.py` to understand the existing scraper. Look for any search/lookup functions.

- [ ] **Step 2: Add search_legislatie() function**

Add a function that searches legislatie.just.ro for a law by number and year, returning the ver_id:

```python
def search_legislatie(law_number: str, law_year: str) -> str | None:
    """Search legislatie.just.ro for a law by number/year, return ver_id if found.

    Uses the search page to find the law. Returns the first matching ver_id
    or None if not found.
    """
    import requests

    # legislatie.just.ro has a search API endpoint
    search_url = "https://legislatie.just.ro/Public/RezultateCautare"
    params = {
        "numar": law_number,
        "an": law_year,
    }

    try:
        resp = requests.get(search_url, params=params, timeout=30)
        resp.raise_for_status()
        # Parse the response to extract ver_id from the results
        # The exact parsing depends on the response format — inspect during implementation
        # Look for links like /Public/DetaliiDocument/XXXXXX
        import re
        matches = re.findall(r'/Public/DetaliiDocument/(\d+)', resp.text)
        if matches:
            return matches[0]
        return None
    except Exception as e:
        logger.warning(f"Failed to search legislatie.just.ro for {law_number}/{law_year}: {e}")
        return None
```

Note: The exact implementation depends on how legislatie.just.ro search works. The implementer should test the actual search endpoint and adjust the parsing accordingly. If the site requires different parameters or returns JSON, adapt the code.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/fetcher.py
git commit -m "feat: add search_legislatie() to find laws by number/year on legislatie.just.ro"
```

---

### Task 7: Update resume_pipeline() to trigger actual imports

**Files:**
- Modify: `backend/app/services/pipeline_service.py:289-310` (resume function import handling)

- [ ] **Step 1: Add import logic to resume_pipeline()**

In `resume_pipeline()`, replace the stub loop (lines 308-311) with actual import logic:

```python
    # Handle imports if user approved
    for law_key, decision in import_decisions.items():
        if decision in ("import", "import_version"):
            try:
                law_number, law_year = law_key.split("/")
                from app.services.leropa_service import import_law as do_import
                from app.services.fetcher import search_legislatie

                ver_id = search_legislatie(law_number, law_year)
                if ver_id:
                    yield {"type": "step", "step": 25, "name": "importing", "status": "running",
                           "data": {"importing": law_key}}
                    do_import(db, ver_id, import_history=True)
                    db.commit()
                    state["flags"].append(f"Imported {law_key} from legislatie.just.ro")
                    yield {"type": "step", "step": 25, "name": "importing", "status": "done",
                           "data": {"imported": law_key}}
                else:
                    state["flags"].append(f"Could not find {law_key} on legislatie.just.ro — continuing without")
            except Exception as e:
                logger.warning(f"Failed to import {law_key}: {e}")
                state["flags"].append(f"Import failed for {law_key}: {str(e)[:100]}")

    # Re-run law mapping to pick up newly imported laws
    state = _step2_law_mapping(state, db)
```

- [ ] **Step 2: Update resume_pipeline docstring**

Replace the deprecation notice (lines 294-297):

```python
    """Resume a paused pipeline after user import decisions.

    Imports requested laws, re-runs law mapping to pick up new data,
    then continues from Step 3 (version selection) onwards.
    """
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/pipeline_service.py
git commit -m "feat: update resume_pipeline to trigger actual imports via leropa_service"
```

---

### Task 8: Update frontend types (api.ts + use-chat.ts + use-event-source.ts)

**Files:**
- Modify: `frontend/src/lib/api.ts:227-232`
- Modify: `frontend/src/app/assistant/use-chat.ts:8,21-25,174,248`
- Modify: `frontend/src/lib/use-event-source.ts:8,21-29,41-46`

- [ ] **Step 1: Add LawPreview type to api.ts**

After the existing `MissingLaw` interface (line 227-232), add:

```typescript
export interface LawPreview {
  law_number: string;
  law_year: string;
  title: string;
  role: "PRIMARY" | "SECONDARY";
  availability: "available" | "wrong_version" | "missing";
  version_info: string | null;
  reason?: string;
}
```

Keep `MissingLaw` for now (other code may reference it).

- [ ] **Step 2: Update PauseData in use-chat.ts**

Replace lines 21-25:

```typescript
export interface PauseData {
  run_id: string;
  message: string;
  laws: LawPreview[];
}
```

Update the import at line 8 to also import `LawPreview`:

```typescript
import {
  api,
  type ChatMessage,
  type ChatSession,
  type LawPreview,
  type StructuredAnswer,
} from "@/lib/api";
```

- [ ] **Step 3: Update use-event-source.ts SSE handler types**

This is CRITICAL — without this the pause event will not reach the frontend correctly.

In `frontend/src/lib/use-event-source.ts`, update the import (line 8):

```typescript
import type { LawPreview, StructuredAnswer } from "@/lib/api";
```

Replace the `onPause` type (lines 21-29):

```typescript
  onPause?: (data: {
    run_id: string;
    message: string;
    laws: LawPreview[];
  }) => void;
```

Replace the `onDone` `missing_laws` field (lines 41-46) — remove the inline type and use `LawPreview`:

```typescript
    missing_laws?: LawPreview[];
```

- [ ] **Step 4: Update use-chat.ts onDone handlers**

In `use-chat.ts`, lines 174 and 248 both reference `data.missing_laws`. These still work because the backend `done` events from the answer generation path don't send `missing_laws`. But for the "no laws identified" `done` event from Step 2.5, we no longer send `missing_laws` — we send it via the `pause` event's `laws` field instead. The `done` event fallback (no laws identified) doesn't include `missing_laws`, so lines 174 and 248 will just be `undefined`, which is fine since the field is optional.

No code change needed here — the optional `missing_laws?: ...` on `ChatMessage` handles this gracefully.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/assistant/use-chat.ts frontend/src/lib/use-event-source.ts
git commit -m "feat: add LawPreview type and update PauseData/SSE handler interfaces"
```

---

### Task 9: Rewrite ImportPrompt component with three-state law preview

**Files:**
- Modify: `frontend/src/app/assistant/import-prompt.tsx` (full rewrite)

- [ ] **Step 1: Replace the component**

```tsx
"use client";

import { useState } from "react";
import type { PauseData } from "./use-chat";

export function ImportPrompt({
  pauseData,
  onDecision,
}: {
  pauseData: PauseData;
  onDecision: (decisions: Record<string, string>) => void;
}) {
  const [loading, setLoading] = useState(false);

  const needsAction = pauseData.laws.filter(
    (l) => l.availability !== "available"
  );

  const handleImport = () => {
    setLoading(true);
    const decisions: Record<string, string> = {};
    for (const law of pauseData.laws) {
      if (law.availability === "missing") {
        decisions[`${law.law_number}/${law.law_year}`] = "import";
      } else if (law.availability === "wrong_version") {
        decisions[`${law.law_number}/${law.law_year}`] = "import_version";
      }
    }
    onDecision(decisions);
  };

  const handleSkip = () => {
    setLoading(true);
    const decisions: Record<string, string> = {};
    for (const law of needsAction) {
      decisions[`${law.law_number}/${law.law_year}`] = "skip";
    }
    onDecision(decisions);
  };

  return (
    <div className="my-3 mx-auto max-w-xl bg-slate-50 border border-slate-200 rounded-lg p-4">
      <div className="text-sm text-slate-700 mb-3 font-medium">
        {pauseData.message}
      </div>

      <div className="mb-3 space-y-1.5">
        {pauseData.laws.map((law) => (
          <div
            key={`${law.law_number}/${law.law_year}`}
            className={`text-xs rounded px-2 py-1.5 flex items-center gap-2 ${
              law.availability === "available"
                ? "bg-green-50 text-green-800 border border-green-200"
                : law.availability === "wrong_version"
                ? "bg-amber-50 text-amber-800 border border-amber-200"
                : "bg-red-50 text-red-800 border border-red-200"
            }`}
          >
            <span>
              {law.availability === "available"
                ? "\u2705"
                : law.availability === "wrong_version"
                ? "\u26A0\uFE0F"
                : "\u274C"}
            </span>
            <div className="flex-1">
              <span className="font-medium">
                {law.title || `${law.law_number}/${law.law_year}`}
              </span>
              <span className="text-[10px] ml-1 opacity-70">
                ({law.law_number}/{law.law_year})
              </span>
              {law.role === "PRIMARY" && (
                <span className="ml-1 text-[10px] font-semibold uppercase opacity-60">
                  primary
                </span>
              )}
              {law.availability === "wrong_version" && law.version_info && (
                <div className="text-[10px] opacity-70 mt-0.5">
                  Available: {law.version_info} (wrong version)
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {needsAction.length > 0 && (
        <div className="flex gap-2">
          <button
            onClick={handleImport}
            disabled={loading}
            className="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Importing..." : "Import and continue"}
          </button>
          <button
            onClick={handleSkip}
            disabled={loading}
            className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:bg-gray-100 disabled:cursor-not-allowed transition-colors"
          >
            Continue without
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/assistant/import-prompt.tsx
git commit -m "feat: rewrite ImportPrompt with three-state law preview (available/wrong_version/missing)"
```

---

### Task 10: Delete LA-S2.5-clarification.txt and clean up prompt manifest

**Files:**
- Delete: `backend/prompts/LA-S2.5-clarification.txt`

- [ ] **Step 1: Delete the clarification prompt**

```bash
rm backend/prompts/LA-S2.5-clarification.txt
```

- [ ] **Step 2: Check if LA-S2.5 is registered in the prompt manifest and remove if so**

Search for `LA-S2.5` in the prompt seeding/manifest code:

```bash
grep -r "LA-S2.5" backend/
```

If found in a manifest or seed file, remove the entry.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove LA-S2.5 clarification prompt (replaced by Claude law identification)"
```

---

### Task 11: End-to-end verification

- [ ] **Step 1: Restart backend**

- [ ] **Step 2: Test cross-domain question**

Ask: "daca un actionar care detine 40% intr o companie a imprumutat firma cu 100.000 euro pe 01.01.2025, iar pe 01.03.2026 i se restituie banii, iar 4 luni mai tarziu, compania intra in insolventa, administratorul companiei este afectat intr-un fel? care sunt riscurile?"

Expected:
- Step 1 should identify: Legea 31/1990 (PRIMARY), Legea 85/2014 (PRIMARY), Codul Civil (SECONDARY)
- Step 2 should show availability status for each
- If Legea 85/2014 is not in library, Step 2.5 should pause with import preview showing all three laws

- [ ] **Step 3: Test happy path (all laws available)**

Ask: "ce capital social minim trebuie la infiintare SRL"

Expected: Pipeline should identify Legea 31/1990 as PRIMARY, find it available, and proceed without pausing. Result should be the same quality as before.

- [ ] **Step 4: Test import flow (if possible)**

If a law is missing, click "Import and continue" and verify:
- The import runs (may take 5-30 seconds)
- Pipeline resumes after import
- The answer uses the newly imported law

- [ ] **Step 5: Test "Continue without"**

Click "Continue without" when a law is missing. Verify:
- Pipeline proceeds with available laws
- Answer includes a flag about missing coverage
- Confidence is appropriately set
