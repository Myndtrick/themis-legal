"""Custom fetcher that wraps leropa with proper HTTP headers."""

from pathlib import Path
from typing import Any

import requests

from leropa.parser.parse_html import parse_html

CACHE_DIR = Path.home() / ".leropa"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}


def fetch_document(
    ver_id: str, cache_dir: Path | None = None, use_cache: bool = True
) -> dict[str, Any]:
    """Fetch and parse a document from legislatie.just.ro.

    Like leropa's fetch_document but with proper HTTP headers to avoid 403 errors.
    """
    cache_dir = cache_dir or CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{ver_id}.html"

    if use_cache and cache_file.exists():
        html = cache_file.read_text(encoding="utf-8")
    else:
        url = f"https://legislatie.just.ro/Public/DetaliiDocument/{ver_id}"
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        html = response.text
        cache_file.write_text(html, encoding="utf-8")

    return parse_html(html, ver_id)
