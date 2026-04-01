# EU XHTML Parser Rewrite — Design Spec

**Date:** 2026-03-30
**Status:** Approved

## Overview

Complete rewrite of `eu_html_parser.py` to use ID-driven structural parsing instead of CSS class scanning. The rewritten parser outputs the same `books_data` + `articles` dict shape as `leropa_service`, enabling shared storage code. This fixes all current issues: missing articles, broken paragraph separation, empty chapter titles, missing sub-clauses, no preamble, and flat hierarchy.

## Problems Being Fixed

1. **Table-based sub-clauses missed** — (a), (b), (c) are in `<table>` cells, parser only checks `<p>` text
2. **Multi-level structure flattened** — Title→Chapter→Section hierarchy collapsed to flat chapters
3. **Sections treated as chapters** — "Secțiunea 1" wrongly elevated to chapter level
4. **Articles skipped** — only direct children of root parsed; nested articles in `enc_1→cpt_*→art_*` missed
5. **Paragraphs merged** — `<div id="NNN.MMM">` wrappers not used for paragraph boundaries
6. **Chapter titles empty** — looks for wrong CSS class (`oj-sti-section-1` instead of `oj-ti-section-2`)
7. **Article labels wrong** — both `article_number` and `label` set to same value → "Art. Art. 1"
8. **Preamble/recitals not captured** — `div#pbl_1` with citations and recitals completely ignored
9. **Nested sub-clauses lost** — (i), (ii), (iii) inside (a), (b) not parsed

## EUR-Lex XHTML Structure Reference

### Document skeleton
```
div.eli-container
├── div#tit_1.eli-main-title          → Document title (oj-doc-ti paragraphs)
├── div#pbl_1.eli-subdivision          → Preamble
│   ├── div#cit_1..cit_N              → Citations ("having regard to...")
│   ├── "Whereas:" text
│   └── div#rct_1..rct_N              → Recitals in tables: (1), (2), (3)...
├── div#enc_1.eli-subdivision          → Enacting clause (main content)
│   ├── div#cpt_I                      → Chapter I (or div#tis_I for Title I)
│   │   ├── p.oj-ti-section-1         → "CAPITOLUL I"
│   │   ├── div.eli-title#cpt_I.tit_1 → p.oj-ti-section-2 = chapter title
│   │   ├── div#cpt_I.sct_1           → Section 1 (optional)
│   │   │   ├── p.oj-ti-section-1     → "Secțiunea 1"
│   │   │   ├── div.eli-title          → section title
│   │   │   └── div#art_13.eli-subdivision → Article 13
│   │   └── div#art_1.eli-subdivision  → Article 1
│   │       ├── p.oj-ti-art            → "Articolul 1"
│   │       ├── div.eli-title#art_1.tit_1 → p.oj-sti-art = article title
│   │       ├── div#001.001            → Paragraph (1)
│   │       │   ├── p.oj-normal        → "(1) text..."
│   │       │   └── table              → Sub-clause (a)
│   │       │       └── tr → td:"(a)" + td:p.oj-normal:"text..."
│   │       └── div#001.002            → Paragraph (2)
│   └── div#cpt_II                     → Chapter II
└── div#fnp_1.eli-subdivision          → Final provisions
```

### ID patterns
| Pattern | Type | Example |
|---------|------|---------|
| `tis_N` | Title | `tis_I`, `tis_II` |
| `cpt_N` | Chapter | `cpt_I`, `tis_II.cpt_I` |
| `sct_N` | Section | `cpt_III.sct_1` |
| `art_N` | Article | `art_1`, `art_99` |
| `NNN.MMM` | Paragraph | `001.001`, `005.002` |
| `pbl_1` | Preamble | `pbl_1` |
| `cit_N` | Citation | `cit_1` through `cit_6` |
| `rct_N` | Recital | `rct_1` through `rct_173` |
| `enc_1` | Enacting clause | `enc_1` |
| `fnp_1` | Final provisions | `fnp_1` |

### Table-based sub-clauses
Each lettered sub-clause is a separate `<table>`:
```html
<table>
  <col width="4%"/><col width="96%"/>
  <tr>
    <td><p class="oj-normal">(a)</p></td>
    <td><p class="oj-normal">text of sub-clause a...</p></td>
  </tr>
</table>
```
Nested (i), (ii) are tables inside the second `<td>`.

## Parser Output Shape

Must match the leropa `books_data` + `articles` dict shape:

```python
{
    "title": "REGULAMENTUL (UE) 2016/679...",
    "preamble": {
        "citations": [{"number": "cit_1", "text": "având în vedere Tratatul..."}],
        "recitals": [{"number": "1", "text": "(1) Protecția persoanelor..."}],
    },
    "books_data": [
        {
            "book_id": "default",
            "title": None,
            "titles": [
                {
                    "title_id": "I",
                    "title": "DISPOZIȚII INTRODUCTIVE",
                    "chapters": [
                        {
                            "chapter_id": "I",
                            "title": "Cerințe și recunoaștere",
                            "sections": [
                                {
                                    "section_id": "1",
                                    "title": "Definiții",
                                    "articles": ["1", "2", "3"]
                                }
                            ],
                            "articles": []
                        }
                    ]
                }
            ]
        }
    ],
    "articles": {
        "1": {
            "label": "Art. 1",
            "title": "Obiect și obiective",
            "full_text": "Art. 1\nObiect și obiective\n(1) Prezentul...",
            "paragraphs": [
                {
                    "label": "(1)",
                    "text": "(1) Prezentul regulament stabilește...",
                    "subparagraphs": [
                        {"label": "(a)", "text": "(a) în cadrul unei activități..."},
                        {"label": "(b)", "text": "(b) de către statele membre..."}
                    ]
                }
            ]
        }
    },
    "annexes": [{"title": "ANEXA I", "source_id": "anx_I", "full_text": "..."}]
}
```

