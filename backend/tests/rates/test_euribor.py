"""EURIBOR parser tests against the real euribor-rates.eu layout
(verified live 2026-04-28: TRANSPOSED — dates in <th>, tenors in row labels,
rates suffixed with " %")."""
from __future__ import annotations

from pathlib import Path

import httpx


FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_euribor_extracts_5_tenors_x_5_dates():
    from app.services.rates.euribor import parse_euribor_html
    rates = parse_euribor_html(_read("euribor.html"))
    # 5 tenors × 5 dates = 25 rows
    assert len(rates) == 25
    by_key = {(r.date, r.tenor): r for r in rates}
    assert by_key[("2026-04-24", "1W")].rate == 1.915
    assert by_key[("2026-04-24", "3M")].rate == 2.163
    assert by_key[("2026-04-24", "12M")].rate == 2.735
    assert by_key[("2026-04-20", "1W")].rate == 1.875
    assert all(r.rate_type == "EURIBOR" for r in rates)


def test_parse_euribor_strips_percent_suffix():
    from app.services.rates.euribor import parse_euribor_html
    rates = parse_euribor_html(_read("euribor.html"))
    # If the parser kept the trailing " %" the float() conversion would have
    # raised; if it tolerated %, the value would have come out unchanged.
    assert any(abs(r.rate - 2.163) < 1e-9 for r in rates)


def test_parse_euribor_handles_us_dates():
    """euribor-rates.eu uses M/D/YYYY in headers."""
    from app.services.rates.euribor import parse_euribor_html
    html = (
        "<table>"
        "<tr><th></th><th>3/6/2026</th></tr>"
        "<tr><th>Euribor 3 months</th><td>2.683 %</td></tr>"
        "</table>"
    )
    rates = parse_euribor_html(html)
    assert len(rates) == 1
    assert rates[0].date == "2026-03-06"
    assert rates[0].rate == 2.683


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
    assert len(rates) == 25
    client.close()


def test_fetch_euribor_empty_on_5xx():
    from app.services.rates.euribor import fetch_euribor_current
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert fetch_euribor_current(client) == []
    client.close()
