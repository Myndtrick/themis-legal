# Version Diff Redesign — Tokenizer-Based Matching

**Date:** 2026-04-07
**Status:** Draft
**Supersedes (partial):** `2026-04-07-structured-version-diff-design.md`

## Problem

The structured-version-diff that shipped on this branch (`fix/version-discovery-dead-state`) renders incorrect and unreadable diffs for any article whose parsed tree is irregular. The two visible failure modes, both reproducible on `/laws/5/diff?a=517&b=529` (Romanian insolvency law, art 5 — Definiții):

1. **Wrong matching.** Article 5 §(1) has 67 (v517) / 73 (v529) flat subparagraph rows, with 17+ different subparagraphs sharing each of `a)`, `b)`, `c)`. `_diff_subparagraphs` builds `map_a[label] = sub` so only the **last** sub per label survives, then pairs every `"a)"` in B with the same single `"a)"` from A. The result is a stream of fake `modified` leaves comparing unrelated definitions.
2. **Giant text blob.** The parser stores `Paragraph.text` for art 5 §(1) as a 28 000-character concatenation of the intro line plus all 75 numbered definitions. When that text differs between versions, `diff_paragraph` runs `word_diff_html` over the whole 28 k-char blob, ships it as `diff_html`, and the frontend renders it inline as one wall of text with a single tiny green highlight.

Both bugs trace to the same root: the diff layer trusts the parsed `Paragraph` / `Subparagraph` rows, and those rows are unreliable. For art 5 the children are not even substrings of `Paragraph.text` — they are two parallel-but-disjoint representations from different parser passes. Patching the diff layer to handle this case is possible but the next pathological article will break it again.

## Goal

Stop trusting the parsed tree for diffing. Re-tokenize each article from `Article.full_text` at diff time using a small, testable Romanian-legal-text tokenizer that produces **atomic units** keyed by their hierarchical path. Match by path; pair leftovers by content similarity. Render the result as inline track-changes with collapsible unchanged runs (display style A from brainstorming).

The tokenizer is the only place that needs to be correct, it is pure (no DB), it is unit-testable in isolation, it is decoupled from parser quality, and it makes every leaf uniquely addressable so duplicate-label collisions become impossible.

## Non-goals

- No parser changes. The leropa parser still produces `Article` / `Paragraph` / `Subparagraph` rows for the regular version view; this work only changes how the diff endpoint reads from them.
- No DB schema changes, no migrations, no re-import.
- No diff caching, exports, history, or cross-law diffs.
- No new diff endpoints. `/laws/{id}/diff?a=&b=` keeps its URL and outer envelope.
- No new frontend test framework. Visual review against mockups, matching existing convention.

## Architecture

Two backend modules in `backend/app/services/`:

```
article_tokenizer.py     NEW — pure: full_text → list[AtomicUnit]
structured_diff.py       REWRITE — tokenizer-based path matching, drops paragraph-row matching
```

`article_tokenizer.py` is pure: it takes a string and returns dataclasses. No SQLAlchemy imports, no DB session. That makes it trivial to test against fixtures and impossible to accidentally couple to the rest of the app.

`structured_diff.py` keeps its top-level entry point `diff_articles(articles_a, articles_b)` so `backend/app/routers/laws.py:1494 diff_versions` does not change. Internally everything below that signature is rewritten. The old `diff_paragraph`, `diff_article`, `_diff_subparagraphs`, `_diff_paragraphs_list` are deleted; the renumbering helper `_pair_renumbered` is kept and reused for unit-level pairing.

A safety net keeps the page resilient: if `tokenize_article()` raises on either side of an article pair, that one article falls back to a single coarse `modified` entry with `diff_html` computed via `word_diff_html(full_text_a, full_text_b)` over the whole article, logged as a warning. The diff page never crashes because of one weird article.

