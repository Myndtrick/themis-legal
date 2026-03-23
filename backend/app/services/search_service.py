"""Search legislatie.just.ro for laws by name, number, or keywords."""

import logging
import re
from dataclasses import dataclass, asdict

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

DOC_TYPE_MAP = {
    "lege": "1", "legea": "1",
    "hotarare": "2", "hotararea": "2", "hg": "2",
    "decret": "3", "decretul": "3",
    "ordin": "5", "ordinul": "5",
    "ordonanta": "13", "ordonanța": "13", "og": "13",
    "decizie": "17", "decizia": "17",
    "oug": "18",
}


@dataclass
class SearchResult:
    ver_id: str
    title: str
    description: str
    doc_type: str
    number: str
    date: str
    issuer: str
    date_iso: str | None = None

    def to_dict(self):
        return asdict(self)


def _get_session_and_token() -> tuple[requests.Session, str]:
    """Create a session with cookies and get the CSRF token."""
    session = requests.Session()
    session.headers.update(HEADERS)
    resp = session.get(BASE_URL + "/", timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    token_input = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token_input:
        raise RuntimeError("Could not find CSRF token on legislatie.just.ro")

    return session, token_input["value"]


def _parse_query(query: str) -> dict:
    """Parse user query into search form fields.

    Handles patterns like:
    - "legea 31/1990" -> DocumentType=1, DocumentNumber=31-1990
    - "oug 99/2006" -> DocumentType=18, DocumentNumber=99-2006
    - "31/1990" -> DocumentNumber=31-1990
    - "codul civil" -> TitleText=codul civil
    - "spalarea banilor" -> TitleText=spalarea banilor
    """
    query = query.strip()
    title_text = query
    doc_number = ""
    doc_type = ""

    # Pattern: "legea 31/1990" or "lege nr. 31 din 1990" or "oug 99/2006"
    num_match = re.match(
        r"(legea?|oug|hg|og|ordin(?:ul)?|hotarare[a]?|decret(?:ul)?|ordona[nț](?:a|ța)?|decizie[a]?|codul?)\s+"
        r"(?:nr\.?\s*)?(\d+)(?:\s*[/-]\s*(\d{4}))?",
        query,
        re.IGNORECASE,
    )
    if num_match:
        type_word = num_match.group(1).lower()
        number = num_match.group(2)
        year = num_match.group(3)
        doc_number = f"{number}-{year}" if year else number
        doc_type = DOC_TYPE_MAP.get(type_word, "")
        # Clear title text when doing a precise number search
        title_text = ""

    # Pattern: bare "31/1990" or "31-1990"
    if not doc_number:
        bare_num = re.match(r"^(\d+)\s*[/-]\s*(\d{4})$", query)
        if bare_num:
            doc_number = f"{bare_num.group(1)}-{bare_num.group(2)}"
            title_text = ""

    return {
        "TitleText": title_text,
        "DocumentType": doc_type,
        "DocumentNumber": doc_number,
    }


def _do_search(
    session: requests.Session,
    token: str,
    title_text: str = "",
    content_text: str = "",
    doc_type: str = "",
    doc_number: str = "",
    emitent: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[SearchResult]:
    """Execute a single search against legislatie.just.ro."""
    form_data = {
        "__RequestVerificationToken": token,
        "TitleText": title_text,
        "ContentText_First": content_text,
        "opContentText_Second": "SI",
        "ContentText_Second": "",
        "opContentText_Third": "SI",
        "ContentText_Third": "",
        "opContentText_Fourth": "SI",
        "ContentText_Fourth": "",
        "DocumentType": doc_type,
        "DocumentNumber": doc_number,
        "DataSemnariiTextFrom": "",
        "DataSemnariiTextTo": date_to,
        "PublishedInName": "",
        "PublishedInNumber": "",
        "DataPublicariiTextFrom": "",
        "DataPublicariiTextTo": "",
        "ActInForceOnDateTextFrom": date_from,
        "EmitentAct": emitent,
        "actiontype": "Căutare",
    }

    resp = session.post(
        BASE_URL + "/",
        data=form_data,
        timeout=15,
        allow_redirects=True,
    )
    resp.raise_for_status()
    return _parse_search_results(resp.text, max_results=20)


def _refresh_token(session: requests.Session) -> str:
    """Get a fresh CSRF token from a new GET request."""
    resp = session.get(BASE_URL + "/", timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    token_input = soup.find("input", {"name": "__RequestVerificationToken"})
    return token_input["value"] if token_input else ""


def search_laws(query: str, max_results: int = 10) -> list[SearchResult]:
    """Search legislatie.just.ro for documents matching a query.

    Uses a multi-strategy approach:
    0. Check for known abbreviations/popular names (PFA, SRL, GDPR, etc.)
    1. If query has a number pattern (e.g., "legea 31/1990"), do precise search.
    2. Search by title keywords.
    3. If title search returns few results, also search in document content.
    Results are merged with deduplication.
    """
    from app.services.legal_aliases import expand_query

    session, token = _get_session_and_token()

    all_results: list[SearchResult] = []
    seen_ids: set[str] = set()

    def _add_results(results: list[SearchResult]):
        for r in results:
            if r.ver_id not in seen_ids:
                seen_ids.add(r.ver_id)
                all_results.append(r)

    # Strategy 0: Check known aliases/abbreviations
    alias_matches = expand_query(query)
    if alias_matches:
        for alias in alias_matches:
            if alias.get("number"):
                results = _do_search(
                    session, token,
                    doc_type=alias.get("type", ""),
                    doc_number=alias["number"],
                )
                _add_results(results)
                if results:
                    token = _refresh_token(session)
            if alias.get("title") and len(all_results) < max_results:
                results = _do_search(session, token, title_text=alias["title"])
                _add_results(results)
                if results:
                    token = _refresh_token(session)

    # Strategy 1: Precise number search (if query has a number pattern)
    parsed = _parse_query(query)
    if parsed["DocumentNumber"]:
        if not all_results:
            token = _refresh_token(session)
        results = _do_search(
            session, token,
            doc_type=parsed["DocumentType"],
            doc_number=parsed["DocumentNumber"],
        )
        _add_results(results)

    # Strategy 2: Title keyword search
    if parsed["TitleText"] and len(all_results) < max_results:
        raw_title = parsed["TitleText"]

        # Detect doc type prefix and extract keywords without it
        prefix_match = re.match(
            r"^(legea?|oug|hg|og|ordin(?:ul)?|hotarare[a]?|decret(?:ul)?|"
            r"ordona[nț](?:a|ța)?|decizie[a]?|codul?|lege)\s+",
            raw_title, flags=re.IGNORECASE,
        )
        if prefix_match:
            prefix_word = prefix_match.group(1).lower()
            keywords = raw_title[prefix_match.end():].strip()
            # Use the prefix to filter by document type
            prefix_doc_type = DOC_TYPE_MAP.get(prefix_word, "")
        else:
            keywords = raw_title
            prefix_doc_type = ""

        if keywords:
            # 2a: Search with doc type filter + stripped keywords
            if prefix_doc_type:
                token = _refresh_token(session)
                results = _do_search(
                    session, token, title_text=keywords,
                    doc_type=prefix_doc_type,
                )
                _add_results(results)

            # 2b: Search with the full original phrase (including prefix)
            # The actual law title often includes "Legea X" in it
            if len(all_results) < max_results:
                token = _refresh_token(session)
                results = _do_search(session, token, title_text=raw_title)
                _add_results(results)

            # 2c: Search stripped keywords without type filter (broader)
            if len(all_results) < max_results:
                token = _refresh_token(session)
                results = _do_search(session, token, title_text=keywords)
                _add_results(results)

            # Strategy 3: Content search if still not enough results
            if len(all_results) < max_results:
                token = _refresh_token(session)
                results = _do_search(session, token, content_text=keywords)
                _add_results(results)
        elif not all_results:
            token = _refresh_token(session)
            results = _do_search(session, token, title_text=raw_title)
            _add_results(results)

    return all_results[:max_results]


def _parse_date_to_iso(date_str: str) -> str | None:
    """Convert DD/MM/YYYY to YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except (ValueError, IndexError):
        pass
    return None


def _parse_search_results(html: str, max_results: int) -> list[SearchResult]:
    """Parse search results from the results page HTML.

    Result items look like:
      <p><a href="/Public/DetaliiDocument/798">1. LEGE  31 16/11/1990</a></p>
      <p>LEGE nr. 31 din 16 noiembrie 1990 privind societăţile comerciale</p>
      <table><tr><td>EMITENT</td><td>Parlamentul</td></tr></table>
      <div><a href="...">Vizualizeaza</a></div>
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Find numbered result entries: links matching "N. TYPE  NUMBER DATE"
    numbered_pattern = re.compile(r"^\d+\.\s+\S+\s+")

    for link in soup.find_all("a", href=re.compile(r"/Public/DetaliiDocument/\d+")):
        link_text = link.get_text(strip=True)

        # Only take the numbered header links (e.g., "1. LEGE  31 16/11/1990")
        if not numbered_pattern.match(link_text):
            continue

        ver_id = re.search(r"/(\d+)", link["href"]).group(1)

        # Skip duplicates
        if any(r.ver_id == ver_id for r in results):
            continue

        # Parse the link text: "1. LEGE  31 16/11/1990"
        parts = re.match(
            r"\d+\.\s+(\S+)\s+(\S+)\s+(\S+)",
            link_text,
        )
        doc_type = parts.group(1) if parts else ""
        number = parts.group(2) if parts else ""
        date = parts.group(3) if parts else ""

        # Get the full title from the next <p> sibling
        description = ""
        parent_p = link.find_parent("p")
        if parent_p:
            next_p = parent_p.find_next_sibling("p")
            if next_p:
                description = next_p.get_text(strip=True)

        # Get the issuer from the nearby table
        issuer = ""
        if parent_p:
            table = parent_p.find_next("table")
            if table:
                cells = table.find_all("td")
                if len(cells) >= 2 and "EMITENT" in cells[0].get_text():
                    issuer = cells[1].get_text(strip=True)

        # Build a clean title
        title = f"{doc_type} nr. {number}" if doc_type and number else link_text

        results.append(SearchResult(
            ver_id=ver_id,
            title=title,
            description=description,
            doc_type=doc_type,
            number=number,
            date=date,
            issuer=issuer,
            date_iso=_parse_date_to_iso(date),
        ))

        if len(results) >= max_results:
            break

    return results


# Map dropdown labels to legislatie.just.ro DocumentType codes
ADVANCED_DOC_TYPE_MAP = {
    "lege": "1",
    "oug": "18",
    "hg": "2",
    "ordin": "5",
    "decizie": "17",
    # Regulament and Directivă EU have no codes — handled via title keyword
}

# Types that have no numeric code and use title keyword instead
TITLE_KEYWORD_TYPES = {"regulament", "directiva_eu"}


def advanced_search(
    keyword: str = "",
    doc_type: str = "",
    number: str = "",
    year: str = "",
    emitent: str = "",
    date_from: str = "",
    date_to: str = "",
    include_repealed: str = "only_in_force",
    max_results: int = 20,
) -> list[SearchResult]:
    """Search legislatie.just.ro with structured filters.

    Args:
        keyword: Free-text search (title + content)
        doc_type: Act type key (e.g. "lege", "oug", "hg", "regulament", "directiva_eu")
        number: Law number
        year: Law year (4 digits)
        emitent: Issuer name
        date_from: YYYY-MM-DD, maps to ActInForceOnDateTextFrom
        date_to: YYYY-MM-DD, maps to DataSemnariiTextTo
        include_repealed: "only_in_force" | "all" | "only_repealed"
        max_results: Max results to return
    """
    from datetime import date as date_type

    session, token = _get_session_and_token()

    # Build document number
    doc_number = ""
    if number:
        doc_number = f"{number}-{year}" if year else number

    # Resolve doc_type code
    resolved_doc_type = ADVANCED_DOC_TYPE_MAP.get(doc_type.lower(), "") if doc_type else ""
    title_prefix = ""
    if doc_type and doc_type.lower() in TITLE_KEYWORD_TYPES:
        # No numeric code — prepend type name to title search
        label_map = {"regulament": "regulament", "directiva_eu": "directiva"}
        title_prefix = label_map.get(doc_type.lower(), "")
        resolved_doc_type = ""

    # Build title text
    title_text = keyword
    if title_prefix:
        title_text = f"{title_prefix} {keyword}".strip()

    # Convert YYYY-MM-DD dates to DD.MM.YYYY for legislatie.just.ro
    def _to_ro_date(iso_date: str) -> str:
        """Convert YYYY-MM-DD to DD.MM.YYYY."""
        if not iso_date:
            return ""
        parts = iso_date.split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
        return iso_date

    ro_date_to = _to_ro_date(date_to)

    # Handle include_repealed via date_from
    if include_repealed == "only_in_force":
        effective_date_from = _to_ro_date(date_from) if date_from else date_type.today().strftime("%d.%m.%Y")
    elif include_repealed == "only_repealed":
        # First search unfiltered, then subtract in-force results later
        effective_date_from = _to_ro_date(date_from) if date_from else ""
    else:  # "all"
        effective_date_from = _to_ro_date(date_from) if date_from else ""

    all_results: list[SearchResult] = []
    seen_ids: set[str] = set()

    def _add_results(results: list[SearchResult]):
        for r in results:
            if r.ver_id not in seen_ids:
                seen_ids.add(r.ver_id)
                all_results.append(r)

    # Primary search: title
    if title_text or resolved_doc_type or doc_number or emitent or effective_date_from or ro_date_to:
        results = _do_search(
            session, token,
            title_text=title_text,
            doc_type=resolved_doc_type,
            doc_number=doc_number,
            emitent=emitent,
            date_from=effective_date_from,
            date_to=ro_date_to,
        )
        _add_results(results)

    # Fallback: content search if keyword provided and title search had few results
    if keyword and len(all_results) < max_results:
        token = _refresh_token(session)
        results = _do_search(
            session, token,
            content_text=keyword,
            doc_type=resolved_doc_type,
            doc_number=doc_number,
            emitent=emitent,
            date_from=effective_date_from,
            date_to=ro_date_to,
        )
        _add_results(results)

    # Handle "only_repealed": requires a second search to find what IS in force,
    # then subtract from the unfiltered results
    if include_repealed == "only_repealed":
        token = _refresh_token(session)
        today_str = date_type.today().strftime("%d.%m.%Y")
        in_force_results = _do_search(
            session, token,
            title_text=title_text,
            doc_type=resolved_doc_type,
            doc_number=doc_number,
            emitent=emitent,
            date_from=today_str,
            date_to=ro_date_to,
        )
        in_force_ids = {r.ver_id for r in in_force_results}
        all_results = [r for r in all_results if r.ver_id not in in_force_ids]

    return all_results[:max_results]
