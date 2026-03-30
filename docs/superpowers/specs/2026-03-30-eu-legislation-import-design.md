# EU Legislation Import — Design Spec

**Date:** 2026-03-30
**Status:** Approved

## Overview

Add the ability to import European Union legislation (directives, regulations, decisions, treaties) into the Legal Library alongside existing Romanian laws. EU laws use the EU Publications Office's open CELLAR API (SPARQL + REST) — no authentication required. The UI stays identical: same search bar, same import buttons, same structure. EU laws appear seamlessly grouped under the existing `eu.*` categories.

## Critical Production Safety Constraints

1. Never drop or reset the database on deployment
2. All import functions must check if data already exists before inserting
3. Previously imported Romanian laws must never be touched
4. All schema changes are additive only (new columns with defaults, new enum values)

## Data Source: CELLAR API

**Search/discovery:** SPARQL endpoint at `https://publications.europa.eu/webapi/rdf/sparql`
- No auth, no registration, no API key
- Query using CDM ontology properties: `cdm:resource_legal_id_celex`, `cdm:work_has_resource-type`, `cdm:expression_title`, `cdm:work_date_document`, `cdm:resource_legal_in-force`
- Resource type URIs: `REG`, `DIR`, `DEC`, `TREATY` at `http://publications.europa.eu/resource/authority/resource-type/{CODE}`

**Content retrieval:** REST at `https://publications.europa.eu/resource/cellar/{uuid}`
- Content negotiation: `Accept: application/xhtml+xml`
- Language: `Accept-Language: ron` (fallback to `eng`)
- Returns structured XHTML with semantic CSS classes for articles, chapters, sections
- Follows 303 redirects

**Document identification:** CELEX numbers
- Legislation format: `{Sector}{Year}{Type}{Number}` — e.g., `32016R0679` (GDPR)
- Sector `3` = legislation: type codes `L` = directive, `R` = regulation, `D` = decision
- Sector `1` = treaties (different format, e.g., `12012M/TXT` for TEU consolidated)
- Consolidated versions: sector `0` + date suffix — e.g., `02016R0679-20160504`

**Consolidation tracking:** SPARQL query for CELEX numbers starting with `0` + base number, using `cdm:act_consolidated_date` for version snapshots.

## Data Model Changes

### Law model — new fields

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `source` | Enum `"ro"` / `"eu"` | `"ro"` | Distinguish origin |
| `celex_number` | String, nullable | `null` | Unique EU identifier |
| `cellar_uri` | String, nullable | `null` | CELLAR UUID for API access |

Existing fields reused:
- `source_url` → EUR-Lex ELI link (e.g., `http://data.europa.eu/eli/reg/2016/679/oj`)
- `document_type` → new enum values: `directive`, `regulation`, `decision`, `treaty`

### LawVersion model — new fields

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `language` | String | `"ro"` | Language of imported content (`"ro"` or `"en"`) |

Existing fields reused:
- `ver_id` → consolidated CELEX number (e.g., `02016R0679-20160504`)
- `date_in_force` → consolidation snapshot date

### KnownVersion model — new fields

Same `language` field as LawVersion.

### New category

Add `eu.decisions` to the EU category group alongside existing `eu.regulations`, `eu.directives`, `eu.treaties`.

### No changes to

Article, StructuralElement, Paragraph, SubParagraph, Annex, AmendmentNote — EU content maps directly to these existing tables.

### Migration safety

- All new columns have defaults — existing rows auto-populated
- No DROP, no table replacement
- Column additions run in lifespan startup, same pattern as existing `diff_summary` backfill
- Category seeding uses existing `get_or_create` pattern

## EU Legislation Service (`eu_cellar_service.py`)

### Search flow

1. Build SPARQL query from user input (keyword, document type, date range, number)
2. POST to SPARQL endpoint with `Accept: application/sparql-results+json`
3. Parse results into `SearchResult` shape (same as Romanian search results)
4. Check `Law.celex_number` for each result to set `already_imported` flag

### Import flow

1. Receive CELEX number (e.g., `32016R0679`)
2. Duplicate check: query `Law.celex_number` — if exists, return 409
3. Fetch metadata via SPARQL: title, date, type, in-force status, CELLAR UUID
4. Fetch full XHTML from CELLAR REST, trying `Accept-Language: ron` first, fallback to `eng`
5. Parse XHTML into articles, structural elements, annexes
6. Create `Law` record: `source="eu"`, `celex_number`, `cellar_uri`, appropriate `document_type`
7. Create `LawVersion`: `ver_id` = consolidated CELEX, `language` = fetched language
8. Store articles, structural elements, annexes — same tables as Romanian laws
9. Auto-categorize: directive → `eu.directives`, regulation → `eu.regulations`, decision → `eu.decisions`, treaty → `eu.treaties`
10. Index into ChromaDB + FTS5

### Consolidated versions

- SPARQL query for CELEX numbers starting with `0` + base number
- Each consolidation date becomes a separate `LawVersion`
- Same `import_history` flag as Romanian — user chooses all versions or latest only
- `import_law_smart()` pattern: import latest + base, schedule remaining via APScheduler

### Language fallback