Frontend updates live under `frontend/src/app/laws/[id]/diff/`. The existing components (`StructuredDiffArticle`, `DiffParagraphLeaf`, `DiffSubparagraphLeaf`, `CollapsedRun`) are reshaped to render an arbitrary-depth path tree instead of the fixed paragraph→subparagraph hierarchy. The CSS, the article-card layout, the "show full article" toggle, and the collapsed-run interaction stay.

## The tokenizer

`tokenize_article(full_text: str) -> list[AtomicUnit]` walks the article text, tracks a hierarchical context stack of the current alineat / numbered point / litera, and emits one `AtomicUnit` per leaf segment.

```python
@dataclass(frozen=True)
class AtomicUnit:
    path: tuple[str, ...]   # ("(1)", "11.", "a)") — full hierarchical location
    text: str               # the leaf body, with the marker prefix stripped
    marker_kind: str        # "alineat" | "numbered" | "litera" | "bullet" | "intro"
```

### Marker recognition

A ranked list of regexes; the first that matches at a segment boundary wins. Each kind has a fixed depth in the context stack (alineat = 1, numbered = 2, litera = 3, bullet = 4). When a marker fires, the stack is popped to its depth and the new marker is pushed.

| Kind     | Depth | Pattern (anchored to segment start, after whitespace) | Examples       |
|----------|-------|--------------------------------------------------------|----------------|
| alineat  | 1     | `\(\s*(\d+(?:\^\d+)?)\s*\)`                            | `(1)`, `(4^1)` |
| numbered | 2     | `(?<![\w\^])(\d+(?:\^\d+)?)\.`                         | `32.`, `42^2.` |
| litera   | 3     | `\b([a-z](?:\^\d+)?)\)`                                | `a)`, `d^1)`   |
| bullet   | 4     | `^[–-]\s`                                              | `–`            |

The negative-lookbehind on `numbered` (`(?<![\w\^])`) prevents `art. 125` from being eaten as a numbered point. Bullet-as-fourth-level only fires when the line literally starts with an en-dash + space; ASCII hyphen-space is also accepted because the parser is inconsistent.

### Segmentation

The current parsed text uses `...` (literal three-dot ellipsis) as a soft separator between definitions and `;` as a hard separator between litere. The tokenizer splits on ellipsis, semicolon, and newline, then re-runs marker recognition on each segment. Whitespace is normalized (collapsed runs of spaces, leading/trailing strip) before recognition. Empty segments are dropped.

If a segment has **no leading marker**, it is treated as a continuation of the previous unit and its text is appended (with a single space) to the previous unit's text. This handles wrapped sentences and embedded notes (`Notă...`, `Decizie de admitere:...`) without spawning fake leaves.

### Intro leaves

The first segment of an alineat is its **intro line** — the lead-in sentence above its children, e.g. `În înțelesul prezentei legi, termenii și expresiile au următoarele semnificații:`. It is emitted as its own atomic unit with `marker_kind="intro"` and `path=("(1)", "intro")`. This makes legitimate intro changes diffable as one small inline edit, while keeping the body content out of the intro text. An alineat with no children at all is still emitted as a single intro unit at `("(1)", "intro")`.

An article with **no alineat markers at all** (a flat one-sentence article) is emitted as a single atomic unit with `path=("intro",)` and `marker_kind="intro"`. The frontend treats `path[0] == "intro"` as a special "no alineat" group with no breadcrumb prefix.

### Why paths solve the duplicate-label bug

Today, 17 different `a)` rows for art 5 §(1) collide in one dict because they share a label. With paths, every leaf is uniquely addressed: `("(1)", "11.", "a)")`, `("(1)", "12.", "a)")`, `("(1)", "13.", "a)")`, … Path-based matching has no collisions by construction. The `(1) · 11. · a)` breadcrumb in the rendered output also tells the user *which* numbered point they're looking at, which the current UI can't show.

### Tokenizer testing

