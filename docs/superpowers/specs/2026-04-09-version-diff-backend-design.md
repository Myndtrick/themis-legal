# Version Diff Backend — Note-Augmented Structural Diff

**Date:** 2026-04-09
**Status:** Draft
**Part of:** Version diff redesign (Approach B). Spec 2 of 3.
**Preceded by:** `2026-04-08-paragraph-notes-and-backfill-design.md` (Spec 1 — data foundation)
**Followed by:** Spec 3 — frontend polish (collapsibles, navigation, citation chips)
**Supersedes:** `2026-04-07-version-diff-redesign-design.md` (the tokenizer approach is replaced by structural matching now that the data is available)

## Problem

The current diff between two law versions, computed by `backend/app/services/structured_diff.py`, has three failure modes that compound on each other:

1. **It tokenizes Article.full_text from scratch with regex.** It throws away the structured `Article` / `Paragraph` / `Subparagraph` rows the parser already created and rebuilds a flat `AtomicUnit` list at diff time. The two representations diverge: a paragraph that the parser stored cleanly may be tokenized into different units a few minutes later because the regex disagrees with leropa about where literae start.

2. **It matches by content similarity, not by stable label.** Inside an article, units are paired with `difflib.SequenceMatcher` keyed on a normalized prefix of their text. When a paragraph is reordered, lightly rewritten, or merged with a sibling, the matching collapses: two unrelated paragraphs end up paired, the diff renders nonsense strikethroughs, and the reader can't tell what actually changed. Spec 1's investigation found one article (insolvency law art. 5) where 17 different subparagraphs share each label `a)`, `b)`, `c)`, and the existing `_diff_subparagraphs` builds `map_a[label] = sub` so only the *last* one per label survives — every comparison after that is between unrelated definitions.

3. **The inline `(la <date>, …)` annotations are still in the text.** Romanian laws on legislatie.just.ro embed an official changelog inside the article body. The current diff tokenizes that changelog as content and renders it as a deletion + addition every time the annotation moves or gets reformatted. The screenshot the user shared showed exactly this: an entire `(la 17-07-2022, Articolul 23 din Secțiunea 1, Capitolul III, Titlul I a fost modificat de Punctul 39, Articolul I din LEGEA nr. 216 din 14 iulie 2022, publicată în MONITORUL OFICIAL nr. 709 din 14 iulie 2022)` block struck through, then a near-identical block re-added one line below. Pure noise.

Spec 1 fixed the data: paragraph-level amendment notes are now stored, every paragraph has a `text_clean` column that has the inline annotations stripped, and the parser's stable `(article.label, paragraph.label)` chain is intact in the database. This spec replaces the diff backend so it actually uses that data.

## Goal

Replace the internals of `structured_diff.py` with a label-based structural matcher that:

- Walks the stored `Article` → `Paragraph` trees of both versions and matches nodes by `(article_label, paragraph_label)`.
- Compares the cleaned text (`text_clean`), not the raw `full_text`. Inline annotations are invisible to the matcher because they were stripped at import time.
- Computes word-level highlights inside a modified paragraph using `difflib`, but on the cleaned text — so the highlights are about substance, not annotation churn.
- Surfaces paragraph-level amendment notes from Spec 1 as **enrichment metadata** next to each modified paragraph (date, source law, official-gazette reference). Notes never determine whether something is in the diff; they only explain it.
- Keeps the existing endpoint URL `/api/laws/{id}/diff?version_a=&version_b=` stable.
- Updates the frontend `DiffResult` shape to a clean hierarchical structure (article → paragraph), and updates `/laws/[id]/diff/page.tsx` to render it. The render is intentionally minimal — collapsibles, sticky headers, navigation, and citation chips are deferred to Spec 3.

The user-facing test for "did Spec 2 work?" is: open the diff page on a real Romanian law that has been amended, and confirm that (a) every paragraph that actually changed appears, (b) every paragraph that didn't is left alone, (c) the inline `(la …)` annotations are gone from both sides, and (d) word-level highlights inside a modified paragraph point at the actual changed words.

## Non-goals

