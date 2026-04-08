# Per-Law Check Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every per-law update check (`POST /api/laws/{id}/check-updates`) into a new append-only `law_check_logs` table and surface it as a combined feed inside Settings → Schedulers and as a per-law history on the law detail page.

**Architecture:** New SQLAlchemy model created via `Base.metadata.create_all()` (no Alembic). Best-effort `record_check()` helper called from both the success and exception branches of the existing `check_law_updates` endpoint. Two new admin/auth-gated GET endpoints (combined feed + per-law history). Two new React components — one full-width section under the scheduler cards, one inside the law detail's versions section, refreshed when the user clicks "Check now".

**Tech Stack:** FastAPI + SQLAlchemy (SQLite, additive `create_all`), pytest with FastAPI `TestClient`, React + TypeScript client components.

**Spec:** `docs/superpowers/specs/2026-04-08-per-law-check-log-design.md`

---

## File Structure

**Create (backend):**
- `backend/app/models/law_check_log.py` — `LawCheckLog` model
- `backend/app/services/law_check_log_service.py` — `record_check()` helper
- `backend/tests/test_law_check_log.py` — service + endpoint tests

**Modify (backend):**
- `backend/app/main.py` — import the new model so `create_all` registers it
- `backend/app/routers/laws.py` — add explicit `current_user` param + `record_check` calls in `check_law_updates`; add new `GET /api/laws/{law_id}/check-logs` endpoint
- `backend/app/routers/settings_schedulers.py` — add `GET /api/admin/law-check-logs` endpoint

**Create (frontend):**
- `frontend/src/app/settings/schedulers/law-check-log-table.tsx` — read-only combined feed table
- `frontend/src/app/laws/[id]/check-history-section.tsx` — read-only per-law history section

**Modify (frontend):**
- `frontend/src/lib/api.ts` — add two response interfaces and two client methods
- `frontend/src/app/settings/schedulers/scheduler-settings.tsx` — render `<LawCheckLogTable />` as a full-width section under the two cards
- `frontend/src/app/laws/[id]/versions-section.tsx` — hold a `checkRefreshKey`, pass it to a new `<CheckHistorySection />`, plumb a callback through `UpdateBanner`
- `frontend/src/app/laws/[id]/update-banner.tsx` — accept an `onCheckComplete` prop and call it after each successful `checkUpdates()` (auto-check `useEffect` and `handleCheckNow`)

---

## Task 1: Create the `LawCheckLog` model

**Files:**
- Create: `backend/app/models/law_check_log.py`
- Modify: `backend/app/main.py` (add import alongside other model registration imports near line 16)

- [ ] **Step 1: Write the model file**

```python
# backend/app/models/law_check_log.py
"""Append-only log of per-law update checks."""

import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LawCheckLog(Base):
    """One row per call to POST /api/laws/{law_id}/check-updates.

    Written by law_check_log_service.record_check.
    Read by GET /api/admin/law-check-logs and GET /api/laws/{law_id}/check-logs.
    """

    __tablename__ = "law_check_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("laws.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(8), nullable=False)  # "ro" | "eu"
    checked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    new_versions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # "ok" | "error"
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_law_check_logs_law_checked", "law_id", "checked_at"),
    )
```

- [ ] **Step 2: Register the model so `create_all` picks it up**

In `backend/app/main.py`, find the existing block around line 16 with the line:

```python
from app.models.scheduler_run_log import SchedulerRunLog  # noqa: F401 — register scheduler_run_logs table
```

Add directly below it:

```python
from app.models.law_check_log import LawCheckLog  # noqa: F401 — register law_check_logs table
```

- [ ] **Step 3: Verify the table is created**

Run:

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -c "
from app.database import Base, engine
import app.models.law_check_log  # noqa
Base.metadata.create_all(bind=engine)
from sqlalchemy import inspect
insp = inspect(engine)
print('table:', 'law_check_logs' in insp.get_table_names())
print('cols:', sorted(c['name'] for c in insp.get_columns('law_check_logs')))
print('indexes:', [i['name'] for i in insp.get_indexes('law_check_logs')])
"
```

Expected output includes `table: True` and the 8 column names.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/law_check_log.py backend/app/main.py
git commit -m "feat(backend): add LawCheckLog model for per-law check log"
```

---

## Task 2: `record_check` helper + unit tests

**Files:**
- Create: `backend/app/services/law_check_log_service.py`
- Create: `backend/tests/test_law_check_log.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_law_check_log.py` with this content:

```python
"""Tests for law_check_log_service.record_check and the two read endpoints."""
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.law import Law
from app.models.law_check_log import LawCheckLog
from app.services import law_check_log_service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _make_law(db, *, source="ro", title="Test Law"):
    law = Law(title=title, law_number="500", law_year=2020, source=source)
    db.add(law)
    db.commit()
    return law


def test_record_check_inserts_row_with_expected_fields(db):
    law = _make_law(db, source="ro")

    law_check_log_service.record_check(
        db, law=law, user_id=42, new_versions=3, status="ok"
    )

    rows = db.query(LawCheckLog).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.law_id == law.id
    assert row.source == "ro"
    assert row.user_id == 42
    assert row.new_versions == 3
    assert row.status == "ok"
    assert row.error_message is None
    assert row.checked_at is not None


def test_record_check_stores_error_message_when_status_is_error(db):
    law = _make_law(db, source="eu")

    law_check_log_service.record_check(
        db, law=law, user_id=1, new_versions=0, status="error", error_message="upstream 503"
    )

    row = db.query(LawCheckLog).one()
    assert row.status == "error"
    assert row.error_message == "upstream 503"
    assert row.source == "eu"


def test_record_check_truncates_long_error_messages(db):
    law = _make_law(db)
    long_msg = "x" * 2000

    law_check_log_service.record_check(
        db, law=law, user_id=1, new_versions=0, status="error", error_message=long_msg
    )

    row = db.query(LawCheckLog).one()
    assert len(row.error_message) == 512
    assert row.error_message == "x" * 512


def test_record_check_accepts_null_user_id(db):
    law = _make_law(db)

    law_check_log_service.record_check(
        db, law=law, user_id=None, new_versions=0, status="ok"
    )

    row = db.query(LawCheckLog).one()
    assert row.user_id is None


def test_record_check_swallows_db_failures(db, monkeypatch, caplog):
    """A logging failure must not break the underlying check call."""
    law = _make_law(db)

    def boom(*a, **kw):
        raise RuntimeError("db is down")

    monkeypatch.setattr(db, "add", boom)

    with caplog.at_level(logging.WARNING, logger="app.services.law_check_log_service"):
        # Should not raise
        law_check_log_service.record_check(
            db, law=law, user_id=1, new_versions=0, status="ok"
        )
    assert any("db is down" in r.message for r in caplog.records)


def test_record_check_rolls_back_when_commit_fails(db, monkeypatch, caplog):
    """When commit fails, the staged row must be rolled back and the error swallowed."""
    law = _make_law(db)
    real_commit = db.commit

    def boom_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", boom_commit)

    with caplog.at_level(logging.WARNING, logger="app.services.law_check_log_service"):
        # Should not raise
        law_check_log_service.record_check(
            db, law=law, user_id=1, new_versions=0, status="ok"
        )

    assert any("commit failed" in r.message for r in caplog.records)

    monkeypatch.setattr(db, "commit", real_commit)
    assert db.query(LawCheckLog).count() == 0
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && pytest tests/test_law_check_log.py -v
```

Expected: collection error (`ModuleNotFoundError: No module named 'app.services.law_check_log_service'`).

- [ ] **Step 3: Implement the helper**

Create `backend/app/services/law_check_log_service.py`:

```python
"""Append rows to law_check_logs. Best-effort: never raises."""

import datetime as _dt
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.law import Law
from app.models.law_check_log import LawCheckLog

logger = logging.getLogger(__name__)

_ERROR_MESSAGE_MAX = 512


def record_check(
    db: Session,
    law: Law,
    user_id: Optional[int],
    new_versions: int,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Insert one law_check_logs row.

    Best-effort: a logging failure is logged at WARNING level and
    swallowed so it cannot break the per-law check that called us.

    Args:
        db: SQLAlchemy session (caller-owned; this function commits on it).
        law: The Law that was checked. Reads law.id and law.source.
        user_id: Triggering user id, or None if unauthenticated.
        new_versions: Number of new KnownVersion rows discovered.
        status: "ok" or "error".
        error_message: Truncated to 512 chars before insert.
    """
    try:
        truncated = error_message[:_ERROR_MESSAGE_MAX] if error_message else None
        row = LawCheckLog(
            law_id=law.id,
            source=law.source,
            checked_at=_dt.datetime.now(_dt.timezone.utc),
            user_id=user_id,
            new_versions=int(new_versions or 0),
            status=status,
            error_message=truncated,
        )
        db.add(row)
        db.commit()
    except Exception as e:  # noqa: BLE001 - intentional best-effort swallow
        logger.warning("Failed to write law_check_log row: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
```