`backend/tests/fixtures/tokenizer/` holds snapshot fixtures: each test case is a `<name>.txt` with raw `Article.full_text` plus a `<name>.expected.json` with the expected `list[AtomicUnit]` (path, text, marker_kind). The test parameterizes over the directory.

Initial fixture set:

- `art5-definitions.txt` — the pathological case (alineat with intro + many numbered + nested litere, with `^N` markers, abrogat entries, and embedded notes).
- `art7-simple.txt` — a normal article with two short alineate.
- `art-with-bullets.txt` — litere whose body has en-dash bullet sub-items.
- `art-abrogat.txt` — an article whose only content is `Abrogat.`.
- `art-no-alineate.txt` — an article that is one flat sentence with no markers.
- `art-renumbered-marker.txt` — an article using `^1` markers at all three levels in one block.

Plus targeted unit tests for each marker kind, the negative lookbehind on `numbered` (must not eat `art. 125`), continuation segments, intro emission, and whitespace normalization.

## Diff algorithm

`diff_articles(articles_a, articles_b)` (signature unchanged):

1. **Article matching** — by `Article.article_number`, identical to today.
   - In one side only → article-level `added` / `removed`. The article's text is shipped whole (no unit tree).
   - In both sides → tokenize both, run the unit-level diff below.
   - If the resulting unit list has zero non-`unchanged` entries, the article is excluded from the response (matches today's behavior).
2. **Renumbered articles** — `_pair_renumbered` is kept and runs on the article-level leftovers, same threshold (0.85), same `(was Art. 73)` rendering.
3. **Unit-level diff** for each matched article pair:

```python
units_a = tokenize_article(article_a.full_text)
units_b = tokenize_article(article_b.full_text)

by_path_a = {u.path: u for u in units_a}
by_path_b = {u.path: u for u in units_b}

leaves: list[dict] = []
unmatched_a, unmatched_b = [], []

for path in set(by_path_a) | set(by_path_b):
    a, b = by_path_a.get(path), by_path_b.get(path)
    if a and b:
        if a.text.strip() == b.text.strip():
            leaves.append(unchanged_leaf(a))
        else:
            leaves.append(modified_leaf(a, b))
    elif a:
        unmatched_a.append(a)
    else:
        unmatched_b.append(b)

# Phase 2: greedy similarity pairing for renumbered units
for r, ad in greedy_pair_units(unmatched_a, unmatched_b, threshold=0.85):
    leaves.append(renumbered_leaf(r, ad))

# Anything still unmatched is a real add or remove
for u in remaining(unmatched_a): leaves.append(removed_leaf(u))
for u in remaining(unmatched_b): leaves.append(added_leaf(u))

# Sort: present in B's path order, with removed-only units inserted after their nearest neighbor
leaves.sort(key=presentation_order(units_b))
```

The greedy pairing reuses the existing `_pair_renumbered` logic (same threshold, same algorithm) applied to atomic units instead of articles. Threshold of 0.85 is conservative on purpose: in the common insertion case (a new `42^2.` definition), nothing gets paired against it and it correctly becomes `added`.

Path matching is O(n). Similarity pairing is O(leftover²) where leftover is typically <10 even for the worst article, so it is effectively free. Tokenization itself is single-pass linear in `len(full_text)`. Total for art 5 (~38 k chars) should stay well under 100 ms.

## API shape

`GET /laws/{law_id}/diff?a={version_a}&b={version_b}` keeps its envelope. The `version_a`, `version_b`, and `summary` blocks are unchanged. Each entry in `changes[*]` becomes:

```jsonc
{
  "article_number": "5",
  "change_type": "modified",                   // "modified" | "added" | "removed"
  "title": "Definiții",
  "renumbered_from": null,                      // article-level renumber, unchanged from today
  "units": [                                    // flat, ordered for presentation
    {
      "path": ["(1)", "intro"],
      "change_type": "unchanged"
    },
    {
      "path": ["(1)", "42^2."],
      "change_type": "added",
      "text_b": "persoana strâns legată de debitor este considerată..."
    },
    {
      "path": ["(1)", "75."],
      "change_type": "modified",
      "text_a": "instrumente de datorie - obligațiuni...",
      "text_b": "instrumente de datorie - obligațiuni și alte forme...",
      "diff_html": "instrumente de datorie - obligațiuni <ins>și alte forme...</ins>"
    },
    {
      "path": ["(2)", "b)"],
      "change_type": "renumbered",
      "renumbered_from_path": ["(2)", "a)"],
      "text_a": "...",
      "text_b": "...",
      "diff_html": "..."
    }
  ]
}
```

Payload rules:

- `unchanged` units carry only `path` and `change_type`. `text_a`, `text_b`, `diff_html` are omitted to keep the response small.
- `added` units carry `text_b` only.
- `removed` units carry `text_a` only.
- `modified` units carry `text_a`, `text_b`, and `diff_html`.
- `renumbered` units carry `renumbered_from_path`, `text_a`, `text_b`, `diff_html`. The `path` field is the **new** path.
- The old `paragraphs` / `subparagraphs` nested structure is removed from the payload entirely. The frontend reconstructs the visual tree from `path` arrays.
- Articles whose unit list collapses to all-`unchanged` are excluded from `changes[*]` (matches today's behavior). The `summary.unchanged` count still reflects them.
- When the tokenizer fallback fires for an article, the entry has `change_type: "modified"`, no `units` field, and a top-level `diff_html` field (article-level word diff). The frontend renders this as a single-block fallback card.

## Frontend

`StructuredDiffArticle` and its leaf components are reshaped to consume `units` instead of `paragraphs`. The reshape is mechanical: the old code already groups things into a header card + body; the body now walks a flat unit list and groups by the first path segment (the alineat).

### Render tree from a flat list

```
For each article in changes:
  Group units by units[i].path[0] (the alineat label)
  For each alineat group:
    Walk units in order
    Collapse runs of consecutive unchanged units into one CollapsedRun
    Each modified / added / removed / renumbered unit renders as one row
```

The collapsed-run renderer groups by the first **two** path segments where possible, so the user sees `… (1) · points 1.–41. — unchanged · show` instead of `… 41 unchanged units · show`. This makes the collapse legible.

### Row layout

Each non-unchanged unit renders as one row with:

- **Path breadcrumb** on the left, monospace, gray. For `("(1)", "11.", "a)")` it shows `(1) · 11. · a)`. For `("(1)", "intro")` it shows `(1)` only. The breadcrumb is the visual cue that lets the user disambiguate the 17 different `a)` rows in art 5.
- **Body** on the right with the same flex layout as the normal version view.
- For `modified` and `renumbered`: `diff_html` injected via `dangerouslySetInnerHTML`. The HTML is server-built from text we control, no XSS surface.
- For `added`: `text_b` rendered with `bg-green-50 / text-green-800`, plus a small green `New` badge after the breadcrumb.
- For `removed`: `text_a` rendered struck-through with `bg-red-50 / text-red-800`.
- For `renumbered`: same styling as `modified`, with `(was (1) · 31.)` appended to the breadcrumb in muted gray.

### Interaction

- The article header is still a button. Clicking it toggles "full article" mode: every unit renders in full, no collapse markers. Clicking again collapses back.
- Each `CollapsedRun` is independently expandable in place, regardless of full-article mode. `show` reveals the unit text for every unit in the run.
- The summary cards at the top of the page (Modified / Added / Removed / Unchanged counts) and the version date pills are unchanged.

### Fallback rendering

Articles flagged with the tokenizer-fallback shape (no `units`, top-level `diff_html`) render as a single block card with the article-level diff html and a small "structural diff unavailable for this article" footnote.

## Error handling

- **Tokenizer raises.** Caught at the article boundary in `diff_articles`. The article falls back to the coarse word-level diff (described above), logged at WARN with article_number, both version IDs, and the exception. The page renders.
- **Tokenizer returns empty list.** Treated the same as the fallback path.
- **Article only on one side.** Already handled today: shipped as `added` / `removed` with the full text. No tokenization needed.
- **Both `full_text` empty.** Article is `unchanged`, excluded from changes.
- **One `full_text` empty, the other non-empty.** Treated as `modified` via fallback (the other side becomes one big add or remove block).

No new exception types are introduced. All errors are caught at the diff-articles boundary so a single bad article cannot break the response.

## Testing

### Backend

- **`backend/tests/test_article_tokenizer.py`** — new file.
  - Parameterized over `tests/fixtures/tokenizer/*.txt` (six initial fixtures listed in the tokenizer section). Each fixture has a paired `.expected.json`. The test loads both and asserts equality.
  - Targeted unit tests:
    - Each marker kind in isolation (alineat, numbered, litera, bullet, intro).
    - `^N` variants at each marker kind (`(4^1)`, `42^2.`, `d^1)`).
    - `art. 125` is **not** eaten as a numbered point (negative lookbehind).
    - Continuation: a segment with no leading marker appends to the previous unit.
    - Intro emission for alineat with children, alineat without children, article with no alineat at all.
    - Whitespace normalization.
- **`backend/tests/test_structured_diff.py`** — rewritten.
  - Path-based unchanged / modified / added / removed at unit level.
  - Greedy similarity pairing: a renumbered unit is detected and emitted as `renumbered`; an unrelated text in the same slot is **not** paired and stays as `removed` + `added`.
  - Article-level renumbering still works (`_pair_renumbered` reuse).
  - Tokenizer-fallback path: monkeypatch `tokenize_article` to raise, assert the article appears as `modified` with `diff_html` and no `units`, assert a warning is logged.
  - Regression test for the art 5 v517 vs v529 bug: load both `Article.full_text` snapshots from a fixture, run `diff_articles`, assert that the result contains the new `42^2.` definition as an `added` unit at path `("(1)", "42^2.")` and contains **zero** `modified` units in §(1) whose `text_a` and `text_b` are completely unrelated (concretely: assert that for every `modified` unit in §(1), the SequenceMatcher ratio between its `text_a` and `text_b` is ≥ 0.5). This is the regression test that the original bug never had — the old code would emit 17+ `modified` units with ratio near zero.
  - Empty `changes` for two identical versions.

### Frontend

Visual review against an updated mockup screen. No automated tests (matches existing project convention). Manual verification path: load `/laws/5/diff?a=517&b=529` after deploy, confirm:

1. Art 5 §(1) shows the new `42^2.` definition as one green `added` row, not a stream of fake `modified` rows.
2. No 28 k-char text blob anywhere on the page.
3. Path breadcrumbs are visible on every non-unchanged row (no bare `a)` without a parent point).
4. Collapsed runs show a sensible range like `(1) · 1.–41.`.
5. Clicking "show full article" expands every collapsed run.

## Migration / rollout

- The work lands on the existing `fix/version-discovery-dead-state` branch (or a fresh branch, decided at plan time).
- No data migration. The new code reads existing `Article.full_text` only.
- The frontend payload shape changes (`paragraphs` → `units`). Both backend and frontend ship in the same PR; there is no staged rollout.
- The old `structured_diff.py` tests are deleted alongside the rewrite (kept in git history if we ever need to inspect them).

## Out of scope

- Fixing the leropa parser. The tokenizer makes parser quality irrelevant for diffing; fixing the parser itself is a separate project against `paragraph-renderer.tsx` and the regular version view.
- Caching computed diffs. Tokenization is fast enough to compute on every request.
- Diff exports, printing, history, sharing.
- Cross-law diffing.
- A UI for choosing the diff strategy or threshold.
- Surfacing the tokenizer-fallback warnings to a user-visible admin panel. Logs only for now.
