"""Custom fetcher that wraps leropa with proper HTTP headers."""

import re
from pathlib import Path
from typing import Any

import requests

from leropa.parser import document_info
from leropa.parser.document_info import DocumentType
from leropa.parser.parse_html import parse_html

# ---------------------------------------------------------------------------
# Monkey-patch leropa to accept ALL document types from legislatie.just.ro.
#
# leropa's DocumentType enum is incomplete — it crashes with a ValueError on
# any type it doesn't recognise (e.g. OUG, CONSTITUTIE, DIRECTIVA, …).
# Instead of patching HTML per-document we extend the enum and the
# prefix_for_type mapping once at import time so every document works.
# ---------------------------------------------------------------------------

_EXTRA_TYPES: dict[str, tuple[str, str]] = {
    # member_name: (enum_value, Romanian display prefix)
    "EMERGENCY_ORD": ("OUG", "Ordonanța de Urgență a Guvernului"),
    "CONSTITUTION": ("CONSTITUTIE", "Constituția"),
    "DIRECTIVE": ("DIRECTIVA", "Directiva"),
    "INSTRUCTION": ("INSTRUCTIUNE", "Instrucțiunea"),
    "METHODOLOGY": ("METODOLOGIE", "Metodologia"),
    "PROTOCOL": ("PROTOCOL", "Protocolul"),
    "STATUTE": ("STATUT", "Statutul"),
    "AGREEMENT": ("ACORD", "Acordul"),
    "CONVENTION": ("CONVENTIE", "Convenția"),
    "TREATY": ("TRATAT", "Tratatul"),
    "PACT": ("PACT", "Pactul"),
    "CHARTER": ("CARTA", "Carta"),
    "DECLARATION": ("DECLARATIE", "Declarația"),
    "RECOMMENDATION": ("RECOMANDARE", "Recomandarea"),
    "CIRCULAR": ("CIRCULARA", "Circulara"),
    "DISPOSITION": ("DISPOZITIE", "Dispoziția"),
    "ADDRESS": ("ADRESA", "Adresa"),
    "ANNEX": ("ANEXA", "Anexa"),
    "ACT": ("ACT", "Actul"),
    "PLAN": ("PLAN", "Planul"),
    "PROGRAM": ("PROGRAM", "Programul"),
    "REPORT": ("RAPORT", "Raportul"),
    "NOTICE": ("AVIZ", "Avizul"),
    "OPINION": ("PUNCT", "Punctul de vedere"),
    "MEMORANDUM": ("MEMORANDUM", "Memorandumul"),
    "REGULATION_EU": ("REGULAMENTUL", "Regulamentul"),
    "HOTARARE": ("HOTARARE", "Hotărârea"),
    "RESOLUTION2": ("REZOLUTIE", "Rezoluția"),
    "ORDONANTA": ("ORDONANTA", "Ordonanța"),
    "ORDONANȚĂ": ("ORDONANȚĂ", "Ordonanța"),
}

for _member_name, (_value, _prefix) in _EXTRA_TYPES.items():
    if _value not in DocumentType.__members__.values():
        try:
            # Extend the StrEnum at runtime
            DocumentType._value2member_map_[_value] = None  # type: ignore[attr-defined]
            new_member = str.__new__(DocumentType, _value)
            new_member._name_ = _member_name
            new_member._value_ = _value
            DocumentType._member_map_[_member_name] = new_member  # type: ignore[attr-defined]
            DocumentType._value2member_map_[_value] = new_member  # type: ignore[attr-defined]
            DocumentType._member_names_.append(_member_name)  # type: ignore[attr-defined]
        except Exception:
            pass
    document_info.prefix_for_type[_value] = _prefix


# Also make the DocumentType/DocumentState checks non-fatal so that truly
# unknown types we haven't anticipated still parse instead of crashing.
_original_post_init = document_info.DocumentInfo.__attrs_post_init__


def _safe_post_init(self: document_info.DocumentInfo) -> None:
    """Wrapper that catches ValueError from unknown types/states."""
    try:
        _original_post_init(self)
    except ValueError:
        # Fall back: keep the raw title, extract kind from first word
        if self.title:
            parts = [
                p for p in self.title.split(" ")
                if p.strip() not in {"", "-", "Portal", "Legislativ"}
            ]
            if parts:
                self.kind = parts[0].upper()
        # Don't re-raise — let the document parse with what we have


document_info.DocumentInfo.__attrs_post_init__ = _safe_post_init  # type: ignore[method-assign]

# ---------------------------------------------------------------------------

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


def _fetch_html(
    url: str, cache_file: Path, use_cache: bool = True, timeout: int = 30
) -> str:
    """Fetch HTML from a URL with caching."""
    if use_cache and cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    html = response.text
    cache_file.write_text(html, encoding="utf-8")
    return html


def fetch_document(
    ver_id: str, cache_dir: Path | None = None, use_cache: bool = True
) -> dict[str, Any]:
    """Fetch and parse a document from legislatie.just.ro.

    Like leropa's fetch_document but with proper HTTP headers to avoid 403 errors.

    For large laws (e.g. Codul Fiscal) the standard DetaliiDocument page loads
    articles dynamically via AJAX, so the static HTML has no content.  When this
    happens we look for a DetaliiDocumentAfis link in the page and fetch from
    that URL instead — it contains the full inline text.
    """
    cache_dir = cache_dir or CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{ver_id}.html"

    url = f"https://legislatie.just.ro/Public/DetaliiDocument/{ver_id}"
    html = _fetch_html(url, cache_file, use_cache)
    result = parse_html(html, ver_id)

    # If no articles/books were parsed, try the DetaliiDocumentAfis fallback.
    # Large codes have their content on a separate "Afis" page linked from the
    # main page via S_REF anchors.
    if not result.get("articles") and not result.get("books"):
        afis_ids = re.findall(r"DetaliiDocumentAfis/(\d+)", html)
        if afis_ids:
            # Use the last Afis link — it's typically the content reference
            afis_id = afis_ids[-1]
            afis_cache = cache_dir / f"{afis_id}_afis.html"
            afis_url = f"https://legislatie.just.ro/Public/DetaliiDocumentAfis/{afis_id}"
            try:
                afis_html = _fetch_html(afis_url, afis_cache, use_cache, timeout=120)
                afis_result = parse_html(afis_html, afis_id)
                if afis_result.get("articles") or afis_result.get("books"):
                    # Merge: keep metadata from the main page, content from Afis
                    result["articles"] = afis_result["articles"]
                    result["books"] = afis_result["books"]
            except Exception:
                pass  # Fall through — caller will handle empty content

    return result
