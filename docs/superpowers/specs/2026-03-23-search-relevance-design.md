# Search Relevance — Alias Boost + Smart Sorting

## Overview

Improve advanced search result relevance by (1) boosting alias-matched laws to the top and (2) sorting remaining results by document type priority.

## Changes

Single function modified: `advanced_search()` in `backend/app/services/search_service.py`.

### Step 1: Alias Boost

Before the main keyword search, check the keyword against `legal_aliases.expand_query()`. If it matches (e.g., "codul civil" → Law 287/2009, "GDPR" → Law 190/2018), do a precise number search first and prepend those results. Then proceed with the normal keyword search and append results, deduplicated by `ver_id`.

Alias boost only runs when a `keyword` is provided and no `number`/`year` filters are set (since those already imply a precise search).

### Step 2: Smart Sorting

After all results are collected, sort non-boosted results by document type priority:

| Priority | Types | Rationale |
|----------|-------|-----------|
| 1 | COD, LEGE | The actual laws |
| 2 | OUG, OG | Government ordinances |
| 3 | HG, ORDIN | Government decisions/orders |
| 4 | REGULAMENT, NORMA | Regulations |
| 5 | DECIZIE, RECTIFICARE, DECRET, other | Ancillary documents |

Alias-boosted results stay at the top in their original order. Sorting applies only to the remaining results.

## Non-Goals

- No frontend changes
- No deduplication of same-law entries (e.g., LEGE 287 vs COD CIVIL)
- No changes to the emitent or status filter logic
