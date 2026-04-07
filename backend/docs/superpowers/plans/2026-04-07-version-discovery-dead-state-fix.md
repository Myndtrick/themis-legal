# Version Discovery Dead-State Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the chicken-and-egg deadlock that prevents the law-detail "Check now" flow from working when no `LawVersion` is marked `is_current` in production, while preserving the strict semantic that `is_current=True` means "matches what legislatie.just.ro currently considers in force".

**Architecture:** Decouple "probe ver_id" (what we send to legislatie.just.ro to fetch the version history) from "is_current LawVersion" (what we display to the user). A new helper picks any usable ver_id we have. Discovery becomes self-healing by re-deriving `LawVersion.is_current` from `KnownVersion.is_current` at the end of every run. The legacy `check-updates` endpoint becomes a thin wrapper around discovery — it no longer auto-imports. The frontend stops swallowing errors silently and renders an inline error row.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.x (backend); Next.js / React / TypeScript (frontend); pytest (backend tests).

**Spec:** `backend/docs/superpowers/specs/2026-04-07-version-discovery-dead-state-fix-design.md`

---

## File Structure

**Backend files modified:**
- `backend/app/services/version_discovery.py` — new helper `_get_probe_ver_id`, rewritten `discover_versions_for_law`, new home for `_recalculate_current_version` (moved from `laws.py`).
- `backend/app/routers/laws.py` — `check_law_updates` rewritten as a thin wrapper, `_recalculate_current_version` definition removed, two existing callers (`import_known_version`, `_background_delete_single_version`) updated to import the function from `app.services.version_discovery`.
- `backend/tests/test_version_discovery.py` — new tests covering the probe helper, no-current-version self-heal, and the dead-state-preserving behaviour.
- `backend/tests/test_laws_router.py` *(create if missing — otherwise extend existing router test file)* — new tests covering the rewritten `check-updates` endpoint.

**Frontend files modified:**
- `frontend/src/lib/api.ts` — `checkUpdates` response type changes from `{has_update, message}` to `{discovered, last_checked_at}`.
- `frontend/src/app/laws/[id]/update-banner.tsx` — add `error` state, replace silent `catch {}` blocks with error-setting handlers, render an inline error row.

**No schema changes. No migrations. No data scripts.**

---

## Conventions

**Test command (backend):**
```bash
cd backend && uv run pytest tests/<file> -v
```

**Test command (frontend):** No frontend tests are added in this plan — the frontend changes are verified manually per the spec's test plan section.

**Commit style:** Conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`). Each task ends with a single commit.

**TDD discipline:** Every backend task that adds behaviour follows the red-green sequence: write a failing test, run it to confirm it fails, write the minimal implementation, run it to confirm it passes, commit.

---

## Task 1: Move `_recalculate_current_version` from `laws.py` to `version_discovery.py`

**Why first:** This is a pure refactor with zero behaviour change. Doing it first lets later tasks call the function from inside `version_discovery.py` without an import cycle, and keeps the diff small in each subsequent task.

**Files:**
- Modify: `backend/app/services/version_discovery.py` — add the function near the bottom of the file, before `seed_known_versions_from_imported`.
- Modify: `backend/app/routers/laws.py:1394-1417` — delete the function definition.
- Modify: `backend/app/routers/laws.py` — at both call sites (currently `_recalculate_current_version(db, law_id)` on line 1023 inside `import_known_version` and on line 1425 inside `_background_delete_single_version`), the function is in the same module so no import is needed. After the move they need an import.

- [ ] **Step 1: Verify the existing test suite is green before changing anything**

Run: `cd backend && uv run pytest tests/test_version_discovery.py -v`
Expected: all existing tests pass.

- [ ] **Step 2: Add `_recalculate_current_version` to `version_discovery.py`**

In `backend/app/services/version_discovery.py`, append the following function **before** `seed_known_versions_from_imported` (which is currently the last function in the file):

```python
def _recalculate_current_version(db: Session, law_id: int) -> None:
    """Set is_current on imported versions based on KnownVersion source of truth.

    Only the imported version whose ver_id matches the KnownVersion that
    LegislatieJust considers current gets is_current=True. If that version
    is not imported, no imported version is marked current.

    Also backfills missing date_in_force from KnownVersion data.
    """
    all_known = db.query(KnownVersion).filter(KnownVersion.law_id == law_id).all()
    known_map = {kv.ver_id: kv for kv in all_known}

    current_known = next((kv for kv in all_known if kv.is_current), None)

    all_imported = db.query(LawVersion).filter(LawVersion.law_id == law_id).all()
    for v in all_imported:
        v.is_current = (
            current_known is not None and v.ver_id == current_known.ver_id
        )
        if v.date_in_force is None and v.ver_id in known_map:
            v.date_in_force = known_map[v.ver_id].date_in_force
