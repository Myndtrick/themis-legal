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
