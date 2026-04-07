# Version Discovery Dead-State Fix

**Date:** 2026-04-07
**Status:** Approved for planning

## Background

Production users report that the law-detail page's "Check now" button cannot detect missing or stale current versions, while the same flow works correctly in local development. The reproduction:

1. Open Codul Fiscal (law id 126), import all 151 versions via the banner's "Import all" button.
2. Observe that v151 (the newest, dated 2026-03-31) is shown as `Imported` but not flagged as the current version.
3. Delete v151.
4. Click "Check now" — the banner shows "No new versions · Never checked · All available versions are imported" instead of detecting that v151 is missing.

The behaviour is correct on the developer's local DB and broken on production. The screenshot attached to the report shows `last_checked_at` is `null` in production (`"Never checked"`), confirming the check endpoint never succeeds.

## Root cause

There are two contradictory definitions of `LawVersion.is_current` living in the same codebase:

- **Old logic** (`backend/app/routers/laws.py:1293-1302`, `backend/app/services/leropa_service.py:620-632`, `backend/app/services/leropa_service.py:831-841`): the LawVersion with the newest `date_in_force` is current.
- **New logic** (`backend/app/routers/laws.py:1394-1417`, `_recalculate_current_version`, called by `import_known_version` and `_background_delete_single_version`): only the LawVersion whose `ver_id` matches the `KnownVersion` row that LegislatieJust says is current is marked current. If that version is not imported, **no** LawVersion is marked current.

The new logic is the intended semantic — `is_current=True` should mean "this matches what legislatie.just.ro currently considers in force." But it interacts catastrophically with downstream code:

- `check_law_updates` (`laws.py:1253-1259`) hard-requires an `is_current=True` LawVersion and raises HTTP 400 otherwise.
- `discover_versions_for_law` (`backend/app/services/version_discovery.py:43-50`) hard-requires the same and silently returns 0.
- `last_checked_at` is only updated on the success paths inside `check_law_updates`, so when it raises 400 the law is permanently stuck displaying "Never checked".
- The frontend (`frontend/src/app/laws/[id]/update-banner.tsx:108-110`) swallows the 400 silently with `catch {}`, so the user sees no error.

Production fell into this dead state because some sequence of imports left `KnownVersion.is_current` not set on any row for Codul Fiscal (the seed-from-imported path can produce that state if the imported versions themselves had no `is_current=True` at seed time, and discovery — which is what would otherwise repair `KnownVersion.is_current` — also requires `is_current` to run, so the system cannot self-heal). The local DB happens to have a correct `KnownVersion.is_current` row from earlier dev state, which is why local "works".

This is a chicken-and-egg deadlock, not data corruption, and the fix is purely in code.

## Goals

1. The strict semantic for `LawVersion.is_current` is preserved: `True` only when the imported version matches LegislatieJust's current version. Users want `is_current` to answer "am I up to date with the official source?", not "what's the newest thing I've imported?"
2. Every code path that probes legislatie.just.ro must be able to do so regardless of whether any LawVersion is currently flagged `is_current`.
3. Production deploys must not require any data migration. The existing prod DB must self-heal on first user visit to a stuck law's page.
4. Backend errors from the check flow must surface in the banner instead of being silently swallowed.

## Non-goals

- No schema changes. No migrations. No `ADD COLUMN`. No data backfill scripts.
- No changes to the import flow itself (`import_known_version`, `import_law_smart`, `import_remaining_versions`) beyond the minimal import-path adjustment needed to call `_recalculate_current_version` from its new location.
- No redesign of how laws are initially added. We are fixing the discover/check loop, not the whole import lifecycle.
- No redesign of the frontend banner layout — we add an inline error row to the existing card.

## Design

### Backend changes

#### 1. Decouple "probe ver_id" from "is_current LawVersion"

Add a helper to `backend/app/services/version_discovery.py`:

```python
def _get_probe_ver_id(db: Session, law: Law) -> str | None:
    """Pick a ver_id we can use as an entry point when fetching upstream history.

    Order of preference:
      1. The is_current=True LawVersion (when the law is up to date)
      2. The newest LawVersion by date_in_force (when we have imports but none are current)
      3. The newest KnownVersion by date_in_force (when discovery has run but nothing is imported)
      4. None (genuine empty state — the law has no versions at all)
    """
```

The helper is safe because legislatie.just.ro returns the same `history` list regardless of which version's page you fetch (each version's HTML carries the full version timeline). Any ver_id we have is a valid entry point for discovery.

#### 2. Rewrite `discover_versions_for_law` to use the probe helper

In `backend/app/services/version_discovery.py:30-148`:

- Replace the `is_current` lookup at lines 43-50 with `_get_probe_ver_id(db, law)`.
- If the helper returns `None`, log and return 0 (true empty state — nothing to do).
- The synthetic-history-entry logic at lines 70-79 should base its "entry ver_id" on whatever the helper returned, not necessarily on a current LawVersion. Use the LawVersion or KnownVersion row that the helper picked to source the fallback `date_in_force`.
- After the existing `KnownVersion.is_current` recompute (lines 124-135), call `_recalculate_current_version(db, law.id)` so `LawVersion.is_current` is re-derived from the freshly-authoritative `KnownVersion.is_current`. **This is what makes the fix self-healing for stuck laws.**