```

This is a verbatim copy from `laws.py:1394-1417`. No logic change.

- [ ] **Step 3: Delete the function definition from `laws.py`**

In `backend/app/routers/laws.py`, delete lines 1394-1417 (the entire `def _recalculate_current_version(...)` block including its docstring).

- [ ] **Step 4: Add the import in `laws.py` and verify both call sites still resolve**

At the top of `backend/app/routers/laws.py`, find the existing block of `from app.services...` imports and add:

```python
from app.services.version_discovery import _recalculate_current_version
```

Verify the two existing call sites are unchanged in spelling: `_recalculate_current_version(db, law_id)` inside `import_known_version` and inside `_background_delete_single_version`. They should now resolve via the imported name.

- [ ] **Step 5: Run the existing test suite to confirm the move is behaviour-neutral**

Run: `cd backend && uv run pytest tests/test_version_discovery.py tests/test_law_mapping_versions.py tests/test_known_version_model.py -v`
Expected: all existing tests still pass (no new failures introduced by the move).

- [ ] **Step 6: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/version_discovery.py backend/app/routers/laws.py
git commit -m "refactor(backend): move _recalculate_current_version into version_discovery"
```

---

## Task 2: Add `_get_probe_ver_id` helper with TDD

**Why:** This is the new abstraction that lets the discover/check flow stop hard-requiring an `is_current` LawVersion.

**Files:**
- Test: `backend/tests/test_version_discovery.py` — add 4 new test functions.
- Modify: `backend/app/services/version_discovery.py` — add the helper function.

- [ ] **Step 1: Write the failing tests**

Append the following test functions to `backend/tests/test_version_discovery.py`:

```python
def test_probe_ver_id_prefers_is_current_law_version():
    """When a LawVersion is marked is_current, the probe helper returns its ver_id."""
    db = _make_db()
    law = Law(title="Test", law_number="100", law_year=2020)
    db.add(law)
    db.flush()

    db.add(LawVersion(law_id=law.id, ver_id="OLD",
                      date_in_force=datetime.date(2020, 1, 1), is_current=False))
    db.add(LawVersion(law_id=law.id, ver_id="CURRENT",
                      date_in_force=datetime.date(2024, 6, 1), is_current=True))
    db.commit()

    from app.services.version_discovery import _get_probe_ver_id
    assert _get_probe_ver_id(db, law) == "CURRENT"


def test_probe_ver_id_falls_back_to_newest_law_version_by_date():
    """When no LawVersion is_current, the probe helper returns the newest by date_in_force."""
    db = _make_db()
    law = Law(title="Test", law_number="100", law_year=2020)
    db.add(law)
    db.flush()

    db.add(LawVersion(law_id=law.id, ver_id="OLDEST",
                      date_in_force=datetime.date(2020, 1, 1), is_current=False))
    db.add(LawVersion(law_id=law.id, ver_id="NEWEST",
                      date_in_force=datetime.date(2024, 6, 1), is_current=False))
    db.add(LawVersion(law_id=law.id, ver_id="MIDDLE",
                      date_in_force=datetime.date(2022, 3, 1), is_current=False))
    db.commit()

    from app.services.version_discovery import _get_probe_ver_id
    assert _get_probe_ver_id(db, law) == "NEWEST"


def test_probe_ver_id_falls_back_to_newest_known_version_when_no_imports():
    """When no LawVersions exist at all, the probe helper returns the newest KnownVersion."""
    db = _make_db()
    law = Law(title="Test", law_number="100", law_year=2020)
    db.add(law)
    db.flush()

    db.add(KnownVersion(law_id=law.id, ver_id="KV_OLD",
                        date_in_force=datetime.date(2020, 1, 1),
                        is_current=False, discovered_at=datetime.datetime.utcnow()))
    db.add(KnownVersion(law_id=law.id, ver_id="KV_NEW",
                        date_in_force=datetime.date(2024, 6, 1),
                        is_current=True, discovered_at=datetime.datetime.utcnow()))
    db.commit()

    from app.services.version_discovery import _get_probe_ver_id
    assert _get_probe_ver_id(db, law) == "KV_NEW"


def test_probe_ver_id_returns_none_when_truly_empty():
    """A law with no LawVersions and no KnownVersions returns None."""
    db = _make_db()
    law = Law(title="Test", law_number="100", law_year=2020)
    db.add(law)
    db.commit()

    from app.services.version_discovery import _get_probe_ver_id
    assert _get_probe_ver_id(db, law) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_version_discovery.py::test_probe_ver_id_prefers_is_current_law_version tests/test_version_discovery.py::test_probe_ver_id_falls_back_to_newest_law_version_by_date tests/test_version_discovery.py::test_probe_ver_id_falls_back_to_newest_known_version_when_no_imports tests/test_version_discovery.py::test_probe_ver_id_returns_none_when_truly_empty -v`
