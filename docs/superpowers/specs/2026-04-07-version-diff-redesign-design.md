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

`tokenize_article(full_text: str) -> list[AtomicUnit]` scans the article text for marker positions, filters false positives, and emits one `AtomicUnit` per item in document order.

```python
@dataclass(frozen=True)
class AtomicUnit:
    alineat_label: str | None  # "(1)", "(2)" — current alineat at the time of emission, or None for items before the first alineat
    marker_kind: str           # "alineat" | "numbered" | "litera" | "upper_litera" | "bullet" | "intro"
    label: str                  # "(1)" | "32." | "a)" | "A." | "" (intro)
    text: str                   # body text after the marker, whitespace-normalized
```

The tokenizer is **flat**: it does not try to reconstruct parent-child relationships between numbered points and their literae. This is intentional. Investigation against real `Article.full_text` for art 5 (Romanian insolvency law) showed that the parser concatenates content in an order that destroys parent context: all 75 numbered definitions appear first, then six independent litera groups (`a) b) c) … a) b) c) …`) are dumped at the end of the alineat with no marker indicating which definition each group belongs to. Any context-stack reconstruction would either collapse all `a)` items into one bucket (recreating the original bug) or mis-attribute literae to the wrong parent. The flat representation avoids both failure modes.

### Marker recognition

The tokenizer scans the entire `full_text` for marker positions using `re.finditer`, applies false-positive filtering, sorts by position, and walks the resulting list. Body text for each item is the slice from the marker's `match.end()` to the next marker's `match.start()`.

| Kind           | Pattern                              | Examples       |
|----------------|--------------------------------------|----------------|
| alineat        | `\(\s*(\d+(?:\^\d+)?)\s*\)`          | `(1)`, `(4^1)` |
| numbered       | `(\d+(?:\^\d+)?)\.\s`                | `32. `, `42^2. ` |
| litera         | `\b([a-z](?:\^\d+)?)\)\s`            | `a) `, `d^1) ` |
| upper_litera   | `\b([A-Z])\.\s`                      | `A. `, `B. `   |
| bullet         | `(?:^|\s)([–-])\s`                   | `– `           |

### False-positive filtering

Markers can appear inside literal references like `art. 90 alin. (1) și (2)`, `pct. 8`, `art. 125`. The filter rejects a candidate marker match if any of the following holds in the **20 characters preceding** `match.start()`:

- Contains `art.` and the marker kind is `numbered` (catches `art. 125`).
- Contains `art. ` (with trailing space) and the marker kind is `alineat` (catches `art. 90 alin. (1)` — the `art.` is part of `art. 90 alin.`).
- Contains `alin.` and the marker kind is `alineat` (catches `alin. (1)`).
- Contains `pct.` and the marker kind is `numbered` (catches `pct. 8`).
- Contains `lit.` and the marker kind is `litera` or `upper_litera` (catches `lit. a)`).
- Contains `nr.` and the marker kind is `numbered` (catches `nr. 19/2020`).
- The first character of the regex group is preceded by a digit (catches `1.617` or `2025.`).

Rejected matches are dropped entirely. The filter is unit-tested against real fixtures including `art. 90 alin. (1) și (2)`, `art. 125`, `art. 234^1`, `Legea nr. 85/2014`.

### Marker conflict resolution

When two marker patterns match at the same `start` position (rare but possible), priority order is: alineat > numbered > upper_litera > litera > bullet. A match that overlaps the body of an earlier-accepted match is dropped.

### Intro and pre-marker text

Whatever text appears in `full_text` **before the first accepted marker** becomes a single intro unit with `alineat_label=None`, `marker_kind="intro"`, `label=""`. This handles articles that start with bare text (no `(1)` marker), as well as articles whose entire content is one sentence with no markers at all.

For articles that start with `(1)` and have content immediately after the alineat marker, the alineat's body text is itself an `AtomicUnit` with `marker_kind="alineat"`, `label="(1)"`, and `text` set to the alineat header text up to the next marker. Subsequent items inside the alineat carry `alineat_label="(1)"`. So `(1) În înțelesul prezentei legi: 1. acord de compensare bilaterală (netting):...` produces:

```
AtomicUnit(alineat_label=None, marker_kind="alineat", label="(1)", text="În înțelesul prezentei legi:")
AtomicUnit(alineat_label="(1)", marker_kind="numbered", label="1.", text="acord de compensare bilaterală (netting):")
```

### Whitespace and continuation

Body text is whitespace-normalized: runs of spaces collapsed to single, leading/trailing stripped. Embedded inline notes (`Notă... Decizie de admitere: ...`) appear inside the body of the previous numbered/litera item naturally — they have no markers of their own, so they fall into the slice between two real markers and become part of that item's body. No special continuation logic is needed.