#### 3. Move `_recalculate_current_version` into `version_discovery.py`

Currently lives in `backend/app/routers/laws.py:1394-1417`. Move it verbatim (no logic change) to `backend/app/services/version_discovery.py` so `discover_versions_for_law` can call it without an import cycle. Update the existing callers in `laws.py`:

- `import_known_version` (`laws.py:1023`)
- `_background_delete_single_version` (`laws.py:1425`)

These callers change from a local function call to an import from `app.services.version_discovery`. No behaviour change.

#### 4. Rewrite `check_law_updates` as a thin wrapper

`backend/app/routers/laws.py:1242-1316` becomes:

```python
@router.post("/{law_id}/check-updates")
def check_law_updates(law_id: int, db: Session = Depends(get_db)):
    """Refresh KnownVersion entries for a single law from legislatie.just.ro."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    try:
        new_count = discover_versions_for_law(db, law)
    except Exception as e:
        logger.exception(f"Error checking updates for law {law_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Update check failed: {str(e)}")

    return {
        "discovered": new_count,
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
    }
```

Removed:
- The 400 on missing current version (line 1258-1259) — `discover_versions_for_law` now handles all entry-point selection internally.
- The auto-import branch (lines 1265-1291) — discovery only writes `KnownVersion`. The user clicks the banner's Import button to actually pull text.
- The is_current recompute by newest date (lines 1293-1302) — this was the old, conflicting logic. `_recalculate_current_version` (called inside discovery) is now the only place LawVersion.is_current is set, and it uses the strict semantic.
- The `detect_law_status` recompute (lines 1304-1307) — only relevant if we just imported text, which we no longer do here. Status is recomputed on actual imports as before.

The response shape changes from `{has_update, message}` to `{discovered, last_checked_at}`. This is a breaking API change but only one frontend caller exists.

#### 5. No changes to `import_known_version`, `import_law_smart`, `import_remaining_versions`, `_background_delete_*`

The strict `_recalculate_current_version` semantic is preserved everywhere. The only new caller is `discover_versions_for_law` itself (point 2 above), which makes discovery self-repair the LawVersion.is_current flag whenever KnownVersion.is_current changes.

### Frontend changes

#### 6. Surface backend errors in the banner

In `frontend/src/app/laws/[id]/update-banner.tsx`:

- Add `const [error, setError] = useState<string | null>(null);`.
- Replace `catch {}` in `handleCheckNow` (line 108) with `catch (e) { setError(e instanceof Error ? e.message : "Check failed"); }`. Clear with `setError(null)` at the start of the function.
- Replace `catch (() => {})` in the auto-check `useEffect` (line 69) with the same error-setting handler.
- Render an inline error row inside the existing banner card when `error !== null`: small red text beneath the "Last checked" line, alongside the existing Check now button (which now doubles as Retry).
- The error row appears regardless of which banner state is rendered (no-new, new-versions, loading-finished). It does not replace the banner — it augments it.

No alerts. No toasts. No layout changes beyond adding the error row.

#### 7. Update the API client and types

In `frontend/src/lib/api.ts:838-840`:

- The `checkUpdates` method's response type changes from `{has_update: boolean, message: string}` to `{discovered: number, last_checked_at: string | null}`.
- Update the call sites in `update-banner.tsx` — they currently chain `.then(() => api.laws.getKnownVersions(lawId))` and discard the response, so the actual change at the call site is type-only. Use the new `last_checked_at` from the response if it makes the chained `getKnownVersions` call optional in future, but for now keep the existing chain (it's the simplest path and still correct).

### Schema changes

**None.** Zero migrations. The deploy is a pure code update. The user's existing production database — including all imported laws, versions, articles, and KnownVersion rows — is untouched.

## Self-healing path on deploy

This is the sequence that repairs the user's stuck production state on first interaction after deploy, without any manual intervention:

1. The fix deploys.
2. The user opens the Codul Fiscal page (law id 126).
3. The banner mounts. `lastCheckedAt` is `null`, so `shouldAutoCheck` returns `true` and the auto-check `useEffect` fires `api.laws.checkUpdates(126)`.
4. The new `check_law_updates` endpoint calls `discover_versions_for_law(db, law)`.
5. `_get_probe_ver_id` returns the newest LawVersion by `date_in_force` (likely v150 in the user's case, since v151 was deleted), since no LawVersion has `is_current=True`.
6. Discovery fetches v150's page from legislatie.just.ro, follows `next_ver` to v151's page (more complete history), and writes/updates all 151 KnownVersion rows. The newest by date (v151) is marked `KnownVersion.is_current=True`. `law.last_checked_at` is updated.
7. Discovery calls `_recalculate_current_version(db, law.id)`. v151's KnownVersion is the upstream-current, but no LawVersion has ver_id matching v151 (it was deleted). All LawVersions remain `is_current=False`. **This is correct under semantic B** — the law really is stale.
8. The endpoint returns `{discovered: 151, last_checked_at: "..."}`. The frontend chains `getKnownVersions(126)` and re-renders.
9. The banner now sees v151 in `knownVersions` but not in `importedVerIds`. v151's ordinal is 151 and `highestImportedNum` is 150, so v151 passes the `num > highestImportedNum` filter. The amber "1 new version available" alert renders with an "Import v151" button.
10. The user clicks Import v151. `import_known_version` runs, fetches v151's text, calls `_recalculate_current_version`, and now LawVersion v151 is marked `is_current=True`. The law is fully healed.

For laws where the upstream-current is **already imported** but `LawVersion.is_current=False` due to the same dead-state bug (i.e. the user did import v151 originally but `_recalculate_current_version` failed to mark it), step 7 will instead find a matching LawVersion and flip its `is_current` to `True` immediately. No user action required beyond visiting the page.

## Test plan

### Backend unit tests (extend `backend/tests/test_version_discovery.py` or similar)

1. **`_get_probe_ver_id` ordering** — given a law with (a) an `is_current=True` LawVersion, returns its ver_id. (b) no `is_current` but multiple LawVersions, returns the newest by `date_in_force`. (c) no LawVersions but KnownVersions, returns the newest KnownVersion. (d) nothing, returns `None`.
2. **`discover_versions_for_law` works without `is_current` LawVersion** — seed a law with LawVersions that all have `is_current=False`, mock the upstream fetcher, run discovery, assert it populated `KnownVersion` and updated `last_checked_at`.
3. **`discover_versions_for_law` self-heals `LawVersion.is_current`** — seed a law where `KnownVersion.is_current=True` exists for a ver_id whose LawVersion has `is_current=False`. Run discovery. Assert that LawVersion now has `is_current=True`.
4. **`discover_versions_for_law` preserves dead-state correctness** — seed a law where the upstream-current ver_id has a `KnownVersion` row but no corresponding `LawVersion`. Run discovery. Assert no LawVersion has `is_current=True` (semantic B preserved).
5. **`check_law_updates` endpoint smoke test** — POST to `/api/laws/{id}/check-updates` for a law with no `is_current` LawVersion. Assert 200 (not 400) and a `discovered` count in the response.
6. **`check_law_updates` no longer auto-imports** — verify that LawVersion count is unchanged after a check, even when discovery finds new KnownVersions.

### Backend integration test

7. **Full reproduction of the dead state** — set up a law where 151 versions exist as KnownVersion + LawVersion rows, none have `is_current=True` anywhere, `last_checked_at` is null. Delete the LawVersion for v151. Call `check-updates`. Assert: `KnownVersion.is_current=True` is now set on v151's row, `last_checked_at` is populated, `getKnownVersions` returns v151 as not-imported, and v151 is missing from LawVersions. This is the user's exact scenario.

### Frontend test

8. **Banner surfaces backend errors** — mock `api.laws.checkUpdates` to reject with an Error. Mount the banner. Assert the error row renders with the error message and the Check now button is still clickable.
9. **Banner clears error on successful retry** — mock `checkUpdates` to reject once then resolve. Click Check now twice. Assert the error row disappears after the second click.

### Manual verification

10. Reproduce the user's exact scenario in a local DB seeded into the dead state. Confirm that visiting the law page after deploy auto-heals the law and surfaces the missing v151 in the amber alert.

## Risk assessment

- **Schema risk:** zero. No migrations.
- **Data loss risk:** zero. No DELETE statements added, no UPDATE statements that touch user data beyond the existing `is_current` flag flipping (which already happens today).
- **API breakage risk:** low. The `checkUpdates` response shape changes, but only one frontend caller exists and it discards the response body. The type update is mechanical.
- **Behaviour-change risk:** moderate. Healthy laws (those that already have correct `is_current` flags) will see no behaviour difference. Stuck laws will start auto-healing on first visit, which is the intended outcome but worth noting in case the user has external monitoring that depended on `is_current` being all-false on those laws (no such monitoring exists in this codebase).
- **Dead-state-preserving risk:** the test at point 4 explicitly guards against accidentally flipping back to "newest imported = current" semantics. As long as that test passes, semantic B is preserved.

## Files touched

- `backend/app/services/version_discovery.py` — add helper, rewrite `discover_versions_for_law`, host moved `_recalculate_current_version`.
- `backend/app/routers/laws.py` — rewrite `check_law_updates`, remove `_recalculate_current_version` definition, update its two callers to import from the new location.
- `frontend/src/app/laws/[id]/update-banner.tsx` — error state, error row rendering, replace silent catches.
- `frontend/src/lib/api.ts` — update `checkUpdates` response type.
- `backend/tests/test_version_discovery.py` (or new file) — new tests per the test plan.