- [ ] **Step 4: Run the tests**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && pytest tests/test_law_check_log.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/law_check_log_service.py backend/tests/test_law_check_log.py
git commit -m "feat(backend): add law_check_log_service.record_check helper"
```

---

## Task 3: Wire helper into `check_law_updates`

**Files:**
- Modify: `backend/app/routers/laws.py` (`check_law_updates` around lines 1476–1500)

The current endpoint is:

```python
@router.post("/{law_id}/check-updates")
def check_law_updates(law_id: int, db: Session = Depends(get_db)):
    """Refresh KnownVersion entries for a single law from legislatie.just.ro."""
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

We add an explicit `current_user` parameter (the router-level dependency already enforces auth — see `routers/laws.py:23` — so this is purely additive) and `record_check` calls in both branches.

- [ ] **Step 1: Modify `check_law_updates`**

Replace the function with:

```python
@router.post("/{law_id}/check-updates")
def check_law_updates(
    law_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Refresh KnownVersion entries for a single law from legislatie.just.ro.

    Discovery only: writes/updates KnownVersion rows and re-derives
    LawVersion.is_current. Does NOT import any version text — that's the
    user's job via the Import buttons in the law-detail page.
    """
    from app.services.version_discovery import discover_versions_for_law
    from app.services.law_check_log_service import record_check

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    try:
        new_count = discover_versions_for_law(db, law)
    except Exception as e:
        logger.exception(f"Error checking updates for law {law_id}")
        db.rollback()
        record_check(
            db,
            law=law,
            user_id=current_user.id,
            new_versions=0,
            status="error",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Update check failed: {str(e)}")

    record_check(
        db,
        law=law,
        user_id=current_user.id,
        new_versions=new_count,
        status="ok",
    )

    return {
        "discovered": new_count,
        "last_checked_at": str(law.last_checked_at) if law.last_checked_at else None,
    }
```

Note: `User` and `get_current_user` are already imported at the top of the file (`backend/app/routers/laws.py:12, 17`).

- [ ] **Step 2: Smoke-check the imports**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && python -c "
import app.routers.laws
print('imports ok')
"
```

Expected: `imports ok`

- [ ] **Step 3: Re-run the helper tests**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && pytest tests/test_law_check_log.py -v
```

Expected: 6 passed (no regressions — only call sites changed).

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/laws.py
git commit -m "feat(backend): record per-law check log on success and error paths"
```

---

## Task 4: Two GET endpoints + tests

**Files:**
- Modify: `backend/app/routers/settings_schedulers.py` (combined feed endpoint)
- Modify: `backend/app/routers/laws.py` (per-law history endpoint)
- Modify: `backend/tests/test_law_check_log.py` (append endpoint tests)

### Step A — Combined feed (admin)

- [ ] **Step A1: Append failing tests for the combined feed**

Append to `backend/tests/test_law_check_log.py`:

```python
import datetime as _dt
from fastapi.testclient import TestClient

from app.auth import get_current_user, require_admin
from app.database import get_db
from app.main import app as fastapi_app
from app.models.user import User


@pytest.fixture
def admin_client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_admin():
        return User(id=1, email="admin@example.com", role="admin")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[require_admin] = override_admin
    fastapi_app.dependency_overrides[get_current_user] = override_admin
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def _seed_user(db, email="ana@example.com"):
    user = User(email=email, role="user")
    db.add(user)
    db.commit()
    return user


def _seed_log_set(db):
    """Seed: 1 user, 2 laws (RO + EU), 5 logs across them, varied timestamps."""
    user = _seed_user(db)
    ro_law = Law(title="Legea societăților", law_number="31", law_year=1990, source="ro")
    eu_law = Law(title="GDPR", law_number="2016/679", law_year=2016, source="eu")
    db.add(ro_law)
    db.add(eu_law)
    db.commit()

    base = _dt.datetime(2026, 4, 8, 9, 0, 0, tzinfo=_dt.timezone.utc)
    for i in range(3):
        db.add(LawCheckLog(
            law_id=ro_law.id, source="ro",
            checked_at=base + _dt.timedelta(hours=i),
            user_id=user.id, new_versions=i, status="ok",
        ))
    for i in range(2):
        db.add(LawCheckLog(
            law_id=eu_law.id, source="eu",
            checked_at=base + _dt.timedelta(hours=10 + i),
            user_id=user.id, new_versions=0, status="ok",
        ))
    db.commit()
    return ro_law, eu_law, user


def test_combined_feed_returns_rows_descending(admin_client, db):
    _seed_log_set(db)
    res = admin_client.get("/api/admin/law-check-logs")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 5
    timestamps = [r["checked_at"] for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)
    # Newest is one of the EU rows (hour 11)
    assert rows[0]["source"] == "eu"
    assert rows[0]["user_email"] == "ana@example.com"
    assert "law_label" in rows[0]


