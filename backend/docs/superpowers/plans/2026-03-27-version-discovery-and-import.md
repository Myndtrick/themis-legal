# Version Discovery & Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate version discovery (lightweight metadata) from version import (full text extraction), giving users explicit control over what lives in their library while ensuring the system always knows what officially exists.

**Architecture:** New `KnownVersion` model stores metadata-only version records discovered from legislatie.just.ro. `LawVersion` continues to hold imported versions with full text. The daily checker writes to `KnownVersion` only; imports happen on user action. The pipeline queries both tables to determine version status.

**Tech Stack:** SQLAlchemy (SQLite), FastAPI, Next.js (React), APScheduler

**Spec:** `backend/docs/superpowers/specs/2026-03-27-version-discovery-and-import-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `backend/app/models/law.py` | Modify | Add `KnownVersion` model, add `last_checked_at` to `Law` |
| `backend/app/services/version_discovery.py` | Create | Daily discovery job: fetch history, write `KnownVersion`, update `last_checked_at` |
| `backend/app/services/update_checker.py` | Modify | Remove auto-import, delegate to `version_discovery` |
| `backend/app/services/law_mapping.py` | Modify | Query `KnownVersion` to produce `version_status` per law |
| `backend/app/routers/laws.py` | Modify | Add endpoints for known versions, single-version import, bulk import; extend GET law detail |
| `frontend/src/lib/api.ts` | Modify | Add types for `KnownVersion`, new API methods |
| `frontend/src/app/laws/[id]/page.tsx` | Modify | Add Versions section with known vs imported display |
| `frontend/src/app/laws/[id]/versions-section.tsx` | Create | Client component for version list with import controls |
| `frontend/src/app/laws/components/law-card.tsx` | Modify | Add "new version available" badge |
| `backend/app/main.py` | Modify | Update scheduler to call discovery job; register model |
| `backend/tests/test_version_discovery.py` | Create | Tests for discovery service |
| `backend/tests/test_law_mapping_versions.py` | Create | Tests for version-aware law mapping |

---

### Task 1: Add `KnownVersion` Model and `last_checked_at` Field

**Files:**
- Modify: `backend/app/models/law.py`
- Modify: `backend/app/main.py:9` (ensure model registration)
- Test: `backend/tests/test_known_version_model.py`

- [ ] **Step 1: Write the test for `KnownVersion` model creation**

```python
# backend/tests/test_known_version_model.py
"""Tests for the KnownVersion model and Law.last_checked_at field."""
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models.law import Law, LawVersion, KnownVersion


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_known_version_creation():
    db = _make_db()
    law = Law(title="Legea societatilor", law_number="31", law_year=1990)
    db.add(law)
    db.flush()

    kv = KnownVersion(
        law_id=law.id,
        ver_id="267625",
        date_in_force=datetime.date(2024, 12, 6),
        is_current=True,
        discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv)
    db.commit()

    result = db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    assert len(result) == 1
    assert result[0].ver_id == "267625"
    assert result[0].is_current is True


def test_known_version_unique_constraint():
    db = _make_db()
    law = Law(title="Test law", law_number="1", law_year=2020)
    db.add(law)
    db.flush()

    kv1 = KnownVersion(
        law_id=law.id, ver_id="111", date_in_force=datetime.date(2020, 1, 1),
        discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv1)
    db.commit()

    kv2 = KnownVersion(
        law_id=law.id, ver_id="111", date_in_force=datetime.date(2020, 6, 1),
        discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv2)
    try:
        db.commit()
        assert False, "Should have raised IntegrityError"
    except Exception:
        db.rollback()


def test_law_last_checked_at_default_null():
    db = _make_db()
    law = Law(title="Test", law_number="2", law_year=2021)
    db.add(law)
    db.commit()
    assert law.last_checked_at is None


