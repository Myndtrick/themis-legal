"""Fetch and cache filter dropdown options from legislatie.just.ro."""

import logging
import re
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
}

BASE_URL = "https://legislatie.just.ro"

# In-memory cache
_cache: dict = {}
_cache_ts: float = 0.0
_CACHE_TTL = 86400  # 24 hours


def _fix_romanian_diacritics(text: str) -> str:
    """Fix corrupted Romanian diacritics in legislatie.just.ro data.

    The site's database has '?' where ș/ț/Ș/Ț should be.  We restore them
    using contextual rules:

    - Standalone '?i' → 'și'  (conjunction "and")
    - '?' before 't'/'T'     → 'ș'/'Ș'  (e.g. Științe, Înaltă)
    - '?' elsewhere           → 'ț'/'Ț'  (e.g. Național, Agenția)

    Also normalises old-style cedilla chars (ş→ș, ţ→ț) for consistency.
    """
    if "?" not in text:
        # Normalise cedilla to comma-below even if no ? present
        return text.translate(str.maketrans("şŞţŢ", "șȘțȚ"))

    # 1. Standalone conjunction: "?i" bounded by non-word chars or string edges
    text = re.sub(r"(?<!\w)\?i(?!\w)", "și", text)

    # 2. '?' at word start before t/T → Ș
    text = re.sub(r"(?<!\w)\?(?=[tT])", "Ș", text)

    # 3. '?' before t/T in the middle of a word → ș
    text = re.sub(r"(?<=\w)\?(?=[tT])", "ș", text)

    # 4. '?' at word start (remaining) → Ț
    text = re.sub(r"(?<!\w)\?(?=\w)", "Ț", text)

    # 5. '?' in the middle of a word → ț
    text = re.sub(r"(?<=\w)\?(?=\w)", "ț", text)

    # 6. Any remaining lone '?' between words → ț (rare edge case)
    text = text.replace("?", "ț")

    # Normalise old-style cedilla to comma-below
    text = text.translate(str.maketrans("şŞţŢ", "șȘțȚ"))

    return text


def _fetch_and_parse() -> dict:
    """Fetch the search page and extract dropdown options."""
    resp = requests.get(BASE_URL + "/", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    doc_types = []
    doc_type_select = soup.find("select", {"name": "DocumentType"})
    if doc_type_select:
        for opt in doc_type_select.find_all("option"):
            val = opt.get("value", "")
            label = opt.get_text(strip=True)
            if val and label:
                doc_types.append({
                    "value": val,
                    "label": _fix_romanian_diacritics(label),
                })

    emitents = []
    emitent_select = soup.find("select", {"name": "EmitentAct"})
    if emitent_select:
        for opt in emitent_select.find_all("option"):
            val = opt.get("value", "")
            label = opt.get_text(strip=True)
            if val and label:
                emitents.append({
                    "value": val,
                    "label": _fix_romanian_diacritics(label),
                })

    return {"doc_types": doc_types, "emitents": emitents}


def get_filter_options() -> dict:
    """Return cached filter options, refreshing if stale."""
    global _cache, _cache_ts

    if _cache and (time.time() - _cache_ts) < _CACHE_TTL:
        return _cache

    try:
        _cache = _fetch_and_parse()
        _cache_ts = time.time()
        logger.info(
            "Refreshed filter options: %d doc_types, %d emitents",
            len(_cache["doc_types"]),
            len(_cache["emitents"]),
        )
    except Exception as e:
        logger.error("Failed to fetch filter options: %s", e)
        if _cache:
            return _cache
        return {"doc_types": [], "emitents": []}

    return _cache


def search_emitents(query: str) -> list[dict]:
    """Search emitents by case-insensitive partial match.

    Returns list of {value, label} dicts.
    Returns all emitents if query is empty or too short.
    """
    options = get_filter_options()
    all_emitents = options.get("emitents", [])

    if not query or len(query) < 2:
        return all_emitents[:30]

    q_lower = query.lower()
    return [e for e in all_emitents if q_lower in e["label"].lower()][:30]
