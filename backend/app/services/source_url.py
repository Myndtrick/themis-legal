"""Extract source-document identifiers from public URLs.

Two pure regex-based extractors:
- legislatie.just.ro → ver_id (numeric document id)
- eur-lex.europa.eu  → CELEX number (e.g. 32016R0679)

No network calls. Used by the suggested-laws settings UI to pin a
LawMapping row to an exact source document.
"""
from __future__ import annotations

import re
from typing import TypedDict
from urllib.parse import urlparse


_VER_ID_RE = re.compile(
    r"legislatie\.just\.ro/Public/DetaliiDocument(?:Afis)?/(\d+)",
    re.IGNORECASE,
)

# Matches CELEX in legal-content URLs. Handles both ":" and "%3A" (URL-encoded).
_CELEX_RE = re.compile(
    r"[?&]uri=CELEX(?::|%3A)([0-9A-Z]+)",
    re.IGNORECASE,
)

# ELI URL: /eli/reg|dir|dec/<year>/<number>/oj
_ELI_RE = re.compile(
    r"/eli/(reg|dir|dec)/(\d{4})/(\d+)/oj",
    re.IGNORECASE,
)

_ELI_TYPE_LETTER = {"reg": "R", "dir": "L", "dec": "D"}


def extract_ver_id(url: str) -> str | None:
    """Extract a legislatie.just.ro document ver_id from a URL."""
    if not url:
        return None
    m = _VER_ID_RE.search(url)
    return m.group(1) if m else None


def extract_celex(url: str) -> str | None:
    """Extract a CELEX number from an EUR-Lex URL.

    Supports both `legal-content/?uri=CELEX:...` and ELI URLs
    (`/eli/reg|dir|dec/<year>/<number>/oj`), reconstructing CELEX
    from ELI parts when needed.
    """
    if not url:
        return None
    m = _CELEX_RE.search(url)
    if m:
        return m.group(1).upper()
    m = _ELI_RE.search(url)
    if m:
        kind, year, number = m.group(1).lower(), m.group(2), m.group(3)
        letter = _ELI_TYPE_LETTER[kind]
        return f"3{year}{letter}{int(number):04d}"
    return None


class ProbeResult(TypedDict):
    kind: str  # "ro" | "eu" | "unknown"
    identifier: str | None
    title: str | None
    error: str | None


def probe_url(url: str) -> ProbeResult:
    """Dispatch a URL to the appropriate extractor by hostname.

    Returns a ProbeResult describing what was found. Title fetching
    is left to the caller (this function is pure and offline).
    """
    if not url:
        return {"kind": "unknown", "identifier": None, "title": None,
                "error": "URL host not recognized"}
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return {"kind": "unknown", "identifier": None, "title": None,
                "error": "URL host not recognized"}

    if host.endswith("legislatie.just.ro"):
        ver_id = extract_ver_id(url)
        return {
            "kind": "ro",
            "identifier": ver_id,
            "title": None,
            "error": None if ver_id else "Could not extract identifier",
        }
    if host.endswith("eur-lex.europa.eu"):
        celex = extract_celex(url)
        return {
            "kind": "eu",
            "identifier": celex,
            "title": None,
            "error": None if celex else "Could not extract identifier",
        }
    return {"kind": "unknown", "identifier": None, "title": None,
            "error": "URL host not recognized"}
