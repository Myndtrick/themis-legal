# Themis Settings Protocol (THEMIS-SETTINGS-v1)

> **Settings, Prompt Management, and Pipeline Tracking**
> Version 1.0
> Applies to: All Themis modules (Legal Assistant — Phase 2 | Contract Review — Phase 3)
> Read alongside: LA-P v1 | RL-DAP v1 | THEMIS-SHARED-v1

---

## META — What This Document Is

This document defines the Settings section of the Themis application.

Settings has three tabs:
1. **Prompt Management** — view, edit, and version-control all AI prompts
2. **Pipeline Tracking** — inspect post-hoc logs of every analysis and answer
3. **Version History** — full history of prompt changes with diff and restore

> **Core principle:** No prompt change takes effect without explicit user approval.
> The system proposes — the user decides.

---

## TAB 1 — Prompt Management

### 1.1 What It Is

A prompt is the instruction text sent to Claude API for each step of the pipeline. The quality of Themis outputs depends directly on prompt quality. This tab gives full visibility and control over every prompt in the system — without requiring code changes.

### 1.2 Prompt Inventory

Every prompt in the system is listed here, organized by module and agent.

**Legal Assistant (Phase 2) prompts:**

| Prompt ID | Agent / Step | Description |
|-----------|-------------|-------------|
| `LA-S1` | Step 1 — Issue Classifier | Classifies question type, legal domain, output mode |
| `LA-S2` | Step 2 — Date Extractor | Identifies relevant dates and periods |
| `LA-S3` | Step 3 — Law Identifier | Identifies candidate applicable laws |
| `LA-S4` | Step 4 — Coverage Checker | Checks Library coverage per law |
| `LA-S5` | Step 5 — Import Request | Generates import permission request message |
| `LA-S7` | Step 7 — Answer Generator (Mode 1 Q&A) | Generates structured Q&A answer |
| `LA-S7-M2` | Step 7 — Answer Generator (Mode 2 Memo) | Generates legal research memo |
| `LA-S7-M3` | Step 7 — Answer Generator (Mode 3 Comparison) | Generates version comparison report |
| `LA-S7-M4` | Step 7 — Answer Generator (Mode 4 Compliance) | Generates compliance check report |
| `LA-S7-M5` | Step 7 — Answer Generator (Mode 5 Checklist) | Generates legal checklist |
| `LA-CONF` | Confidence Scorer | Assesses confidence level of answer |
| `LA-CONFLICT` | Conflict Resolver | Handles conflicts between applicable laws |

**Contract Review (Phase 3) prompts:**

| Prompt ID | Agent | Description |
|-----------|-------|-------------|
| `CR-A1` | Agent 1 — Document Identifier | Classifies document type, extracts parties and date |
| `CR-A1-NER` | Agent 1 — Party Extractor | Named entity recognition for parties |
| `CR-A2` | Agent 2 — Clause Classifier | Detects and classifies clauses |
| `CR-A3` | Agent 3 — Law Mapper | Maps document type to applicable laws |
| `CR-A3-VER` | Agent 3 — Version Selector | Selects correct law versions |
| `CR-A3-TEMP` | Agent 3 — Temporal Compliance | Checks temporal obligation compliance |
| `CR-A4` | Agent 4 — Risk Detector | Detects risks and classifies RED/YELLOW/GREEN |
| `CR-A4-PERSP` | Agent 4 — Perspective Analyzer | Applies party perspective to risk analysis |
| `CR-A5` | Agent 5 — Report Generator | Generates final structured report |
| `CR-A5-REDLINE` | Agent 5 — Redline Generator | Generates Word redline suggestions |
| `CR-CHAT` | Contract Chat | Legal Assistant RAG adapted for contract context |

---

### 1.3 How to View a Prompt

Each prompt entry shows:

```
PROMPT: [Prompt ID] — [Description]
Module: [Legal Assistant / Contract Review]
Status: ACTIVE
Last modified: [date] by [you directly / via chat]
Version: v[N]

─────────────────────────────────────────
CURRENT PROMPT TEXT:
[full prompt text — editable]
─────────────────────────────────────────

[✏️ Edit directly]  [💬 Modify via chat]  [📋 View version history]
```

---

### 1.4 How to Modify a Prompt

**Method A — Direct Edit**

1. Click `[✏️ Edit directly]` on any prompt
2. A text editor opens with the current prompt text
3. Make your changes
4. Click `[Propose change]`
5. System shows a diff between current and proposed version
6. You review the diff
7. Click `[✅ Approve & save]` or `[❌ Discard]`
8. If approved: new version becomes active, previous version saved to history

**Method B — Modify via Chat**

1. Click `[💬 Modify via chat]` on any prompt
2. A chat panel opens with context: "You are modifying prompt [ID]"
3. Describe what you want changed:
   ```
   EXAMPLE: "Make the risk detection prompt more conservative —
   flag as YELLOW anything that could possibly be ambiguous,
   not just things that are clearly problematic."
   ```
4. System generates a proposed modified prompt
5. System shows diff between current and proposed
6. You review
7. Click `[✅ Approve & save]` or `[❌ Discard]` or `[💬 Refine further]`
8. If approved: new version becomes active

**Approval is mandatory for both methods.**
No prompt change takes effect without your explicit approval.
The system can propose but never auto-save.

---

### 1.5 Approval Workflow

```
Modification proposed (by you directly OR via chat)
        │
        ▼
PENDING APPROVAL state
  → Diff shown: current version vs proposed version
  → Changes highlighted (additions in green, removals in red)
  → Proposed version preview: "How this prompt would read"
  → Impact note: "This prompt affects [N] pipeline steps"
        │
        ├── [✅ Approve & save]
        │     → Proposed becomes ACTIVE (v[N+1])
        │     → Previous version saved to history as v[N]
        │     → Timestamp + "modified by: you" logged
        │
        ├── [❌ Discard]
        │     → No change made
        │     → Proposed version discarded
        │
        └── [💬 Refine further]
              → Return to chat to continue modifying
              → Current active prompt unchanged until approval
```

---

### 1.6 Prompt Diff View

Shown before every approval decision:

```
PROMPT DIFF — [Prompt ID] v[N] → v[N+1]
─────────────────────────────────────────
REMOVED (red):
  "Flag a clause as YELLOW if it appears one-sided."

ADDED (green):
  "Flag a clause as YELLOW if it appears one-sided OR if
   it contains ambiguous language that could be interpreted
   in multiple ways."

UNCHANGED:
  [rest of prompt shown in normal color]

Net change: +1 sentence | +18 words
─────────────────────────────────────────
[✅ Approve & save]  [❌ Discard]  [💬 Refine further]
```

---

### 1.7 Active vs Inactive Prompts

```
ACTIVE   — currently used in the pipeline
PENDING  — proposed change awaiting approval
INACTIVE — a prompt that has been superseded by a newer version
           (still visible in Version History, never deleted)
```

All prompt versions are kept permanently. Nothing is deleted.

---

## TAB 2 — Pipeline Tracking

### 2.1 What It Is

Every time the Legal Assistant answers a question or Contract Review analyzes a document, the system logs the complete execution trace. This tab lets you inspect those logs post-hoc to understand how the system worked, where it struggled, and what it decided.

### 2.2 Run Log List

The main view shows all runs, most recent first:

```
PIPELINE RUNS
─────────────────────────────────────────
Filter by: [Module ▼] [Date range ▼] [Confidence ▼] [Status ▼]

[Run ID]  [Timestamp]          [Module]   [Mode/Type]        [Confidence]  [Status]   [Issues]
───────────────────────────────────────────────────────────────────────────────────────────────
#0142     23 Mar 2026 14:32    Legal Q&A  Mode 1 — Q&A       HIGH          ✅ OK      —
#0141     23 Mar 2026 11:15    Contract   A2 — Cesiune        MEDIUM        ⚠️ Warn    2 laws missing
#0140     23 Mar 2026 09:44    Legal Q&A  Mode 2 — Memo       HIGH          ✅ OK      —
#0139     22 Mar 2026 16:20    Contract   C7 — NDA            LOW           🔴 Flag    1 primary law missing
```