### Why content-based matching solves the duplicate-label bug

Each `AtomicUnit` is unique by its position in `full_text`, but `(alineat_label, label)` is **not** unique — art 5 has 17 items with `("(1)", "a)")`. Path-based dict matching cannot work. Instead, the diff algorithm uses content-based alignment via `difflib.SequenceMatcher` over the items' `(label + first 200 normalized chars of text)` keys. Identical items match on the equal opcode regardless of their position; near-duplicates within a `replace` opcode are paired by `SequenceMatcher.ratio()` similarity. The duplicate-`a)` collision becomes irrelevant because the matching is per-content, not per-label.

### Tokenizer testing

`backend/tests/fixtures/tokenizer/` holds snapshot fixtures: each test case is a `<name>.txt` with raw `Article.full_text` plus a `<name>.expected.json` with the expected `list[AtomicUnit]` (alineat_label, marker_kind, label, text). The test parameterizes over the directory.

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
3. **Unit-level diff** for each matched article pair, using **content-based alignment via SequenceMatcher**:

```python
units_a = tokenize_article(article_a.full_text)
units_b = tokenize_article(article_b.full_text)

# Group items by (alineat_label or "" for pre-alineat content)
groups_a = group_by_alineat(units_a)   # {"": [...], "(1)": [...], "(2)": [...]}
groups_b = group_by_alineat(units_b)

leaves: list[dict] = []
all_alineat_labels = ordered_union(groups_a.keys(), groups_b.keys())  # B's order, then A-only

for alineat_label in all_alineat_labels:
    items_a = groups_a.get(alineat_label, [])
    items_b = groups_b.get(alineat_label, [])
    leaves.extend(diff_alineat_items(items_a, items_b))

return leaves


def diff_alineat_items(items_a, items_b):
    """Content-based alignment of two flat item lists within one alineat."""
    # Hash-friendly key per item: label + normalized first 200 chars of text
    def key(item):
        return (item.label, normalize(item.text)[:200])

    keys_a = [key(i) for i in items_a]
    keys_b = [key(i) for i in items_b]
    matcher = difflib.SequenceMatcher(a=keys_a, b=keys_b, autojunk=False)

    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out.append(unchanged_leaf(items_b[j1 + k]))
        elif tag == "delete":
            for k in range(i1, i2):
                out.append(removed_leaf(items_a[k]))
        elif tag == "insert":
            for k in range(j1, j2):
                out.append(added_leaf(items_b[k]))
        elif tag == "replace":
            # Greedy similarity pairing inside the replace block
            block_a = items_a[i1:i2]
            block_b = items_b[j1:j2]
            pairs, leftover_a, leftover_b = greedy_pair_by_text_ratio(
                block_a, block_b, threshold=0.5
            )
            # Emit modified pairs in B's order, then leftovers as removed/added
            for ra, rb in pairs:
                out.append(modified_leaf(ra, rb))
            for ra in leftover_a:
                out.append(removed_leaf(ra))
            for rb in leftover_b:
                out.append(added_leaf(rb))
    return out
```

**Why this works for art 5.** The 17 duplicate-`a)` items in v517 and 18 in v529 align by their text content via SequenceMatcher's `equal` opcodes — items whose `(label, text[:200])` keys match exactly become `unchanged` regardless of where they sit in the list. A genuinely new definition like `42^2.` appears as an `insert` opcode → one `added` leaf. A definition with edited wording appears in a `replace` opcode and gets paired with its old version by the 0.5 similarity threshold (pairs above the threshold become `modified`; the rest become add+remove). The original bug — fake "modified" leaves between unrelated definitions — becomes structurally impossible because the alignment is by content, not by colliding labels.

**Threshold of 0.5 inside replace blocks** is intentionally lower than the article-level renumbering threshold (0.85) because items inside a `replace` opcode are already known to be in the same alignment slot and we want to surface even moderately-edited items as `modified` rather than add+remove. The 0.85 threshold for article-level renumbering stays unchanged because that operates on articles that SequenceMatcher couldn't align by `article_number` and we want to be conservative there.

