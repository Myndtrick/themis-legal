# Structured Version Diff

**Date:** 2026-04-07
**Status:** Draft

## Problem

The current `/laws/{id}/diff?a=&b=` view (`frontend/src/app/laws/[id]/diff/page.tsx`) is unreadable. Users cannot see what actually changed between two versions of a law:

- The backend (`backend/app/routers/laws.py:1478` `diff_versions`, `:1590` `_word_diff`) compares articles by `Article.full_text` — a flattened string containing the entire article (all alineate, litere, points, amendment notes) mashed together. It runs `difflib.SequenceMatcher` over the words and returns one giant `<ins>`/`<del>` HTML blob per article.
- The frontend renders that blob via `dangerouslySetInnerHTML`. There is no article structure (`(1)`, `a)`, `b^1)`), no indentation, and the few changed words sit inside a wall of unchanged text that is repeated for the whole article.
- The same article rendered through the regular version view (`paragraph-renderer.tsx`) is clean and structured because that view consumes the parsed `Paragraph` / `Subparagraph` rows. The diff view throws those rows away.

The structural information is already in the database — it's produced by the leropa parser at import time. The diff endpoint just needs to use it.

## Goals

- A version-comparison view that uses the same structural rendering as the normal version view: article header → `(1)`, `(2)` alineate → `a)`, `b)` litere → numbered points, with the same labels, indentation, and font.
- Unchanged leaves are hidden by default. Runs of consecutive unchanged leaves under a paragraph collapse to one dashed `… litere a)–j) — unchanged [show]` line that can be expanded in place.
- Each modified leaf is shown in full with its label and surrounding structural context, with inline word-level red/green highlighting.
- Added leaves render in green with a "New" badge; removed leaves render struck-through in red.
- The article header is clickable: clicking it expands the entire article (changed and unchanged leaves) so the user can read the full updated text in context.
- Pure additions and deletions of labels (e.g. new litera `e^1)`, abrogated litera `g)`) are detected correctly via label matching.
- Renumbering — where labels shift because an earlier sibling was removed — is recognized as a single removal rather than a cluster of fake modifications, via a similarity-pairing fallback.

## Non-goals

- No changes to import or parsing. The leropa parser already produces the structure we need.
- No changes to the article-level summary counts shown on the law detail page (`backend/app/services/diff_summary.py`).
- No syntax-aware or semantic diff. Word-level `difflib` at the leaf level is sufficient.
- No diff history, no per-user diff preferences, no exports.

## How changes are detected

Diffing is structural and runs at request time on the parsed rows already stored in the database. The leropa parser is **not** re-invoked.

### Article matching

Articles are matched across versions by `Article.article_number` (this is the existing key). For each article number present in either side:

- In A only → article-level `removed`.
- In B only → article-level `added`.
- In both with byte-identical `full_text` → article-level `unchanged` (skipped from the response payload as today).
- In both with different text → recurse into paragraph-level diffing; the article's `change_type` becomes `modified` if any descendant leaf differs.

### Paragraph and subparagraph matching

Within a `modified` article:

1. Build a map of paragraphs by `Paragraph.label` (e.g. `(1)`, `(2)`, `(4^1)`). Paragraphs without a label (preamble lines, intros) are matched by position among the unlabeled set.
2. For each label present in either side:
   - In A only → leaf marked `removed`.
   - In B only → leaf marked `added`.
   - In both → recurse into the subparagraph map (`Subparagraph.label` — `a)`, `b^1)`, `1.`, `-`).
3. The actual leaf is the lowest level that has text: a subparagraph if the paragraph has children, otherwise the paragraph itself. A paragraph is also a leaf if it carries an intro line above its subparagraphs (compared as its own diff entry).

### Leaf comparison

For each matched leaf:

- If `text_a.strip() == text_b.strip()` → `unchanged`.
- Otherwise → `modified`. Compute word-level `<ins>`/`<del>` HTML by running the existing `_word_diff` logic on the **leaf text only** (not the full article). The HTML stays small and the highlighting is precise.