Expected: all 4 fail with `ImportError: cannot import name '_get_probe_ver_id'`.

- [ ] **Step 3: Implement the helper**

In `backend/app/services/version_discovery.py`, add this function near the top of the file, immediately after the existing `_parse_date` helper (around line 28):

```python
def _get_probe_ver_id(db: Session, law: Law) -> str | None:
    """Pick a ver_id we can use as an entry point when fetching upstream history.

    Order of preference:
      1. The is_current=True LawVersion (when the law is up to date).
      2. The newest LawVersion by date_in_force (we have imports but none are current).
      3. The newest KnownVersion by date_in_force (discovery has run but nothing is imported).
      4. None (genuine empty state — the law has no versions at all).

    Safe because legislatie.just.ro returns the same `history` list regardless of
    which version's page you fetch.
    """
    current_lv = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)  # noqa: E712
        .first()
    )
    if current_lv:
        return current_lv.ver_id

    newest_lv = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.date_in_force.is_not(None))
        .order_by(LawVersion.date_in_force.desc())
        .first()
    )
    if newest_lv:
        return newest_lv.ver_id

    # Last-resort fallback: any LawVersion at all (date may be NULL)
    any_lv = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id)
        .first()
    )
    if any_lv:
        return any_lv.ver_id

    newest_kv = (
        db.query(KnownVersion)
        .filter(KnownVersion.law_id == law.id)
        .order_by(KnownVersion.date_in_force.desc())
        .first()
    )
    if newest_kv:
        return newest_kv.ver_id

    return None
```

- [ ] **Step 4: Run the four new tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_version_discovery.py -k "probe_ver_id" -v`
Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/version_discovery.py backend/tests/test_version_discovery.py
git commit -m "feat(backend): add _get_probe_ver_id helper for version discovery"
```

---

## Task 3: Make `discover_versions_for_law` use the probe helper and self-heal `LawVersion.is_current`

**Why:** This is the core fix. After this task, discovery works on laws with no `is_current` LawVersion, and it re-derives `LawVersion.is_current` from `KnownVersion.is_current` at the end of every run.

