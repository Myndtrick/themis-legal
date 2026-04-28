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