- **No frontend polish.** The diff page in Spec 2 renders the new hierarchy in the simplest possible way. No collapsibles, no per-article anchors, no sticky article headers, no fancy navigation, no per-change citation chips. Spec 3 owns that.
- **No notes-as-source-of-truth.** Notes are enrichment, not authoritative for the diff. We do not use `note.replaced` / `note.replacement` as the literal old/new text even when present. The decision is locked: the comparison is the source of truth, the notes are the explanation.
- **No diff caching.** Each diff request runs the matcher fresh. Performance is fine because we operate on already-stored rows; no network or parser involvement.
- **No changes to the importer or to the notes_backfill job.** Spec 1 owns those.
- **No new diff endpoints.** Same URL, same query parameters, same auth. Only the response shape changes.
- **No changes to EU laws.** EU laws use a different parser; the structural-matching strategy is built for Romanian leropa output. EU diffs continue to use whatever they used before (or are out of scope; verify during implementation).
- **No "metadata-only" change state.** If `text_clean(A) == text_clean(B)`, the paragraph is unchanged. Period. Notes are not a state determinant.

## Architecture

Three pieces, all in `backend/app/services/`:

```
structural_diff.py       NEW   — pure matching + comparison; replaces structured_diff.py internals
diff_renumbering.py      NEW   — pure helpers for greedy text-similarity pairing of leftovers
structured_diff.py       EDIT  — keeps the public function name `diff_articles()` for the
                                 router; internally delegates to structural_diff
```

The router (`backend/app/routers/laws.py:1494`) is unchanged. It still calls `diff_articles(articles_a, articles_b)` and serializes the result. Only the internals of that call change. This means we can rip out the old tokenizer-based path in one PR with no router or test plumbing breakage, and the change is reversible by reverting one file.

The two new modules are pure: no SQLAlchemy, no I/O, no DB session. They take Python objects (with `.label`, `.text_clean`, `.amendment_notes`, etc.) and return Python dataclasses. This makes them trivial to test against fixtures and impossible to accidentally couple to the rest of the app.

Frontend: one file changes — `frontend/src/app/laws/[id]/diff/page.tsx` — to render the new shape. The TypeScript types in `frontend/src/lib/api.ts` get a new shape (`DiffArticle` and `DiffParagraph`); the existing `DiffUnit` shape is removed once the page no longer references it. No new components, no new styling, no Spec 3 affordances.

## Data flow

```
GET /api/laws/{id}/diff?version_a=A&version_b=B
        │
        ▼
laws.diff_versions(...)                    (existing handler, unchanged)
        │
        │ loads version A and version B
        │ pulls Article rows + their Paragraph rows + amendment_notes
        │ for each version (already eager-loadable; see "Data access")
        │
        ▼
structured_diff.diff_articles(articles_a, articles_b)
        │  delegates to:
        ▼
structural_diff.diff_versions(articles_a, articles_b)
        │
        │  1. match articles by .label
        │  2. for each pair: compare text_clean + structural diff
        │  3. for unmatched leftovers: greedy text-similarity pairing
        │  4. anything still leftover → added or removed
        │
        ▼
DiffResult (new hierarchical shape)
        │
        ▼
serialized as JSON, returned to frontend
        │
        ▼
frontend/src/app/laws/[id]/diff/page.tsx renders
```

## The matching algorithm

### Step 1 — Article matching

Input: `articles_a: list[Article]`, `articles_b: list[Article]`.

Build two label-keyed dicts:

```python
by_label_a = {a.label or a.article_number: a for a in articles_a}
by_label_b = {a.label or a.article_number: a for a in articles_b}
```

Iterate `by_label_a.items()`. For every `(label, art_a)`:

- If `label in by_label_b`: matched pair `(art_a, by_label_b[label])`. Mark both as consumed.
- Else: `art_a` is a leftover from A.

Iterate `by_label_b` and collect anything not already consumed: leftovers from B.

### Step 2 — Renumbering pairing on leftovers