**Files:**
- Test: `backend/tests/test_version_discovery.py` — add 3 new tests.
- Modify: `backend/app/services/version_discovery.py:30-148` — replace the `is_current` lookup, base the synthetic-history-entry on the probe row, call `_recalculate_current_version` at the end.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_version_discovery.py`:

```python
def test_discover_versions_works_without_is_current_law_version():
    """Discovery succeeds when no LawVersion has is_current=True."""
    db = _make_db()
    law = Law(title="Test", law_number="200", law_year=2020)
    db.add(law)
    db.flush()
    # Imported versions, none marked current (the dead state)
    db.add(LawVersion(law_id=law.id, ver_id="V1",
                      date_in_force=datetime.date(2024, 1, 1), is_current=False))
    db.add(LawVersion(law_id=law.id, ver_id="V2",
                      date_in_force=datetime.date(2024, 6, 1), is_current=False))
    db.commit()

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "V3", "date": "2024-12-01"},
                {"ver_id": "V2", "date": "2024-06-01"},
                {"ver_id": "V1", "date": "2024-01-01"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law
    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        new_count = discover_versions_for_law(db, law)

    assert new_count == 1  # V3 is new
    known_ids = {kv.ver_id for kv in
                 db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()}
    assert known_ids == {"V1", "V2", "V3"}
    assert law.last_checked_at is not None


def test_discover_versions_self_heals_law_version_is_current():
    """When KnownVersion.is_current points to an imported ver_id, the LawVersion's
    is_current flag is flipped to True at the end of discovery."""
    db = _make_db()
    law = Law(title="Test", law_number="300", law_year=2020)
    db.add(law)
    db.flush()
    db.add(LawVersion(law_id=law.id, ver_id="V1",
                      date_in_force=datetime.date(2024, 1, 1), is_current=False))
    db.add(LawVersion(law_id=law.id, ver_id="V2",
                      date_in_force=datetime.date(2024, 6, 1), is_current=False))
    db.commit()

    # Discovery will find V2 as the newest in upstream history → mark its
    # KnownVersion is_current=True → recalc should flip LawVersion V2 to is_current=True
    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "V2", "date": "2024-06-01"},
                {"ver_id": "V1", "date": "2024-01-01"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law
    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        discover_versions_for_law(db, law)

    v2 = db.query(LawVersion).filter(LawVersion.ver_id == "V2").one()
    v1 = db.query(LawVersion).filter(LawVersion.ver_id == "V1").one()
    assert v2.is_current is True
    assert v1.is_current is False


def test_discover_versions_preserves_dead_state_correctly():
    """When upstream's current ver_id is NOT imported, no LawVersion is marked current.
    This is semantic B — we're not up to date and the truth is reflected."""
    db = _make_db()
    law = Law(title="Test", law_number="400", law_year=2020)
    db.add(law)
    db.flush()
    db.add(LawVersion(law_id=law.id, ver_id="V1",
                      date_in_force=datetime.date(2024, 1, 1), is_current=False))
    db.commit()

    # Upstream has V2 (newer, not yet imported)
    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "V2", "date": "2024-06-01"},
                {"ver_id": "V1", "date": "2024-01-01"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law
    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        discover_versions_for_law(db, law)

    # KnownVersion V2 should be is_current=True
    kv_v2 = db.query(KnownVersion).filter(KnownVersion.ver_id == "V2").one()
    assert kv_v2.is_current is True

    # But no LawVersion should be marked current (V2 isn't imported)
    current_lvs = db.query(LawVersion).filter(
        LawVersion.law_id == law.id, LawVersion.is_current == True  # noqa: E712
    ).all()
    assert current_lvs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_version_discovery.py::test_discover_versions_works_without_is_current_law_version tests/test_version_discovery.py::test_discover_versions_self_heals_law_version_is_current tests/test_version_discovery.py::test_discover_versions_preserves_dead_state_correctly -v`
Expected: all 3 fail. The first two fail because `discover_versions_for_law` returns 0 early when no `is_current` LawVersion is found (today's behaviour at line 48-50). The third fails because no `_recalculate_current_version` call exists in discovery yet, so `LawVersion.is_current` is never updated (although the test happens to assert the empty case, it will only become reliable after the recalc is added).

- [ ] **Step 3: Replace the entry-point logic in `discover_versions_for_law`**

In `backend/app/services/version_discovery.py`, locate the existing block (currently lines 42-79) inside `discover_versions_for_law`:

```python
    # Get current LawVersion as entry point
    current_version = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)  # noqa: E712
        .first()
    )
    if not current_version:
        logger.warning("No current LawVersion for law %s (%s)", law.id, law.title)
        return 0

    entry_ver_id = current_version.ver_id

    try:
        # First fetch using the current ver_id
        result = fetch_document(entry_ver_id, use_cache=False)
        doc = result["document"]

        history: list[dict] = list(doc.get("history", []))

        # If there's a next_ver, follow it — its history will be more complete
        next_ver = doc.get("next_ver")
        if next_ver:
            next_result = fetch_document(next_ver, use_cache=False)
            next_doc = next_result["document"]
            next_history = next_doc.get("history", [])
            if next_history:
                history = list(next_history)

        # Ensure the original entry ver_id appears in the history
        history_ver_ids = {h["ver_id"] for h in history}
        if entry_ver_id not in history_ver_ids:
            # Add a synthetic entry using the date_in_force from LawVersion
            date_str = (
                current_version.date_in_force.isoformat()
                if current_version.date_in_force
                else ""
            )
            history.append({"ver_id": entry_ver_id, "date": date_str})
```

Replace it with:

```python
    # Pick any usable ver_id as the upstream probe entry point. We do NOT
    # require an is_current LawVersion — see _get_probe_ver_id docstring.
    entry_ver_id = _get_probe_ver_id(db, law)
    if entry_ver_id is None:
        logger.warning("No versions at all for law %s (%s) — skipping discovery", law.id, law.title)
        return 0

    # Resolve a date_in_force to use for the synthetic-history fallback below.
    # Prefer LawVersion (richer source), fall back to KnownVersion.
    probe_lv = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.ver_id == entry_ver_id)
        .first()
    )
    probe_kv = (
        db.query(KnownVersion)
        .filter(KnownVersion.law_id == law.id, KnownVersion.ver_id == entry_ver_id)
        .first()
    )
    probe_date = (
        (probe_lv.date_in_force if probe_lv else None)
        or (probe_kv.date_in_force if probe_kv else None)
    )

    try:
        # First fetch using the probe ver_id
        result = fetch_document(entry_ver_id, use_cache=False)
        doc = result["document"]

        history: list[dict] = list(doc.get("history", []))

        # If there's a next_ver, follow it — its history will be more complete
        next_ver = doc.get("next_ver")
        if next_ver:
            next_result = fetch_document(next_ver, use_cache=False)
            next_doc = next_result["document"]
            next_history = next_doc.get("history", [])
            if next_history:
                history = list(next_history)

        # Ensure the probe ver_id appears in the history
        history_ver_ids = {h["ver_id"] for h in history}
        if entry_ver_id not in history_ver_ids:
            date_str = probe_date.isoformat() if probe_date else ""
            history.append({"ver_id": entry_ver_id, "date": date_str})