def test_combined_feed_respects_limit(admin_client, db):
    _seed_log_set(db)
    res = admin_client.get("/api/admin/law-check-logs?limit=2")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_combined_feed_caps_limit_at_200(admin_client, db):
    _seed_log_set(db)
    res = admin_client.get("/api/admin/law-check-logs?limit=9999")
    assert res.status_code == 200
    assert len(res.json()) <= 200


def test_combined_feed_empty_returns_empty_array(admin_client):
    res = admin_client.get("/api/admin/law-check-logs")
    assert res.status_code == 200
    assert res.json() == []


def test_combined_feed_handles_null_user(admin_client, db):
    law = Law(title="Orphan", law_number="1", law_year=2020, source="ro")
    db.add(law)
    db.commit()
    db.add(LawCheckLog(
        law_id=law.id, source="ro",
        checked_at=_dt.datetime(2026, 4, 8, 12, 0, 0, tzinfo=_dt.timezone.utc),
        user_id=None, new_versions=0, status="ok",
    ))
    db.commit()

    res = admin_client.get("/api/admin/law-check-logs")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["user_email"] is None
```

- [ ] **Step A2: Run the combined-feed tests to confirm they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && pytest tests/test_law_check_log.py -v -k combined_feed
```

Expected: 5 failed (404 — endpoint missing).

- [ ] **Step A3: Implement the combined-feed endpoint**

Open `backend/app/routers/settings_schedulers.py`. Add to the imports near the top:

```python
from app.models.law_check_log import LawCheckLog
from app.models.law import Law
```

Add this response model after the existing `SchedulerRunLogOut` class (added in the earlier scheduler-activity-log feature):

```python
class LawCheckLogOut(BaseModel):
    id: int
    law_id: int
    source: str
    law_label: str
    checked_at: str
    user_email: str | None
    new_versions: int
    status: str
    error_message: str | None
```

Add this endpoint at the bottom of the file:

```python
@router.get("/law-check-logs", response_model=list[LawCheckLogOut])
def list_law_check_logs(
    limit: int = 20,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Combined feed of per-law update checks across both sources, newest first.

    Read-only. Admin-only.
    """
    capped = max(1, min(limit, 200))

    rows = (
        db.query(LawCheckLog, Law, User)
        .join(Law, Law.id == LawCheckLog.law_id)
        .outerjoin(User, User.id == LawCheckLog.user_id)
        .order_by(LawCheckLog.checked_at.desc())
        .limit(capped)
        .all()
    )

    return [
        LawCheckLogOut(
            id=log.id,
            law_id=log.law_id,
            source=log.source,
            law_label=f"{law.title} ({law.law_number}/{law.law_year})",
            checked_at=log.checked_at.isoformat(),
            user_email=user.email if user else None,
            new_versions=log.new_versions,
            status=log.status,
            error_message=log.error_message,
        )
        for (log, law, user) in rows
    ]
```

- [ ] **Step A4: Run the combined-feed tests to verify they pass**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && pytest tests/test_law_check_log.py -v -k combined_feed
```

Expected: 5 passed.

### Step B — Per-law history (any logged-in user)

- [ ] **Step B1: Append failing tests for the per-law endpoint**

Append to `backend/tests/test_law_check_log.py`:

```python
@pytest.fixture
def user_client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_user():
        return User(id=1, email="ana@example.com", role="user")

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_user] = override_user
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


def test_per_law_history_returns_only_that_law(user_client, db):
    ro_law, eu_law, _ = _seed_log_set(db)

    res = user_client.get(f"/api/laws/{ro_law.id}/check-logs")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 3  # 3 RO logs seeded
    for r in rows:
        assert "law_id" not in r  # constant, omitted from response


def test_per_law_history_orders_descending(user_client, db):
    ro_law, _, _ = _seed_log_set(db)
    res = user_client.get(f"/api/laws/{ro_law.id}/check-logs")
    timestamps = [r["checked_at"] for r in res.json()]
    assert timestamps == sorted(timestamps, reverse=True)


def test_per_law_history_respects_limit(user_client, db):
    ro_law, _, _ = _seed_log_set(db)
    res = user_client.get(f"/api/laws/{ro_law.id}/check-logs?limit=2")
    assert len(res.json()) == 2


def test_per_law_history_returns_404_for_unknown_law(user_client):
    res = user_client.get("/api/laws/9999/check-logs")
    assert res.status_code == 404


def test_per_law_history_empty_returns_empty_array(user_client, db):
    law = Law(title="Quiet Law", law_number="42", law_year=2024, source="ro")
    db.add(law)
    db.commit()
    res = user_client.get(f"/api/laws/{law.id}/check-logs")
    assert res.status_code == 200
    assert res.json() == []
```

- [ ] **Step B2: Run the per-law tests to confirm they fail**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && pytest tests/test_law_check_log.py -v -k per_law_history
```

