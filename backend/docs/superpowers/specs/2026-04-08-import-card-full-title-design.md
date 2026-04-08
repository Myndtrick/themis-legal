# Import/Failed Cards: Show Full Law Description

## Problem

On the `/laws` page, the **Importing** and **Failed** cards render only the
short identifier (`Legea N din DATE — Legea N`), while the Legal Library cards
below render the full descriptive title (`Legea N din DATE — privind măsuri
de punere în aplicare a Regulamentului…`). The user wants the import progress
cards to match the library format so the law is identifiable at a glance.

## Goal

Importing and Failed cards render `{title} — {description}`, mirroring
`LawCard`. The redundant `— Legea {lawNumber}` segment is dropped (the title
already contains "Legea N din DATE").

## Scope

Three flows feed the Importing/Failed sections; all three must propagate
`description`:

1. **New-versions flow** — user clicks "import" on a new version of a law that
   already exists in the library. The DB row has `Law.description`.
2. **Search-result flow** — user searches and imports a law for the first
   time. The external search result already includes a `description` field.
3. **Retry flow** — user retries a failed import. `description` must round-trip
   through `FailedEntry → ImportingEntry`.

Out of scope: bulk-import progress UI (`bulkProgress`), `LawCard` (already
correct), backend storage (`Law.description` already exists).

## Changes

### Backend — `backend/app/routers/laws.py`

`get_new_versions` (line 1020) — add `"description": law.description` to each
result row.

### Frontend types — `frontend/src/lib/api.ts`

`NewVersionEntry` (line 255) — add `description: string | null`.

### Frontend types — `frontend/src/app/laws/components/import-progress-section.tsx`

`ImportingEntry` (line 5) and `FailedEntry` (line 25) — add
`description: string | null`.

Render block at lines 88–95 (Importing) and 172–179 (Failed): replace

```tsx
<div className="font-semibold text-sm text-gray-900">
  {entry.title}
  {entry.lawNumber && (
    <span className="text-gray-500 font-normal"> — Legea {entry.lawNumber}</span>
  )}
</div>
```

with

```tsx
<div className="font-semibold text-sm text-gray-900 line-clamp-2">
  {entry.title}
  {entry.description && (
    <span className="font-normal text-gray-900"> — {entry.description}</span>
  )}
</div>
```

(Matches `law-card.tsx:86-91` exactly, including `line-clamp-2`.)

### Frontend search source — `frontend/src/app/laws/components/combined-search.tsx`

`BackgroundImportInfo` (line 74) — add `description: string | null`.

`bgImportPendingCategory` state shape — add `description`.

`startBackgroundImport` (line 318) — accept and forward `description`.

`handleImport` (line 328): stop conflating title and description. Replace:

```ts
const title = result.description || result.title;
```

with explicit propagation of `result.title` and `result.description ?? null`
to both the auto-match branch and the category-picker branch.

### Frontend orchestration — `frontend/src/app/laws/library-page.tsx`

`handleBackgroundImport` (line 707) — propagate `info.description` into the
`ImportingEntry`.

`startStreamingImport` failure path (line 690) — copy `description` from the
`ImportingEntry` into the new `FailedEntry`.

`handleRetry` (line 731) — copy `failedEntry.description` into the new
`ImportingEntry`.

`importVersionsForLaw` (line 764) — set `description: entry.description` on
the `ImportingEntry` (line 775) and on both `FailedEntry` constructions
(lines 814, 836).

## Edge cases

- **Description missing in DB** (older laws): `entry.description` is `null`,
  the `&&` guard skips the span — card renders just `{title}`.
- **Search result with no description**: same fallback — just `{title}`.
- **"Legea unknown" string** in current Failed cards: disappears because the
  `— Legea {lawNumber}` segment is removed entirely.

## Verification

Manual: trigger imports through each of the three flows, confirm the card
shows `Legea N din DATE — privind…` matching the corresponding library card.
No automated tests added — pure rendering change with no logic branches.