```

- [ ] **Step 4: Add the self-heal call at the end of `discover_versions_for_law`**

Still in `backend/app/services/version_discovery.py`, locate the existing block at the end of the function (currently around lines 137-148):

```python
    # Update law.last_checked_at on success
    law.last_checked_at = datetime.datetime.utcnow()

    db.commit()

    logger.info(
        "Discovered %d new version(s) for law %s (%s)",
        new_count,
        law.id,
        law.title,
    )
    return new_count
```

Replace with:

```python
    # Re-derive LawVersion.is_current from the freshly-authoritative
    # KnownVersion.is_current. This is what makes stuck production laws
    # self-heal on first visit after deploy.
    _recalculate_current_version(db, law.id)

    # Update law.last_checked_at on success
    law.last_checked_at = datetime.datetime.utcnow()

    db.commit()

    logger.info(
        "Discovered %d new version(s) for law %s (%s)",
        new_count,
        law.id,
        law.title,
    )
    return new_count
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_version_discovery.py::test_discover_versions_works_without_is_current_law_version tests/test_version_discovery.py::test_discover_versions_self_heals_law_version_is_current tests/test_version_discovery.py::test_discover_versions_preserves_dead_state_correctly -v`
Expected: all 3 pass.

- [ ] **Step 6: Run the full version-discovery test file to make sure existing tests still pass**

Run: `cd backend && uv run pytest tests/test_version_discovery.py -v`
Expected: all tests pass (including the original four). The `test_discover_versions_for_law_finds_new` test still asserts `current[0].ver_id == "300000"` for the KnownVersion is_current — that logic is unchanged.

- [ ] **Step 7: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/services/version_discovery.py backend/tests/test_version_discovery.py
git commit -m "fix(backend): make version discovery work and self-heal without is_current"
```

---

## Task 4: Rewrite `check_law_updates` endpoint as a thin discovery wrapper

**Why:** Removes the duplicated and conflicting "newest date = current" logic, removes the auto-import behaviour that no longer fits the discover→Import flow, and removes the 400 dead state. After this task the production bug is fixed.

**Files:**
- Test: `backend/tests/test_check_updates_endpoint.py` *(create)* — add tests for the new endpoint behaviour.
- Modify: `backend/app/routers/laws.py:1242-1316` — replace the entire `check_law_updates` function body.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_check_updates_endpoint.py` with the following content:

```python
"""Tests for POST /api/laws/{id}/check-updates."""
import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.law import Law, LawVersion, KnownVersion
import app.models.category  # register categories table


@pytest.fixture
def client_and_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()
    yield TestClient(app), db
    db.close()
    app.dependency_overrides.clear()


def _seed_law(db, *, ver_ids_with_dates, current_ver_id=None):
    law = Law(title="Test Law", law_number="500", law_year=2020)
    db.add(law)
    db.flush()
    for vid, d in ver_ids_with_dates:
        db.add(LawVersion(
            law_id=law.id, ver_id=vid, date_in_force=d,
            is_current=(vid == current_ver_id),
        ))
    db.commit()
    return law


def test_check_updates_returns_200_when_no_law_version_is_current(client_and_db):
    """The dead-state bug: previously returned 400. Now returns 200 with discovered count."""
    client, db = client_and_db
    law = _seed_law(db, ver_ids_with_dates=[
        ("V1", datetime.date(2024, 1, 1)),
        ("V2", datetime.date(2024, 6, 1)),
    ], current_ver_id=None)  # nothing is_current

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "V2", "date": "2024-06-01"},
                {"ver_id": "V1", "date": "2024-01-01"},
            ],
        }
    }

    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        response = client.post(f"/api/laws/{law.id}/check-updates")

    assert response.status_code == 200
    body = response.json()
    assert "discovered" in body
    assert "last_checked_at" in body
    assert body["last_checked_at"] is not None


def test_check_updates_does_not_auto_import(client_and_db):
    """The new contract: check-updates only refreshes KnownVersion, never imports text."""
    client, db = client_and_db
    law = _seed_law(db, ver_ids_with_dates=[
        ("V1", datetime.date(2024, 1, 1)),
    ], current_ver_id="V1")

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "V99", "date": "2025-01-01"},  # new upstream version
                {"ver_id": "V1", "date": "2024-01-01"},
            ],
        }
    }

    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        response = client.post(f"/api/laws/{law.id}/check-updates")

    assert response.status_code == 200
    # No new LawVersion should have been created — only KnownVersion
    lv_ids = {lv.ver_id for lv in
              db.query(LawVersion).filter(LawVersion.law_id == law.id).all()}
    assert lv_ids == {"V1"}  # V99 must NOT have been auto-imported

    kv_ids = {kv.ver_id for kv in
              db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()}
    assert "V99" in kv_ids  # but V99 should now be a KnownVersion


