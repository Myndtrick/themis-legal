# Chat Response Redesign — Design Spec

## Problem

Two issues with the current Legal Assistant:

1. **Pipeline fails to find relevant laws.** Step 3 (Law Identification) returns empty candidate lists even when the law IS in the database. This happens because the library list passed to Claude is truncated and Claude fails to match. With no candidates, the RAG search has nothing to filter on and retrieves wrong articles.

2. **Display is a raw text dump.** Claude outputs markdown formatting (`**RASPUNS SCURT**`, `[DB]`, `[Unverified]`) but the frontend renders it as literal text with `whitespace-pre-wrap`. The response looks like a developer log, not a legal tool.

## Design

### A. Pipeline Fixes

#### A1. Better Library Context for Step 3

Change how the library list is passed to Claude in `_step3_law_identification`:
- Include **full titles** (not truncated at 80 chars)
- Format as a numbered list with document type: `"1. Legea 31/1990 — Legea nr. 31 din 16 noiembrie 1990 privind societățile comerciale (law, in_force)"`
- Include status so Claude knows if a law is repealed

**File:** `backend/app/services/pipeline_service.py`, `_step3_law_identification`

#### A2. Fuzzy Law Matching After Step 3

After Claude returns candidates, do a **database cross-check**:
- For each candidate, search the DB by `law_number` and `law_year` (case-insensitive, trimmed)
- Also try matching by partial title
- Mark matched laws as `source: "DB"` and attach `db_law_id`

This catches cases where Claude says "Legea 31/1990" but the DB stores the number as "31".

**File:** `backend/app/services/pipeline_service.py`, `_step3_law_identification` (after Claude call)

#### A3. Fallback Broad Search

If after Step 4, no laws are covered (all missing), do a **broad ChromaDB search** without law filters. At least return the most semantically relevant articles from the entire library. Flag the answer as `[Partial]`.

**File:** `backend/app/services/pipeline_service.py`, `_step7_answer_generation` (before RAG query)

### B. Structured JSON Response

#### B1. Change Answer Prompt to Output JSON

Modify the Step 7 prompts (all 5 modes) to output **structured JSON** instead of markdown:

```json
{
  "short_answer": "Capitalul social minim pentru un SRL la infiintare este de 200 lei, conform Legii 31/1990.",
  "legal_basis": "Art. 11 alin. (1) din Legea 31/1990 prevede ca...",
  "version_logic": "S-a utilizat versiunea din 2007 a Legii 31/1990, cea mai recenta disponibila in Biblioteca Juridica.",
  "nuances": "Aceasta suma reprezinta minimul legal. In practica...",
  "changes_over_time": null,
  "missing_info": null,
  "sources": [
    {"statement": "capitalul social minim este de 200 lei", "label": "DB", "law": "31/1990", "article": "Art. 11", "version": "2007-01-12"},
    {"statement": "informatia despre modificari recente", "label": "General"}
  ]
}
```

**Key rule for the short_answer field:** NO source labels, NO markdown headers, NO formatting. Just a natural, conversational answer in the same language as the question. Written as if a lawyer were speaking to a non-lawyer.

Source labels only appear in the `sources` array.

**Files:** All `backend/prompts/LA-S7*.txt` files

#### B2. Two-Phase Streaming

1. **Phase 1 — Stream the short answer:** Claude generates the full JSON, but we extract the `short_answer` field and stream it token by token. During this phase, the user sees the answer typing out conversationally.

2. **Phase 2 — Deliver the full response:** Once streaming completes, parse the full JSON and send it as the `done` SSE event with all sections separated.

**Implementation approach:** Actually, streaming partial JSON is fragile. Simpler approach:
- Keep streaming the raw text as tokens (user sees the answer building)
- When done, parse the complete text as JSON
- Send the parsed structure in the `done` event
- The frontend replaces the streaming text with the properly rendered structured response

If JSON parsing fails (Claude didn't output valid JSON), fall back to displaying the raw text with basic markdown rendering.

**Files:**
- `backend/app/services/pipeline_service.py`, `_step7_answer_generation`
- `frontend/src/app/assistant/use-chat.ts` (handling `done` event)

### C. Frontend Display Redesign

#### C1. Main Answer — Conversational

The **short_answer** is displayed as clean conversational text:
- No section headers
- No source labels
- No markdown formatting
- Just the answer, like a person talking

Below it: small confidence badge + mode badge.

#### C2. Collapsible Details Section

A "Show details" toggle reveals:
- **Legal Basis** — with small colored `[DB]` / `[General]` badges inline
- **Version Logic** — which version was used and why
- **Nuances** — conditions, caveats, edge cases
- **Changes Over Time** — only if relevant (not shown if null)
- **Missing Information** — only if relevant (not shown if null)
- **Sources** — table of all source attributions: statement, label, law, article, version

Use `react-markdown` for rendering inside the details section (for bold, lists, etc. that Claude may use in the detailed sections).

#### C3. Disclaimer

Always visible below the details toggle, in small gray text:
> ⚠️ Analiză juridică preliminară asistată de AI — necesită revizuire umană.

#### C4. Pipeline Reasoning — Moved to Settings

The 7-step pipeline accordion (currently shown under each message) is **too technical for the chat**. Move it:
- Remove from the chat message display entirely
- It's already visible in **Settings > Pipeline Tracking** where each run can be inspected
- If the user wants to debug a specific answer, they click through to the run detail in Settings

#### C5. Streaming UX

During streaming:
1. Show pipeline step indicators (small, subtle — just step names with checkmarks, not an accordion)
2. When Step 7 starts, show the answer text streaming in
3. When streaming completes, replace with the structured response (short answer + details toggle)

### D. Add react-markdown Dependency

Install `react-markdown` in the frontend for rendering markdown in the details section.

```bash
cd frontend && npm install react-markdown
```

## Files to Modify

**Backend:**
- `backend/app/services/pipeline_service.py` — Steps 3, 7 (library list, fallback search, JSON output)
- `backend/prompts/LA-S7-answer-qa.txt` — JSON output format
- `backend/prompts/LA-S7-M2-answer-memo.txt` — JSON output format
- `backend/prompts/LA-S7-M3-answer-comparison.txt` — JSON output format
- `backend/prompts/LA-S7-M4-answer-compliance.txt` — JSON output format
- `backend/prompts/LA-S7-M5-answer-checklist.txt` — JSON output format

**Frontend:**
- `frontend/src/app/assistant/message-bubble.tsx` — Complete rewrite of assistant message rendering
- `frontend/src/app/assistant/reasoning-panel.tsx` — Remove from chat, or simplify to subtle step indicators
- `frontend/src/app/assistant/use-chat.ts` — Parse structured JSON from `done` event
- `frontend/package.json` — Add react-markdown

**New frontend files:**
- `frontend/src/app/assistant/answer-detail.tsx` — Collapsible details section with legal basis, sources table
- `frontend/src/app/assistant/step-indicator.tsx` — Small, subtle pipeline progress (replaces heavy accordion)