For documents **without titles** (only chapters): chapters go into a single default title within a default book.
For documents **with Title→Chapter→Section**: maps 1:1 to the hierarchy.

## ID-Driven Parsing Logic

### Structure extraction (recursive)

1. Find `div#enc_1` — the enacting clause container
2. Walk its child divs, checking `id` attribute:
   - `id` starts with `tis_` → Title node. Extract number from text. Recurse children for chapters.
   - `id` contains `cpt_` → Chapter node. Extract number and title from `oj-ti-section-2`. Recurse for sections and articles.
   - `id` contains `sct_` → Section node. Extract number and title. Recurse for articles.
   - `id` starts with `art_` → Article. Parse content (paragraphs, sub-clauses).
3. Title text is in `<div class="eli-title">` → `<p class="oj-ti-section-2">` (strip span wrappers)

### Article content extraction

For each `div#art_N`:
1. Article number from `<p class="oj-ti-art">` text → extract digit → format as "Art. N"
2. Article title from `<p class="oj-sti-art">` → stored in `label` field
3. Walk child elements for paragraphs:
   - `<div id="NNN.MMM">` → numbered paragraph container
   - Inside: `<p class="oj-normal">` = paragraph intro text
   - Inside: `<table>` elements = lettered sub-clauses
4. For articles without NNN.MMM divs: collect all `<p class="oj-normal">` as single paragraph

### Table sub-clause extraction

For each `<table>` inside a paragraph div:
1. First `<td>` → label text, e.g., "(a)", "(b)", "(i)"
2. Second `<td>` → sub-clause text from `<p class="oj-normal">`
3. Check if second `<td>` contains nested `<table>` elements → those are (i), (ii), (iii)
4. Nested items: concatenate into parent subparagraph text with newlines (DB model is 2 levels only)

### Preamble extraction

From `div#pbl_1`:
1. Citations: each `div#cit_N` → extract `<p class="oj-normal">` text
2. Recitals: each `div#rct_N` → parse table (number in first `<td>`, text in second `<td>`)
3. Store as a "Preambul" article with `order_index=-1`, citations and recitals as paragraphs

## Storage Integration

### Delete custom `_store_eu_version`

Replace with reuse of leropa storage functions:

```python
from app.services.leropa_service import _store_hierarchy, _store_single_article

# After parsing:
parsed = parse_eu_xhtml(html)

# Store preamble as special article
if parsed["preamble"]:
    _store_preamble_article(db, version, parsed["preamble"])

# Store hierarchy + articles (same as Romanian laws)
_store_hierarchy(db, version, parsed["books_data"], parsed["articles"])

# Store orphan articles (not in any structural element)
_store_orphan_articles(db, version, parsed["articles"], stored_ids)

# Store annexes
_store_annexes(db, version, parsed["annexes"])
```

### Article number and label

- `article_number` = `"Art. 1"` (matching Romanian format)
- `label` = article title from `oj-sti-art` (e.g., "Obiect și obiective")
- For preamble: `article_number` = `"Preambul"`, `label` = `"Preambul"`

### No frontend changes needed

The version detail page already renders StructuralElements as a tree. EU laws will display identically to Romanian ones — same colors, same chapter/section/article hierarchy, same paragraph/subparagraph nesting.

## Test Strategy

### Unit tests (against cached real XHTML)

1. GDPR structure: 11 chapters extracted with correct numbers and titles
2. GDPR articles: all 99 articles present, no gaps
3. GDPR sub-clauses: Art 2(2) → 4 subparagraphs (a)-(d), Art 5(1) → 6 subparagraphs (a)-(f)
4. GDPR paragraphs: Art 1 → 3 separate paragraphs, not merged
5. GDPR preamble: citations extracted, 173 recitals numbered
6. Reg 891/2017 structure: titles with nested chapters and sections
7. Reg 891/2017 nested sub-clauses: Art 2(f) → (i)-(vii) text in subparagraph
8. Article labels: `article_number="Art. 1"`, `label="Obiect și obiective"`
9. Output shape: `books_data` accepted by `_store_hierarchy`

### Integration test

Full import with mocked CELLAR → verify DB has correct StructuralElement tree with parent_id chain.

### Test fixtures

Update `eu_gdpr_sample.xhtml` and `eu_directive_sample.xhtml` to include real HTML patterns: `eli-container`, `div#enc_1`, `cpt_*` ids, `div[id=NNN.MMM]` paragraphs, table-based sub-clauses.
