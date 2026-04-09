"""Search legislatie.just.ro for laws by name, number, or keywords."""

import logging
import re
import unicodedata
from dataclasses import dataclass, asdict

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def _strip_diacritics(text: str) -> str:
    """Remove diacritics so 'societăților' matches 'societatilor'."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ---------------------------------------------------------------------------
# Romanian word-form expansion
# ---------------------------------------------------------------------------
# legislatie.just.ro does literal matching — "lege" won't find "legea".
# This table maps a *base* form to all the inflected forms we should try.
# We keep it focused on legal vocabulary (not a full stemmer).
#
# Strategy: for every word the user types, if it matches any form in a group
# we generate title-search variants using the *other* forms in that group.

_FORM_GROUPS: list[tuple[str, ...]] = [
    # singular indef / singular def / plural indef / plural def
    ("lege", "legea", "legi", "legile", "legii"),
    ("cod", "codul", "coduri", "codurile", "codului"),
    ("ordin", "ordinul", "ordine", "ordinele", "ordinului"),
    ("hotarare", "hotararea", "hotarari", "hotararile", "hotararii"),
    ("decret", "decretul", "decrete", "decretele", "decretului"),
    ("decizie", "decizia", "decizii", "deciziile", "deciziei"),
    ("ordonanta", "ordonanța", "ordonanta", "ordonante", "ordonantele", "ordonanței"),
    ("regulament", "regulamentul", "regulamente", "regulamentele", "regulamentului"),
    ("norma", "norma", "norme", "normele", "normei"),
    ("directiva", "directiva", "directive", "directivele", "directivei"),
    ("constitutie", "constitutia", "constituția", "constitutiei", "constituției"),
    ("societate", "societatea", "societati", "societatile", "societatilor", "societăți", "societățile", "societăților"),
    ("contract", "contractul", "contracte", "contractele", "contractului"),
    ("articol", "articolul", "articole", "articolele", "articolului"),
    ("procedura", "procedura", "proceduri", "procedurile", "procedurii"),
    ("infractiune", "infractiunea", "infracțiunea", "infractiuni", "infractiunile", "infracțiuni"),
    ("obligatie", "obligatia", "obligația", "obligatii", "obligatiile", "obligații"),
    ("raspundere", "raspunderea", "răspundere", "răspunderea"),
    ("protectie", "protectia", "protecția", "protectiei", "protecției"),
    ("prevenire", "prevenirea", "prevenirii"),
    ("spalare", "spalarea", "spălare", "spălarea", "spalarii", "spălării"),
    ("banilor", "bani", "banilor"),
    ("fiscal", "fiscala", "fiscale", "fiscalul", "fiscală"),
    ("civil", "civila", "civile", "civilul", "civilă"),
    ("penal", "penala", "penale", "penalul", "penală"),
    ("munca", "muncii", "muncă"),
    ("energie", "energiei", "energii"),
    ("educatie", "educatiei", "educației"),
    ("sanatate", "sanatatii", "sănătate", "sănătății"),
    ("achizitie", "achizitia", "achiziția", "achizitii", "achizitiile", "achiziții", "achizițiile"),
    ("insolventa", "insolventei", "insolvență", "insolvenței"),
    ("contabilitate", "contabilitatii", "contabilitatea", "contabilității"),
    ("concurenta", "concurentei", "concurență", "concurenței"),
    ("mediu", "mediului", "medii"),
    ("comert", "comertului", "comerț", "comerțului"),
    ("capital", "capitalului", "capitaluri"),
    ("asigurare", "asigurarea", "asigurari", "asigurarile", "asigurarilor", "asigurări", "asigurărilor"),
    ("consumator", "consumatorului", "consumatori", "consumatorilor"),
    ("administratie", "administratiei", "administrația", "administrației"),
    ("pensie", "pensia", "pensii", "pensiile", "pensiilor"),
]

# Build a lookup: lowercase form -> set of all forms in the same group
_FORM_LOOKUP: dict[str, set[str]] = {}
for _group in _FORM_GROUPS:
    _all = set(_group)
    for _form in _group:
        fl = _form.lower()
        if fl in _FORM_LOOKUP:
            _FORM_LOOKUP[fl] |= _all
        else:
            _FORM_LOOKUP[fl] = set(_all)


def _expand_word_forms(text: str) -> list[str]:
    """Return alternative phrasings of *text* by expanding Romanian word forms.

    Returns a list of up to 3 alternative strings (excluding the original).
    Each variant replaces ONE word at a time with an alternative form.
    We pick the forms most likely to appear in official titles (definite article).
    """
    words = text.lower().split()
    variants: list[str] = []
    seen: set[str] = {text.lower()}

    for i, word in enumerate(words):
        forms = _FORM_LOOKUP.get(word)
        if not forms:
            continue
        for alt in forms:
            if alt == word:
                continue
            new_words = words[:i] + [alt] + words[i + 1:]
            candidate = " ".join(new_words)
            if candidate not in seen:
                seen.add(candidate)
                variants.append(candidate)
            if len(variants) >= 3:
                return variants

    return variants


# Romanian stopwords — filler words to skip when splitting keywords into
# separate AND-connected search fields on legislatie.just.ro.
_STOPWORDS = {
    "de", "din", "si", "și", "la", "cu", "nr", "al", "ale", "a", "in", "în",
    "pe", "prin", "pentru", "sau", "care", "se", "le", "o", "un", "unei",
    "unui", "unor", "cel", "cea", "cei", "cele", "mai", "nu", "ca", "dar",
    "este", "sunt", "fie", "ori", "precum", "privind", "referitoare",
}


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


def _split_content_keywords(text: str) -> list[str]:
    """Split text into significant keywords, dropping Romanian stopwords.

    Returns up to 4 words (the max number of content fields on the site).
    """
    words = [w for w in text.lower().split() if w not in _STOPWORDS and len(w) >= 2]
    return words[:4]


def _do_search(
    session: requests.Session,
    token: str,
    title_text: str = "",
    content_text: str = "",
    content_keywords: list[str] | None = None,
    doc_type: str = "",
    doc_number: str = "",
    emitent: str = "",
    date_from: str = "",
    date_to: str = "",
    date_signed_from: str = "",
) -> list[SearchResult]:
    """Execute a single search against legislatie.just.ro.

    Args:
        content_text: Single phrase for ContentText_First (legacy).
        content_keywords: List of up to 4 keywords to spread across the
            ContentText_First/Second/Third/Fourth fields with AND (SI) operator.
            When provided, takes precedence over content_text.
    """
    # Spread keywords across the 4 content fields if provided
    ct = ["", "", "", ""]
    if content_keywords:
        for i, kw in enumerate(content_keywords[:4]):
            ct[i] = kw
    elif content_text:
        ct[0] = content_text

    form_data = {
        "__RequestVerificationToken": token,
        "TitleText": title_text,
        "ContentText_First": ct[0],
        "opContentText_Second": "SI",
        "ContentText_Second": ct[1],
        "opContentText_Third": "SI",
        "ContentText_Third": ct[2],
        "opContentText_Fourth": "SI",
        "ContentText_Fourth": ct[3],
        "DocumentType": doc_type,
        "DocumentNumber": doc_number,
        "DataSemnariiTextFrom": date_signed_from,
        "DataSemnariiTextTo": date_to,
        "PublishedInName": "",
        "PublishedInNumber": "",
        "DataPublicariiTextFrom": "",
        "DataPublicariiTextTo": "",
        "ActInForceOnDateTextFrom": date_from,
        "EmitentAct": emitent,
        "actiontype": "Căutare",
    }

    # Upstream legislatie.just.ro is flaky for broad title-only queries
    # (returns HTTP 500 on the redirect target when the result set is huge).
    # We swallow request-level errors so a single failing sub-query in
    # advanced_search() doesn't kill the whole search — the caller can
    # still try word-form variants and the content-keyword fallback.
    try:
        resp = session.post(
            BASE_URL + "/",
            data=form_data,
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning(
            "legislatie.just.ro sub-query failed (%s) for title=%r doc_type=%r "
            "doc_number=%r content=%r — returning [] and continuing",
            exc, title_text, doc_type, doc_number, ct,
        )
        return []
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
    2. Search by title keywords (with word-form expansion).
    Results are merged with deduplication, then post-filtered so every keyword
    word appears as a substring in at least one visible field (title,
    description, emitent, doc_type, number, date).
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

            # 2d: Word-form expansion — try Romanian inflection variants
            if len(all_results) < max_results:
                for variant in _expand_word_forms(raw_title):
                    if len(all_results) >= max_results:
                        break
                    token = _refresh_token(session)
                    results = _do_search(session, token, title_text=variant)
                    _add_results(results)

            # 2e: Content search as broader candidate fetcher — split keywords
            # across multiple AND-connected content fields for better matching
            if len(all_results) < max_results:
                split_kw = _split_content_keywords(keywords)
                token = _refresh_token(session)
                results = _do_search(session, token, content_keywords=split_kw)
                _add_results(results)
        elif not all_results:
            token = _refresh_token(session)
            results = _do_search(session, token, title_text=raw_title)
            _add_results(results)

    # Keyword post-filter: keep only results where every significant query word
    # appears as a substring in at least one visible field.
    # Stopwords are skipped, and words are expanded to Romanian inflections.
    kw_words = [_strip_diacritics(w).lower() for w in query.split()
                 if w and w.lower() not in _STOPWORDS and len(w) >= 2]
    if kw_words:
        def _word_variants(word: str) -> list[str]:
            forms = _FORM_LOOKUP.get(word)
            if not forms:
                return [word]
            return [word] + [_strip_diacritics(f).lower() for f in forms if _strip_diacritics(f).lower() != word]

        kw_variants = [_word_variants(w) for w in kw_words]

        def _matches(r: SearchResult) -> bool:
            searchable = _strip_diacritics(" ".join([
                r.title, r.description, r.issuer, r.doc_type, r.number, r.date,
            ])).lower()
            return all(
                any(v in searchable for v in variants)
                for variants in kw_variants
            )

        all_results = [r for r in all_results if _matches(r)]

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

        # Get the full title and metadata from the next <p> sibling.
        # The <p> contains spans for: title, description, EMITENT, PUBLICAT ÎN.
        # We extract just the description (before EMITENT:) and the issuer.
        description = ""
        issuer = ""
        parent_p = link.find_parent("p")
        if parent_p:
            next_p = parent_p.find_next_sibling("p")
            if next_p:
                # Collect text parts before EMITENT: marker.
                # Use get_text with " " separator to avoid words running together
                # across <br/> and <span> boundaries, then stop at EMITENT.
                raw_desc = next_p.get_text(" ", strip=True)
                emitent_pos = raw_desc.find("EMITENT:")
                if emitent_pos > 0:
                    description = raw_desc[:emitent_pos].strip()
                else:
                    description = raw_desc.strip()
                # Clean up BOM and excess whitespace
                description = re.sub(r"\s+", " ", description).strip().lstrip("\ufeff")

                # Extract issuer from the span right after "EMITENT:"
                full_text = next_p.get_text(" ", strip=True)
                emitent_match = re.search(r"EMITENT:\s*(.+?)(?:\s*PUBLICAT\s|$)", full_text)
                if emitent_match:
                    issuer = emitent_match.group(1).strip()

        # Fallback: try getting issuer from a nearby table (older format)
        if not issuer and parent_p:
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


# Map legacy string keys to legislatie.just.ro DocumentType numeric codes.
# New flow: frontend sends numeric codes directly from the scraped dropdown.
# This map is kept for backward compatibility with old string-based keys.
ADVANCED_DOC_TYPE_MAP = {
    "lege": "1",
    "og": "13",
    "oug": "18",
    "hg": "2",
    "decret": "3",
    "ordin": "5",
    "decizie": "17",
    "constitutie": "22",
    "cod": "170",
    "norma": "11",
    "regulament": "12",
    "directiva_eu": "113",
}


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

    # When year is provided without a number, use signing date range to filter
    # (DataSemnariiTextFrom/To are the reliable date fields on legislatie.just.ro)
    year_signed_from = ""
    if year and not number:
        if not date_from:
            year_signed_from = f"{year}-01-01"
        if not date_to:
            date_to = f"{year}-12-31"

    # Resolve doc_type code(s).
    # Supports comma-separated values for multi-select (e.g. "1,18,13").
    # Each value can be a numeric code or a legacy string key.
    def _resolve_one_type(t: str) -> str:
        t = t.strip()
        if t.isdigit():
            return t
        return ADVANCED_DOC_TYPE_MAP.get(t.lower(), "")

    doc_type_codes: list[str] = []
    if doc_type:
        for part in doc_type.split(","):
            code = _resolve_one_type(part)
            if code:
                doc_type_codes.append(code)

    # For single type, use it directly.  For multi, we'll loop below.
    resolved_doc_type = doc_type_codes[0] if len(doc_type_codes) == 1 else ""

    # Build title text
    title_text = keyword

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
    ro_signed_from = _to_ro_date(year_signed_from) if year_signed_from else _to_ro_date(date_from)

    # NOTE: ActInForceOnDateTextFrom does not work reliably on legislatie.just.ro
    # (returns 0 results regardless of format). We only pass it through if the
    # user explicitly provides a date_from value, but never auto-set it.
    # The include_repealed filter is kept for future use / UI consistency.
    effective_date_from = _to_ro_date(date_from) if date_from else ""

    boosted_results: list[SearchResult] = []
    all_results: list[SearchResult] = []
    seen_ids: set[str] = set()

    def _add_results(results: list[SearchResult], target: list[SearchResult] | None = None):
        dest = target if target is not None else all_results
        for r in results:
            if r.ver_id not in seen_ids:
                seen_ids.add(r.ver_id)
                dest.append(r)

    # Step 0: Number/year boost — if the keyword contains a NUMBER/YEAR
    # pattern (e.g. "57/2019"), do a precise number-based search across all
    # act types first, so that LEGE/OUG/OG/etc. with that exact number+year
    # are surfaced before any description-only matches.
    if keyword and not number:
        ny_match = re.search(r"\b(\d+)\s*/\s*(\d{4})\b", keyword)
        if ny_match:
            num_part, year_part = ny_match.group(1), ny_match.group(2)
            if all_results or boosted_results:
                token = _refresh_token(session)
            results = _do_search(
                session, token,
                doc_number=f"{num_part}-{year_part}",
            )
            _add_results(results, target=boosted_results)
            if results:
                token = _refresh_token(session)

    # Step 1: Alias boost — if keyword matches a known alias, do a precise
    # number search first and put those results at the very top.
    if keyword and not number:
        from app.services.legal_aliases import expand_query
        alias_matches = expand_query(keyword)
        if alias_matches:
            for alias in alias_matches:
                if alias.get("number"):
                    results = _do_search(
                        session, token,
                        doc_type=alias.get("type", ""),
                        doc_number=alias["number"],
                    )
                    _add_results(results, target=boosted_results)
                    if results:
                        token = _refresh_token(session)
                elif alias.get("title"):
                    results = _do_search(
                        session, token,
                        title_text=alias["title"],
                        doc_type=alias.get("type", ""),
                        date_signed_from=ro_signed_from,
                        date_to=ro_date_to,
                    )
                    _add_results(results, target=boosted_results)
                    if results:
                        token = _refresh_token(session)

    # Build list of doc type codes to search.
    # For multi-select (2+ types), do one search per type and merge.
    # For 0 or 1 type, search once with that type (or no type filter).
    search_type_codes = doc_type_codes if len(doc_type_codes) > 1 else [resolved_doc_type]

    for type_code in search_type_codes:
        if len(all_results) >= max_results:
            break

        # Primary search: title
        if title_text or type_code or doc_number or emitent or effective_date_from or ro_date_to or ro_signed_from:
            if all_results or boosted_results:
                token = _refresh_token(session)
            results = _do_search(
                session, token,
                title_text=title_text,
                doc_type=type_code,
                doc_number=doc_number,
                emitent=emitent,
                date_from=effective_date_from,
                date_to=ro_date_to,
                date_signed_from=ro_signed_from,
            )
            _add_results(results)

        # Word-form expansion: try alternative Romanian inflections for the title
        if title_text and len(all_results) < max_results:
            for variant in _expand_word_forms(title_text):
                if len(all_results) >= max_results:
                    break
                token = _refresh_token(session)
                results = _do_search(
                    session, token,
                    title_text=variant,
                    doc_type=type_code,
                    doc_number=doc_number,
                    emitent=emitent,
                    date_from=effective_date_from,
                    date_to=ro_date_to,
                    date_signed_from=ro_signed_from,
                )
                _add_results(results)

        # Content search as broader candidate fetcher — legislatie.just.ro
        # does whole-word title matching ("audiovizual" won't find
        # "audiovizualului"), so we also search document content to cast a
        # wider net.  We split keywords across multiple AND-connected content
        # fields so each word is matched independently (not as an exact phrase).
        if keyword and len(all_results) < max_results:
            split_kw = _split_content_keywords(keyword)
            token = _refresh_token(session)
            results = _do_search(
                session, token,
                content_keywords=split_kw,
                doc_type=type_code,
                doc_number=doc_number,
                emitent=emitent,
                date_from=effective_date_from,
                date_to=ro_date_to,
                date_signed_from=ro_signed_from,
            )
            _add_results(results)

    # Keyword post-filter: keep only results where EVERY significant keyword
    # word appears as a substring in at least one visible field.
    # We expand each word to all its Romanian word forms so that e.g.
    # "legea" matches "lege" and "societatilor" matches "societatile".
    # Stopwords are skipped — "de", "din", etc. don't need to match.
    if keyword:
        # Expand NUMBER/YEAR pairs (e.g. "57/2019") into two separate tokens
        # ("57", "2019") so the post-filter can match acts whose number and
        # date appear in different visible fields.
        def _expand_tokens(text: str) -> list[str]:
            out: list[str] = []
            for raw in text.split():
                m = re.fullmatch(r"(\d+)/(\d{4})", raw)
                if m:
                    out.append(m.group(1))
                    out.append(m.group(2))
                else:
                    out.append(raw)
            return out

        kw_words = [_strip_diacritics(w).lower() for w in _expand_tokens(keyword)
                     if w and w.lower() not in _STOPWORDS and len(w) >= 2]

        def _word_variants(word: str) -> list[str]:
            """Return the word plus all its known Romanian inflections (diacritic-stripped)."""
            forms = _FORM_LOOKUP.get(word)
            if not forms:
                return [word]
            return [word] + [_strip_diacritics(f).lower() for f in forms if _strip_diacritics(f).lower() != word]

        kw_variants = [_word_variants(w) for w in kw_words]

        def _matches_keyword(r: SearchResult) -> bool:
            searchable = _strip_diacritics(" ".join([
                r.title, r.description, r.issuer, r.doc_type, r.number, r.date,
            ])).lower()
            return all(
                any(v in searchable for v in variants)
                for variants in kw_variants
            )

        boosted_results = [r for r in boosted_results if _matches_keyword(r)]
        all_results = [r for r in all_results if _matches_keyword(r)]

    # Default tier ordering (1=top, 4=bottom). Codes are placed with LEGE
    # because most Romanian codes are issued via LEGE; codes issued via OUG
    # (e.g. Codul administrativ) come back from legislatie.just.ro with
    # doc_type="OUG" so they naturally land in tier 2 anyway.
    DOC_TYPE_TIER = {
        "LEGE": 1, "COD": 1,
        "OUG": 2, "OG": 2, "ORDONANTA": 2, "ORDONANȚĂ": 2,
        "HG": 3, "HOTARARE": 3, "HOTĂRÂRE": 3,
    }
    DEFAULT_TIER = 4  # everything else, including CONSTITUTIE/DECRET/...

    def _tier_for(doc_type: str) -> int:
        return DOC_TYPE_TIER.get((doc_type or "").upper(), DEFAULT_TIER)

    # Keyword-type override: if the user typed a token that names an act type
    # (and they did NOT pick a doc_type in the structured filter), promote
    # results of that type to rank 0, above the default tier sort. The rest
    # still appear after, in normal tier order.
    promoted_tier: int | None = None
    if keyword and not doc_type_codes:
        kw_norm = _strip_diacritics(keyword).lower()
        kw_tokens = set(re.findall(r"[a-z]+", kw_norm))
        # Order matters: check more specific tokens first.
        if {"oug"} & kw_tokens or "de urgenta" in kw_norm or "de urgență" in kw_norm:
            promoted_tier = 2  # OUG specifically
        elif {"ordonanta", "ordonanță", "og"} & kw_tokens:
            promoted_tier = 2  # OG/OUG/ordonanță
        elif {"hotarare", "hotărâre", "hg"} & kw_tokens:
            promoted_tier = 3  # HG
        elif {"lege", "legea"} & kw_tokens:
            promoted_tier = 1  # LEGE

    def _sort_key(r: SearchResult) -> tuple[int, int]:
        tier = _tier_for(r.doc_type)
        # Rank 0 = promoted; rank 1 = everything else (then by tier).
        rank = 0 if promoted_tier is not None and tier == promoted_tier else 1
        return (rank, tier)

    all_results.sort(key=_sort_key)
    # Apply the same tier sort to boosted_results so that within the boost
    # block (e.g. NUMBER/YEAR exact matches across multiple act types) the
    # LEGE > OUG > HG > rest order still holds.
    boosted_results.sort(key=_sort_key)

    # Combine: boosted results first, then sorted remainder
    final = boosted_results + all_results
    return final[:max_results]