**Complexity.** Tokenization is O(n) in `len(full_text)`. SequenceMatcher is O(m × n) where m, n are item counts per alineat — bounded by ~100 even for art 5, so well under 10 ms per article. Greedy similarity pairing inside replace blocks is O(k²) where k is the replace-block size, typically <10. Total for a 400-article diff stays well under one second.

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
      "alineat_label": "(1)",
      "marker_kind": "alineat",
      "label": "(1)",
      "change_type": "unchanged"
    },
    {
      "alineat_label": "(1)",
      "marker_kind": "numbered",
      "label": "42^2.",
      "change_type": "added",
      "text_b": "persoana strâns legată de debitor este considerată..."
    },
    {
      "alineat_label": "(1)",
      "marker_kind": "numbered",
      "label": "75.",
      "change_type": "modified",
      "text_a": "instrumente de datorie - obligațiuni...",
      "text_b": "instrumente de datorie - obligațiuni și alte forme...",
      "diff_html": "instrumente de datorie - obligațiuni <ins>și alte forme...</ins>"
    },
    {
      "alineat_label": "(1)",
      "marker_kind": "litera",
      "label": "a)",
      "change_type": "removed",
      "text_a": "orice acord master de netting - orice înțelegere..."
    }
  ]
}
```

Payload rules:

- Every unit carries `alineat_label`, `marker_kind`, `label`, and `change_type`. `alineat_label` is the alineat the item belongs to (or `null` for items before the first alineat marker / articles with no alineate at all).
- `unchanged` units carry only those four fields. `text_a`, `text_b`, `diff_html` are omitted to keep the response small.
- `added` units carry `text_b` only (in addition to the four base fields).
- `removed` units carry `text_a` only.
- `modified` units carry `text_a`, `text_b`, and `diff_html`.
- The old `paragraphs` / `subparagraphs` nested structure is removed from the payload entirely. The frontend groups units by `alineat_label` and renders each alineat as a section.
- Renumbered items (a definition that gained a `^N` suffix or shifted index) are not flagged with a special change_type; they fall out of SequenceMatcher's `replace` opcode and are emitted as a `modified` pair if their text similarity is high enough, or as an `added` + `removed` pair otherwise. This is honest: from `full_text` alone we cannot reliably distinguish "renumbered" from "deleted X, inserted Y with similar text". A future enhancement could add a `was_label` field once we have a more authoritative source.
- Articles whose unit list collapses to all-`unchanged` are excluded from `changes[*]` (matches today's behavior). The `summary.unchanged` count still reflects them.
- When the tokenizer fallback fires for an article, the entry has `change_type: "modified"`, no `units` field, and a top-level `diff_html` field (article-level word diff). The frontend renders this as a single-block fallback card.

## Frontend

`StructuredDiffArticle` and its leaf components are reshaped to consume `units` instead of `paragraphs`. The reshape is mechanical: the old code already groups things into a header card + body; the body now walks a flat unit list and groups by `alineat_label`.

### Render tree from a flat list

```
For each article in changes:
  Group article.units by units[i].alineat_label  (preserving B's order)
  For each alineat group:
    Render an alineat header (e.g. "(1)") if alineat_label is not null
    Walk units in order
    Collapse runs of consecutive unchanged units into one CollapsedRun
    Each modified / added / removed unit renders as one row
```

A `CollapsedRun` shows a sensible label range based on the first and last collapsed item's `label` field, e.g. `… items 1.–41. unchanged · show`.

### Row layout

Each non-unchanged unit renders as one row with:

- **Marker label** on the left, monospace, gray, e.g. `1.`, `42^2.`, `a)`, `A.`, `–`. Items with `marker_kind="alineat"` render their label as an alineat header above the row group, not as a row label.
- **Body** on the right with the same flex layout as the normal version view.
- For `modified`: `diff_html` injected via `dangerouslySetInnerHTML`. The HTML is server-built from text we control, no XSS surface.
- For `added`: `text_b` rendered with `bg-green-50 / text-green-800`, plus a small green `New` badge after the label.
- For `removed`: `text_a` rendered struck-through with `bg-red-50 / text-red-800`.

There is no parent-context breadcrumb. The investigation found that `Article.full_text` does not preserve which numbered definition a litera belongs to, so we cannot show one accurately. The alineat header (`(1)`) is the one structural anchor we keep.

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
  - Regression test for the art 5 v517 vs v529 bug: load both `Article.full_text` snapshots from a fixture, run `diff_articles`, assert that the result contains a unit with `label="42^2."`, `change_type="added"`, `alineat_label="(1)"` and contains **zero** `modified` units whose `text_a` and `text_b` are completely unrelated (concretely: assert that for every `modified` unit in §(1), `difflib.SequenceMatcher(None, u.text_a, u.text_b).ratio() >= 0.5`). This is the regression test the original bug never had — the old code emitted 17+ `modified` units with ratio near zero.
  - Empty `changes` for two identical versions.

### Frontend

Visual review against an updated mockup screen. No automated tests (matches existing project convention). Manual verification path: load `/laws/5/diff?a=517&b=529` after deploy, confirm:

1. Art 5 §(1) shows the new `42^2.` definition as one green `added` row, not a stream of fake `modified` rows.
2. No 28 k-char text blob anywhere on the page.
3. Items render under their alineat header (e.g. `(1)`, `(2)`) with bare marker labels (`1.`, `42^2.`, `a)`).
4. Collapsed runs show a sensible range like `items 1.–41. unchanged · show`.
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
