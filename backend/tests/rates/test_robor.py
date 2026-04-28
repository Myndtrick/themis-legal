"""ROBOR parser tests against the real curs-valutar-bnr.ro layout
(verified live 2026-04-28: no thead/tbody split, comma decimals, T/N column
present but skipped)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_robor_extracts_6_tenors_per_date_skipping_tn():
    from app.services.rates.robor import parse_robor_html
    rates = parse_robor_html(_read("robor.html"))
    # 2 dates × 6 tenors (ON, 1W, 1M, 3M, 6M, 12M) — T/N is skipped.
    assert len(rates) == 12
    by_key = {(r.date, r.tenor): r for r in rates}
    assert by_key[("2026-04-27", "ON")].rate == 5.69
    assert by_key[("2026-04-27", "1W")].rate == 5.72
    assert by_key[("2026-04-27", "1M")].rate == 5.78
    assert by_key[("2026-04-27", "3M")].rate == 5.87
    assert by_key[("2026-04-27", "6M")].rate == 5.94
    assert by_key[("2026-04-27", "12M")].rate == 6.00
    assert all(r.rate_type == "ROBOR" for r in rates)
    # T/N must NOT appear as a tenor.
    assert all(r.tenor != "TN" for r in rates)


def test_parse_robor_handles_comma_decimals():
    """The real source uses Romanian comma decimals (5,69 not 5.69)."""
    from app.services.rates.robor import parse_robor_html
    rates = parse_robor_html(_read("robor.html"))
    # If we accidentally float() "5,69" it'd raise; if we tolerated only
    # dot decimals the parser would skip every cell and return 0.
    assert any(abs(r.rate - 5.69) < 1e-9 for r in rates)


def test_parse_robor_returns_empty_on_garbage():
    from app.services.rates.robor import parse_robor_html
    assert parse_robor_html("") == []
    assert parse_robor_html("<html><body>nothing here</body></html>") == []


def test_parse_robor_skips_unparseable_rate():
    """A header that the parser recognises (O/N) followed by a non-number
    must yield zero rows (not crash)."""
    from app.services.rates.robor import parse_robor_html
    bad = (
        "<table>"
        "<tr><th>Data</th><th>O/N</th></tr>"
        "<tr><td>06 Apr 2026</td><td>not-a-number</td></tr>"
        "</table>"
    )
    assert parse_robor_html(bad) == []


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