def test_check_updates_returns_404_for_unknown_law(client_and_db):
    client, _ = client_and_db
    response = client.post("/api/laws/999999/check-updates")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_check_updates_endpoint.py -v`
Expected: at least the first two fail. `test_check_updates_returns_200_when_no_law_version_is_current` fails with 400 (the current dead-state behaviour). `test_check_updates_does_not_auto_import` fails because the current code auto-imports new history entries.

- [ ] **Step 3: Replace `check_law_updates` in `laws.py`**

In `backend/app/routers/laws.py`, locate the existing `check_law_updates` function (currently lines 1242-1316). Replace the **entire function** with:

```python
@router.post("/{law_id}/check-updates")
def check_law_updates(law_id: int, db: Session = Depends(get_db)):
    """Refresh KnownVersion entries for a single law from legislatie.just.ro.

    Discovery only: writes/updates KnownVersion rows and re-derives
    LawVersion.is_current. Does NOT import any version text — that's the
    user's job via the Import buttons in the law-detail page.
    """
    from app.services.version_discovery import discover_versions_for_law

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

This deletes (by replacement):
- The 400 raised when `current` is None.
- The auto-import branches that called `fetch_and_store_version`.
- The newest-date `is_current` recompute that conflicted with the strict semantic.
- The `detect_law_status` call that only made sense when text was just imported.

- [ ] **Step 4: Run the new endpoint tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_check_updates_endpoint.py -v`
Expected: all 3 pass.

- [ ] **Step 5: Run the broader backend test suite as a regression check**

Run: `cd backend && uv run pytest tests/test_version_discovery.py tests/test_check_updates_endpoint.py tests/test_law_mapping_versions.py tests/test_known_version_model.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add backend/app/routers/laws.py backend/tests/test_check_updates_endpoint.py
git commit -m "fix(backend): rewrite check-updates as discovery-only wrapper"
```

---

## Task 5: Update the frontend `checkUpdates` API client type

**Why:** The endpoint's response shape changes from `{has_update, message}` to `{discovered, last_checked_at}`. The TypeScript type must match.

**Files:**
- Modify: `frontend/src/lib/api.ts:838-842`.

- [ ] **Step 1: Update the type literal**

In `frontend/src/lib/api.ts`, locate lines 838-842:

```ts
    checkUpdates: (id: number) =>
      apiFetch<{ has_update: boolean; message: string }>(
        `/api/laws/${id}/check-updates`,
        { method: "POST" }
      ),
```

Replace with:

```ts
    checkUpdates: (id: number) =>
      apiFetch<{ discovered: number; last_checked_at: string | null }>(
        `/api/laws/${id}/check-updates`,
        { method: "POST" }
      ),
```

- [ ] **Step 2: Run TypeScript build to verify no callers depend on the old shape**

Run: `cd frontend && npm run build` (or whatever build command this project uses — check `package.json` `scripts.build`).
Expected: build succeeds. The only caller is `update-banner.tsx` and it discards the response body, so no consumer code needs updating.

If a caller does break, the only acceptable fix is to remove its dependency on `has_update` / `message` (those fields no longer exist) — there is no feature in this plan that re-introduces them.

- [ ] **Step 3: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): update checkUpdates response type to discovery shape"
```

---

## Task 6: Surface backend errors in the update banner

**Why:** Without this, future bugs in the discovery flow will be silently hidden the same way this one was. The user explicitly asked for backend errors to be visible.

**Files:**
- Modify: `frontend/src/app/laws/[id]/update-banner.tsx`.

- [ ] **Step 1: Add error state to the component**

In `frontend/src/app/laws/[id]/update-banner.tsx`, find the existing `useState` block (lines 52-56):

```tsx
  const [dismissed, setDismissed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [importingVerId, setImportingVerId] = useState<string | null>(null);
  const [importingAll, setImportingAll] = useState(false);
  const [checkedAt, setCheckedAt] = useState(lastCheckedAt);
```

Add a new line below it:

```tsx
  const [dismissed, setDismissed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [importingVerId, setImportingVerId] = useState<string | null>(null);
  const [importingAll, setImportingAll] = useState(false);
  const [checkedAt, setCheckedAt] = useState(lastCheckedAt);
  const [checkError, setCheckError] = useState<string | null>(null);
```

- [ ] **Step 2: Replace the silent catch in the auto-check `useEffect`**

In the same file, locate the auto-check `useEffect` (lines 59-71):

```tsx
  // Auto-check on mount if stale
  useEffect(() => {
    if (!shouldAutoCheck(lastCheckedAt)) return;
    setChecking(true);
    api.laws
      .checkUpdates(lawId)
      .then(() => api.laws.getKnownVersions(lawId))
      .then((data) => {
        onKnownVersionsLoaded(data.versions);
        setCheckedAt(data.last_checked_at);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [lawId, lastCheckedAt, onKnownVersionsLoaded]);
```

Replace the `.catch(() => {})` line so the block becomes:

```tsx
  // Auto-check on mount if stale
  useEffect(() => {
    if (!shouldAutoCheck(lastCheckedAt)) return;
    setChecking(true);
    setCheckError(null);
    api.laws
      .checkUpdates(lawId)
      .then(() => api.laws.getKnownVersions(lawId))
      .then((data) => {
        onKnownVersionsLoaded(data.versions);
        setCheckedAt(data.last_checked_at);
      })
      .catch((e: unknown) => {
        setCheckError(e instanceof Error ? e.message : "Failed to check for updates");
      })
      .finally(() => setChecking(false));
  }, [lawId, lastCheckedAt, onKnownVersionsLoaded]);
```

- [ ] **Step 3: Replace the silent catch in `handleCheckNow`**

In the same file, locate `handleCheckNow` (lines 101-113):

```tsx
  async function handleCheckNow() {
    setChecking(true);
    try {
      await api.laws.checkUpdates(lawId);
      const data = await api.laws.getKnownVersions(lawId);
      onKnownVersionsLoaded(data.versions);
      setCheckedAt(data.last_checked_at);
    } catch {
      // silently fail — user can retry
    } finally {
      setChecking(false);
    }
  }
```

Replace with:

```tsx
  async function handleCheckNow() {
    setChecking(true);
    setCheckError(null);
    try {
      await api.laws.checkUpdates(lawId);
      const data = await api.laws.getKnownVersions(lawId);
      onKnownVersionsLoaded(data.versions);
      setCheckedAt(data.last_checked_at);
    } catch (e: unknown) {
      setCheckError(e instanceof Error ? e.message : "Failed to check for updates");
    } finally {
      setChecking(false);
    }
  }
```

- [ ] **Step 4: Render the error row inside the no-new-versions banner**

In the same file, locate the "Up to date" branch (lines 156-176):

```tsx
  // Up to date
  if (newVersions.length === 0 || dismissed) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <svg className="w-5 h-5 text-green-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <p className="text-sm font-medium text-green-800">No new versions</p>
            <p className="text-sm text-gray-500">{checkedText} &middot; All available versions are imported</p>
          </div>
        </div>
        <button
          onClick={handleCheckNow}
          className="px-3 py-1.5 text-sm font-medium text-gray-600 bg-white border border-gray-300 rounded-md hover:bg-gray-100 transition-colors shrink-0"
        >
          Check now
        </button>
      </div>
    );
  }
```

Replace with:

```tsx
  // Up to date
  if (newVersions.length === 0 || dismissed) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-green-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <p className="text-sm font-medium text-green-800">No new versions</p>
              <p className="text-sm text-gray-500">{checkedText} &middot; All available versions are imported</p>
              {checkError && (
                <p className="text-sm text-red-600 mt-1">
                  Check failed: {checkError}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={handleCheckNow}
            className="px-3 py-1.5 text-sm font-medium text-gray-600 bg-white border border-gray-300 rounded-md hover:bg-gray-100 transition-colors shrink-0"
          >
            {checkError ? "Retry" : "Check now"}
          </button>
        </div>
      </div>
    );
  }
```

- [ ] **Step 5: Render the same error row inside the new-versions-available banner**

In the same file, locate the "New versions available" return block (starts around line 181, `return ( <div className="rounded-lg border border-amber-200 ...`).

Inside the existing `<div>` immediately after `<p className="text-sm text-amber-700/70">{checkedText} &middot; ...</p>` (around line 192-195):

```tsx
            <p className="text-sm text-amber-700/70">
              {checkedText} &middot; {newVersions.length} version{newVersions.length !== 1 ? "s" : ""} not yet imported
            </p>
```

Add a new conditional paragraph immediately after:

```tsx
            <p className="text-sm text-amber-700/70">
              {checkedText} &middot; {newVersions.length} version{newVersions.length !== 1 ? "s" : ""} not yet imported
            </p>
            {checkError && (
              <p className="text-sm text-red-600 mt-1">
                Check failed: {checkError}
              </p>
            )}
```

- [ ] **Step 6: Manual verification**

The frontend has no automated tests for this banner; verify manually:

1. Run the frontend dev server: `cd frontend && npm run dev`.
2. Open a law page where `last_checked_at` is null (or stale). Confirm no error row renders on a successful check.
3. With browser devtools, throttle network or block `POST /api/laws/*/check-updates` (e.g. via Network tab → Block request URL). Reload the page. Confirm the banner now shows the "Check failed: <message>" red row beneath the existing text, and the button label changes to "Retry".
4. Unblock the request and click Retry. Confirm the error row disappears.

If any step doesn't behave as described, fix the JSX before committing.

- [ ] **Step 7: Commit**