Click any row to open the full run detail.

---

### 2.3 Run Detail View

For each run, the full execution trace is shown:

```
RUN DETAIL — #0141
─────────────────────────────────────────
Module          : Contract Review
Document type   : A2 — Contract de cesiune părți sociale
Started         : 23 Mar 2026 at 11:15:32
Completed       : 23 Mar 2026 at 11:16:08
Total duration  : 36 seconds
Overall status  : ⚠️ WARNING
─────────────────────────────────────────

STEP-BY-STEP EXECUTION:

Step 1 — Document Identification
  Status        : ✅ completed
  Duration      : 3.2s
  Prompt used   : CR-A1 v4
  Input         : [document text excerpt — first 200 chars]
  Output        : doc_type=A2, confidence=94%
  Parties found : SRL X (Cedent), SRL Y (Cesionar)
  Date found    : 15 January 2024
  Mode          : [perspective selection paused — user selected Cedent]

Step 2 — Clause Classification
  Status        : ✅ completed
  Duration      : 5.1s
  Prompt used   : CR-A2 v3
  Clauses found : 11
  Missing       : Termination clause, Force majeure
  Confidence    : HIGH

Step 3 — Law Mapping + Version Selection
  Status        : ⚠️ WARNING — 2 laws not in Library
  Duration      : 4.8s
  Prompt used   : CR-A3 v2
  Laws mapped   : 4 laws
  ✅ Legea 31/1990   : version 15 Mar 2022 selected
  ✅ Codul Civil     : version 01 Oct 2011 selected
  ❌ Codul Fiscal    : NOT IN LIBRARY — flagged
  ❌ Legea 21/1996   : NOT IN LIBRARY — flagged
  Temporal check    : ✅ no temporal issues found

Step 4 — Risk Detection
  Status        : ✅ completed
  Duration      : 8.4s
  Prompt used   : CR-A4 v5, CR-A4-PERSP v2
  RED issues    : 1
  YELLOW issues : 3
  GREEN clauses : 7
  Perspective   : Cedent (SRL X)
  Confidence    : MEDIUM (2 laws unverified)

Step 5 — Report Generation
  Status        : ✅ completed
  Duration      : 6.2s
  Prompt used   : CR-A5 v3
  Output        : Report generated, PARTIAL flag applied

─────────────────────────────────────────
PROMPTS USED IN THIS RUN:
  CR-A1 v4 | CR-A2 v3 | CR-A3 v2 | CR-A4 v5 | CR-A4-PERSP v2 | CR-A5 v3
  [Click any prompt to view the exact text sent to Claude API]

CLAUDE API CALLS:
  Call 1 (Step 1): [tokens in: 842 | tokens out: 312 | duration: 3.1s]
  Call 2 (Step 2): [tokens in: 2140 | tokens out: 891 | duration: 4.9s]
  Call 3 (Step 4): [tokens in: 3840 | tokens out: 1420 | duration: 8.2s]
  Call 4 (Step 5): [tokens in: 4200 | tokens out: 2100 | duration: 6.0s]
  Total tokens    : 11,022 in + 4,723 out
  Estimated cost  : ~$0.18

FLAGS & WARNINGS:
  ⚠️ Codul Fiscal not in Legal Library — risk analysis incomplete on fiscal aspects
  ⚠️ Legea 21/1996 not in Legal Library — competition law not checked
  ℹ️ Answer marked PARTIAL due to missing laws

─────────────────────────────────────────
[📋 View full prompt texts]  [🔍 View raw Claude responses]  [📊 Compare with other runs]
```

---

### 2.4 What Pipeline Tracking Logs

For every run:

```
ALWAYS LOGGED:
  - Run ID, timestamp, duration
  - Module and mode/document type
  - Every step: status, duration, prompt version used
  - Every law searched: found / missing / wrong version
  - Law versions selected and why
  - Overall and per-step confidence scores
  - All flags and warnings generated
  - Number and type of Claude API calls
  - Token counts and estimated cost
  - Final output status (OK / PARTIAL / WARNING / ERROR)

LOGGED ON REQUEST (expandable):
  - Full prompt text sent to Claude for each step
  - Full Claude API response for each step
  - Complete retrieved law articles (verbatim)
  - Session context passed between steps

NEVER LOGGED:
  - User account passwords or credentials
  - Full document text in plaintext logs
    (document ID referenced, not content)
```

---

### 2.5 Filters and Search

```
Filter runs by:
  Module          : Legal Assistant / Contract Review / All
  Date range      : [from] → [to]
  Confidence      : HIGH / MEDIUM / LOW / Any
  Status          : OK / Warning / Error / Partial / Any
  Prompt version  : Show runs that used prompt [ID] v[N]
  Missing law     : Show runs where [law name] was missing
  Document type   : [any document type code]
  Cost range      : [min] → [max] estimated cost

Search:
  Free text search across run summaries
```

---

### 2.6 System Health Overview

At the top of Pipeline Tracking, a summary dashboard:

```
SYSTEM HEALTH — last 30 days
─────────────────────────────────────────
Total runs          : 142
✅ OK               : 118 (83%)
⚠️ With warnings    : 19  (13%)
🔴 With errors      : 5   (4%)

Average confidence  : HIGH (78% of runs)
Average duration    : 28 seconds
Average cost        : $0.12 per run

Most common warning : "Law not in Legal Library" (14 runs)
→ [Suggested imports: Codul Fiscal, Legea 21/1996]

Prompt versions active:
  All prompts on latest versions ✅
```

---

## TAB 3 — Version History

### 3.1 What It Is

Complete history of every prompt version ever saved. Nothing is deleted. Every version is inspectable, comparable, and restorable.

### 3.2 Version List Per Prompt

Select a prompt from the inventory to see its full history:

```
VERSION HISTORY — CR-A4 (Risk Detector)
─────────────────────────────────────────
v5  23 Mar 2026  ACTIVE    Modified via chat — "more conservative on ambiguous clauses"
v4  15 Mar 2026  inactive  Modified directly — "added perspective reasoning rules"
v3  02 Mar 2026  inactive  Modified via chat — "improved RED classification criteria"
v2  24 Feb 2026  inactive  Initial refinement after first test
v1  20 Feb 2026  inactive  Initial version (auto-generated at build)

[Select any two versions to compare →]
```

---

### 3.3 Version Diff

Select any two versions to see a diff:

```
DIFF — CR-A4 v3 vs v5
─────────────────────────────────────────
[v3 — 02 Mar 2026]              [v5 — 23 Mar 2026 — ACTIVE]

REMOVED:                         ADDED:
"Flag as YELLOW if clause        "Flag as YELLOW if clause
 appears one-sided."              appears one-sided OR contains
                                  ambiguous language that could
                                  be interpreted in multiple ways."

REMOVED:                         ADDED:
"Flag as RED only if clause      "Flag as RED if clause directly
 directly contradicts            contradicts mandatory law OR if
 mandatory law."                  the contradiction is reasonably
                                  likely based on context."

UNCHANGED: [rest of prompt]
─────────────────────────────────────────
Net change across v3→v5: +2 sentences | +41 words | 2 modifications
```

---

### 3.4 Restore a Previous Version

```
To restore a previous version:

1. Select the version you want to restore
2. Click [↩️ Restore this version]
3. System creates a PENDING APPROVAL entry:
   "Restore CR-A4 to v3 (02 Mar 2026)"
4. Diff shown: current ACTIVE (v5) vs version to restore (v3)
5. You review
6. Click [✅ Approve restore] or [❌ Cancel]
7. If approved:
   → v3 content becomes new v6 (ACTIVE)
   → v5 becomes inactive
   → History preserved: v1, v2, v3, v4, v5, v6
   → v6 notes: "Restored from v3 on [date]"

NOTE: Restoring creates a new version — it does not delete
any existing version. The full history is always preserved.
```