def test_law_last_checked_at_can_be_set():
    db = _make_db()
    law = Law(title="Test", law_number="3", law_year=2022)
    db.add(law)
    db.flush()
    law.last_checked_at = datetime.datetime(2026, 3, 27, 3, 15)
    db.commit()
    assert law.last_checked_at == datetime.datetime(2026, 3, 27, 3, 15)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_known_version_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'KnownVersion'` and `Law` has no `last_checked_at`

- [ ] **Step 3: Add `KnownVersion` model and `last_checked_at` to `Law`**

In `backend/app/models/law.py`, add after the `LawVersion` class (after line 103):

```python
class KnownVersion(Base):
    __tablename__ = "known_versions"
    __table_args__ = (
        UniqueConstraint("law_id", "ver_id", name="uq_known_version_law_ver"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("laws.id"), nullable=False)
    ver_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    date_in_force: Mapped[datetime.date] = mapped_column(nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    discovered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )

    law: Mapped["Law"] = relationship(back_populates="known_versions")
```

Add the import at the top of the file (line 4):
```python
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
```

Add to the `Law` class (after line 71, before `created_at`):
```python
    last_checked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
```

Add the relationship to `Law` (after the `versions` relationship, line 76):
```python
    known_versions: Mapped[list["KnownVersion"]] = relationship(
        back_populates="law", cascade="all, delete-orphan"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_known_version_model.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add backend/app/models/law.py backend/tests/test_known_version_model.py
git commit -m "feat: add KnownVersion model and Law.last_checked_at field"
```

---

### Task 2: Create Version Discovery Service

**Files:**
- Create: `backend/app/services/version_discovery.py`
- Test: `backend/tests/test_version_discovery.py`

- [ ] **Step 1: Write the test for the discovery service**

```python
# backend/tests/test_version_discovery.py
"""Tests for the version discovery service."""
import datetime
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.law import Law, LawVersion, KnownVersion


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _make_law_with_version(db, law_number="31", law_year=1990, ver_id="267625", date_in_force=None):
    law = Law(title=f"Law {law_number}/{law_year}", law_number=law_number, law_year=law_year)
    db.add(law)
    db.flush()
    version = LawVersion(
        law_id=law.id,
        ver_id=ver_id,
        date_in_force=date_in_force or datetime.date(2024, 12, 6),
        is_current=True,
    )
    db.add(version)
    db.commit()
    return law


def test_discover_versions_for_law_finds_new():
    """Discovery finds versions in history that aren't in KnownVersion yet."""
    db = _make_db()
    law = _make_law_with_version(db)

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "300000", "date": "2025-09-15"},
                {"ver_id": "267625", "date": "2024-12-06"},
                {"ver_id": "250000", "date": "2024-06-15"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law

    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        new_count = discover_versions_for_law(db, law)

    assert new_count == 2  # 300000 and 250000 are new
    known = db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    assert len(known) == 3  # all 3 history entries
    assert law.last_checked_at is not None

    # Check is_current set correctly (newest = first in history)
    current = [kv for kv in known if kv.is_current]
    assert len(current) == 1
    assert current[0].ver_id == "300000"


def test_discover_versions_skips_existing():
    """Versions already in KnownVersion are not re-inserted."""
    db = _make_db()
    law = _make_law_with_version(db)

    # Pre-populate one known version
    kv = KnownVersion(
        law_id=law.id, ver_id="267625",
        date_in_force=datetime.date(2024, 12, 6),
        is_current=True, discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv)
    db.commit()

    mock_result = {
        "document": {
            "next_ver": None,
            "history": [
                {"ver_id": "267625", "date": "2024-12-06"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law

    with patch("app.services.version_discovery.fetch_document", return_value=mock_result):
        new_count = discover_versions_for_law(db, law)

    assert new_count == 0
    known = db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    assert len(known) == 1


def test_discover_versions_handles_fetch_error():
    """If legislatie.just.ro is unreachable, last_checked_at stays unchanged."""
    db = _make_db()
    law = _make_law_with_version(db)
    original_checked = law.last_checked_at  # None

    from app.services.version_discovery import discover_versions_for_law

    with patch("app.services.version_discovery.fetch_document", side_effect=Exception("Connection refused")):
        new_count = discover_versions_for_law(db, law)

    assert new_count == 0
    assert law.last_checked_at == original_checked  # unchanged


def test_discover_versions_uses_next_ver():
    """Discovery follows next_ver pointer to find newer version."""
    db = _make_db()
    law = _make_law_with_version(db)

    # First fetch returns next_ver
    first_result = {
        "document": {
            "next_ver": "300000",
            "history": [{"ver_id": "267625", "date": "2024-12-06"}],
        }
    }
    # Second fetch (of the next_ver) returns its own history
    second_result = {
        "document": {
            "next_ver": None,
            "date_in_force": "2025-09-15",
            "history": [
                {"ver_id": "300000", "date": "2025-09-15"},
                {"ver_id": "267625", "date": "2024-12-06"},
            ],
        }
    }

    from app.services.version_discovery import discover_versions_for_law

    with patch("app.services.version_discovery.fetch_document", side_effect=[first_result, second_result]):
        new_count = discover_versions_for_law(db, law)

    known = db.query(KnownVersion).filter(KnownVersion.law_id == law.id).all()
    ver_ids = {kv.ver_id for kv in known}
    assert "300000" in ver_ids
    assert "267625" in ver_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_version_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.version_discovery'`

- [ ] **Step 3: Implement the discovery service**

```python
# backend/app/services/version_discovery.py
"""Version discovery service — discover official versions without importing them.

Fetches version history from legislatie.just.ro and writes metadata to the
KnownVersion table. Does NOT import full text or modify LawVersion.
"""

import logging
import time
from datetime import date as date_type, datetime

from sqlalchemy.orm import Session

from app.models.law import KnownVersion, Law, LawVersion
from app.services.fetcher import fetch_document

logger = logging.getLogger(__name__)


def discover_versions_for_law(db: Session, law: Law) -> int:
    """Discover all official versions for a single law.

    Fetches the history list from legislatie.just.ro and inserts any
    previously unknown versions into KnownVersion.

    Returns the number of newly discovered versions.
    Does NOT modify last_checked_at on failure.
    """
    # Get current version to use as entry point
    current = (
        db.query(LawVersion)
        .filter(LawVersion.law_id == law.id, LawVersion.is_current == True)
        .first()
    )
    if not current:
        logger.warning(f"No current version for law {law.id} ({law.title})")
        return 0

    # Fetch document metadata from legislatie.just.ro
    try:
        result = fetch_document(current.ver_id, use_cache=False)
    except Exception as e:
        logger.warning(f"Failed to fetch {current.ver_id} for law {law.id}: {e}")
        return 0

    doc = result.get("document", {})
    history = doc.get("history", [])

    # If there's a next_ver, follow it to get a more complete history
    next_ver = doc.get("next_ver")
    if next_ver:
        try:
            next_result = fetch_document(next_ver, use_cache=False)
            next_history = next_result.get("document", {}).get("history", [])
            # Merge histories: use the longer one as base
            if len(next_history) > len(history):
                history = next_history
            # Ensure the next_ver itself is in the history
            next_date = next_result.get("document", {}).get("date_in_force")
            next_in_history = any(h["ver_id"] == next_ver for h in history)
            if not next_in_history:
                history.insert(0, {"ver_id": next_ver, "date": next_date})
        except Exception as e:
            logger.warning(f"Failed to follow next_ver {next_ver}: {e}")
            # Still add next_ver as discovered even without date
            if not any(h.get("ver_id") == next_ver for h in history):
                history.insert(0, {"ver_id": next_ver, "date": None})

    # Ensure the current ver_id is in the history
    if not any(h.get("ver_id") == current.ver_id for h in history):
        history.append({
            "ver_id": current.ver_id,
            "date": str(current.date_in_force) if current.date_in_force else None,
        })

    # Get existing known version ver_ids for this law
    existing_ver_ids = {
        row[0]
        for row in db.query(KnownVersion.ver_id)
        .filter(KnownVersion.law_id == law.id)
        .all()
    }

    # Insert new known versions
    new_count = 0
    now = datetime.utcnow()
    for entry in history:
        vid = entry.get("ver_id")
        if not vid or vid in existing_ver_ids:
            continue

        date_str = entry.get("date")
        try:
            dif = date_type.fromisoformat(date_str) if date_str else date_type(1900, 1, 1)
        except (ValueError, TypeError):
            dif = date_type(1900, 1, 1)

        kv = KnownVersion(
            law_id=law.id,
            ver_id=vid,
            date_in_force=dif,
            is_current=False,
            discovered_at=now,
        )
        db.add(kv)
        existing_ver_ids.add(vid)
        new_count += 1

    # Update is_current flags: newest date_in_force = current
    if existing_ver_ids:
        all_known = (
            db.query(KnownVersion)
            .filter(KnownVersion.law_id == law.id)
            .all()
        )
        if all_known:
            for kv in all_known:
                kv.is_current = False
            newest = max(all_known, key=lambda kv: kv.date_in_force)
            newest.is_current = True

    # Update last_checked_at on success
    law.last_checked_at = now
    db.commit()

    return new_count


def run_daily_discovery(rate_limit_delay: float = 2.0) -> dict:
    """Run version discovery for all laws in the database.

    This is the daily job that replaces the old auto-import update checker.
    """
    from app.database import SessionLocal
    from app.models.notification import AuditLog, Notification

    db = SessionLocal()
    results = {"checked": 0, "discovered": 0, "errors": 0, "details": []}

    try:
        laws = db.query(Law).all()
        logger.info(f"Running version discovery for {len(laws)} laws")

        for law in laws:
            results["checked"] += 1

            # Skip laws without any imported version (no ver_id to start from)
            has_version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == law.id)
                .first()
            )
            if not has_version:
                results["details"].append({"law": law.title, "status": "no_version"})
                continue

            time.sleep(rate_limit_delay)

            new_count = discover_versions_for_law(db, law)

            if new_count > 0:
                results["discovered"] += new_count
                results["details"].append({
                    "law": law.title,
                    "status": "new_versions",
                    "count": new_count,
                })
                # Create notification for new versions
                notification = Notification(
                    title=f"New versions found: {law.title}",
                    message=(
                        f"{new_count} new version(s) of Legea {law.law_number}/{law.law_year} "
                        f"discovered on legislatie.just.ro. Import from the Legal Library."
                    ),
                    notification_type="law_update",
                )
                db.add(notification)
                db.commit()
            else:
                results["details"].append({"law": law.title, "status": "up_to_date"})

        # Audit log
        audit = AuditLog(
            action="version_discovery",
            module="legal_library",
            details=(
                f"Checked {results['checked']} laws: "
                f"{results['discovered']} new versions discovered, "
                f"{results['errors']} errors"
            ),
        )
        db.add(audit)
        db.commit()

    except Exception as e:
        logger.exception("Version discovery failed")
        db.rollback()
    finally:
        db.close()

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_version_discovery.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add backend/app/services/version_discovery.py backend/tests/test_version_discovery.py
git commit -m "feat: add version discovery service (metadata-only, no auto-import)"
```

---

### Task 3: Wire Up Daily Discovery Job and Refactor Update Checker

**Files:**
- Modify: `backend/app/main.py:19-28` (change scheduled job)
- Modify: `backend/app/services/update_checker.py` (delegate to discovery)

- [ ] **Step 1: Update `main.py` to use discovery job**

In `backend/app/main.py`, replace the `run_update_check` function (lines 19-28):

```python
def run_update_check():
    """Scheduled job: discover new versions for all laws (metadata only)."""
    from app.services.version_discovery import run_daily_discovery

    logger.info("Running scheduled version discovery...")
    results = run_daily_discovery()
    logger.info(
        f"Version discovery complete: {results['checked']} checked, "
        f"{results['discovered']} new versions discovered, {results['errors']} errors"
    )
```

- [ ] **Step 2: Update `update_checker.py` to delegate to discovery**

Replace the contents of `backend/app/services/update_checker.py`:

```python
"""Daily law update checker service.

DEPRECATED: The auto-import behavior has been replaced by version discovery.
This module now delegates to version_discovery.run_daily_discovery().
Retained for backward compatibility with any direct callers.
"""

import logging

from app.services.version_discovery import run_daily_discovery

logger = logging.getLogger(__name__)


def check_for_updates(rate_limit_delay: float = 2.0) -> dict:
    """Check all stored laws for new versions.

    Now delegates to version discovery (metadata-only, no auto-import).
    """
    return run_daily_discovery(rate_limit_delay=rate_limit_delay)
```

- [ ] **Step 3: Verify the app still starts**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add backend/app/main.py backend/app/services/update_checker.py
git commit -m "refactor: replace auto-import checker with discovery-only job"
```

---

### Task 4: Extend Law Mapping to Use `KnownVersion`

**Files:**
- Modify: `backend/app/services/law_mapping.py`
- Test: `backend/tests/test_law_mapping_versions.py`

- [ ] **Step 1: Write the test for version-status-aware law mapping**

```python
# backend/tests/test_law_mapping_versions.py
"""Tests for version-aware law mapping using KnownVersion."""
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.law import KnownVersion, Law, LawVersion
from app.services.law_mapping import check_laws_in_db


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _setup_law_with_versions(db):
    """Create a law with one imported version and three known versions."""
    law = Law(title="Legea societatilor", law_number="31", law_year=1990)
    db.add(law)
    db.flush()

    # Imported version (older)
    lv = LawVersion(
        law_id=law.id, ver_id="250000",
        date_in_force=datetime.date(2024, 6, 15), is_current=True,
    )
    db.add(lv)

    # Known versions
    for vid, dif, current in [
        ("300000", datetime.date(2025, 9, 15), True),
        ("267625", datetime.date(2024, 12, 6), False),
        ("250000", datetime.date(2024, 6, 15), False),
    ]:
        kv = KnownVersion(
            law_id=law.id, ver_id=vid, date_in_force=dif,
            is_current=current, discovered_at=datetime.datetime.utcnow(),
        )
        db.add(kv)

    db.commit()
    return law


def test_version_status_stale():
    """Law has imported version but a newer known version exists."""
    db = _make_db()
    _setup_law_with_versions(db)

    laws = [{"law_number": "31", "law_year": "1990", "role": "PRIMARY"}]
    result = check_laws_in_db(laws, db, law_date_map={"31/1990": "2026-03-27"})

    assert result[0]["availability"] == "available"
    assert result[0]["version_status"] == "stale"
    assert result[0]["official_current_ver_id"] == "300000"
    assert result[0]["official_current_date"] == "2025-09-15"


def test_version_status_up_to_date():
    """Law's current known version is imported."""
    db = _make_db()
    law = Law(title="Test", law_number="5", law_year=2020)
    db.add(law)
    db.flush()

    lv = LawVersion(
        law_id=law.id, ver_id="111", date_in_force=datetime.date(2025, 1, 1),
        is_current=True,
    )
    db.add(lv)

    kv = KnownVersion(
        law_id=law.id, ver_id="111", date_in_force=datetime.date(2025, 1, 1),
        is_current=True, discovered_at=datetime.datetime.utcnow(),
    )
    db.add(kv)
    db.commit()

    laws = [{"law_number": "5", "law_year": "2020", "role": "PRIMARY"}]
    result = check_laws_in_db(laws, db, law_date_map={"5/2020": "2026-03-27"})

    assert result[0]["version_status"] == "up_to_date"


def test_version_status_not_checked():
    """Law exists and is imported but has no KnownVersion records."""
    db = _make_db()
    law = Law(title="Test", law_number="10", law_year=2021)
    db.add(law)
    db.flush()

    lv = LawVersion(
        law_id=law.id, ver_id="222", date_in_force=datetime.date(2024, 1, 1),
        is_current=True,
    )
    db.add(lv)
    db.commit()

    laws = [{"law_number": "10", "law_year": "2021", "role": "PRIMARY"}]
    result = check_laws_in_db(laws, db, law_date_map={"10/2021": "2026-03-27"})

    assert result[0]["availability"] == "available"
    assert result[0]["version_status"] == "not_checked"


def test_version_status_missing_law():
    """Law not in DB at all."""
    db = _make_db()
    laws = [{"law_number": "999", "law_year": "2099", "role": "PRIMARY"}]
    result = check_laws_in_db(laws, db)
    assert result[0]["availability"] == "missing"
    assert result[0]["version_status"] == "not_checked"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_law_mapping_versions.py -v`
Expected: FAIL — `version_status` key not present in results

- [ ] **Step 3: Extend `check_laws_in_db` to query `KnownVersion`**

In `backend/app/services/law_mapping.py`, add the import at line 8:

```python
from app.models.law import KnownVersion, Law, LawVersion
```

Then add the version status check after each law's availability is determined. Replace the entire function body (lines 30-95) with:

```python
    for law in laws:
        law_number = str(law["law_number"])
        law_year = str(law["law_year"])
        law_key = f"{law_number}/{law_year}"

        db_law = (
            db.query(Law)
            .filter(
                Law.law_number == law_number,
                Law.law_year == int(law_year),
            )
            .first()
        )

        if not db_law:
            law["db_law_id"] = None
            law["in_library"] = False
            law["availability"] = "missing"
            law["available_version_date"] = None
            law["version_status"] = "not_checked"
            continue

        law["db_law_id"] = db_law.id
        law["in_library"] = True
        law["title"] = law.get("title") or db_law.title

        # Look up the relevant date for this specific law
        relevant_date = law_date_map.get(law_key) if law_date_map else None

        if relevant_date:
            pd = date_type.fromisoformat(relevant_date)
            version = (
                db.query(LawVersion)
                .filter(
                    LawVersion.law_id == db_law.id,
                    LawVersion.date_in_force <= pd,
                )
                .order_by(LawVersion.date_in_force.desc())
                .first()
            )
            if version:
                law["availability"] = "available"
                law["available_version_date"] = str(version.date_in_force)
            else:
                # No version for this date — check if any version exists
                any_version = (
                    db.query(LawVersion)
                    .filter(LawVersion.law_id == db_law.id)
                    .first()
                )
                if any_version:
                    law["availability"] = "wrong_version"
                    law["available_version_date"] = str(any_version.date_in_force)
                else:
                    law["availability"] = "missing"
                    law["available_version_date"] = None
        else:
            # No date specified — just check if law has any version
            any_version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == db_law.id)
                .first()
            )
            law["availability"] = "available" if any_version else "missing"
            law["available_version_date"] = str(any_version.date_in_force) if any_version else None

        # --- Version status from KnownVersion ---
        current_known = (
            db.query(KnownVersion)
            .filter(KnownVersion.law_id == db_law.id, KnownVersion.is_current == True)
            .first()
        )

        if not current_known:
            # No discovery has run for this law yet
            law["version_status"] = "not_checked"
            continue

        # Check if the current official version is imported
        imported_match = (
            db.query(LawVersion)
            .filter(
                LawVersion.law_id == db_law.id,
                LawVersion.ver_id == current_known.ver_id,
            )
            .first()
        )

        if imported_match:
            law["version_status"] = "up_to_date"
        else:
            law["version_status"] = "stale"
            law["official_current_ver_id"] = current_known.ver_id
            law["official_current_date"] = str(current_known.date_in_force)

    return laws
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/test_law_mapping_versions.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add backend/app/services/law_mapping.py backend/tests/test_law_mapping_versions.py
git commit -m "feat: extend law mapping to produce version_status from KnownVersion"
```

---

### Task 5: Update Pipeline to Use `version_status` Instead of `currency_status`

**Files:**
- Modify: `backend/app/services/pipeline_service.py:1295-1301` (early relevance gate)
- Modify: `backend/app/services/pipeline_service.py:2220-2227` (confidence cap)

The pipeline already checks `currency_status` from the real-time version currency checker. Now that `law_mapping.py` produces `version_status` from `KnownVersion` (a local DB query), we should use it as the primary check, falling back to `currency_status` from the real-time checker when `version_status == "not_checked"`.

- [ ] **Step 1: Update the early relevance gate pause condition**

In `backend/app/services/pipeline_service.py`, modify lines 1295-1301. Replace:

```python
    # Check if any PRIMARY law needs import, has wrong version, or is stale
    primary_laws = [c for c in candidate_laws if c["role"] == "PRIMARY"]
    needs_pause = any(
        law.get("availability") in ("missing", "wrong_version")
        or law.get("currency_status") == "stale"
        for law in primary_laws
    )
```

With:

```python
    # Check if any PRIMARY law needs import, has wrong version, or is stale
    primary_laws = [c for c in candidate_laws if c["role"] == "PRIMARY"]
    needs_pause = any(
        law.get("availability") in ("missing", "wrong_version")
        or law.get("version_status") == "stale"
        or law.get("currency_status") == "stale"
        for law in primary_laws
    )
```

- [ ] **Step 2: Update stale detection in the pause message builder**

In the same function, update the stale laws detection (line 1334). Replace:

```python
        stale = [l for l in primary_laws if l.get("currency_status") == "stale"]
```

With:

```python
        stale = [
            l for l in primary_laws
            if l.get("version_status") == "stale" or l.get("currency_status") == "stale"
        ]
```

- [ ] **Step 3: Update the stale info fields in the pause message**

In the stale message builder (lines 1343-1348), update to use both field sources. Replace:

```python
        if stale:
            names = ", ".join(
                f"{l.get('title', '')} ({l['law_number']}/{l['law_year']}) — "
                f"biblioteca: {l.get('db_latest_date', '?')}, legislatie.just.ro: {l.get('official_latest_date', '?')}"
                for l in stale
            )
            parts.append(f"au versiune mai nouă disponibilă: {names}")
```

With:

```python
        if stale:
            names = ", ".join(
                f"{l.get('title', '')} ({l['law_number']}/{l['law_year']}) — "
                f"biblioteca: {l.get('db_latest_date') or l.get('available_version_date', '?')}, "
                f"legislatie.just.ro: {l.get('official_latest_date') or l.get('official_current_date', '?')}"
                for l in stale
            )
            parts.append(f"au versiune mai nouă disponibilă: {names}")
```

- [ ] **Step 4: Update the preview builder to include version_status**

In the preview builder (lines 1310-1329), add `version_status` to the preview dict. After line 1324 (`"currency_status": ...`), add:

```python
                "version_status": law.get("version_status", "not_checked"),
                "official_current_ver_id": law.get("official_current_ver_id"),
                "official_current_date": law.get("official_current_date"),
```

- [ ] **Step 5: Update confidence cap to include version_status stale**

In the confidence section (lines 2220-2227), update the stale check. Replace:

```python
    # Cap confidence for stale versions (user continued without updating)
    if state.get("stale_versions"):
```

With:

```python
    # Cap confidence for stale versions (user continued without updating)
    # stale_versions comes from resume decisions; version_status comes from KnownVersion
    stale_laws_in_use = [
        c for c in state.get("candidate_laws", [])
        if c.get("version_status") == "stale" and c.get("role") == "PRIMARY"
    ]
    if state.get("stale_versions") or stale_laws_in_use:
```

- [ ] **Step 6: Run existing pipeline tests**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add backend/app/services/pipeline_service.py
git commit -m "feat: use version_status from KnownVersion in pipeline pause and confidence logic"
```

---

### Task 6: Add Backend API Endpoints for Known Versions and Single-Version Import

**Files:**
- Modify: `backend/app/routers/laws.py`

- [ ] **Step 1: Add GET endpoint for known versions with import status**

Add to `backend/app/routers/laws.py`, after the existing `get_law` endpoint (after line 393):

```python
@router.get("/{law_id}/known-versions")
def get_known_versions(law_id: int, db: Session = Depends(get_db)):
    """Get all known versions for a law, with import status."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    known = (
        db.query(KnownVersion)
        .filter(KnownVersion.law_id == law_id)
        .order_by(KnownVersion.date_in_force.desc())
        .all()
    )

    # Get imported ver_ids for this law
    imported_ver_ids = {
        row[0]
        for row in db.query(LawVersion.ver_id)
        .filter(LawVersion.law_id == law_id)
        .all()
    }

    return {
        "law_id": law_id,
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
        "versions": [
            {
                "id": kv.id,
                "ver_id": kv.ver_id,
                "date_in_force": str(kv.date_in_force),
                "is_current": kv.is_current,
                "is_imported": kv.ver_id in imported_ver_ids,
                "discovered_at": str(kv.discovered_at),
            }
            for kv in known
        ],
        "unimported_count": sum(
            1 for kv in known if kv.ver_id not in imported_ver_ids
        ),
    }
```

Add the `KnownVersion` import at line 10:

```python
from app.models.law import Annex, Article, KnownVersion, Law, LawVersion, StructuralElement
```

- [ ] **Step 2: Add POST endpoint to import a single known version**

Add after the new GET endpoint:

```python
class ImportKnownVersionRequest(BaseModel):
    ver_id: str


@router.post("/{law_id}/known-versions/import")
def import_known_version(law_id: int, req: ImportKnownVersionRequest, db: Session = Depends(get_db)):
    """Import a specific known version (full text extraction)."""
    from app.services.leropa_service import fetch_and_store_version
    import app.services.leropa_service as _ls

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    # Verify it's a known version for this law
    kv = (
        db.query(KnownVersion)
        .filter(KnownVersion.law_id == law_id, KnownVersion.ver_id == req.ver_id)
        .first()
    )
    if not kv:
        raise HTTPException(status_code=404, detail="Version not found in known versions")

    # Check if already imported
    existing = db.query(LawVersion).filter(LawVersion.ver_id == req.ver_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="This version is already imported")

    _ls._stored_article_ids = set()
    _, new_version = fetch_and_store_version(db, req.ver_id, law=law)

    # Update is_current flags on LawVersion
    all_versions = db.query(LawVersion).filter(LawVersion.law_id == law_id).all()
    dated = [(v, v.date_in_force) for v in all_versions if v.date_in_force]
    if dated:
        dated.sort(key=lambda x: x[1], reverse=True)
        for v in all_versions:
            v.is_current = False
        dated[0][0].is_current = True

    db.commit()

    return {"status": "imported", "ver_id": req.ver_id, "law_version_id": new_version.id}


@router.post("/{law_id}/known-versions/import-all")
def import_all_missing(law_id: int, db: Session = Depends(get_db)):
    """Import all known versions that aren't imported yet."""
    from app.services.leropa_service import fetch_and_store_version
    import app.services.leropa_service as _ls

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    imported_ver_ids = {
        row[0]
        for row in db.query(LawVersion.ver_id)
        .filter(LawVersion.law_id == law_id)
        .all()
    }

    missing = (
        db.query(KnownVersion)
        .filter(
            KnownVersion.law_id == law_id,
            KnownVersion.ver_id.notin_(imported_ver_ids) if imported_ver_ids else True,
        )
        .order_by(KnownVersion.date_in_force.asc())
        .all()
    )

    if not missing:
        return {"status": "nothing_to_import", "imported": 0}

    imported_count = 0
    errors = []
    for kv in missing:
        try:
            _ls._stored_article_ids = set()
            fetch_and_store_version(db, kv.ver_id, law=law)
            imported_count += 1
        except Exception as e:
            logger.error(f"Failed to import version {kv.ver_id}: {e}")
            errors.append({"ver_id": kv.ver_id, "error": str(e)[:200]})

    # Update is_current flags
    all_versions = db.query(LawVersion).filter(LawVersion.law_id == law_id).all()
    dated = [(v, v.date_in_force) for v in all_versions if v.date_in_force]
    if dated:
        dated.sort(key=lambda x: x[1], reverse=True)
        for v in all_versions:
            v.is_current = False
        dated[0][0].is_current = True

    db.commit()

    return {"status": "done", "imported": imported_count, "errors": errors}
```

- [ ] **Step 3: Extend the GET law detail to include `last_checked_at` and unimported count**

In `backend/app/routers/laws.py`, in the `get_law` function (line 368), add fields to the response dict. After `"category_confidence": law.category_confidence,` (line 381), add:

```python
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
        "unimported_version_count": db.query(KnownVersion).filter(
            KnownVersion.law_id == law.id,
            KnownVersion.ver_id.notin_(
                db.query(LawVersion.ver_id).filter(LawVersion.law_id == law.id)
            ),
        ).count(),
```

- [ ] **Step 4: Verify the app starts and endpoints work**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add backend/app/routers/laws.py
git commit -m "feat: add known-versions API endpoints and extend law detail response"
```

---

### Task 7: Extend Frontend Types and API Client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add types for known versions**

In `frontend/src/lib/api.ts`, after the `LawVersionSummary` interface (line 149), add:

```typescript
export interface KnownVersionData {
  id: number;
  ver_id: string;
  date_in_force: string;
  is_current: boolean;
  is_imported: boolean;
  discovered_at: string;
}

export interface KnownVersionsResponse {
  law_id: number;
  last_checked_at: string | null;
  versions: KnownVersionData[];
  unimported_count: number;
}
```

- [ ] **Step 2: Add `last_checked_at` and `unimported_version_count` to `LawDetail`**

In the `LawDetail` interface (line 117), add after `status_override`:

```typescript
  last_checked_at: string | null;
  unimported_version_count: number;
```

- [ ] **Step 3: Add API methods for known versions**

Find the `laws` object inside the `api` export and add these methods:

```typescript
    getKnownVersions: (lawId: number) =>
      apiFetch<KnownVersionsResponse>(`/api/laws/${lawId}/known-versions`),

    importKnownVersion: (lawId: number, ver_id: string) =>
      apiFetch<{ status: string; ver_id: string; law_version_id: number }>(
        `/api/laws/${lawId}/known-versions/import`,
        { method: "POST", body: JSON.stringify({ ver_id: ver_id }) }
      ),

    importAllMissing: (lawId: number) =>
      apiFetch<{ status: string; imported: number; errors: Array<{ ver_id: string; error: string }> }>(
        `/api/laws/${lawId}/known-versions/import-all`,
        { method: "POST" }
      ),
```

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add frontend/src/lib/api.ts
git commit -m "feat: add known versions types and API methods to frontend client"
```

---

### Task 8: Build the Versions Section Component for Law Detail Page

**Files:**
- Create: `frontend/src/app/laws/[id]/versions-section.tsx`
- Modify: `frontend/src/app/laws/[id]/page.tsx`

**Important:** Read `node_modules/next/dist/docs/` for any relevant Next.js changes before writing frontend code, as this project's AGENTS.md warns about breaking changes.

- [ ] **Step 1: Create the VersionsSection client component**

```tsx
// frontend/src/app/laws/[id]/versions-section.tsx
"use client";

import { useEffect, useState } from "react";
import { api, KnownVersionData } from "@/lib/api";

interface VersionsSectionProps {
  lawId: number;
  lastCheckedAt: string | null;
  importedVerIds: Set<string>;
}

function formatLastChecked(dateStr: string | null): string {
  if (!dateStr) return "Not yet checked";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) {
    return `Last checked: today at ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  }
  if (diffDays <= 7) {
    return `Last checked: ${diffDays} day${diffDays > 1 ? "s" : ""} ago`;
  }
  return `Last checked: ${date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}`;
}

export default function VersionsSection({ lawId, lastCheckedAt, importedVerIds: initialImported }: VersionsSectionProps) {
  const [versions, setVersions] = useState<KnownVersionData[]>([]);
  const [importedVerIds, setImportedVerIds] = useState<Set<string>>(initialImported);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState<string | null>(null);
  const [importingAll, setImportingAll] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    api.laws.getKnownVersions(lawId).then((data) => {
      setVersions(data.versions);
      setImportedVerIds(new Set(data.versions.filter((v) => v.is_imported).map((v) => v.ver_id)));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [lawId]);

  const unimportedCount = versions.filter((v) => !importedVerIds.has(v.ver_id)).length;

  async function handleImport(verId: string) {
    setImporting(verId);
    try {
      await api.laws.importKnownVersion(lawId, verId);
      setImportedVerIds((prev) => new Set([...prev, verId]));
    } catch (e: any) {
      alert(`Import failed: ${e.message}`);
    } finally {
      setImporting(null);
    }
  }

  async function handleImportAll() {
    if (unimportedCount > 10 && !confirm(`Import ${unimportedCount} versions? This may take several minutes.`)) {
      return;
    }
    setImportingAll(true);
    try {
      const result = await api.laws.importAllMissing(lawId);
      // Refresh the list
      const data = await api.laws.getKnownVersions(lawId);
      setVersions(data.versions);
      setImportedVerIds(new Set(data.versions.filter((v) => v.is_imported).map((v) => v.ver_id)));
      if (result.errors.length > 0) {
        alert(`Imported ${result.imported} versions. ${result.errors.length} failed.`);
      }
    } catch (e: any) {
      alert(`Import failed: ${e.message}`);
    } finally {
      setImportingAll(false);
    }
  }

  if (loading) {
    return <div className="text-sm text-gray-400 py-4">Loading version history...</div>;
  }

  if (versions.length === 0) {
    return (
      <div className="mt-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Official Versions</h2>
        <p className="text-sm text-gray-500">{formatLastChecked(lastCheckedAt)}</p>
        <p className="text-sm text-gray-400 mt-2">No version history discovered yet.</p>
      </div>
    );
  }

  const TWO_YEARS_AGO = new Date();
  TWO_YEARS_AGO.setFullYear(TWO_YEARS_AGO.getFullYear() - 2);
  const recentVersions = versions.filter((v) => new Date(v.date_in_force) >= TWO_YEARS_AGO);
  const olderVersions = versions.filter((v) => new Date(v.date_in_force) < TWO_YEARS_AGO);
  const displayVersions = showAll ? versions : (recentVersions.length > 0 ? recentVersions : versions.slice(0, 5));

  return (
    <div className="mt-8">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-semibold text-gray-900">Official Versions</h2>
        {unimportedCount > 0 && (
          <button
            onClick={handleImportAll}
            disabled={importingAll}
            className="text-xs border border-blue-500 text-blue-600 px-2.5 py-1 rounded hover:bg-blue-50 disabled:opacity-50"
          >
            {importingAll ? "Importing..." : `Import all missing (${unimportedCount})`}
          </button>
        )}
      </div>
      <p className="text-sm text-gray-500 mb-3">
        {formatLastChecked(lastCheckedAt)}
        {unimportedCount > 0 && (
          <span className="ml-2 text-amber-600 font-medium">
            {unimportedCount} version{unimportedCount > 1 ? "s" : ""} not imported
          </span>
        )}
      </p>

      <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-200">
        {displayVersions.map((v) => {
          const isImported = importedVerIds.has(v.ver_id);
          return (
            <div key={v.ver_id} className="p-3 flex items-center justify-between">
              <div>
                <span className="font-medium text-sm text-gray-900">{v.date_in_force}</span>
                <span className="ml-2 text-xs text-gray-400">(ver_id: {v.ver_id})</span>
                <div className="flex items-center gap-1.5 mt-0.5">
                  {v.is_current && (
                    <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-700">
                      CURRENT
                    </span>
                  )}
                  <span
                    className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${
                      isImported ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {isImported ? "IMPORTED" : "NOT IMPORTED"}
                  </span>
                </div>
              </div>
              {!isImported && (
                <button
                  onClick={() => handleImport(v.ver_id)}
                  disabled={importing === v.ver_id}
                  className="text-xs border border-blue-500 text-blue-600 px-2.5 py-1 rounded hover:bg-blue-50 disabled:opacity-50"
                >
                  {importing === v.ver_id ? "Importing..." : "Import"}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {!showAll && olderVersions.length > 0 && (
        <button
          onClick={() => setShowAll(true)}
          className="mt-2 text-sm text-blue-600 hover:underline"
        >
          Show {olderVersions.length} older version{olderVersions.length > 1 ? "s" : ""}
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Update the law detail page to include VersionsSection**

In `frontend/src/app/laws/[id]/page.tsx`, add the import at the top:

```tsx
import VersionsSection from "./versions-section";
```

Then add after the existing versions section closing `</div>` (after line 116, before the final `</div>`):

```tsx
      <VersionsSection
        lawId={law.id}
        lastCheckedAt={law.last_checked_at}
        importedVerIds={new Set(law.versions.map((v) => v.ver_id))}
      />
```

- [ ] **Step 3: Verify the frontend builds**

Run: `cd /Users/anaandrei/projects/legalese/frontend && npx next build 2>&1 | tail -20`
Expected: Build succeeds (or only pre-existing warnings)

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add frontend/src/app/laws/[id]/versions-section.tsx frontend/src/app/laws/[id]/page.tsx
git commit -m "feat: add VersionsSection component with import controls on law detail page"
```

---

### Task 9: Add "New Version Available" Badge to Law Card

**Files:**
- Modify: `frontend/src/app/laws/components/law-card.tsx`
- Modify: `frontend/src/lib/api.ts` (add field to `LibraryLaw`)

- [ ] **Step 1: Add `unimported_version_count` to the `LibraryLaw` type**

In `frontend/src/lib/api.ts`, in the `LibraryLaw` interface (line 65), add:

```typescript
  unimported_version_count: number;
```

- [ ] **Step 2: Add the backend field to the library list endpoint**

In `backend/app/routers/laws.py`, in the `list_laws` endpoint (line 315), add `unimported_version_count` to each law dict. After `"status_override": law.status_override,` (line 342), add:

```python
            "unimported_version_count": db.query(KnownVersion).filter(
                KnownVersion.law_id == law.id,
                KnownVersion.ver_id.notin_(
                    db.query(LawVersion.ver_id).filter(LawVersion.law_id == law.id)
                ),
            ).count(),
```

Also add extra fields needed by the frontend. After `"description": law.description,` (line 325), add:

```python
            "issuer": law.issuer,
            "category_id": law.category_id,
            "category_group_slug": law.category.group.slug if law.category else None,
            "category_confidence": law.category_confidence,
```

- [ ] **Step 3: Add the badge to the law card component**

In `frontend/src/app/laws/components/law-card.tsx`, after the version count span (line 97-98), add:

```tsx
        {law.unimported_version_count > 0 && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
            {law.unimported_version_count} new
          </span>
        )}
```

- [ ] **Step 4: Verify the frontend builds**

Run: `cd /Users/anaandrei/projects/legalese/frontend && npx next build 2>&1 | tail -20`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add frontend/src/app/laws/components/law-card.tsx frontend/src/lib/api.ts backend/app/routers/laws.py
git commit -m "feat: add 'new version available' badge to law card in library list"
```

---

### Task 10: Seed `KnownVersion` from Existing `LawVersion` Data (Migration)

**Files:**
- Modify: `backend/app/main.py` (add seeding on startup)

- [ ] **Step 1: Add seed function to version_discovery.py**

Add to `backend/app/services/version_discovery.py`:

```python
def seed_known_versions_from_imported(db: Session) -> int:
    """Backfill KnownVersion from existing LawVersion rows.

    For each LawVersion that has no corresponding KnownVersion, create one.
    This ensures clean initial state after deploying the KnownVersion feature.
    Returns the number of rows created.
    """
    existing_known = {
        row[0] for row in db.query(KnownVersion.ver_id).all()
    }

    versions = db.query(LawVersion).all()
    count = 0
    now = datetime.utcnow()

    for v in versions:
        if v.ver_id in existing_known:
            continue
        kv = KnownVersion(
            law_id=v.law_id,
            ver_id=v.ver_id,
            date_in_force=v.date_in_force or date_type(1900, 1, 1),
            is_current=v.is_current,
            discovered_at=now,
        )
        db.add(kv)
        existing_known.add(v.ver_id)
        count += 1

    if count > 0:
        db.commit()
    return count
```

- [ ] **Step 2: Call seed function on startup in main.py**

In `backend/app/main.py`, in the `lifespan` function, after the `ensure_fts_index(db)` call (line 50), add:

```python
        from app.services.version_discovery import seed_known_versions_from_imported
        seeded = seed_known_versions_from_imported(db)
        if seeded:
            logger.info(f"Seeded {seeded} KnownVersion rows from existing imports")
```

- [ ] **Step 3: Verify the app starts and seeds correctly**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -c "from app.main import app; print('OK')"`
Expected: `OK` (and log message about seeded rows if any data exists)

- [ ] **Step 4: Commit**

```bash
cd /Users/anaandrei/projects/legalese
git add backend/app/services/version_discovery.py backend/app/main.py
git commit -m "feat: seed KnownVersion from existing LawVersion on startup"
```

---

### Task 11: Final Integration Test

**Files:**
- Test: Manual verification

- [ ] **Step 1: Run all backend tests**

Run: `cd /Users/anaandrei/projects/legalese/backend && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify the full backend starts**

Run: `cd /Users/anaandrei/projects/legalese/backend && timeout 10 python -m uvicorn app.main:app --port 8001 2>&1 || true`
Expected: App starts successfully, scheduler registers

- [ ] **Step 3: Verify frontend builds**

Run: `cd /Users/anaandrei/projects/legalese/frontend && npx next build 2>&1 | tail -20`
Expected: Build succeeds

- [ ] **Step 4: Final commit (if any adjustments needed)**

```bash
cd /Users/anaandrei/projects/legalese
git add -A
git status
# Only commit if there are changes
```