```bash
cd /Users/anaandrei/projects/themis-legal
git add frontend/src/app/laws/\[id\]/update-banner.tsx
git commit -m "feat(frontend): surface check-updates errors in the update banner"
```

---

## Task 7: Full backend regression sweep

**Why:** This is a refactor-heavy plan touching shared code paths. Run the entire backend suite to catch anything we missed.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && uv run pytest -v`
Expected: all tests pass. If any unrelated test fails, stop and investigate — do not paper over the failure.

- [ ] **Step 2: If everything passes, no commit is needed. If any test failed, fix it (in a new task) and commit the fix separately**

There is intentionally nothing to commit in this task on the green path. This task exists to enforce a regression checkpoint.

---

## Task 8: Manual end-to-end reproduction of the user's bug

**Why:** The whole point of this work is the production scenario. Reproduce it locally before declaring done.

- [ ] **Step 1: Seed a local DB into the dead state**

Open a Python shell against the local SQLite DB the dev server uses (`legal_library.db` in the project root). Pick a law you can experiment on (or import a fresh one). Force its dead state:

```python
from app.database import SessionLocal
from app.models.law import Law, LawVersion, KnownVersion

db = SessionLocal()
law = db.query(Law).filter(Law.title.like("%Codul fiscal%")).first()  # or whichever
# Force the dead state
db.query(LawVersion).filter(LawVersion.law_id == law.id).update({"is_current": False})
db.query(KnownVersion).filter(KnownVersion.law_id == law.id).update({"is_current": False})
law.last_checked_at = None
db.commit()
print("Dead state seeded for law", law.id)
```

- [ ] **Step 2: Confirm the bug reproduces against the OLD branch first (optional, for sanity)**

Optional sanity check: stash the working tree, check out `main` before this PR's commits, restart the backend, visit the law page, observe "Never checked" + Check now does nothing. Then return to the feature branch.

- [ ] **Step 3: Restart the backend and frontend dev servers on the feature branch**

```bash
cd backend && uv run uvicorn app.main:app --reload &
cd frontend && npm run dev &
```

- [ ] **Step 4: Visit the law's page in the browser**

Open `http://localhost:3000/laws/<id>` for the seeded law. The auto-check `useEffect` fires `POST /api/laws/<id>/check-updates`.

Observe: the banner spinner appears, then resolves. After the check completes:
- `last_checked_at` is now populated (banner no longer says "Never checked").
- If upstream's current version is already imported, the imported-versions table shows the green "Current version" badge on the matching row.
- If upstream's current version is NOT imported (e.g. you also deleted the newest version), the amber "1 new version available" banner appears with an Import button, and no row in the imported table is marked current (this is the expected semantic-B behaviour).

- [ ] **Step 5: Verify the import flow heals the law**

Click Import on the missing newest version. Wait for it to complete. Confirm that the green "Current version" badge now appears on the freshly imported row.

- [ ] **Step 6: Verify error surfacing**

In browser devtools → Network tab, block the URL `**/check-updates`. Reload the page. Confirm the banner now shows a red "Check failed: ..." row and a "Retry" button. Unblock and click Retry — the error should clear.

- [ ] **Step 7: Document any issues**

If any of the above does not behave as expected, do not declare done. File the discrepancy (or fix it in a new task) and re-run the manual flow before merging.

---

## Task 9: Final spec-coverage self-check

- [ ] **Step 1: Re-read the spec and verify every requirement is implemented**

Open `backend/docs/superpowers/specs/2026-04-07-version-discovery-dead-state-fix-design.md`.

Walk through each numbered point in the **Design** section:

1. `_get_probe_ver_id` helper added → Task 2 ✓
2. `discover_versions_for_law` rewritten to use it + self-heal → Task 3 ✓
3. `_recalculate_current_version` moved → Task 1 ✓
4. `check_law_updates` rewritten as thin wrapper → Task 4 ✓
5. No changes to `import_known_version` etc → Tasks 1-4 (the function move is the only touch on those callers) ✓
6. Frontend error surfacing → Task 6 ✓
7. API client type update → Task 5 ✓
8. No schema changes → confirm no migration files, no model edits ✓

Walk through the **Test plan** section:

1. `_get_probe_ver_id` ordering → Task 2 (4 tests) ✓
2. discovery works without is_current → Task 3 ✓
3. discovery self-heals → Task 3 ✓
4. discovery preserves dead state → Task 3 ✓
5. endpoint smoke test → Task 4 ✓
6. endpoint no longer auto-imports → Task 4 ✓
7. full reproduction → Task 8 (manual) ✓
8. banner surfaces errors → Task 6 (manual step 6) ✓
9. banner clears error on retry → Task 6 (manual step 6) ✓
10. manual prod-scenario reproduction → Task 8 ✓

If any item is missing, add it as a new task before declaring the plan complete.

- [ ] **Step 2: No commit — this is a checklist task**
