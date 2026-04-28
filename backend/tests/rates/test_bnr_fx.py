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
