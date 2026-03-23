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