The leftover pools from A and B may contain articles that were renumbered (so labels don't match) or actually added/removed. We pair them by content similarity, exactly like the existing `_pair_renumbered` helper does today. Move the helper into `diff_renumbering.py` and use `text_clean` rather than `full_text` so the inline annotations don't pollute the similarity score.

The pairing rule is greedy: for each leftover article in A, find the leftover in B with the highest `SequenceMatcher.ratio()` over `text_clean`. Pair them if the ratio is ≥ a threshold (start at 0.85, the same as today; tune if real data shows it's wrong). Mark both as consumed. Anything left after that is either an added or a removed article — deterministic.

### Step 3 — Article-level diff

For each matched article pair (whether by label or by renumbering):

- Compare `art_a.text_clean` to `art_b.text_clean`. If identical → article is **unchanged** (skip the paragraph walk; emit a single "unchanged" entry that the frontend can render as a one-line "Art. X — no changes").
- Otherwise: walk paragraphs.

For unmatched articles:

- A-only → **removed**. Render the article body from `text_clean(A)` with red highlight.
- B-only → **added**. Render from `text_clean(B)` with green highlight.

### Step 4 — Paragraph matching within a matched article

Same algorithm, one level down:

- Build `by_label_a` and `by_label_b` keyed on `paragraph.label`. Match by exact label.
- Leftovers: greedy text-similarity pairing (`diff_renumbering.greedy_pair_by_text_ratio`), threshold 0.85, on `text_clean`.
- Anything still unmatched is added (B-only) or removed (A-only).

### Step 5 — Paragraph-level diff

For each matched paragraph pair:

- `text_clean(A) == text_clean(B)` → **unchanged**.
- Otherwise → **modified**. Compute word-level diff via `difflib` and emit an HTML string with `<del>` / `<ins>` spans (the existing `word_diff_html` function from `structured_diff.py:20` is fine — move it into `structural_diff.py`).
- Attach **enrichment metadata**: collect any `amendment_notes` rows from B that have `paragraph_id == this paragraph` and serialize the relevant fields (date, law_number, monitor_number, monitor_date, subject). These appear next to the paragraph in the API response so the frontend can render the citation. They are *informational only*; they do not change the state.

For unmatched paragraphs:

- A-only → **removed**, render `text_clean(A)`.
- B-only → **added**, render `text_clean(B)`. Attach any notes from B with this paragraph_id as enrichment.

### What the matcher does NOT do

- It does not re-tokenize the article body. The existing `article_tokenizer.py` is no longer called.
- It does not match below the paragraph level. Literae are part of the paragraph's text and are rendered as part of `text_clean`. When a single literă changes, the word-level highlight inside the paragraph diff is what calls it out — there is no separate literă matching pass. (This was Q2 in brainstorming; the user picked "all literae visible inside the modified paragraph", which this approach delivers naturally.)
- It does not look at `Subparagraph` rows. They remain in the DB for the article-detail view, but the diff layer ignores them.
- It does not run any text comparison on `Article.full_text` or `Paragraph.text` (the un-cleaned versions). Everything is on `text_clean`.

## API contract

The endpoint URL and query parameters are unchanged. The response shape changes to:

```typescript
interface DiffResult {
  law_id: number;
  version_a: { id: number; ver_id: string; date_in_force: string | null };
  version_b: { id: number; ver_id: string; date_in_force: string | null };
  summary: {
    added: number;       // count of added articles
    removed: number;     // count of removed articles
    modified: number;    // count of modified articles
    unchanged: number;   // count of unchanged articles
  };
  articles: DiffArticleEntry[];   // RENAMED from `changes`
}

interface DiffArticleEntry {
  article_label: string;            // e.g. "336", "1^2"
  change_type: "added" | "removed" | "modified" | "unchanged";
  renumbered_from: string | null;   // set when paired by text similarity, not label
  // Present when change_type === "added" or "removed":
  text_clean?: string;
  // Present when change_type === "modified":
  paragraphs?: DiffParagraphEntry[];
  // Always present (may be empty): article-level amendment notes
  // (paragraph_id IS NULL) attached to this article in version B.
  notes: AmendmentNoteRef[];
}

interface DiffParagraphEntry {
  paragraph_label: string | null;   // e.g. "(1)", "(2^1)", or null for the article intro
  change_type: "added" | "removed" | "modified" | "unchanged";
  renumbered_from: string | null;
  // Present for "added" or "removed":
  text_clean?: string;
  // Present for "modified":
  text_clean_a?: string;            // pre-diff cleaned text
  text_clean_b?: string;            // post-diff cleaned text
  diff_html?: string;               // <del>/<ins> highlighted version of text_clean_b
  // Always present (may be empty):
  notes: AmendmentNoteRef[];        // enrichment from version B
}

interface AmendmentNoteRef {
  date: string | null;              // "31-03-2026"
  subject: string | null;           // "Alineatul (1) al articolului 336"
  law_number: string | null;        // "89"
  law_date: string | null;          // "23-12-2025"
  monitor_number: string | null;    // "1203"
  monitor_date: string | null;      // "24-12-2025"
}
```

### What's gone from the old shape

- `DiffUnit` (the flat AtomicUnit-shaped thing) is removed entirely.
- `DiffArticle.units` is removed.
- `DiffArticle.text_a` / `text_b` / `diff_html` (the article-level fallbacks) are removed; word-level diffs only happen at the paragraph level now.
- `changes` is renamed to `articles` for clarity.

### What's new

- `DiffArticleEntry.paragraphs` — the new hierarchy.
- `DiffParagraphEntry.notes` — the enrichment list.
- `text_clean_a` / `text_clean_b` / `diff_html` move from the article level to the paragraph level.
- `paragraph_label` is the matching key, exposed on the wire so the frontend can render it.

### Backwards compatibility

There is none. The old shape is removed entirely. The router test `test_diff_endpoint.py` is rewritten to assert against the new shape. The frontend page is updated in the same PR so the user never sees a broken state.

This is fine because (a) the diff endpoint has exactly one consumer (the diff page), (b) the old shape was internal, and (c) no third-party integration depends on it.

## Frontend rendering (minimal)

`frontend/src/app/laws/[id]/diff/page.tsx` is rewritten to render the new shape with the simplest possible markup. The structure:

```
For each article in articles:
  Render an article card with the label and the change_type badge.
  If change_type === "unchanged":
    One line: "No changes."
  If change_type === "added":
    Render text_clean wrapped in a green-background block.
  If change_type === "removed":
    Render text_clean wrapped in a red-background block, line-through.
  If change_type === "modified":
    For each paragraph in paragraphs:
      Render the paragraph_label (or "intro" if null).
      If change_type === "unchanged":
        Render text_clean (we need to fetch it; see "Data access" below).
      If change_type === "added":
        Render text_clean in green.
      If change_type === "removed":
        Render text_clean in red strikethrough.
      If change_type === "modified":
        Render diff_html (the HTML with <del>/<ins> spans), styled with background colors.
      If notes is non-empty:
        Render a small "modified by …" line below with the date + law number.
```

No collapsibles, no navigation, no nesting beyond article → paragraph. The CSS uses simple background colors (green/red/yellow). The components `structured-diff-article.tsx`, `diff-leaf.tsx`, `collapsed-run.tsx` from the current page are deleted; the rewrite is small enough to live inside `page.tsx` without sub-components, which is intentional (Spec 3 will reintroduce sub-components when the affordances justify them).

### One UX gotcha to handle

Per the user's locked-in answer to Q2, **all literae must be visible inside a modified paragraph**, not just the changed ones. Because we treat the whole paragraph as a single diff target and run word-level `difflib` on the full `text_clean` (which includes all literae concatenated), this falls out naturally — the diff_html string contains every literă in document order, with `<del>` / `<ins>` spans wherever the text differs. The frontend just renders the HTML as a block. No special logic for "show all literae" because they're already there.

## Data access

The router currently loads `Article` rows and passes them into `diff_articles`. For the new matcher to work, each `Article` needs its `paragraphs` collection eager-loaded with the `text_clean` column populated, and each `Paragraph` needs its `amendment_notes` collection eager-loaded. The router handler should use `joinedload` or `selectinload` to avoid N+1 queries:

```python
articles_q = (
    db.query(Article)
    .filter(Article.law_version_id == version.id)
    .options(
        selectinload(Article.paragraphs).selectinload(Paragraph.amendment_notes)
    )
    .order_by(Article.order_index)
)
```

For an "unchanged" paragraph in a modified article, we still need its `text_clean` so the frontend can render it as context. The matcher should populate `text_clean` on every emitted `DiffParagraphEntry` regardless of state — no optional/missing fields for unchanged rows.

## Renumbering and edge cases

### Articles renumbered

Handled by Step 2. The `renumbered_from` field on `DiffArticleEntry` carries the old label so the UI can show "Art. 24 (was 23)".

### Paragraphs renumbered

Same algorithm at the paragraph level. The `renumbered_from` field on `DiffParagraphEntry` carries the old label.

### Article that exists in A but is "Abrogat" (repealed) in B

`Article.is_abrogated` is true on the B side. The matcher sees this as a normal pair: text differs (A has substantive content, B has just "Abrogat"), so it emits a "modified" entry. The frontend can show this naturally — one big strikethrough on the A side and a single "Abrogat." line on the B side. No special-case code needed.

### A paragraph with no `text_clean` (NULL)

This can happen for rows imported before Spec 1 if the backfill missed them (parser drift, label collision). The matcher falls back to `paragraph.text` for that row only and logs a warning. This guarantees we never crash on a NULL, and the `text_clean is null` case decays gracefully into the slightly-noisier old behaviour.

### An article with no paragraphs

Some articles in the parser output have no paragraph rows — the entire article body lives in `Article.full_text` only. For these, the matcher emits **a single synthetic `DiffParagraphEntry`** with `paragraph_label = null`, `text_clean_a = art_a.text_clean`, `text_clean_b = art_b.text_clean`, and `diff_html` computed by `word_diff_html` over those two strings. This keeps the rendering path uniform — the frontend always renders `paragraphs[]` and never has to deal with article-level `text_a`/`text_b`/`diff_html` fields. The synthetic paragraph is the only place where word-level diff runs over what is effectively a whole article body, and it only happens for articles that genuinely have no paragraph structure.

### Two paragraphs in the same article share the same label

This is the bug from insolvency law art. 5 that broke the old matcher. With label-keyed matching, building `by_label_a[label] = par` overwrites earlier entries with the same key — same failure mode. Fix: instead of a dict, use a list of `(label, paragraph)` tuples and pair them positionally within the same label group, then text-similarity-pair any leftovers. The implementation detail belongs in the implementation plan (Spec 2's plan doc), not here, but the design must acknowledge that "label is unique within an article" is not a safe assumption for legacy / pathological cases.

### Notes attached to articles, not paragraphs

Spec 1 stores both kinds. Article-level notes (with `paragraph_id IS NULL`) are surfaced at the article level in the response — a new `notes` field on `DiffArticleEntry`. They appear above the paragraphs in the rendered article card.

## Testing

### Unit tests (`backend/tests/test_structural_diff.py`)

Pure tests against constructed `Article` / `Paragraph` / `AmendmentNote` objects (no DB):

- `test_identical_versions_produce_no_changes` — same articles in both, all `unchanged`.
- `test_modified_paragraph_with_word_level_highlight` — text_clean differs by one word; assert the diff_html contains `<del>` and `<ins>` spans around exactly that word.
- `test_paragraph_added_in_b` — A has no paragraph (1), B has it; assert `change_type == "added"` and `text_clean` is from B.
- `test_paragraph_removed_in_a` — symmetric.
- `test_article_renumbered` — A has art 23, B has art 24 with the same text; assert one matched pair with `renumbered_from == "23"` and `change_type == "unchanged"` (or "modified" if any tiny diff).
- `test_paragraph_renumbered_within_article` — A paragraph (1) becomes (2) in B; assert pairing.
- `test_two_paragraphs_share_label` — pathological case from insolvency art. 5; assert no over-pairing, both A versions matched to both B versions, no fake modifications.
- `test_inline_annotation_does_not_affect_state` — A has paragraph X with no inline annotation, B has the same paragraph but with `(la 31-03-2026, … a fost modificat)` appended in `text` (not `text_clean`); assert `change_type == "unchanged"` because `text_clean` is identical.
- `test_amendment_note_surfaces_as_enrichment` — modified paragraph, B has one note attached; assert the response contains the note's date / law_number / etc. in `notes`.
- `test_abrogated_article` — A has full content, B has `text_clean == "Abrogat."`, assert `change_type == "modified"`.

### Integration test (`backend/tests/test_diff_endpoint.py`)

Rewrite the existing endpoint test to seed two `LawVersion` rows with realistic articles + paragraphs + a paragraph-level amendment note, hit `GET /api/laws/{id}/diff?version_a=&version_b=`, and assert against the new response shape. One test for the success path, one for the 404-when-versions-missing path (which already exists; just update its expected status assertions if needed).

### Manual smoke test

After the local backend changes are in:

1. Open `/laws/<id>/diff?a=<verA>&b=<verB>` for the same Codul Insolventei article 5 / 23 case the user screenshotted.
2. Confirm: no inline `(la …)` strikethroughs, every paragraph (1)/(2)/… is its own row, the modified ones have clean word-level highlights, the unchanged ones say "no changes" or render the body in gray.

## Rollout

Single PR sequence, in order:

1. **Backend new diff** — new `structural_diff.py`, new `diff_renumbering.py`, edited `structured_diff.py` (pure delegation), updated router for eager loading, rewritten `tests/test_structural_diff.py` (new file) and `tests/test_diff_endpoint.py` (rewritten). The old `article_tokenizer.py` stays in the tree (still used by the article-detail view? verify; if not, it can be deleted in a follow-up).
2. **Frontend rewrite of `page.tsx`** — new types in `api.ts`, rewritten page component, deletion of the now-unused `structured-diff-article.tsx` / `diff-leaf.tsx` / `collapsed-run.tsx`.
3. **Manual verification on local** — diff a few real laws, eyeball the output.
4. **Push to production.** No migration, no backfill, no schema change. The data Spec 2 needs is already in the prod DB once the prod backfill from Spec 1 finishes.

Spec 2 has no infra step. No Railway dashboard work. No volume mounts.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| The label-uniqueness assumption breaks on pathological articles | Use list-of-tuples + positional pairing within label groups, not a dict |
| `text_clean` is NULL on some rows (Spec 1 backfill missed them) | Fall back to `paragraph.text` per-row with a warning log; never crash |
| Renumbering similarity threshold (0.85) is wrong for some laws | Same threshold the current code uses; tune based on real data after first run |
| Large law (e.g. Codul Fiscal) is slow to diff | Operations are pure Python on already-loaded rows; no I/O, no parser. ~hundreds of articles × ~tens of paragraphs is sub-second on Codul Fiscal-scale documents. If it's slow, profile and add per-article memoization later — not pre-optimized |
| Inline annotations creep back into `text_clean` for some rows | The cleaner is conservative; a row with malformed annotations gets returned unchanged rather than mangled. The diff layer doesn't know or care — it operates on whatever `text_clean` says |
| Frontend breaks because it's coupled to the old shape | Same PR replaces both ends; no half-deployed state |
| The diff endpoint test that exists today is brittle | Rewrite it from scratch in the same PR; it currently asserts against the old `units` shape that no longer exists |
| Deleting `article_tokenizer.py` breaks something else | Verify it's not imported elsewhere before deleting; otherwise leave it in place and just stop calling it from the diff path |

## Open questions

- **What does the diff page's article-detail view do with subparagraphs?** The current page renders `Subparagraph` rows in the article detail view (not the diff). That code path is untouched by Spec 2. But if `article_tokenizer.py` is also used by that view, deletion is blocked — verify.
- **Are EU laws in scope for the diff at all today?** If a user tries to diff two versions of an EU law, what does the current backend do? If it just returns empty, no change needed. If it tries to diff and fails, we might want to add a guard at the router. Verify during implementation, fix if it breaks.
- **Where do article-level notes render in the page?** The spec says "above the paragraphs in the rendered article card", which is a Spec 3 polish detail. For Spec 2's minimal render, we can put them directly under the article header as a flat list and call it good.