### Renumbering fallback

After label-matching produces the leaf list for a paragraph (or for the article level), pair stray adds/removes that look like the same content shifted by a label change:

- Collect all leaves in this paragraph marked `added` and all leaves marked `removed`.
- For each `(removed_leaf, added_leaf)` pair, compute `difflib.SequenceMatcher(None, removed.text, added.text).ratio()`.
- If the best pair has ratio ≥ 0.85, replace the two entries with a single `modified` leaf whose label is rendered as `{new_label} (was {old_label})`. Compute its `diff_html` from the two texts.
- Repeat greedily on the next-best pair until no pair clears the threshold.

The same pairing runs at the article level so a renumbered article (`Art. 73 → Art. 74`) appears as one `modified` card with `Art. 74 (was Art. 73)` rather than one removal + one addition.

The threshold (0.85) is conservative on purpose: in the common case (genuine inserts of `e^1)`, abrogated `g)`) the texts are unrelated and the heuristic does nothing. It only fires on the rare true-renumbering case.

## API shape

`GET /laws/{law_id}/diff?a={version_a}&b={version_b}` keeps its envelope but the `changes[*]` entries become a tree.

```jsonc
{
  "law_id": 24,
  "version_a": { "id": 331, "ver_id": "...", "date_in_force": "2025-08-01" },
  "version_b": { "id": 519, "ver_id": "...", "date_in_force": "2026-03-01" },
  "summary": { "modified": 12, "added": 0, "removed": 0, "unchanged": 218 },
  "changes": [
    {
      "article_number": "62",
      "change_type": "modified",
      "title": "Venituri neimpozabile",
      "citation": "Capitolul I, Titlul IV",
      "renumbered_from": null,
      "paragraphs": [
        {
          "label": "(1)",
          "change_type": "modified",
          "text_a": null,
          "text_b": null,
          "diff_html": null,
          "subparagraphs": [
            { "label": "a)", "change_type": "unchanged" },
            { "label": "b)", "change_type": "unchanged" },
            // ... j) ...
            {
              "label": "k)",
              "change_type": "modified",
              "text_a": "...old text...",
              "text_b": "...new text...",
              "diff_html": "...<del>inclusiv cele</del> din fonduri de pensii <del>facultative</del> <ins>facultative, din fonduri de pensii ocupaționale</ins>...",
              "renumbered_from": null
            },
            // ... l)–z) ...
          ]
        }
      ]
    }
  ]
}
```

Rules for the payload:

- `unchanged` leaves carry only `label` and `change_type`. `text_a`, `text_b`, `diff_html`, and any nested `subparagraphs` are omitted to keep the response small.
- `added` leaves carry `text_b` only; `removed` leaves carry `text_a` only.
- `modified` leaves carry both texts and `diff_html`.
- `renumbered_from` is `null` unless the renumbering fallback paired two leaves; then it holds the old label string (e.g. `"c)"`).
- Articles that are fully `unchanged` are still excluded from the response (matches today's behavior).

## Frontend

A new component, `StructuredDiffArticle`, replaces the current `dangerouslySetInnerHTML` rendering inside `frontend/src/app/laws/[id]/diff/page.tsx`. It lives next to the existing version-view components at `frontend/src/app/laws/[id]/diff/components/structured-diff-article.tsx`. A few small leaf renderers (`DiffParagraphLeaf`, `DiffSubparagraphLeaf`, `CollapsedRun`) live in the same directory.

These components reuse the layout primitives from `paragraph-renderer.tsx` (label/text flex layout, `renderLabel` superscript helper, abrogat handling). The shared bits are extracted into a small `paragraph-layout.tsx` module so both the normal version view and the diff view use the same JSX shape — guaranteeing visual parity. The existing `paragraph-renderer.tsx` keeps its public API.

### Article card

```
┌──────────────────────────────────────────────────────┐
│ Art. 62 — Venituri neimpozabile      [Modified]      │  ← clickable header
│ Capitolul I, Titlul IV                               │
├──────────────────────────────────────────────────────┤
│ … alineatul (1), literele a)–j) — unchanged [show]  │
│                                                      │
│   k)  pensiile pentru invalizii de război, ...      │
│       ... <del>inclusiv cele</del> ...               │
│       ... <ins>facultative, din fonduri ...</ins>    │
│                                                      │
│ … litere l)–z) — unchanged [show]                    │
└──────────────────────────────────────────────────────┘
```

### Behavior

- The whole article header is a button. Clicking it toggles **"full article" mode**: every leaf in the tree (changed and unchanged) renders in full, with no collapse markers. Clicking again collapses back to changes-only.
- In the default (changes-only) view, runs of consecutive unchanged leaves under a paragraph are merged into a single `CollapsedRun` line: `… litere a)–j) — unchanged [show]`. The label range comes from the first and last unchanged leaf in the run. Clicking `show` expands that run in place (independent of full-article mode) and renders the full text of every leaf inside it.
- A paragraph that contains only unchanged subparagraphs but is itself part of a modified article is replaced by a single `… alineatul (1) — unchanged [show]` line.
- Modified leaves render with the same flex layout as the normal renderer: monospace label on the left, body text on the right. The `diff_html` is injected into the body via `dangerouslySetInnerHTML` (the HTML is server-built from text we control, so no XSS surface).
- Added leaves render the full `text_b` with a small green `New` badge next to the label and a `bg-green-50/text-green-800` body style. The whole text is wrapped in `<ins>` so the inline highlighting matches the rest of the page.
- Removed leaves render the full `text_a` struck-through with a `bg-red-50/text-red-800` body style.
- Renumbered leaves render their new label with `(was {old_label})` in muted gray next to it. The body uses the same modified styling.
- Whole `added` / `removed` articles get their own card (no header click target since there are no unchanged leaves to expand). Renumbered articles render normally with `Art. 74 (was Art. 73)` as the title.

### Styling

`<ins>` and `<del>` styles live in a shared CSS rule in `frontend/src/app/laws/[id]/diff/diff.css` (or the existing `diff-content` rule moved there):

```css
.diff-content ins { background:#d1fae5; color:#065f46; text-decoration:none; padding:0 2px; border-radius:2px; }
.diff-content del { background:#fee2e2; color:#991b1b; text-decoration:line-through; padding:0 2px; border-radius:2px; }
```

The summary cards at the top of the diff page (`Modified / Added / Removed / Unchanged` counts) and the version date pills are unchanged.

## Testing

Backend (`backend/tests/test_diff.py`, new file):

- Two versions of an article that differ in one litera → response has one paragraph with one `modified` subparagraph and the rest `unchanged`; `diff_html` contains the changed words only.
- A litera added in B → `added` leaf with `text_b`, no `text_a`.
- A litera abrogated in B (text becomes `Abrogat.`) → `modified` leaf with both texts.
- An article removed entirely → article-level `removed`, no paragraph tree.
- Renumbering: paragraph A has `a)`, `b)`, `c)`; paragraph B has `a)`, `b)` where new `b)` text is the old `c)` text. Result: `b)` (was `c)`) modified, `b)` (the original) removed. Verify the similarity threshold by also testing the negative case where the new `b)` is unrelated text — it must stay as one add + one remove.
- Whole article renumbered (`Art. 73 → Art. 74`).
- A version pair with no differences → empty `changes` array.

Frontend: rely on visual review against the mockup at `.superpowers/brainstorm/78790-1775569962/content/diff-mockup.html`. No test framework changes.

## Out of scope

- Changing the parser, the import pipeline, or the database schema.
- Changing how `diff_summary` counts are computed for the version list.
- Server-side caching of computed diffs. Diffs are computed on demand; payload size is small enough now that this is fine.
- Diffing across laws (only same-law version pairs).
- Any UI for choosing the diff strategy or threshold.
