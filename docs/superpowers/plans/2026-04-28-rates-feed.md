# Rates Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Daily fetch + storage + REST API for FX (BNR), ROBOR, and EURIBOR rates, with 7-year backfill and AICC-scheduler-driven cron, exposed via auth-gated `/api/rates/{exchange,interest}` for Exodus and Themis users.

**Architecture:** Two new SQLAlchemy models (`ExchangeRate`, `InterestRate`) auto-created by `Base.metadata.create_all`. Three independent fetcher modules under `app/services/rates/` (one per source). One AICC scheduler webhook that triggers all three on a daily cron. Public read endpoints accept either a Themis user PKCE token or a shared `RATES_API_TOKEN` bearer. Admin backfill endpoint kicks a Job using the existing `job_service` infrastructure.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, httpx, beautifulsoup4 (HTML parsing for ROBOR/EURIBOR), Python's stdlib `xml.etree.ElementTree` (BNR XML), pytest.

**Spec:** `docs/superpowers/specs/2026-04-28-rates-feed-design.md`

**Pre-implementation manual prep:**
- (None at PR time.) Post-merge, the operator generates `RATES_API_TOKEN` and adds the AICC scheduler task. Both are in the cutover runbook (Task 13).

---

## File map

### Created
- `backend/app/models/rates.py` — `ExchangeRate`, `InterestRate` SQLAlchemy models
- `backend/app/services/rates/__init__.py` (empty)
- `backend/app/services/rates/bnr_fx.py` — BNR FX parser + fetcher + storage
- `backend/app/services/rates/robor.py` — ROBOR parser + fetcher + storage
- `backend/app/services/rates/euribor.py` — EURIBOR parser + fetcher + storage
- `backend/app/services/rates/run.py` — `run_rates_update_check()` orchestrates the three fetchers
- `backend/app/services/rates/backfill.py` — `run_rates_backfill(years)` for the admin job
- `backend/app/auth_service.py` — `verify_caller` dependency (PKCE OR service token)
- `backend/app/routers/rates.py` — public API: `GET /api/rates/exchange` and `GET /api/rates/interest`
- `backend/tests/rates/__init__.py` (empty)
- `backend/tests/rates/test_bnr_fx.py`
- `backend/tests/rates/test_robor.py`
- `backend/tests/rates/test_euribor.py`
- `backend/tests/rates/test_api_endpoints.py`
- `backend/tests/rates/test_scheduler_webhook.py`
- `backend/tests/rates/test_verify_caller.py`
- `backend/tests/rates/fixtures/bnr_daily.xml`
- `backend/tests/rates/fixtures/bnr_yearly.xml`
- `backend/tests/rates/fixtures/robor.html`
- `backend/tests/rates/fixtures/euribor.html`
- `docs/superpowers/runbooks/2026-04-28-rates-feed-cutover.md`

### Modified
- `backend/pyproject.toml` — add `beautifulsoup4>=4.12`
- `backend/app/main.py` — import `rates` model module so `Base.metadata.create_all` picks it up; add `run_rates_update_check` for the scheduler; register the rates router
- `backend/app/routers/internal_scheduler.py` — add `POST /internal/scheduler/rates-update`
- `backend/app/routers/admin.py` — add `POST /api/admin/rates/backfill`
- `backend/app/config.py` — add `RATES_API_TOKEN` env var
- `backend/.env` (gitignored, for local dev only) — add `RATES_API_TOKEN=dev-only`

---

## Task 1: Add `beautifulsoup4` dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add the dep**

In `backend/pyproject.toml`, in the `dependencies` array, insert `"beautifulsoup4>=4.12",` in alphabetical position (between `apscheduler` and `cachetools`):

```toml
dependencies = [
    "aiosqlite>=0.22.1",
    "alembic>=1.18.4",
    "anthropic>=0.40.0",
    "apscheduler>=3.11.2",
    "beautifulsoup4>=4.12",
    "cachetools>=5.5.0",
    "chromadb>=0.6.0",
    "fastapi>=0.135.1",
    "httpx>=0.27.0",
    "leropa",
    "mistralai>=2.1.3",
    "openai>=2.30.0",
    "python-multipart>=0.0.22",
    "sqlalchemy>=2.0.48",
    "sse-starlette>=2.0",
    "uvicorn>=0.42.0",
]
```

- [ ] **Step 2: Sync deps**

Run: `cd backend && uv sync`
Expected: `bs4` and `beautifulsoup4` show up in installed packages.

- [ ] **Step 3: Verify import**

Run: `cd backend && uv run python -c "from bs4 import BeautifulSoup; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build(backend): add beautifulsoup4 for ROBOR/EURIBOR HTML parsing"
```

---

## Task 2: Models — `ExchangeRate` and `InterestRate`

**Files:**
- Create: `backend/app/models/rates.py`
- Modify: `backend/app/main.py` (add the import so `create_all` picks them up)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/rates/__init__.py` empty.

Create `backend/tests/rates/test_models.py`:

```python
"""Schema sanity tests for ExchangeRate and InterestRate models."""
from __future__ import annotations

import pytest


@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    # Importing the models module registers the tables on Base.metadata
    import app.models.rates  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    yield s
    s.close()


def test_exchange_rate_round_trip(db):
    from app.models.rates import ExchangeRate
    db.add(ExchangeRate(date="2026-03-06", currency="EUR", rate=4.9741, multiplier=1, source="BNR"))
    db.commit()
    rows = db.query(ExchangeRate).all()
    assert len(rows) == 1
    assert rows[0].currency == "EUR"
    assert rows[0].rate == 4.9741


def test_exchange_rate_unique_constraint(db):
    from app.models.rates import ExchangeRate
    from sqlalchemy.exc import IntegrityError
    db.add(ExchangeRate(date="2026-03-06", currency="EUR", rate=4.9741, source="BNR"))
    db.commit()
    db.add(ExchangeRate(date="2026-03-06", currency="EUR", rate=4.9999, source="BNR"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_interest_rate_round_trip(db):
    from app.models.rates import InterestRate
    db.add(InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92, source="curs-valutar-bnr.ro"))
    db.commit()
    rows = db.query(InterestRate).all()
    assert len(rows) == 1
    assert rows[0].rate_type == "ROBOR"
    assert rows[0].tenor == "3M"


def test_interest_rate_unique_constraint(db):
    from app.models.rates import InterestRate
    from sqlalchemy.exc import IntegrityError
    db.add(InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92, source="x"))
    db.commit()
    db.add(InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=6.10, source="x"))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_models.py -v`
Expected: `ModuleNotFoundError: No module named 'app.models.rates'`

- [ ] **Step 3: Implement the models**

Create `backend/app/models/rates.py`:

```python
"""Models for the rates feed (FX + interest rates)."""
from __future__ import annotations

import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExchangeRate(Base):
    """One row per (date, currency, source) — typically BNR daily fixings.

    Schema mirrors exodus-live so Exodus can swap source URL with no other
    changes.
    """
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("date", "currency", "source", name="ux_exchange_rates_dcs"),
        Index("idx_exchange_rates_date", "date"),
        Index("idx_exchange_rates_currency", "currency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    # BNR publishes some currencies multiplied by 100 (HUF, JPY, etc.). Preserve
    # the multiplier so callers can divide if they want a per-unit rate.
    multiplier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="BNR")
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )


class InterestRate(Base):
    """One row per (date, rate_type, tenor). rate_type ∈ {ROBOR, EURIBOR}."""
    __tablename__ = "interest_rates"
    __table_args__ = (
        UniqueConstraint("date", "rate_type", "tenor", name="ux_interest_rates_drt"),
        Index("idx_interest_rates_date", "date"),
        Index("idx_interest_rates_type", "rate_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(16), nullable=False)
    tenor: Mapped[str] = mapped_column(String(8), nullable=False)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
```

- [ ] **Step 4: Wire into `Base.metadata.create_all`**

In `backend/app/main.py`, find the existing block of `from app.models import ...` near the top of the file (around line 12-18) that lists model modules with `# noqa: F401 — register models` style comments. Add `rates` to one of those imports, e.g. change:

```python
from app.models import assistant, pipeline, prompt, category, user, favorite, law  # noqa: F401 — register models
```

to:

```python
from app.models import assistant, pipeline, prompt, category, user, favorite, law, rates  # noqa: F401 — register models
```

- [ ] **Step 5: Run model tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_models.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Boot the app, confirm tables created on a fresh DB**

Run: `cd backend && uv run python -c "
from app.main import app
from app.database import engine, Base
from sqlalchemy import inspect
# Ensure model module imported (main.py does this)
inspector = inspect(engine)
tables = inspector.get_table_names()
assert 'exchange_rates' in tables, tables
assert 'interest_rates' in tables, tables
print('ok: rate tables present')
"`
Expected: `ok: rate tables present`

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/rates.py backend/app/main.py backend/tests/rates/__init__.py backend/tests/rates/test_models.py
git commit -m "feat(backend): ExchangeRate and InterestRate models"
```

---

## Task 3: Service-token auth dependency (`verify_caller`)

**Files:**
- Create: `backend/app/auth_service.py`
- Modify: `backend/app/config.py`
- Create: `backend/tests/rates/test_verify_caller.py`

- [ ] **Step 1: Add the env var to config**

In `backend/app/config.py`, after `EMBEDDING_MODEL_AICC` definition, add:

```python
# Shared bearer token for service-to-service callers (e.g. Exodus pulling
# rates). Empty string disables service-token auth — only Themis user PKCE
# tokens are then accepted by /api/rates/*. In production, generate via
# `openssl rand -base64 48` and set on Railway.
RATES_API_TOKEN = os.environ.get("RATES_API_TOKEN", "")
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/rates/test_verify_caller.py`:

```python
"""verify_caller accepts either a Themis user PKCE token or a shared
RATES_API_TOKEN bearer. Either path → request proceeds. Neither → 401."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _request_with(headers: dict | None = None):
    headers = headers or {}
    req = MagicMock()
    req.headers = headers
    return req


def test_no_auth_header_raises_401():
    from app.auth_service import verify_caller
    req = _request_with({})
    with pytest.raises(HTTPException) as exc:
        verify_caller(request=req, db=MagicMock())
    assert exc.value.status_code == 401


def test_service_token_match_returns_caller_dict():
    from app.auth_service import verify_caller
    with patch("app.auth_service.RATES_API_TOKEN", "service-secret-xyz"):
        req = _request_with({"Authorization": "Bearer service-secret-xyz"})
        result = verify_caller(request=req, db=MagicMock())
        assert result["kind"] == "service"


def test_service_token_mismatch_falls_through_to_user_path_and_fails():
    """If service token doesn't match, treat as user PKCE attempt — and that
    will 401 too without a real Themis user setup."""
    from app.auth_service import verify_caller
    aicc_mock = MagicMock()
    aicc_mock.verify_token.return_value = None  # rejects this fake token
    req = _request_with({"Authorization": "Bearer wrong-token"})
    req.app.state.aicc_auth = aicc_mock
    with patch("app.auth_service.RATES_API_TOKEN", "service-secret-xyz"):
        with pytest.raises(HTTPException) as exc:
            verify_caller(request=req, db=MagicMock())
        assert exc.value.status_code == 401


def test_user_pkce_token_path_returns_user_dict(tmp_path):
    """A bearer that's NOT the service token but IS a valid AICC user token."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models.user  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    from app.services.aicc_auth_client import AiccUser
    aicc_mock = MagicMock()
    aicc_mock.verify_token.return_value = AiccUser(
        id="u1", email="alice@example.com", name="Alice",
        avatar_url=None, project_role="admin",
    )
    req = _request_with({"Authorization": "Bearer user-pkce-token"})
    req.app.state.aicc_auth = aicc_mock

    from app.auth_service import verify_caller
    with patch("app.auth_service.RATES_API_TOKEN", "service-secret-xyz"):
        result = verify_caller(request=req, db=db)
    assert result["kind"] == "user"
    assert result["email"] == "alice@example.com"
    db.close()


def test_empty_service_token_disables_service_auth():
    """RATES_API_TOKEN='' must NEVER match — otherwise an attacker sending
    `Authorization: Bearer ` (literal empty) would auth in."""
    from app.auth_service import verify_caller
    aicc_mock = MagicMock()
    aicc_mock.verify_token.return_value = None
    with patch("app.auth_service.RATES_API_TOKEN", ""):
        req = _request_with({"Authorization": "Bearer "})
        req.app.state.aicc_auth = aicc_mock
        with pytest.raises(HTTPException) as exc:
            verify_caller(request=req, db=MagicMock())
        assert exc.value.status_code == 401
```

- [ ] **Step 3: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_verify_caller.py -v`
Expected: ImportError (`app.auth_service` doesn't exist yet)

- [ ] **Step 4: Implement `verify_caller`**

Create `backend/app/auth_service.py`:

```python
"""Auth dependency for endpoints that accept either a Themis user PKCE
bearer (existing get_current_user path) OR a shared service-token bearer
(for service-to-service callers like Exodus).

Returns a small dict describing the caller. Routes that need to know who
made the call can inspect the result; routes that just need access control
can ignore it.
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import RATES_API_TOKEN
from app.database import get_db

logger = logging.getLogger(__name__)


def _extract_bearer(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer "):].strip()
    return None


def verify_caller(request: Request, db: Session = Depends(get_db)) -> dict:
    """Accept service token OR Themis user PKCE token. Return a caller dict.

    Order of checks:
      1. If RATES_API_TOKEN is configured AND the bearer matches → service caller.
      2. Otherwise, fall through to get_current_user (user PKCE).

    Raises 401 if neither path authenticates.
    """
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Service-token path: only when token is configured (non-empty).
    if RATES_API_TOKEN and token == RATES_API_TOKEN:
        return {"kind": "service", "name": "rates-api-service"}

    # User-PKCE fallback: delegate to the existing user dependency. Any
    # exception from get_current_user (typically 401) propagates.
    from app.auth import get_current_user
    user = get_current_user(request=request, token=None, db=db)
    return {
        "kind": "user",
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
    }
```

- [ ] **Step 5: Run the tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_verify_caller.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/auth_service.py backend/tests/rates/test_verify_caller.py
git commit -m "feat(backend): verify_caller accepts service token OR user PKCE"
```

---

## Task 4: BNR FX parser

**Files:**
- Create: `backend/app/services/rates/__init__.py` (empty)
- Create: `backend/app/services/rates/bnr_fx.py`
- Create: `backend/tests/rates/fixtures/bnr_daily.xml`
- Create: `backend/tests/rates/fixtures/bnr_yearly.xml`
- Create: `backend/tests/rates/test_bnr_fx.py`

- [ ] **Step 1: Create the empty package init**

```bash
mkdir -p backend/app/services/rates
touch backend/app/services/rates/__init__.py
mkdir -p backend/tests/rates/fixtures
```

- [ ] **Step 2: Write the BNR fixtures**

Create `backend/tests/rates/fixtures/bnr_daily.xml` (single-day feed):

```xml
<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="http://www.bnr.ro/xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.bnr.ro/xsd nbrfxrates.xsd">
  <Header>
    <Publisher>National Bank of Romania</Publisher>
    <PublishingDate>2026-03-06</PublishingDate>
    <MessageType>DR</MessageType>
  </Header>
  <Body>
    <Subject>Reference rates</Subject>
    <OrigCurrency>RON</OrigCurrency>
    <Cube date="2026-03-06">
      <Rate currency="EUR">4.9741</Rate>
      <Rate currency="USD">4.3981</Rate>
      <Rate currency="GBP">5.7234</Rate>
      <Rate currency="HUF" multiplier="100">1.1234</Rate>
      <Rate currency="JPY" multiplier="100">2.9876</Rate>
    </Cube>
  </Body>
</DataSet>
```

Create `backend/tests/rates/fixtures/bnr_yearly.xml` (multi-day feed):

```xml
<?xml version="1.0" encoding="utf-8"?>
<DataSet xmlns="http://www.bnr.ro/xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.bnr.ro/xsd nbrfxrates.xsd">
  <Header>
    <Publisher>National Bank of Romania</Publisher>
    <PublishingDate>2026-03-06</PublishingDate>
    <MessageType>DR</MessageType>
  </Header>
  <Body>
    <Subject>Reference rates</Subject>
    <OrigCurrency>RON</OrigCurrency>
    <Cube date="2026-03-04">
      <Rate currency="EUR">4.9700</Rate>
      <Rate currency="USD">4.3900</Rate>
    </Cube>
    <Cube date="2026-03-05">
      <Rate currency="EUR">4.9720</Rate>
      <Rate currency="USD">4.3950</Rate>
      <Rate currency="HUF" multiplier="100">1.1200</Rate>
    </Cube>
    <Cube date="2026-03-06">
      <Rate currency="EUR">4.9741</Rate>
      <Rate currency="USD">4.3981</Rate>
      <Rate currency="HUF" multiplier="100">1.1234</Rate>
    </Cube>
  </Body>
</DataSet>
```

- [ ] **Step 3: Write the failing parser test**

Create `backend/tests/rates/test_bnr_fx.py`:

```python
"""BNR XML parser tests. Covers single-day daily feed + multi-day yearly feed."""
from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_single_day_returns_5_rates_with_correct_multipliers():
    from app.services.rates.bnr_fx import parse_bnr_xml
    rates = parse_bnr_xml(_read("bnr_daily.xml"))
    assert len(rates) == 5
    by_currency = {r.currency: r for r in rates}
    assert by_currency["EUR"].rate == 4.9741
    assert by_currency["EUR"].multiplier == 1
    assert by_currency["EUR"].date == "2026-03-06"
    assert by_currency["USD"].rate == 4.3981
    assert by_currency["HUF"].multiplier == 100
    assert by_currency["JPY"].multiplier == 100


def test_parse_multi_day_returns_8_rates_across_3_dates():
    from app.services.rates.bnr_fx import parse_bnr_xml
    rates = parse_bnr_xml(_read("bnr_yearly.xml"))
    assert len(rates) == 8
    dates = {r.date for r in rates}
    assert dates == {"2026-03-04", "2026-03-05", "2026-03-06"}


def test_parse_empty_returns_empty():
    from app.services.rates.bnr_fx import parse_bnr_xml
    assert parse_bnr_xml("") == []
    assert parse_bnr_xml("   ") == []


def test_parse_garbage_returns_empty():
    from app.services.rates.bnr_fx import parse_bnr_xml
    assert parse_bnr_xml("not xml at all") == []
    assert parse_bnr_xml("<unrelated>x</unrelated>") == []


def test_parse_skips_rate_with_unparseable_value():
    from app.services.rates.bnr_fx import parse_bnr_xml
    bad = """<?xml version="1.0"?>
<DataSet xmlns="http://www.bnr.ro/xsd">
  <Body><Cube date="2026-03-06">
    <Rate currency="EUR">4.97</Rate>
    <Rate currency="USD">not-a-number</Rate>
  </Cube></Body>
</DataSet>"""
    rates = parse_bnr_xml(bad)
    assert len(rates) == 1
    assert rates[0].currency == "EUR"
```

- [ ] **Step 4: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_bnr_fx.py -v`
Expected: ImportError on `app.services.rates.bnr_fx`

- [ ] **Step 5: Implement the parser**

Create `backend/app/services/rates/bnr_fx.py`:

```python
"""BNR FX rate fetcher + parser + storage.

Sources:
  - Daily:  https://www.bnr.ro/nbrfxrates.xml
  - Yearly: https://www.bnr.ro/files/xml/years/nbrfxrates{year}.xml
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

BNR_DAILY_URL = "https://www.bnr.ro/nbrfxrates.xml"


def bnr_year_url(year: int) -> str:
    return f"https://www.bnr.ro/files/xml/years/nbrfxrates{year}.xml"


# BNR XML uses a default namespace; ElementTree exposes the namespace prefix.
# We use a wildcard match so our parser is namespace-agnostic.
_NS_WILDCARD = "{*}"


@dataclass(frozen=True)
class ParsedFxRate:
    date: str       # YYYY-MM-DD
    currency: str
    rate: float
    multiplier: int


def parse_bnr_xml(xml_text: str) -> list[ParsedFxRate]:
    """Parse a BNR DataSet XML into ParsedFxRate objects.

    Tolerant of malformed input — returns [] on any parse error rather than
    raising, so the daily run keeps going if BNR ever ships unexpected data.
    """
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    out: list[ParsedFxRate] = []
    # Body/Cube; tolerate the BNR default namespace via wildcard.
    body = root.find(f"{_NS_WILDCARD}Body")
    if body is None:
        return []
    for cube in body.findall(f"{_NS_WILDCARD}Cube"):
        date = cube.attrib.get("date", "")
        if not date:
            continue
        for rate_el in cube.findall(f"{_NS_WILDCARD}Rate"):
            currency = rate_el.attrib.get("currency", "")
            multiplier_attr = rate_el.attrib.get("multiplier", "1")
            try:
                multiplier = int(multiplier_attr)
            except ValueError:
                multiplier = 1
            try:
                rate = float((rate_el.text or "").strip())
            except (ValueError, AttributeError):
                continue
            if not currency:
                continue
            out.append(ParsedFxRate(date=date, currency=currency, rate=rate, multiplier=multiplier))
    return out


def fetch_bnr_daily(client: httpx.Client | None = None) -> list[ParsedFxRate]:
    """Fetch + parse today's BNR feed. Returns [] on HTTP/parse errors."""
    return _fetch_url(BNR_DAILY_URL, client)


def fetch_bnr_year(year: int, client: httpx.Client | None = None) -> list[ParsedFxRate]:
    """Fetch + parse one year's BNR feed."""
    return _fetch_url(bnr_year_url(year), client)


def _fetch_url(url: str, client: httpx.Client | None) -> list[ParsedFxRate]:
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0)
    try:
        r = client.get(url)
    except httpx.RequestError as e:
        logger.error("[rates/bnr_fx] HTTP error for %s: %s", url, e)
        return []
    finally:
        if own:
            client.close()
    if r.status_code != 200:
        logger.warning("[rates/bnr_fx] %d for %s", r.status_code, url)
        return []
    return parse_bnr_xml(r.text)


def store_fx_rates(db: Session, rates: Iterable[ParsedFxRate]) -> int:
    """Store rates with INSERT OR IGNORE — idempotent. Returns count of newly
    inserted rows."""
    inserted = 0
    for r in rates:
        result = db.execute(
            text(
                "INSERT OR IGNORE INTO exchange_rates "
                "(date, currency, rate, multiplier, source, fetched_at) "
                "VALUES (:date, :currency, :rate, :multiplier, 'BNR', datetime('now'))"
            ),
            {"date": r.date, "currency": r.currency, "rate": r.rate, "multiplier": r.multiplier},
        )
        inserted += result.rowcount or 0
    db.commit()
    return inserted
```

- [ ] **Step 6: Run parser tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_bnr_fx.py -v`
Expected: 5 PASS.

- [ ] **Step 7: Add storage tests**

Append to `backend/tests/rates/test_bnr_fx.py`:

```python
@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models.rates  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_store_fx_rates_inserts_new_and_idempotently_ignores_duplicates(db):
    from app.services.rates.bnr_fx import ParsedFxRate, store_fx_rates
    rates = [
        ParsedFxRate(date="2026-03-06", currency="EUR", rate=4.97, multiplier=1),
        ParsedFxRate(date="2026-03-06", currency="USD", rate=4.39, multiplier=1),
    ]
    assert store_fx_rates(db, rates) == 2
    # Re-insert same rates → 0 new
    assert store_fx_rates(db, rates) == 0
    # New currency on same day → 1 new
    assert store_fx_rates(db, [ParsedFxRate(date="2026-03-06", currency="GBP", rate=5.7, multiplier=1)]) == 1


def test_fetch_bnr_daily_with_mock_returns_parsed():
    """Smoke test for fetch_bnr_daily using httpx.MockTransport."""
    import httpx
    from app.services.rates.bnr_fx import fetch_bnr_daily, BNR_DAILY_URL

    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == BNR_DAILY_URL
        return httpx.Response(200, text=_read("bnr_daily.xml"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rates = fetch_bnr_daily(client)
    assert len(rates) == 5
    client.close()


def test_fetch_bnr_daily_returns_empty_on_5xx():
    import httpx
    from app.services.rates.bnr_fx import fetch_bnr_daily
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert fetch_bnr_daily(client) == []
    client.close()


def test_fetch_bnr_daily_returns_empty_on_network_error():
    import httpx
    from app.services.rates.bnr_fx import fetch_bnr_daily

    def handler(req):
        raise httpx.ConnectError("dns failed")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert fetch_bnr_daily(client) == []
    client.close()
```

- [ ] **Step 8: Run all BNR tests**

Run: `cd backend && uv run pytest tests/rates/test_bnr_fx.py -v`
Expected: 9 PASS (5 parser + 4 storage/fetch).

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/rates/__init__.py backend/app/services/rates/bnr_fx.py backend/tests/rates/test_bnr_fx.py backend/tests/rates/fixtures/bnr_daily.xml backend/tests/rates/fixtures/bnr_yearly.xml
git commit -m "feat(backend): BNR FX parser, fetcher, and storage"
```

---

## Task 5: ROBOR parser + fetcher + storage

**Files:**
- Create: `backend/app/services/rates/robor.py`
- Create: `backend/tests/rates/fixtures/robor.html`
- Create: `backend/tests/rates/test_robor.py`

- [ ] **Step 1: Write the fixture**

Create `backend/tests/rates/fixtures/robor.html` — a minimal version of the curs-valutar-bnr.ro/robor table that mirrors what their site emits. The parser only needs the table structure:

```html
<!DOCTYPE html>
<html>
<head><title>ROBOR</title></head>
<body>
<table class="table">
  <thead>
    <tr>
      <th>Data</th>
      <th>ROBOR ON</th>
      <th>ROBOR 1S</th>
      <th>ROBOR 1L</th>
      <th>ROBOR 3L</th>
      <th>ROBOR 6L</th>
      <th>ROBOR 12L</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>06 Mar 2026</td>
      <td>5.50</td>
      <td>5.62</td>
      <td>5.78</td>
      <td>5.92</td>
      <td>6.05</td>
      <td>6.18</td>
    </tr>
    <tr>
      <td>05 Mar 2026</td>
      <td>5.48</td>
      <td>5.60</td>
      <td>5.76</td>
      <td>5.90</td>
      <td>6.03</td>
      <td>6.16</td>
    </tr>
  </tbody>
</table>
</body>
</html>
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/rates/test_robor.py`:

```python
"""ROBOR parser tests. The HTML fixture is a minimal version of what
curs-valutar-bnr.ro emits; if their schema drifts, the parser will return
empty and the daily run will log a warning."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_robor_extracts_6_tenors_per_date():
    from app.services.rates.robor import parse_robor_html
    rates = parse_robor_html(_read("robor.html"))
    # 2 dates × 6 tenors = 12 rows
    assert len(rates) == 12
    by_key = {(r.date, r.tenor): r for r in rates}
    # 06 Mar 2026 → 2026-03-06; "ROBOR ON" → "ON" tenor
    assert by_key[("2026-03-06", "ON")].rate == 5.50
    assert by_key[("2026-03-06", "3M")].rate == 5.92
    assert by_key[("2026-03-06", "12M")].rate == 6.18
    # All rate_type = ROBOR
    assert all(r.rate_type == "ROBOR" for r in rates)


def test_parse_robor_returns_empty_on_garbage():
    from app.services.rates.robor import parse_robor_html
    assert parse_robor_html("") == []
    assert parse_robor_html("<html><body>nothing here</body></html>") == []


def test_parse_robor_skips_unparseable_rate():
    from app.services.rates.robor import parse_robor_html
    bad = """<table><thead><tr><th>Data</th><th>ROBOR ON</th></tr></thead>
    <tbody><tr><td>06 Mar 2026</td><td>not-a-number</td></tr></tbody></table>"""
    assert parse_robor_html(bad) == []  # nothing valid to extract


@pytest.fixture
def db(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models.rates  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_store_robor_inserts_and_is_idempotent(db):
    from app.services.rates.robor import ParsedInterestRate, store_interest_rates
    rates = [
        ParsedInterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92),
        ParsedInterestRate(date="2026-03-06", rate_type="ROBOR", tenor="6M", rate=6.05),
    ]
    assert store_interest_rates(db, rates, source="curs-valutar-bnr.ro") == 2
    assert store_interest_rates(db, rates, source="curs-valutar-bnr.ro") == 0


def test_fetch_robor_returns_parsed_via_mock_transport():
    from app.services.rates.robor import fetch_robor_current
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=_read("robor.html"))
    ))
    rates = fetch_robor_current(client)
    assert len(rates) == 12
    client.close()


def test_fetch_robor_empty_on_5xx():
    from app.services.rates.robor import fetch_robor_current
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    assert fetch_robor_current(client) == []
    client.close()
```

- [ ] **Step 3: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_robor.py -v`
Expected: ImportError on `app.services.rates.robor`

- [ ] **Step 4: Implement the parser + fetcher + storage**

Create `backend/app/services/rates/robor.py`:

```python
"""ROBOR rate fetcher + parser + storage.

Source: https://www.curs-valutar-bnr.ro/robor
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ROBOR_URL = "https://www.curs-valutar-bnr.ro/robor"

# Map column header tokens to standard tenor codes.
# curs-valutar-bnr.ro uses Romanian-language headers like "ROBOR 1S" (1 week),
# "ROBOR 1L" (1 month), etc. ROBOR ON = overnight.
_TENOR_MAP = {
    "ON": "ON",
    "1S": "1W",
    "1L": "1M",
    "3L": "3M",
    "6L": "6M",
    "12L": "12M",
}


# Romanian + English month abbreviations seen in the table's date column.
_MONTHS = {
    # English (used by some BNR tables)
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    # Romanian (used by curs-valutar-bnr.ro)
    "Ian": "01", "Ian.": "01",
    "Feb.": "02",
    "Mar.": "03",
    "Apr.": "04",
    "Mai": "05",
    "Iun": "06", "Iun.": "06",
    "Iul": "07", "Iul.": "07",
    "Aug.": "08",
    "Sep.": "09", "Sept": "09", "Sept.": "09",
    "Oct.": "10",
    "Noi": "11", "Noi.": "11",
    "Dec.": "12",
}


@dataclass(frozen=True)
class ParsedInterestRate:
    date: str         # YYYY-MM-DD
    rate_type: str    # "ROBOR" | "EURIBOR"
    tenor: str        # "ON" | "1W" | "1M" | "3M" | "6M" | "12M"
    rate: float


def _parse_date(raw: str) -> str | None:
    """Parse "06 Mar 2026" or "6 Mar 2026" -> "2026-03-06"."""
    parts = raw.strip().split()
    if len(parts) != 3:
        return None
    day, month_token, year = parts
    month = _MONTHS.get(month_token) or _MONTHS.get(month_token + ".")
    if not month:
        return None
    try:
        return f"{int(year):04d}-{month}-{int(day):02d}"
    except ValueError:
        return None


def parse_robor_html(html: str) -> list[ParsedInterestRate]:
    """Parse curs-valutar-bnr.ro ROBOR table into ParsedInterestRate rows."""
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    thead = table.find("thead")
    tbody = table.find("tbody")
    if thead is None or tbody is None:
        return []

    headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    if not headers or headers[0].lower() != "data":
        return []

    # For columns 1..N, derive their tenor (or None to skip)
    column_tenors: list[str | None] = [None]  # column 0 is the date column
    for h in headers[1:]:
        # Header looks like "ROBOR ON" / "ROBOR 1S" — last token is the tenor.
        token = h.split()[-1] if h.split() else ""
        column_tenors.append(_TENOR_MAP.get(token))

    out: list[ParsedInterestRate] = []
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 2:
            continue
        date = _parse_date(cells[0])
        if not date:
            continue
        for i in range(1, min(len(cells), len(column_tenors))):
            tenor = column_tenors[i]
            if tenor is None:
                continue
            try:
                rate = float(cells[i])
            except ValueError:
                continue
            out.append(ParsedInterestRate(
                date=date, rate_type="ROBOR", tenor=tenor, rate=rate,
            ))
    return out


def fetch_robor_current(client: httpx.Client | None = None) -> list[ParsedInterestRate]:
    """Fetch + parse current ROBOR table. Returns [] on HTTP/parse errors."""
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0)
    try:
        r = client.get(ROBOR_URL)
    except httpx.RequestError as e:
        logger.error("[rates/robor] HTTP error: %s", e)
        return []
    finally:
        if own:
            client.close()
    if r.status_code != 200:
        logger.warning("[rates/robor] %d for %s", r.status_code, ROBOR_URL)
        return []
    return parse_robor_html(r.text)


def store_interest_rates(
    db: Session,
    rates: Iterable[ParsedInterestRate],
    source: str,
) -> int:
    """Store interest rates idempotently. Returns count of newly inserted rows."""
    inserted = 0
    for r in rates:
        result = db.execute(
            text(
                "INSERT OR IGNORE INTO interest_rates "
                "(date, rate_type, tenor, rate, source, fetched_at) "
                "VALUES (:date, :rate_type, :tenor, :rate, :source, datetime('now'))"
            ),
            {"date": r.date, "rate_type": r.rate_type, "tenor": r.tenor, "rate": r.rate, "source": source},
        )
        inserted += result.rowcount or 0
    db.commit()
    return inserted
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_robor.py -v`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/rates/robor.py backend/tests/rates/test_robor.py backend/tests/rates/fixtures/robor.html
git commit -m "feat(backend): ROBOR parser, fetcher, and shared interest-rate storage"
```

---

## Task 6: EURIBOR parser + fetcher

**Files:**
- Create: `backend/app/services/rates/euribor.py`
- Create: `backend/tests/rates/fixtures/euribor.html`
- Create: `backend/tests/rates/test_euribor.py`

- [ ] **Step 1: Write the fixture**

Create `backend/tests/rates/fixtures/euribor.html` — a minimal sample of euribor-rates.eu's current-rates page:

```html
<!DOCTYPE html>
<html>
<body>
<table class="table">
  <thead>
    <tr>
      <th>Date</th>
      <th>Euribor 1-week</th>
      <th>Euribor 1-month</th>
      <th>Euribor 3-month</th>
      <th>Euribor 6-month</th>
      <th>Euribor 12-month</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>3/6/2026</td>
      <td>2.612</td>
      <td>2.625</td>
      <td>2.683</td>
      <td>2.760</td>
      <td>2.815</td>
    </tr>
    <tr>
      <td>3/5/2026</td>
      <td>2.610</td>
      <td>2.622</td>
      <td>2.681</td>
      <td>2.755</td>
      <td>2.810</td>
    </tr>
  </tbody>
</table>
</body>
</html>
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/rates/test_euribor.py`:

```python
"""EURIBOR parser tests."""
from __future__ import annotations

from pathlib import Path

import httpx


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_euribor_extracts_5_tenors_per_date():
    from app.services.rates.euribor import parse_euribor_html
    rates = parse_euribor_html(_read("euribor.html"))
    assert len(rates) == 10  # 2 dates × 5 tenors
    by_key = {(r.date, r.tenor): r for r in rates}
    assert by_key[("2026-03-06", "1W")].rate == 2.612
    assert by_key[("2026-03-06", "3M")].rate == 2.683
    assert by_key[("2026-03-06", "12M")].rate == 2.815
    assert all(r.rate_type == "EURIBOR" for r in rates)


def test_parse_euribor_handles_us_and_iso_dates():
    """euribor-rates.eu uses M/D/YYYY (US format). Make sure we handle it
    AND any ISO fallback."""
    from app.services.rates.euribor import parse_euribor_html
    html = """<table><thead><tr><th>Date</th><th>Euribor 3-month</th></tr></thead>
    <tbody><tr><td>3/6/2026</td><td>2.683</td></tr></tbody></table>"""
    rates = parse_euribor_html(html)
    assert len(rates) == 1
    assert rates[0].date == "2026-03-06"


def test_parse_euribor_empty_on_garbage():
    from app.services.rates.euribor import parse_euribor_html
    assert parse_euribor_html("") == []
    assert parse_euribor_html("<html>nothing</html>") == []


def test_fetch_euribor_with_mock_returns_parsed():
    from app.services.rates.euribor import fetch_euribor_current
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=_read("euribor.html"))
    ))
    rates = fetch_euribor_current(client)
    assert len(rates) == 10
    client.close()


def test_fetch_euribor_empty_on_5xx():
    from app.services.rates.euribor import fetch_euribor_current
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert fetch_euribor_current(client) == []
    client.close()
```

- [ ] **Step 3: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_euribor.py -v`
Expected: ImportError on `app.services.rates.euribor`

- [ ] **Step 4: Implement the parser + fetcher**

Create `backend/app/services/rates/euribor.py`:

```python
"""EURIBOR rate fetcher + parser.

Source: https://www.euribor-rates.eu/en/current-euribor-rates/
        https://www.euribor-rates.eu/en/euribor-rates-by-year/{year}/
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from app.services.rates.robor import ParsedInterestRate

logger = logging.getLogger(__name__)

EURIBOR_URL = "https://www.euribor-rates.eu/en/current-euribor-rates/"


def euribor_year_url(year: int) -> str:
    return f"https://www.euribor-rates.eu/en/euribor-rates-by-year/{year}/"


# Map header tokens like "1-week", "1-month", "12-month" to standard tenors.
_TENOR_RE = re.compile(r"euribor\s+(\d+)[\s-]?(week|month)", re.IGNORECASE)


def _header_to_tenor(header: str) -> str | None:
    m = _TENOR_RE.search(header)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "week":
        return f"{n}W"
    if unit == "month":
        return f"{n}M"
    return None


def _parse_us_or_iso_date(raw: str) -> str | None:
    """Accept '3/6/2026' (M/D/YYYY) or '2026-03-06' (ISO)."""
    raw = raw.strip()
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) == 3:
            try:
                m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
                return f"{y:04d}-{m:02d}-{d:02d}"
            except ValueError:
                return None
    if "-" in raw and len(raw) == 10:
        # already ISO
        return raw
    return None


def parse_euribor_html(html: str) -> list[ParsedInterestRate]:
    if not html or not html.strip():
        return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    thead = table.find("thead")
    tbody = table.find("tbody")
    if thead is None or tbody is None:
        return []

    headers = [th.get_text(strip=True) for th in thead.find_all("th")]
    if not headers:
        return []
    column_tenors: list[str | None] = [None]  # column 0 is the date column
    for h in headers[1:]:
        column_tenors.append(_header_to_tenor(h))

    out: list[ParsedInterestRate] = []
    for tr in tbody.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 2:
            continue
        date = _parse_us_or_iso_date(cells[0])
        if not date:
            continue
        for i in range(1, min(len(cells), len(column_tenors))):
            tenor = column_tenors[i]
            if tenor is None:
                continue
            try:
                rate = float(cells[i])
            except ValueError:
                continue
            out.append(ParsedInterestRate(
                date=date, rate_type="EURIBOR", tenor=tenor, rate=rate,
            ))
    return out


def _fetch(url: str, client: httpx.Client | None) -> list[ParsedInterestRate]:
    own = client is None
    if own:
        client = httpx.Client(timeout=30.0)
    try:
        r = client.get(url)
    except httpx.RequestError as e:
        logger.error("[rates/euribor] HTTP error for %s: %s", url, e)
        return []
    finally:
        if own:
            client.close()
    if r.status_code != 200:
        logger.warning("[rates/euribor] %d for %s", r.status_code, url)
        return []
    return parse_euribor_html(r.text)


def fetch_euribor_current(client: httpx.Client | None = None) -> list[ParsedInterestRate]:
    return _fetch(EURIBOR_URL, client)


def fetch_euribor_year(year: int, client: httpx.Client | None = None) -> list[ParsedInterestRate]:
    return _fetch(euribor_year_url(year), client)
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_euribor.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/rates/euribor.py backend/tests/rates/test_euribor.py backend/tests/rates/fixtures/euribor.html
git commit -m "feat(backend): EURIBOR parser and fetcher"
```

---

## Task 7: `run_rates_update_check` orchestrator

**Files:**
- Create: `backend/app/services/rates/run.py`
- Create: `backend/tests/rates/test_run.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/rates/test_run.py`:

```python
"""Orchestrator that calls all three fetchers and stores results."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models.rates  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    # Patch SessionLocal so run_rates_update_check uses our test session
    monkeypatch.setattr("app.database.SessionLocal", Session)
    s = Session()
    yield s
    s.close()


def test_run_calls_all_three_fetchers_and_stores(db):
    from app.services.rates.bnr_fx import ParsedFxRate
    from app.services.rates.robor import ParsedInterestRate
    from app.services.rates.run import run_rates_update_check

    fake_fx = [ParsedFxRate(date="2026-03-06", currency="EUR", rate=4.97, multiplier=1)]
    fake_robor = [ParsedInterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92)]
    fake_eur = [ParsedInterestRate(date="2026-03-06", rate_type="EURIBOR", tenor="3M", rate=2.68)]

    with patch("app.services.rates.run.fetch_bnr_daily", return_value=fake_fx), \
         patch("app.services.rates.run.fetch_robor_current", return_value=fake_robor), \
         patch("app.services.rates.run.fetch_euribor_current", return_value=fake_eur):
        result = run_rates_update_check()

    assert result["fx_inserted"] == 1
    assert result["robor_inserted"] == 1
    assert result["euribor_inserted"] == 1
    assert result["errors"] == 0


def test_run_continues_when_one_fetcher_returns_empty(db):
    from app.services.rates.run import run_rates_update_check

    with patch("app.services.rates.run.fetch_bnr_daily", return_value=[]), \
         patch("app.services.rates.run.fetch_robor_current", return_value=[]), \
         patch("app.services.rates.run.fetch_euribor_current", return_value=[]):
        result = run_rates_update_check()

    assert result["fx_inserted"] == 0
    assert result["robor_inserted"] == 0
    assert result["euribor_inserted"] == 0
    # Empty isn't an error per se — could be a holiday
    assert result["errors"] == 0


def test_run_records_error_when_fetcher_raises(db):
    from app.services.rates.run import run_rates_update_check

    def boom(*a, **k):
        raise RuntimeError("BNR is down")

    with patch("app.services.rates.run.fetch_bnr_daily", side_effect=boom), \
         patch("app.services.rates.run.fetch_robor_current", return_value=[]), \
         patch("app.services.rates.run.fetch_euribor_current", return_value=[]):
        result = run_rates_update_check()

    assert result["errors"] == 1
    # Other fetchers still ran
    assert result["robor_inserted"] == 0
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_run.py -v`
Expected: ImportError on `app.services.rates.run`

- [ ] **Step 3: Implement the orchestrator**

Create `backend/app/services/rates/run.py`:

```python
"""Orchestrate the daily rates update.

Called from:
  - The AICC scheduler webhook handler (POST /internal/scheduler/rates-update).
  - Tests (directly).

Each fetcher is wrapped in its own try/except so one source's outage doesn't
block the others. Errors are counted; fully-failing runs still return a
result dict so the scheduler can log a non-empty summary.
"""
from __future__ import annotations

import logging
from typing import Any

from app.database import SessionLocal
from app.services.rates.bnr_fx import fetch_bnr_daily, store_fx_rates
from app.services.rates.euribor import fetch_euribor_current
from app.services.rates.robor import fetch_robor_current, store_interest_rates

logger = logging.getLogger(__name__)


def run_rates_update_check() -> dict[str, Any]:
    """Fetch + store rates from BNR, ROBOR, and EURIBOR sources.

    Returns a summary dict suitable for logging via scheduler_log_service.
    """
    summary: dict[str, Any] = {
        "fx_inserted": 0,
        "robor_inserted": 0,
        "euribor_inserted": 0,
        "errors": 0,
        "error_messages": [],
    }

    db = SessionLocal()
    try:
        # BNR FX
        try:
            fx = fetch_bnr_daily()
            summary["fx_inserted"] = store_fx_rates(db, fx)
            logger.info("[rates] BNR FX: %d new rows", summary["fx_inserted"])
        except Exception as e:
            summary["errors"] += 1
            summary["error_messages"].append(f"bnr_fx: {e}")
            logger.error("[rates] BNR FX failed: %s", e)

        # ROBOR
        try:
            robor = fetch_robor_current()
            summary["robor_inserted"] = store_interest_rates(db, robor, source="curs-valutar-bnr.ro")
            logger.info("[rates] ROBOR: %d new rows", summary["robor_inserted"])
        except Exception as e:
            summary["errors"] += 1
            summary["error_messages"].append(f"robor: {e}")
            logger.error("[rates] ROBOR failed: %s", e)

        # EURIBOR
        try:
            eur = fetch_euribor_current()
            summary["euribor_inserted"] = store_interest_rates(db, eur, source="euribor-rates.eu")
            logger.info("[rates] EURIBOR: %d new rows", summary["euribor_inserted"])
        except Exception as e:
            summary["errors"] += 1
            summary["error_messages"].append(f"euribor: {e}")
            logger.error("[rates] EURIBOR failed: %s", e)
    finally:
        db.close()

    return summary
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_run.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rates/run.py backend/tests/rates/test_run.py
git commit -m "feat(backend): run_rates_update_check orchestrates daily ingest"
```

---

## Task 8: Scheduler webhook + main.py wiring

**Files:**
- Modify: `backend/app/routers/internal_scheduler.py` (add `rates-update` handler)
- Modify: `backend/app/main.py` (no-op; the run function lives in services already)
- Create: `backend/tests/rates/test_scheduler_webhook.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/rates/test_scheduler_webhook.py`:

```python
"""POST /internal/scheduler/rates-update — HMAC-signed by AICC scheduler."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient


SECRET = "test-scheduler-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _set_secret(monkeypatch):
    monkeypatch.setattr("app.routers.internal_scheduler.AICC_SCHEDULER_SECRET", SECRET)


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_signed_request_accepts_and_returns_202(client, monkeypatch):
    called = {}
    def fake_run():
        called["yes"] = True
        return {"fx_inserted": 1}
    monkeypatch.setattr("app.services.rates.run.run_rates_update_check", fake_run)

    body = json.dumps({"taskId": "x"}).encode()
    r = client.post(
        "/internal/scheduler/rates-update",
        content=body,
        headers={"X-AICC-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert r.json()["job"] == "rates-update"


def test_unsigned_request_rejected_with_401(client):
    r = client.post(
        "/internal/scheduler/rates-update",
        content=b'{"taskId":"x"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_wrong_signature_rejected_with_401(client):
    r = client.post(
        "/internal/scheduler/rates-update",
        content=b'{"taskId":"x"}',
        headers={"X-AICC-Signature": "sha256=bogus", "Content-Type": "application/json"},
    )
    assert r.status_code == 401
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_scheduler_webhook.py -v`
Expected: 404 on POST (route doesn't exist yet).

- [ ] **Step 3: Add the handler**

In `backend/app/routers/internal_scheduler.py`, find the `eu_update` handler at the bottom and ADD this directly after it:

```python
@router.post("/rates-update")
async def rates_update(request: Request, background_tasks: BackgroundTasks):
    """AICC cron: daily FX (BNR) + ROBOR + EURIBOR rates ingest."""
    await _verify_signature(request)

    def _run_and_log():
        from app.database import SessionLocal
        from app.services.rates.run import run_rates_update_check
        from app.services.scheduler_log_service import record_run

        results = run_rates_update_check()
        db = SessionLocal()
        try:
            record_run(db, "rates", results, "scheduled")
        finally:
            db.close()

    background_tasks.add_task(_run_and_log)
    logger.info("AICC scheduler webhook accepted: rates-update")
    return {"status": "accepted", "job": "rates-update"}
```

- [ ] **Step 4: Run webhook tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_scheduler_webhook.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/internal_scheduler.py backend/tests/rates/test_scheduler_webhook.py
git commit -m "feat(backend): /internal/scheduler/rates-update webhook handler"
```

---

## Task 9: Public API endpoints

**Files:**
- Create: `backend/app/routers/rates.py`
- Modify: `backend/app/main.py` (register the router)
- Create: `backend/tests/rates/test_api_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/rates/test_api_endpoints.py`:

```python
"""Public API: GET /api/rates/exchange and GET /api/rates/interest.

Both endpoints accept a Themis user PKCE bearer OR a shared service-token
bearer (RATES_API_TOKEN). Without auth → 401.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient


SERVICE_TOKEN = "test-service-token"


@pytest.fixture(autouse=True)
def _patch_token(monkeypatch):
    monkeypatch.setattr("app.auth_service.RATES_API_TOKEN", SERVICE_TOKEN)


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Boot the app pointing at an in-memory test DB seeded with rate rows."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, get_db
    import app.models.rates  # noqa: F401
    from app.models.rates import ExchangeRate, InterestRate

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    seed = Session()
    # Seed: 3 FX rows, 4 interest-rate rows
    seed.add_all([
        ExchangeRate(date="2026-03-06", currency="EUR", rate=4.9741, source="BNR"),
        ExchangeRate(date="2026-03-06", currency="USD", rate=4.3981, source="BNR"),
        ExchangeRate(date="2026-03-05", currency="EUR", rate=4.9720, source="BNR"),
        InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="3M", rate=5.92, source="x"),
        InterestRate(date="2026-03-06", rate_type="ROBOR", tenor="6M", rate=6.05, source="x"),
        InterestRate(date="2026-03-06", rate_type="EURIBOR", tenor="3M", rate=2.68, source="y"),
        InterestRate(date="2026-03-05", rate_type="ROBOR", tenor="3M", rate=5.90, source="x"),
    ])
    seed.commit()
    seed.close()

    from app.main import app

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


def test_exchange_no_auth_returns_401(client):
    r = client.get("/api/rates/exchange")
    assert r.status_code == 401


def test_exchange_service_token_returns_rows(client):
    r = client.get(
        "/api/rates/exchange",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    # Sorted: most recent first, then currency ASC
    assert rows[0]["date"] == "2026-03-06"
    # Service-pulled rows are sorted in JS-compatible shape
    assert "rate" in rows[0]


def test_exchange_filter_by_currency(client):
    r = client.get(
        "/api/rates/exchange?currency=EUR",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    rows = r.json()
    assert len(rows) == 2
    assert all(row["currency"] == "EUR" for row in rows)


def test_exchange_filter_by_date_range(client):
    r = client.get(
        "/api/rates/exchange?from=2026-03-06&to=2026-03-06",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    rows = r.json()
    assert len(rows) == 2
    assert all(row["date"] == "2026-03-06" for row in rows)


def test_exchange_limit(client):
    r = client.get(
        "/api/rates/exchange?limit=1",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    assert len(r.json()) == 1


def test_interest_filter_by_rate_type(client):
    r = client.get(
        "/api/rates/interest?rate_type=ROBOR",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    rows = r.json()
    assert len(rows) == 3
    assert all(row["rate_type"] == "ROBOR" for row in rows)


def test_interest_filter_by_tenor(client):
    r = client.get(
        "/api/rates/interest?tenor=3M",
        headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
    )
    rows = r.json()
    assert all(row["tenor"] == "3M" for row in rows)


def test_interest_no_auth_returns_401(client):
    r = client.get("/api/rates/interest")
    assert r.status_code == 401
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_api_endpoints.py -v`
Expected: 404 (router not registered yet).

- [ ] **Step 3: Implement the router**

Create `backend/app/routers/rates.py`:

```python
"""Public read API for FX + interest rates.

Auth: either Themis user PKCE bearer or shared RATES_API_TOKEN bearer.
Both gated by the verify_caller dependency.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.auth_service import verify_caller
from app.database import get_db
from app.models.rates import ExchangeRate, InterestRate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rates", tags=["Rates"])


@router.get("/exchange")
def list_exchange_rates(
    currency: str | None = Query(None, description="Filter by currency, e.g. 'EUR'"),
    from_: str | None = Query(None, alias="from", description="ISO date >= filter"),
    to: str | None = Query(None, description="ISO date <= filter"),
    limit: int = Query(30, ge=1, le=10000),
    db: Session = Depends(get_db),
    _caller: dict = Depends(verify_caller),
) -> list[dict]:
    q = db.query(ExchangeRate)
    if currency:
        q = q.filter(ExchangeRate.currency == currency.upper())
    if from_:
        q = q.filter(ExchangeRate.date >= from_)
    if to:
        q = q.filter(ExchangeRate.date <= to)
    rows = (
        q.order_by(ExchangeRate.date.desc(), ExchangeRate.currency.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "date": r.date,
            "currency": r.currency,
            "rate": r.rate,
            "multiplier": r.multiplier,
            "source": r.source,
        }
        for r in rows
    ]


@router.get("/interest")
def list_interest_rates(
    rate_type: str | None = Query(None, description="Filter by rate_type, e.g. 'ROBOR'"),
    tenor: str | None = Query(None, description="Filter by tenor, e.g. '3M'"),
    from_: str | None = Query(None, alias="from", description="ISO date >= filter"),
    to: str | None = Query(None, description="ISO date <= filter"),
    limit: int = Query(30, ge=1, le=10000),
    db: Session = Depends(get_db),
    _caller: dict = Depends(verify_caller),
) -> list[dict]:
    q = db.query(InterestRate)
    if rate_type:
        q = q.filter(InterestRate.rate_type == rate_type.upper())
    if tenor:
        q = q.filter(InterestRate.tenor == tenor.upper())
    if from_:
        q = q.filter(InterestRate.date >= from_)
    if to:
        q = q.filter(InterestRate.date <= to)
    rows = (
        q.order_by(
            InterestRate.date.desc(),
            InterestRate.rate_type.asc(),
            InterestRate.tenor.asc(),
        )
        .limit(limit)
        .all()
    )
    return [
        {
            "date": r.date,
            "rate_type": r.rate_type,
            "tenor": r.tenor,
            "rate": r.rate,
            "source": r.source,
        }
        for r in rows
    ]
```

- [ ] **Step 4: Register the router in `app/main.py`**

In `backend/app/main.py`, find the existing block of `from app.routers import ...` near the top of the file. Add `rates` to one of those lines, e.g. change:

```python
from app.routers import settings_categories, settings_pipeline, settings_prompts
```

to add a new line:

```python
from app.routers import rates as rates_router
```

Then find where other routers are included with `app.include_router(...)` (search for `app.include_router`) and add:

```python
app.include_router(rates_router.router)
```

(Match the style of the existing includes.)

- [ ] **Step 5: Run API tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_api_endpoints.py -v`
Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/rates.py backend/app/main.py backend/tests/rates/test_api_endpoints.py
git commit -m "feat(backend): GET /api/rates/exchange and /api/rates/interest"
```

---

## Task 10: Backfill (admin endpoint + job runner)

**Files:**
- Create: `backend/app/services/rates/backfill.py`
- Modify: `backend/app/routers/admin.py` (add `POST /api/admin/rates/backfill`)
- Create: `backend/tests/rates/test_backfill.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/rates/test_backfill.py`:

```python
"""Backfill orchestration: iterates years, calls per-year fetchers, stores."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models.rates  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.database.SessionLocal", Session)
    s = Session()
    yield s
    s.close()


def test_backfill_iterates_years_and_aggregates_counts(db):
    from app.services.rates.backfill import run_rates_backfill
    from app.services.rates.bnr_fx import ParsedFxRate
    from app.services.rates.robor import ParsedInterestRate

    fx_per_year = {
        2024: [ParsedFxRate(date="2024-01-15", currency="EUR", rate=4.9, multiplier=1)],
        2025: [
            ParsedFxRate(date="2025-01-15", currency="EUR", rate=4.95, multiplier=1),
            ParsedFxRate(date="2025-06-01", currency="USD", rate=4.4, multiplier=1),
        ],
    }
    eur_per_year = {
        2024: [ParsedInterestRate(date="2024-01-15", rate_type="EURIBOR", tenor="3M", rate=3.6)],
        2025: [],
    }

    def fake_fx_year(year, client=None):
        return fx_per_year.get(year, [])

    def fake_eur_year(year, client=None):
        return eur_per_year.get(year, [])

    with patch("app.services.rates.backfill.fetch_bnr_year", side_effect=fake_fx_year), \
         patch("app.services.rates.backfill.fetch_euribor_year", side_effect=fake_eur_year), \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=2, current_year=2025)

    assert result["fx_inserted"] == 3
    assert result["euribor_inserted"] == 1
    # ROBOR backfill uses fetch_robor_current as a placeholder (no per-year URL);
    # acceptable. Test just confirms the call doesn't crash.


def test_backfill_continues_when_year_returns_empty(db):
    from app.services.rates.backfill import run_rates_backfill

    with patch("app.services.rates.backfill.fetch_bnr_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_euribor_year", return_value=[]), \
         patch("app.services.rates.backfill.fetch_robor_current", return_value=[]):
        result = run_rates_backfill(years=3, current_year=2026)

    assert result["fx_inserted"] == 0
    assert result["euribor_inserted"] == 0
    assert result["years_processed"] == [2024, 2025, 2026]
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd backend && uv run pytest tests/rates/test_backfill.py -v`
Expected: ImportError on `app.services.rates.backfill`

- [ ] **Step 3: Implement the backfill orchestrator**

Create `backend/app/services/rates/backfill.py`:

```python
"""Multi-year backfill of FX + interest rates.

ROBOR's source (curs-valutar-bnr.ro) doesn't expose per-year URLs the same
way BNR / euribor-rates.eu do. The simplest practical approach: call the
"current" page once during backfill — it returns a window of recent dates
which we INSERT OR IGNORE, so we don't double-store. Older ROBOR data is
out of scope until we identify a reliable archive source.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Callable

from app.database import SessionLocal
from app.services.rates.bnr_fx import fetch_bnr_year, store_fx_rates
from app.services.rates.euribor import fetch_euribor_year
from app.services.rates.robor import fetch_robor_current, store_interest_rates

logger = logging.getLogger(__name__)


def run_rates_backfill(
    years: int,
    current_year: int | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Backfill `years` years of rates from upstream sources.

    `current_year` is parameterized so tests don't depend on the system clock.
    """
    if current_year is None:
        current_year = datetime.datetime.utcnow().year

    start_year = current_year - years + 1
    year_range = list(range(start_year, current_year + 1))

    summary: dict[str, Any] = {
        "fx_inserted": 0,
        "euribor_inserted": 0,
        "robor_inserted": 0,
        "years_processed": [],
        "errors": 0,
        "error_messages": [],
    }

    db = SessionLocal()
    try:
        # ROBOR: one call up front. curs-valutar-bnr.ro shows recent history
        # in one page; older ROBOR is out of scope.
        try:
            robor = fetch_robor_current()
            summary["robor_inserted"] = store_interest_rates(
                db, robor, source="curs-valutar-bnr.ro"
            )
            logger.info("[backfill] ROBOR: %d rows", summary["robor_inserted"])
        except Exception as e:
            summary["errors"] += 1
            summary["error_messages"].append(f"robor: {e}")
            logger.error("[backfill] ROBOR failed: %s", e)

        for i, year in enumerate(year_range, start=1):
            if on_progress is not None:
                on_progress(i, len(year_range), f"year {year}")

            # BNR FX yearly
            try:
                fx = fetch_bnr_year(year)
                inserted = store_fx_rates(db, fx)
                summary["fx_inserted"] += inserted
                logger.info("[backfill] BNR %d: %d rows", year, inserted)
            except Exception as e:
                summary["errors"] += 1
                summary["error_messages"].append(f"bnr_fx[{year}]: {e}")
                logger.error("[backfill] BNR %d failed: %s", year, e)

            # EURIBOR yearly
            try:
                eur = fetch_euribor_year(year)
                inserted = store_interest_rates(db, eur, source="euribor-rates.eu")
                summary["euribor_inserted"] += inserted
                logger.info("[backfill] EURIBOR %d: %d rows", year, inserted)
            except Exception as e:
                summary["errors"] += 1
                summary["error_messages"].append(f"euribor[{year}]: {e}")
                logger.error("[backfill] EURIBOR %d failed: %s", year, e)

            summary["years_processed"].append(year)
    finally:
        db.close()

    return summary
```

- [ ] **Step 4: Run backfill tests, verify pass**

Run: `cd backend && uv run pytest tests/rates/test_backfill.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Add the admin endpoint**

In `backend/app/routers/admin.py`, find the existing `BACKFILL_NOTES_KIND = "backfill_notes"` block. After the existing backfill-notes endpoint, ADD:

```python
# ---------------------------------------------------------------------------
# Rates backfill (Spec: 2026-04-28-rates-feed-design)
# ---------------------------------------------------------------------------

BACKFILL_RATES_KIND = "backfill_rates"


@router.post("/rates/backfill")
def trigger_rates_backfill(
    years: int = 7,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Backfill `years` years of FX + interest rates. Returns job_id."""
    if years < 1 or years > 30:
        raise HTTPException(status_code=400, detail="years must be 1..30")

    from app.services import job_service

    if job_service.has_active(db, kind=BACKFILL_RATES_KIND):
        raise HTTPException(status_code=409, detail="rates backfill is already running")

    def _runner(db, job_id, params):
        from app.services import job_service as _js
        from app.services.rates.backfill import run_rates_backfill

        years_param = int(params.get("years", 7))

        def _on_progress(current: int, total: int, label: str):
            from app.database import SessionLocal
            ps = SessionLocal()
            try:
                _js.update_progress(
                    ps, job_id, phase=label, current=current, total=total,
                )
            finally:
                ps.close()

        return run_rates_backfill(years=years_param, on_progress=_on_progress)

    job_id = job_service.submit(
        kind=BACKFILL_RATES_KIND,
        params={"years": years},
        runner=_runner,
        user_id=admin.id,
        db=db,
    )
    logger.info("Triggered rates backfill (years=%d) as job %s", years, job_id)
    return {"status": "started", "years": years, "job_id": job_id}
```

- [ ] **Step 6: Verify the admin endpoint loads**

Run: `cd backend && uv run python -c "from app.main import app; routes = [r.path for r in app.routes]; assert '/api/admin/rates/backfill' in routes; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Run full backend suite**

Run: `cd backend && uv run pytest --no-header -q`
Expected: pass count up by ~31 (all our new tests). Pre-existing failures unchanged.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/rates/backfill.py backend/app/routers/admin.py backend/tests/rates/test_backfill.py
git commit -m "feat(backend): rates backfill admin endpoint + job runner"
```

---

## Task 11: Cutover runbook

**Files:**
- Create: `docs/superpowers/runbooks/2026-04-28-rates-feed-cutover.md`

- [ ] **Step 1: Write the runbook**

Create `docs/superpowers/runbooks/2026-04-28-rates-feed-cutover.md`:

```markdown
# Rates Feed Cutover Runbook

**Spec:** `docs/superpowers/specs/2026-04-28-rates-feed-design.md`
**Plan:** `docs/superpowers/plans/2026-04-28-rates-feed.md`

## What this enables

Daily ingest of FX rates (BNR), ROBOR, and EURIBOR into Themis, with REST
read endpoints for Exodus / other consumers, on AICC's scheduler.

## After PR merges

### Step 1 — backend env: RATES_API_TOKEN

Generate a shared service token:
```bash
openssl rand -base64 48
```

On Railway `Themis-legal` service → Variables → add:
```
RATES_API_TOKEN=<the value from openssl>
```

(Backend redeploys; ~1 min.)

### Step 2 — smoke check the API responds with 401

```bash
curl -s -o /dev/null -w "no-auth: %{http_code}\n" \
  https://themis-legal-production.up.railway.app/api/rates/exchange
```
Expect: `no-auth: 401` (auth gate is up).

```bash
curl -s -o /dev/null -w "with-token: %{http_code}\n" \
  -H "Authorization: Bearer <RATES_API_TOKEN>" \
  https://themis-legal-production.up.railway.app/api/rates/exchange?limit=1
```
Expect: `with-token: 200` and an empty body (no rows yet).

### Step 3 — kick the backfill

The backfill endpoint requires admin auth, not the service token.
Sign in to Themis as an admin, then from the browser DevTools console:

```js
const r = await fetch('/api/admin/rates/backfill?years=7', {
  method: 'POST',
  headers: { Authorization: `Bearer ${aicc_access_cookie}` },
});
console.log(await r.json());
```

Or via railway ssh:
```bash
railway ssh --service Themis-legal -- bash -c '
  cd /app && PYTHONPATH=. /app/.venv/bin/python -c "
from app.services.rates.backfill import run_rates_backfill
import json
r = run_rates_backfill(years=7)
print(json.dumps(r, default=str))
"'
```

Expect: ~10-20 min walltime; result like
```json
{"fx_inserted": 1800, "euribor_inserted": 1500, "robor_inserted": 250, "years_processed": [...], "errors": 0}
```

### Step 4 — register the AICC scheduler task

Either via dashboard (THEMIS project → Scheduler → + ADD TASK) or via API:

```bash
railway run --service Themis-legal -- bash -c 'curl -sS -X POST \
  -H "Authorization: Bearer $AICC_KEY" -H "Content-Type: application/json" \
  -d "{
    \"name\":\"themis-rates-daily-update\",
    \"cron\":\"0 12 * * 1-5\",
    \"enabled\":true,
    \"handlerType\":\"remote\",
    \"handlerRef\":\"https://themis-legal-production.up.railway.app/internal/scheduler/rates-update\",
    \"handlerConfig\":{\"timeoutMs\":60000,\"payload\":{},\"idempotent\":true},
    \"retryPolicy\":{\"maxAttempts\":3,\"backoffMs\":2000,\"backoffStrategy\":\"exponential\"}
  }" \
  "https://aicommandcenter-production-d7b1.up.railway.app/api/v2/projects/edacc097-1001-489b-a50b-0724ce7514e1/tasks"'
```

### Step 5 — RUN NOW the new task once

In AICC dashboard, click "RUN NOW" on `themis-rates-daily-update`. Expect:
- `lastResult: success` within ~30 sec.
- Backend log: `AICC scheduler webhook accepted: rates-update`.
- Then within ~10 sec: `[rates] BNR FX: N new rows`, `[rates] ROBOR: M new rows`, `[rates] EURIBOR: K new rows`.
- `scheduler_run_log` table gets a row with `id='rates'`.

### Step 6 — give Exodus the token

Add to Exodus's Railway env:
```
THEMIS_RATES_BASE_URL=https://themis-legal-production.up.railway.app
THEMIS_RATES_API_TOKEN=<same value as Themis>
```

Update Exodus's rates-pulling code to point at the Themis URL with the
`Authorization: Bearer ${THEMIS_RATES_API_TOKEN}` header.

## Rollback

If anything's wrong:
1. Disable the AICC scheduler task (toggle off in dashboard).
2. The endpoints stay live (no code revert needed); they just return whatever
   was already in the tables.
3. To fully back out: `git revert <merge-commit>` and redeploy.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/runbooks/2026-04-28-rates-feed-cutover.md
git commit -m "docs: cutover runbook for rates feed"
```

---

## Task 12: Final verification + push PR

**Files:** none

- [ ] **Step 1: Full backend suite**

Run: `cd backend && uv run pytest --no-header -q`
Expected: all green except the 10 pre-existing failures (`test_compare_endpoint`, `test_settings_endpoints`, `test_step7_revised`).

- [ ] **Step 2: Confirm app boots**

Run: `cd backend && uv run python -c "from app.main import app; print(f'ok: {len(app.routes)} routes')"`
Expected: `ok: <N> routes` where N is meaningfully larger than before (~3 new public routes + 1 admin + 1 internal scheduler).

- [ ] **Step 3: Confirm new routes are present**

Run: `cd backend && uv run python -c "
from app.main import app
paths = sorted(r.path for r in app.routes if hasattr(r, 'path'))
expected = [
    '/api/admin/rates/backfill',
    '/api/rates/exchange',
    '/api/rates/interest',
    '/internal/scheduler/rates-update',
]
for e in expected:
    assert e in paths, f'missing route: {e}'
print('all expected routes present')
"`
Expected: `all expected routes present`

- [ ] **Step 4: Push branch + open PR**

```bash
git push -u myndtrick feat/rates-feed
gh pr create --repo Myndtrick/themis-legal --base main \
  --head feat/rates-feed \
  --title "feat: rates feed (FX + ROBOR + EURIBOR) for Exodus" \
  --body "$(cat <<'EOF'
## Summary

Daily ingest of EUR/RON, USD/RON (and all BNR currencies), ROBOR, and EURIBOR into Themis. 7-year backfill on first run. AICC scheduler drives the daily cron. Public REST API at \`/api/rates/{exchange,interest}\` for Exodus and other consumers.

Schema and API surface mirror exodus-live exactly so Exodus can switch source URL with no other changes.

- New tables: \`exchange_rates\`, \`interest_rates\` (auto-created on boot)
- Three independent fetchers: \`app/services/rates/{bnr_fx,robor,euribor}.py\`
- Orchestrator: \`app/services/rates/run.py:run_rates_update_check()\`
- Scheduler webhook: \`POST /internal/scheduler/rates-update\` (HMAC-signed by AICC)
- Public API: \`GET /api/rates/exchange\`, \`GET /api/rates/interest\`
- Admin backfill: \`POST /api/admin/rates/backfill?years=7\` → background Job
- Auth: \`verify_caller\` accepts a Themis user PKCE bearer OR a shared \`RATES_API_TOKEN\` bearer

Spec: \`docs/superpowers/specs/2026-04-28-rates-feed-design.md\`
Plan: \`docs/superpowers/plans/2026-04-28-rates-feed.md\`
Runbook: \`docs/superpowers/runbooks/2026-04-28-rates-feed-cutover.md\`

## Test plan

- [x] 31 new tests across parser, fetcher, storage, orchestrator, webhook, API, backfill, auth.
- [x] Full backend suite: only pre-existing 10 failures remain.
- [ ] Post-merge cutover per runbook: set RATES_API_TOKEN, kick backfill, register AICC task, RUN NOW once.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Confirm PR opened**

The CLI returns a PR URL. Done with implementation; cutover is operator-driven per the runbook.

## Done criteria

- All backend tests pass (modulo 10 pre-existing failures).
- App boots with the new routes registered.
- `Base.metadata.create_all` produces `exchange_rates` and `interest_rates` on a fresh DB.
- All 12 tasks committed.
- PR open against main.
