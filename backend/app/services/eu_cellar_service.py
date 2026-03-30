"""EU legislation service — CELLAR SPARQL + REST API integration."""
import re
import logging

logger = logging.getLogger(__name__)

# --- CELEX parsing ---

_CELEX_LEGISLATION_RE = re.compile(r"^([03])(\d{4})([RLDHF])(\d+)(?:-(\d{8}))?$")
_CELEX_TREATY_RE = re.compile(r"^(1)(\d{4})([A-Z])/?(.+)$")

_TYPE_CODE_TO_DOC_TYPE = {"R": "regulation", "L": "directive", "D": "eu_decision"}
_TYPE_CODE_TO_CATEGORY = {"R": "eu.regulation", "L": "eu.directive", "D": "eu.decision"}


def parse_celex(celex: str) -> dict | None:
    """Parse a CELEX number into its components. Returns None if invalid."""
    if not celex:
        return None
    m = _CELEX_LEGISLATION_RE.match(celex)
    if m:
        result = {"sector": m.group(1), "year": m.group(2), "type_code": m.group(3), "number": m.group(4)}
        if m.group(5):
            result["consol_date"] = m.group(5)
        return result
    m = _CELEX_TREATY_RE.match(celex)
    if m:
        return {"sector": m.group(1), "year": m.group(2), "type_code": m.group(3), "number": m.group(4)}
    return None


def celex_to_document_type(celex: str) -> str:
    """Map a CELEX number to an internal document_type string."""
    parsed = parse_celex(celex)
    if not parsed:
        return "other"
    if parsed["sector"] == "1":
        return "treaty"
    return _TYPE_CODE_TO_DOC_TYPE.get(parsed["type_code"], "other")


def celex_to_category_slug(celex: str) -> str | None:
    """Map a CELEX number to a category slug (e.g., 'eu.regulation')."""
    parsed = parse_celex(celex)
    if not parsed:
        return None
    if parsed["sector"] == "1":
        return "eu.treaty"
    return _TYPE_CODE_TO_CATEGORY.get(parsed["type_code"])