---

## Implementation Notes for Claude Code

### Data Model

```python
# Prompt version
class PromptVersion:
    prompt_id: str          # e.g. "CR-A4"
    version_number: int     # e.g. 5
    prompt_text: str        # full prompt text
    status: str             # ACTIVE / PENDING / inactive
    created_at: datetime
    created_by: str         # "direct_edit" / "chat_modification"
    modification_note: str  # what was changed and why
    approved_at: datetime
    approved_by: str        # always the user

# Pipeline run log
class PipelineRun:
    run_id: str
    module: str             # "legal_assistant" / "contract_review"
    mode: str               # "qa" / "memo" / "comparison" / etc.
    started_at: datetime
    completed_at: datetime
    overall_status: str     # "ok" / "warning" / "error" / "partial"
    overall_confidence: str # "HIGH" / "MEDIUM" / "LOW"
    steps: List[StepLog]
    prompts_used: List[str] # prompt_id + version for each step
    api_calls: List[APICallLog]
    flags: List[str]
    estimated_cost: float

# Step log
class StepLog:
    step_name: str
    status: str
    duration_seconds: float
    prompt_id: str
    prompt_version: int
    input_summary: str      # not full content — summary only
    output_summary: str
    confidence: str
    warnings: List[str]
```

### Approval Endpoint

```python
# All prompt changes go through this endpoint — no exceptions
POST /api/settings/prompts/{prompt_id}/propose
  body: { proposed_text: str, modification_note: str, source: "direct" | "chat" }
  returns: { diff: str, pending_version_id: str }

POST /api/settings/prompts/{prompt_id}/approve/{pending_version_id}
  returns: { new_version: int, activated_at: datetime }

POST /api/settings/prompts/{prompt_id}/discard/{pending_version_id}
  returns: { status: "discarded" }
```

### Pipeline Logging

```python
# Called automatically at end of every pipeline run
POST /api/pipeline/runs/log
  body: PipelineRun object
  Note: Log is append-only — runs are never modified or deleted

GET /api/pipeline/runs
  params: module, date_from, date_to, status, confidence, prompt_version
  returns: List[PipelineRun] (paginated)

GET /api/pipeline/runs/{run_id}
  returns: PipelineRun with full step details
```

### UI Components Needed

```
PromptEditor
  - Syntax-highlighted text editor (no special language — plain text)
  - "Propose change" button
  - Diff viewer (side-by-side or inline)
  - Approve / Discard / Refine buttons

VersionList
  - Table: version number, date, status, note
  - Version selector for diff
  - Restore button → triggers approval workflow

RunList
  - Filterable table of pipeline runs
  - Click-through to RunDetail

RunDetail
  - Step-by-step accordion (collapsed by default, expand each step)
  - Prompt text viewer (expandable per step)
  - Raw Claude response viewer (expandable per step)
  - Flag/warning list
  - Cost summary

HealthDashboard
  - Simple metrics: total runs, OK%, warning%, error%
  - Average confidence, duration, cost
  - Most common warnings with suggested actions
```

---

## Summary — Settings Tab Overview

| Tab | What you do there |
|-----|------------------|
| **Prompt Management** | View all prompts, edit directly or via chat, approve changes before they take effect |
| **Pipeline Tracking** | Inspect post-hoc logs of every run — what happened, what was used, what went wrong |
| **Version History** | See all prompt versions, compare any two, restore any previous version |

> **All three tabs are read-only by default.**
> Changes require explicit approval.
> Nothing is auto-saved or auto-applied.
> Nothing is ever deleted.

---

*THEMIS-SETTINGS-v1 — Settings Protocol*
*For use with Themis Legal AI Application*
*Applies to: Legal Assistant (Phase 2) + Contract Review (Phase 3)*
*Last updated: March 2026*