- Request Romanian (`ron`) first
- If CELLAR returns 404 or empty for Romanian, request English (`eng`)
- Store actual language in `LawVersion.language`
- If Romanian becomes available later, user can re-import that version

## XHTML Parser (`eu_html_parser.py`)

Parses EUR-Lex XHTML using semantic CSS classes:

| CSS Class | Maps to |
|-----------|---------|
| `oj-ti-art` | Article boundary (Article title) |
| `oj-sti-art` | Article subtitle/heading |
| `oj-ti-section-1` | Title-level StructuralElement |
| `oj-ti-section-2` | Chapter-level StructuralElement |
| `oj-ti-section-3` | Section-level StructuralElement |
| `oj-normal` | Paragraph text within articles |
| `oj-note` | Footnotes |
| `eli-subdivision` | ELI structural markers |

Output: same dict structure as `leropa_service`: `{articles, books, annexes}` — so downstream storage code is shared.

## API Routes

### New endpoints

- `GET /api/laws/eu/search` — search EU legislation via SPARQL
- `POST /api/laws/eu/import` — import by CELEX number `{celex_number, import_history: bool}`
- `GET /api/laws/eu/filter-options` — EU document types

### Modified endpoints

- `GET /api/laws/search` — optional `source` param: `"ro"`, `"eu"`, or omitted (both)
  - When omitted: fires both legislatie.just.ro and SPARQL in parallel, merges results with `source` badge
  - When `"ro"`: current behavior unchanged
  - When `"eu"`: SPARQL only
- `GET /api/laws/advanced-search` — same `source` param addition
- `GET /api/laws/library` — no changes needed (EU laws are just Law records with categories)

### Import response

Same shape as existing: `{law_id, title, versions_imported}`

### Suggestion system

- Add EU law seed mappings to `LawMapping` (GDPR, AI Act, NIS2, etc.)
- `LawMapping` gets optional `celex_number` field for EU suggestions
- Same suggestion flow: if mapping exists but law not imported, show as suggestion

## Frontend Changes

### Search & Import form (`search-import-form.tsx`)

- Source toggle: three pills — "All" | "Romanian" | "EU" — above the search bar (default: "All")
- When "EU" selected: document type dropdown shows EU types (Directive, Regulation, Decision, Treaty)
- When "All": both type sets shown, grouped under headers
- Search results get a small "RO" or "EU" badge next to document type
- Import button calls appropriate endpoint based on result's source
- Direct URL import: detect `data.europa.eu/eli/` or `eur-lex.europa.eu` URLs → extract CELEX → call EU import

### Library page (`library-page.tsx`)

- No structural changes — EU laws group under `eu.*` categories automatically
- Law cards get subtle "EU" or "RO" badge (small colored chip)
- English-only imports show "EN" indicator
- Sidebar filters: existing "EU" category group works out of the box

### API client (`lib/api.ts`)

- Add `euSearch(params)`, `euImport(celex, importHistory)`, `euFilterOptions()` methods
- Update `search()` to accept optional `source` param

## Version Discovery & Background Jobs

### EU version discovery

- New scheduled job: `run_eu_version_discovery()`
- Runs **weekly** (Sunday 04:00) — separate from daily Romanian discovery
- For each EU `Law`:
  - SPARQL query for consolidated CELEX numbers matching base act
  - Compare against existing `KnownVersion`
  - Insert new consolidation dates
  - Mark newest as `is_current=True`
  - Update `law.last_checked_at`

### Background import

- Same `import_law_smart()` pattern: latest + base version first, schedule remaining
- `import_remaining_eu_versions()` as APScheduler background task
- Rate limiting: 2s between fetches
- SQLite lock contention: exponential backoff (identical to existing)

### Caching

- EU XHTML cached at `~/.cellar/{celex_number}.xhtml`
- Same pattern as `~/.leropa/{ver_id}.html`: check exists → use cache, else fetch → save

## Auto-Categorization

| EU Document Type | Category Slug |
|-----------------|---------------|
| Directive | `eu.directives` |
| Regulation | `eu.regulations` |
| Decision | `eu.decisions` (new) |
| Treaty | `eu.treaties` |

Set `category_confidence = "auto"` on assignment.

## Testing Strategy

### Unit tests

- SPARQL query builder: correct queries for each filter combination
- XHTML parser: test against saved sample documents (GDPR, a directive, a decision)
- CELEX number parsing: extract type, year, number from various formats
- Duplicate detection: verify import rejected when `celex_number` exists

### Integration tests

- Full import flow: CELEX → SPARQL → XHTML → parse → DB → verify records
- Version discovery: mock SPARQL with multiple consolidations → verify KnownVersion created
- Search merge: unified search returns both RO and EU results with correct badges
- Language fallback: mock Romanian 404 → verify English fetched, `language="en"` stored

### Safety tests

- Import EU law → verify no Romanian law records modified
- Run migration on existing DB → verify all RO records unchanged, defaults correct
- Double-import same CELEX → verify 409, no duplicate

### Test fixtures

- Cache real XHTML responses (GDPR, NIS2 directive, an EU decision) as fixtures
- Deterministic parser tests without live API calls