Expected: 5 failed (404 because the endpoint doesn't exist yet — note that for `test_per_law_history_returns_404_for_unknown_law` the failure mode is the same status but the wrong route, so the test still proves "endpoint missing" by failing one of the body assertions; once the endpoint exists, this specific test will pass legitimately).

- [ ] **Step B3: Implement the per-law endpoint**

Open `backend/app/routers/laws.py`. Find the `check_law_updates` function (modified in Task 3). Add a new endpoint immediately after it.

First, add the response model near the other Pydantic models near the top of the file (after the existing `ImportRequest` / `ImportSuggestionRequest` / `ImportStreamRequest` classes around lines 26–38):

```python
class LawCheckLogRowOut(BaseModel):
    id: int
    checked_at: str
    user_email: str | None
    new_versions: int
    status: str
    error_message: str | None
```

Then add the endpoint right after `check_law_updates`:

```python
@router.get("/{law_id}/check-logs", response_model=list[LawCheckLogRowOut])
def list_law_check_logs_for_law(
    law_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Return the per-law update check history, newest first."""
    from app.models.law_check_log import LawCheckLog

    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise HTTPException(status_code=404, detail="Law not found")

    capped = max(1, min(limit, 200))

    rows = (
        db.query(LawCheckLog, User)
        .outerjoin(User, User.id == LawCheckLog.user_id)
        .filter(LawCheckLog.law_id == law_id)
        .order_by(LawCheckLog.checked_at.desc())
        .limit(capped)
        .all()
    )

    return [
        LawCheckLogRowOut(
            id=log.id,
            checked_at=log.checked_at.isoformat(),
            user_email=user.email if user else None,
            new_versions=log.new_versions,
            status=log.status,
            error_message=log.error_message,
        )
        for (log, user) in rows
    ]
```

Note: the laws router has `dependencies=[Depends(get_current_user)]` at the router level (line 23), so this endpoint is automatically auth-required without needing an explicit `Depends` parameter.

- [ ] **Step B4: Run all tests in the file**

```bash
cd /Users/anaandrei/projects/themis-legal/backend && pytest tests/test_law_check_log.py -v
```

Expected: 16 passed (6 service unit tests + 5 combined-feed tests + 5 per-law history tests).

- [ ] **Step C: Commit**

```bash
git add backend/app/routers/settings_schedulers.py backend/app/routers/laws.py backend/tests/test_law_check_log.py
git commit -m "feat(backend): add GET law-check-logs endpoints (combined + per-law)"
```

---

## Task 5: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add response type interfaces**

Find the `SchedulerRunLogData` interface (added in the previous feature, around line 638). Immediately after it (and after `SchedulerSettingsUpdate` if that's still right above), add:

```typescript
export interface LawCheckLogData {
  id: number;
  law_id: number;
  source: string;
  law_label: string;
  checked_at: string;
  user_email: string | null;
  new_versions: number;
  status: "ok" | "error";
  error_message: string | null;
}

export interface LawCheckLogRowData {
  id: number;
  checked_at: string;
  user_email: string | null;
  new_versions: number;
  status: "ok" | "error";
  error_message: string | null;
}
```

- [ ] **Step 2: Add the combined-feed client method**

In the `api.settings.schedulers` namespace, after the existing `listLogs` method (added in the previous feature, around line 1023), add:

```typescript
      listLawCheckLogs: (limit = 20) =>
        apiFetch<LawCheckLogData[]>(`/api/admin/law-check-logs?limit=${limit}`),
```

- [ ] **Step 3: Add the per-law client method**

Find `api.laws.checkUpdates` (around line 720). Add the new method right after `getKnownVersions` (around line 725):

```typescript
    listCheckLogs: (lawId: number, limit = 20) =>
      apiFetch<LawCheckLogRowData[]>(
        `/api/laws/${lawId}/check-logs?limit=${limit}`
      ),
```

- [ ] **Step 4: Type-check**

```bash
cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): add law-check-log api client methods"
```

---

## Task 6: `LawCheckLogTable` component + render in Settings → Schedulers

**Files:**
- Create: `frontend/src/app/settings/schedulers/law-check-log-table.tsx`
- Modify: `frontend/src/app/settings/schedulers/scheduler-settings.tsx`

- [ ] **Step 1: Write the table component**

Create `frontend/src/app/settings/schedulers/law-check-log-table.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { api, type LawCheckLogData } from "@/lib/api";

export function LawCheckLogTable() {
  const [rows, setRows] = useState<LawCheckLogData[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.settings.schedulers
      .listLawCheckLogs(20)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load per-law check log.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    });

  const userShortName = (email: string | null) =>
    email ? email.split("@")[0] : "—";

  const hasErrors = (rows ?? []).some((r) => r.status === "error");

  return (
    <div className="mt-6 border border-gray-200 rounded-xl bg-white p-4">
      <div className="text-sm font-semibold text-gray-900 mb-2">
        Per-law update checks
      </div>
      <div className="text-xs text-gray-500 mb-3">
        Last 20 manual update checks across all laws
      </div>

      {error && <div className="text-xs text-red-600">{error}</div>}
      {!error && rows === null && (
        <div className="text-xs text-gray-400">Loading…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="text-xs text-gray-400">No per-law checks recorded yet.</div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500 sticky top-0 bg-white">
              <tr>
                <th className="text-left font-medium py-1 pr-2">Time</th>
                <th className="text-left font-medium py-1 pr-2">Source</th>
                <th className="text-left font-medium py-1 pr-2">Law</th>
                <th className="text-right font-medium py-1 pr-2">New</th>
                {hasErrors && (
                  <th className="text-right font-medium py-1 pr-2">Errors</th>
                )}
                <th className="text-left font-medium py-1">By</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="py-1 pr-2 text-gray-900 whitespace-nowrap">
                    {formatTime(r.checked_at)}
                  </td>
                  <td className="py-1 pr-2">
                    <span
                      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${
                        r.source === "ro"
                          ? "bg-blue-100 text-blue-700"
                          : "bg-purple-100 text-purple-700"
                      }`}
                    >
                      {r.source}
                    </span>
                  </td>
                  <td className="py-1 pr-2 text-gray-900 truncate max-w-xs" title={r.law_label}>
                    {r.law_label}
                  </td>
                  <td
                    className={`py-1 pr-2 text-right ${
                      r.new_versions > 0 ? "text-gray-900 font-medium" : "text-gray-400"
                    }`}
                  >
                    {r.new_versions}
                  </td>
                  {hasErrors && (
                    <td
                      className={`py-1 pr-2 text-right font-medium ${
                        r.status === "error" ? "text-red-600" : "text-gray-300"
                      }`}
                      title={r.error_message ?? undefined}
                    >
                      {r.status === "error" ? "1" : "0"}
                    </td>
                  )}
                  <td className="py-1 text-gray-600 truncate max-w-[8rem]" title={r.user_email ?? undefined}>
                    {userShortName(r.user_email)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Render it in `SchedulerSettings`**

In `frontend/src/app/settings/schedulers/scheduler-settings.tsx`, add the import alongside the existing `SchedulerCard` import:

```tsx
import { LawCheckLogTable } from "./law-check-log-table";
```

Find the closing `</div>` of the two-card grid (around line 128):

```tsx
      {/* Two cards side-by-side */}
      <div className="flex gap-5">
        {settings.map((s) => {
          ...
        })}
      </div>
    </div>
  );
}
```

Insert `<LawCheckLogTable />` between the closing `</div>` of the two-card grid and the closing `</div>` of the outer container:

```tsx
      {/* Two cards side-by-side */}
      <div className="flex gap-5">
        {settings.map((s) => {
          ...
        })}
      </div>

      <LawCheckLogTable />
    </div>
  );
}
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/settings/schedulers/law-check-log-table.tsx frontend/src/app/settings/schedulers/scheduler-settings.tsx
git commit -m "feat(frontend): add per-law check log table to Settings → Schedulers"
```

---

## Task 7: `CheckHistorySection` + wire into law detail page

**Files:**
- Create: `frontend/src/app/laws/[id]/check-history-section.tsx`
- Modify: `frontend/src/app/laws/[id]/update-banner.tsx` (add `onCheckComplete` prop, call after each successful checkUpdates)
- Modify: `frontend/src/app/laws/[id]/versions-section.tsx` (hold `checkRefreshKey`, plumb callback, render `<CheckHistorySection />`)

- [ ] **Step 1: Create the history component**

Create `frontend/src/app/laws/[id]/check-history-section.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { api, type LawCheckLogRowData } from "@/lib/api";

interface Props {
  lawId: number;
  /** Bumped by the parent after a check completes; triggers a refetch. */
  refreshKey: number;
}

export default function CheckHistorySection({ lawId, refreshKey }: Props) {
  const [rows, setRows] = useState<LawCheckLogRowData[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.laws
      .listCheckLogs(lawId, 20)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load check history.");
      });
    return () => {
      cancelled = true;
    };
  }, [lawId, refreshKey]);

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    });

  const userShortName = (email: string | null) =>
    email ? email.split("@")[0] : "—";

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="text-sm font-semibold text-gray-900 mb-3">
        Recent update checks
      </div>

      {error && <div className="text-xs text-red-600">{error}</div>}
      {!error && rows === null && (
        <div className="text-xs text-gray-400">Loading…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="text-xs text-gray-400">No update checks recorded yet.</div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="max-h-60 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500 sticky top-0 bg-white">
              <tr>
                <th className="text-left font-medium py-1 pr-2">Time</th>
                <th className="text-right font-medium py-1 pr-2">New</th>
                <th className="text-left font-medium py-1 pr-2">Result</th>
                <th className="text-left font-medium py-1">By</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="py-1 pr-2 text-gray-900 whitespace-nowrap">
                    {formatTime(r.checked_at)}
                  </td>
                  <td
                    className={`py-1 pr-2 text-right ${
                      r.new_versions > 0 ? "text-gray-900 font-medium" : "text-gray-400"
                    }`}
                  >
                    {r.new_versions}
                  </td>
                  <td className="py-1 pr-2">
                    {r.status === "ok" ? (
                      <span className="text-green-700">OK</span>
                    ) : (
                      <span
                        className="text-red-600"
                        title={r.error_message ?? "Error"}
                      >
                        Error
                      </span>
                    )}
                  </td>
                  <td className="py-1 text-gray-600 truncate max-w-[8rem]" title={r.user_email ?? undefined}>
                    {userShortName(r.user_email)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add `onCheckComplete` prop to `UpdateBanner`**

In `frontend/src/app/laws/[id]/update-banner.tsx`, find the `UpdateBannerProps` interface (lines 7–14):

```tsx
interface UpdateBannerProps {
  lawId: number;
  lastCheckedAt: string | null;
  importedVerIds: Set<string>;
  knownVersions: KnownVersionData[] | null;
  onVersionImported: (verId: string, lawVersionId: number) => void;
  onKnownVersionsLoaded: (versions: KnownVersionData[]) => void;
}
```

Add a new optional prop:

```tsx
interface UpdateBannerProps {
  lawId: number;
  lastCheckedAt: string | null;
  importedVerIds: Set<string>;
  knownVersions: KnownVersionData[] | null;
  onVersionImported: (verId: string, lawVersionId: number) => void;
  onKnownVersionsLoaded: (versions: KnownVersionData[]) => void;
  onCheckComplete?: () => void;
}
```

Destructure it in the function signature (line 44):

```tsx
export default function UpdateBanner({
  lawId,
  lastCheckedAt,
  importedVerIds,
  knownVersions,
  onVersionImported,
  onKnownVersionsLoaded,
  onCheckComplete,
}: UpdateBannerProps) {
```

In the auto-check `useEffect` (lines 63–78), call `onCheckComplete?.()` after the chain resolves. Replace the existing chain:

```tsx
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
```

with:

```tsx
    api.laws
      .checkUpdates(lawId)
      .then(() => api.laws.getKnownVersions(lawId))
      .then((data) => {
        onKnownVersionsLoaded(data.versions);
        setCheckedAt(data.last_checked_at);
        onCheckComplete?.();
      })
      .catch((e: unknown) => {
        setCheckError(e instanceof Error ? e.message : "Failed to check for updates");
        onCheckComplete?.();
      })
      .finally(() => setChecking(false));
```

(Note: we call `onCheckComplete` on both success AND error so the history table refreshes even when the check failed — the failure produces a log row too.)

In `handleCheckNow` (lines 108–125), make the same change:

```tsx
  async function handleCheckNow() {
    setChecking(true);
    setCheckError(null);
    setDismissed(false);
    try {
      await api.laws.checkUpdates(lawId);
      const data = await api.laws.getKnownVersions(lawId);
      onKnownVersionsLoaded(data.versions);
      setCheckedAt(data.last_checked_at);
      onCheckComplete?.();
    } catch (e: unknown) {
      setCheckError(e instanceof Error ? e.message : "Failed to check for updates");
      onCheckComplete?.();
    } finally {
      setChecking(false);
    }
  }
```

The `onCheckComplete` reference is stable across renders only if the parent memoizes it (which Task 7 Step 3 below does via `useState` dispatch). It does not need to be in any dependency array because it's used inside an effect-fired function and a callback, not as an effect dependency.

- [ ] **Step 3: Wire the history section + refresh callback into `VersionsSection`**

In `frontend/src/app/laws/[id]/versions-section.tsx`, add the import alongside the others (after the `UpdateBanner` import):

```tsx
import CheckHistorySection from "./check-history-section";
```

Add a new state variable inside the `VersionsSection` function body (after the `loading` useState around line 25):

```tsx
  const [checkRefreshKey, setCheckRefreshKey] = useState(0);
```

Build a stable callback (after `handleVersionDeleted`, around line 56):

```tsx
  const handleCheckComplete = useCallback(() => {
    setCheckRefreshKey((k) => k + 1);
  }, []);
```

Wire it through `<UpdateBanner>` (line 63 currently passes `lawId, lastCheckedAt, importedVerIds, knownVersions, onVersionImported, onKnownVersionsLoaded`). Add the prop:

```tsx
      <UpdateBanner
        lawId={lawId}
        lastCheckedAt={lastCheckedAt}
        importedVerIds={importedVerIds}
        knownVersions={knownVersions}
        onVersionImported={handleVersionImported}
        onKnownVersionsLoaded={handleKnownVersionsLoaded}
        onCheckComplete={handleCheckComplete}
      />
```

Render the new section at the end of the returned JSX (after the `UnimportedVersionsTable` block, before the closing `</div>`):

```tsx
      <CheckHistorySection lawId={lawId} refreshKey={checkRefreshKey} />
```

The final JSX of `VersionsSection` should look like:

```tsx
  return (
    <div className="space-y-4 mt-8">
      <UpdateBanner
        lawId={lawId}
        lastCheckedAt={lastCheckedAt}
        importedVerIds={importedVerIds}
        knownVersions={knownVersions}
        onVersionImported={handleVersionImported}
        onKnownVersionsLoaded={handleKnownVersionsLoaded}
        onCheckComplete={handleCheckComplete}
      />

      <ImportedVersionsTable lawId={lawId} versions={versions} knownVersions={knownVersions} onVersionDeleted={handleVersionDeleted} />

      {!loading && knownVersions && unimportedVersions.length > 0 && (
        <UnimportedVersionsTable
          lawId={lawId}
          versions={unimportedVersions}
          allKnownVersions={knownVersions}
          onVersionImported={handleVersionImported}
        />
      )}

      <CheckHistorySection lawId={lawId} refreshKey={checkRefreshKey} />
    </div>
  );
```

- [ ] **Step 4: Type-check**

```bash
cd /Users/anaandrei/projects/themis-legal/frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 5: Manual smoke test**

Start the backend and frontend, log in, and:

1. Open any law detail page → confirm "Recent update checks" section appears at the bottom of the versions area.
2. If the law has `last_checked_at` more than 1h old, the auto-check fires on mount → after it completes, confirm a new row appears in "Recent update checks".
3. Click "Check now" on the update banner → confirm a new row appears in "Recent update checks" without a page reload.
4. Navigate to **Settings → Schedulers** → confirm "Per-law update checks" section appears below the two scheduler cards, and the row from step 3 is at the top of the combined feed.
5. Open browser devtools → verify `GET /api/laws/{id}/check-logs` and `GET /api/admin/law-check-logs` both return 200 with the expected payload shape.
6. Confirm there are no edit/delete affordances anywhere in either table.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/laws/[id]/check-history-section.tsx frontend/src/app/laws/[id]/update-banner.tsx frontend/src/app/laws/[id]/versions-section.tsx
git commit -m "feat(frontend): add per-law check history section with refresh on check"
```

---

## Verification Checklist (run before declaring done)

- [ ] `cd backend && pytest tests/test_law_check_log.py -v` → 16 tests pass
- [ ] `cd backend && pytest tests/test_check_updates_endpoint.py -v` → existing tests still pass (the existing fixture already overrides `get_current_user`, so the new `current_user` parameter resolves cleanly)
- [ ] `cd frontend && npx tsc --noEmit` → no errors
- [ ] Manual smoke test (Task 7 Step 5) passes
- [ ] No DELETE/PUT/POST endpoints added for the new logs
- [ ] No changes to existing tables (`law_check_logs` is the only new table)
- [ ] No changes to the existing scheduler activity log table or its UI

---

## Spec ↔ Plan Coverage

| Spec section                                          | Implemented in |
|-------------------------------------------------------|----------------|
| Data model `LawCheckLog`                              | Task 1         |
| `record_check` helper (best-effort)                   | Task 2         |
| Wire helper into `check_law_updates` (success+error)  | Task 3         |
| Auth — explicit `current_user` parameter              | Task 3         |
| `GET /api/admin/law-check-logs` (combined, admin)     | Task 4 Step A  |
| `GET /api/laws/{id}/check-logs` (per-law, user)       | Task 4 Step B  |
| Frontend api client methods                           | Task 5         |
| `LawCheckLogTable` + Settings → Schedulers placement  | Task 6         |
| `CheckHistorySection` + law detail wiring             | Task 7         |
| Refresh on Check Now (parent state bump)              | Task 7         |
| Read-only enforcement                                 | Tasks 4 + 6 + 7 (no mutating endpoints, no UI affordances) |
| Backend tests                                         | Tasks 2 + 4    |
| Manual smoke test                                     | Task 7 Step 5  |
