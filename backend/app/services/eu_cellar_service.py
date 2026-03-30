"""EU legislation service — CELLAR SPARQL + REST API integration."""
import re
import logging
import time
import datetime
import requests
from dataclasses import dataclass, asdict
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.law import Law, LawVersion, KnownVersion, Article, StructuralElement, Paragraph, Subparagraph, Annex
from app.models.category import Category
from app.services.eu_html_parser import parse_eu_xhtml

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


# --- SPARQL / CELLAR constants ---

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CELLAR_BASE = "https://publications.europa.eu/resource/cellar"

SPARQL_HEADERS = {
    "Accept": "application/sparql-results+json",
    "Content-Type": "application/x-www-form-urlencoded",
}

RESOURCE_TYPE_BASE = "http://publications.europa.eu/resource/authority/resource-type"
LANGUAGE_BASE = "http://publications.europa.eu/resource/authority/language"

EU_DOC_TYPE_TO_RESOURCE = {
    "directive": f"{RESOURCE_TYPE_BASE}/DIR",
    "regulation": f"{RESOURCE_TYPE_BASE}/REG",
    "eu_decision": f"{RESOURCE_TYPE_BASE}/DEC",
    "treaty": f"{RESOURCE_TYPE_BASE}/TREATY",
}


@dataclass
class EUSearchResult:
    celex: str
    title: str
    date: str
    doc_type: str
    in_force: bool
    cellar_uri: str
    already_imported: bool = False

    def to_dict(self):
        return asdict(self)


# Common EU law abbreviations → title keywords for SPARQL title search
_EU_ALIASES = {
    "gdpr": "general data protection regulation",
    "ai act": "artificial intelligence",
    "dsa": "digital services act",
    "dma": "digital markets act",
    "nis2": "high common level of cybersecurity",
    "nis 2": "high common level of cybersecurity",
    "mdr": "medical devices regulation",
    "mifid": "markets in financial instruments",
    "psd2": "payment services",
    "emir": "otc derivatives",
    "reach": "registration, evaluation, authorisation",
    "rohs": "restriction of the use of certain hazardous substances",
}


def build_search_sparql(
    keyword: str | None = None,
    doc_type: str | None = None,
    year: str | None = None,
    number: str | None = None,
    in_force_only: bool = False,
    language: str = "ENG",
    limit: int = 50,
) -> str:
    """Build a SPARQL query to search EU legislation via CELLAR."""
    filters = []

    # When year+number are provided, CELEX prefix is precise enough — skip type filter
    # to avoid SPARQL performance issues with multi-join queries
    has_celex_filter = bool(year or number)
    if doc_type and doc_type in EU_DOC_TYPE_TO_RESOURCE and not has_celex_filter:
        type_clause = f"?work cdm:work_has_resource-type <{EU_DOC_TYPE_TO_RESOURCE[doc_type]}> ."
    elif not has_celex_filter:
        type_values = " ".join(f"<{uri}>" for uri in EU_DOC_TYPE_TO_RESOURCE.values())
        type_clause = f"VALUES ?type {{ {type_values} }}\n  ?work cdm:work_has_resource-type ?type ."
    else:
        type_clause = ""

    if keyword:
        escaped = keyword.replace('"', '\\"')
        filters.append(f'FILTER(CONTAINS(LCASE(?title), LCASE("{escaped}")))')

    if year and number:
        # When both provided, construct precise CELEX prefix: 3{year}{type}{number}
        padded = number.zfill(4)
        # Use STRSTARTS with year prefix + CONTAINS for number (more efficient)
        filters.append(f'FILTER(STRSTARTS(STR(?celex), "3{year}") && CONTAINS(STR(?celex), "{padded}"))')
    elif year:
        filters.append(f'FILTER(STRSTARTS(STR(?celex), "3{year}"))')
    elif number:
        padded = number.zfill(4)
        filters.append(f'FILTER(CONTAINS(STR(?celex), "{padded}"))')

    if in_force_only:
        filters.append('FILTER(?inForce = "true"^^xsd:boolean)')

    filter_block = "\n  ".join(filters)

    return f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?work ?celex ?title ?date ?inForce WHERE {{
  {type_clause}
  ?work cdm:resource_legal_id_celex ?celex .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <{LANGUAGE_BASE}/{language}> .
  ?expr cdm:expression_title ?title .
  OPTIONAL {{ ?work cdm:work_date_document ?date }}
  OPTIONAL {{ ?work cdm:resource_legal_in-force ?inForce }}
  FILTER(STRSTARTS(?celex, "3"))
  {filter_block}
}} ORDER BY DESC(?date) LIMIT {limit}"""


def search_eu_legislation(
    keyword: str | None = None,
    doc_type: str | None = None,
    year: str | None = None,
    number: str | None = None,
    in_force_only: bool = False,
    limit: int = 50,
) -> list[EUSearchResult]:
    """Search EU legislation via CELLAR SPARQL endpoint."""
    # Expand common abbreviations
    if keyword:
        expanded = _EU_ALIASES.get(keyword.strip().lower())
        if expanded:
            keyword = expanded
    for lang in ("RON", "ENG"):
        sparql = build_search_sparql(
            keyword=keyword, doc_type=doc_type, year=year, number=number,
            in_force_only=in_force_only, language=lang, limit=limit,
        )
        try:
            resp = requests.post(
                SPARQL_ENDPOINT, data={"query": sparql}, headers=SPARQL_HEADERS, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            bindings = data.get("results", {}).get("bindings", [])
            if bindings:
                return _parse_sparql_results(bindings)
        except Exception as e:
            logger.warning(f"SPARQL search failed (lang={lang}): {e}")
    return []


def _parse_sparql_results(bindings: list[dict]) -> list[EUSearchResult]:
    results = []
    seen_celex = set()
    for b in bindings:
        celex = b.get("celex", {}).get("value", "")
        if not celex or celex in seen_celex:
            continue
        seen_celex.add(celex)
        in_force_val = b.get("inForce", {}).get("value", "")
        results.append(EUSearchResult(
            celex=celex,
            title=b.get("title", {}).get("value", ""),
            date=b.get("date", {}).get("value", ""),
            doc_type=celex_to_document_type(celex),
            in_force=in_force_val.lower() == "true" if in_force_val else True,
            cellar_uri=b.get("work", {}).get("value", ""),
        ))
    return results


# --- Task 9: CELLAR REST Content Fetcher ---

CACHE_DIR = Path.home() / ".cellar"

CELLAR_HEADERS = {
    "User-Agent": "Themis-Legal/1.0 (EU legislation import)",
}


def fetch_eu_content(cellar_uri: str, celex: str, language: str = "ron", use_cache: bool = True) -> tuple[dict, str]:
    """Fetch and parse EU legislation content from CELLAR.
    Returns (parsed_content, language_code) where language_code is 'ro' or 'en'.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for lang_code, accept_lang in [("ro", "ron"), ("en", "eng")]:
        if language == "eng" and lang_code == "ro":
            continue

        cache_file = CACHE_DIR / f"{celex}_{lang_code}.xhtml"

        if use_cache and cache_file.exists():
            html = cache_file.read_text(encoding="utf-8")
            return parse_eu_xhtml(html), lang_code

        try:
            resp = requests.get(
                cellar_uri,
                headers={**CELLAR_HEADERS, "Accept": "application/xhtml+xml", "Accept-Language": accept_lang},
                timeout=60,
                allow_redirects=True,
            )
            if resp.status_code == 200 and "html" in resp.headers.get("content-type", "").lower():
                html = resp.text
                cache_file.write_text(html, encoding="utf-8")
                return parse_eu_xhtml(html), lang_code
        except Exception as e:
            logger.warning(f"CELLAR fetch failed (lang={lang_code}, celex={celex}): {e}")

    raise RuntimeError(f"Could not fetch content for {celex} in any language")


def fetch_eu_metadata(celex: str) -> dict | None:
    """Fetch metadata for a single EU act via SPARQL by CELEX number."""
    sparql = f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?work ?title ?date ?inForce WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STR(?celex) = "{celex}")
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <{LANGUAGE_BASE}/ENG> .
  ?expr cdm:expression_title ?title .
  OPTIONAL {{ ?work cdm:work_date_document ?date }}
  OPTIONAL {{ ?work cdm:resource_legal_in-force ?inForce }}
}} LIMIT 1"""

    try:
        resp = requests.post(SPARQL_ENDPOINT, data={"query": sparql}, headers=SPARQL_HEADERS, timeout=30)
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])
        if not bindings:
            return None
        b = bindings[0]
        in_force_val = b.get("inForce", {}).get("value", "")
        return {
            "celex": celex,
            "cellar_uri": b.get("work", {}).get("value", ""),
            "title": b.get("title", {}).get("value", ""),
            "date": b.get("date", {}).get("value", ""),
            "in_force": in_force_val.lower() == "true" if in_force_val else True,
            "doc_type": celex_to_document_type(celex),
        }
    except Exception as e:
        logger.error(f"Failed to fetch metadata for {celex}: {e}")
        return None


def fetch_consolidated_versions(celex: str) -> list[dict]:
    """Fetch all consolidated versions for a base act via SPARQL."""
    parsed = parse_celex(celex)
    if not parsed:
        return []
    base_pattern = f"0{parsed['year']}{parsed['type_code']}{parsed['number']}"

    sparql = f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT ?work ?celex ?date WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "{base_pattern}"))
  OPTIONAL {{ ?work cdm:work_date_document ?date }}
}} ORDER BY DESC(?date)"""

    try:
        resp = requests.post(SPARQL_ENDPOINT, data={"query": sparql}, headers=SPARQL_HEADERS, timeout=30)
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])
        return [
            {
                "celex": b.get("celex", {}).get("value", ""),
                "cellar_uri": b.get("work", {}).get("value", ""),
                "date": b.get("date", {}).get("value", ""),
            }
            for b in bindings
        ]
    except Exception as e:
        logger.error(f"Failed to fetch consolidated versions for {celex}: {e}")
        return []


# --- Task 10: EU Import Orchestration ---


def import_eu_law(db: Session, celex: str, import_history: bool = True, rate_limit_delay: float = 2.0) -> dict:
    """Import an EU law by CELEX number."""
    existing = db.query(Law).filter(Law.celex_number == celex).first()
    if existing:
        raise ValueError(f"Law with CELEX {celex} already imported (law_id={existing.id})")

    meta = fetch_eu_metadata(celex)
    if not meta:
        raise RuntimeError(f"Could not fetch metadata for CELEX {celex}")

    doc_type = celex_to_document_type(celex)
    category_slug = celex_to_category_slug(celex)
    category = db.query(Category).filter_by(slug=category_slug).first() if category_slug else None

    parsed = parse_celex(celex)
    law_number = parsed["number"].lstrip("0") if parsed else ""
    law_year = int(parsed["year"]) if parsed else 0

    eli_url = _build_eli_url(doc_type, parsed)
    law = Law(
        title=meta["title"],
        law_number=law_number,
        law_year=law_year,
        document_type=doc_type,
        source_url=eli_url,
        source="eu",
        celex_number=celex,
        cellar_uri=meta["cellar_uri"],
        status="in_force" if meta["in_force"] else "unknown",
        category_id=category.id if category else None,
        category_confidence="auto" if category else None,
    )
    db.add(law)
    db.flush()

    content, lang = fetch_eu_content(meta["cellar_uri"], celex)
    version = _store_eu_version(db, law, celex, meta["date"], content, lang, is_current=True)
    versions_imported = 1

    if import_history:
        consol_versions = fetch_consolidated_versions(celex)
        for cv in consol_versions:
            if db.query(LawVersion).filter_by(ver_id=cv["celex"]).first():
                continue
            try:
                time.sleep(rate_limit_delay)
                cv_content, cv_lang = fetch_eu_content(cv["cellar_uri"], cv["celex"])
                # Skip versions with empty content (CELLAR returns empty XHTML for some)
                if not cv_content.get("articles"):
                    logger.info(f"Skipping consolidated version {cv['celex']} — no article content")
                    continue
                _store_eu_version(db, law, cv["celex"], cv["date"], cv_content, cv_lang, is_current=False)
                versions_imported += 1
            except Exception as e:
                logger.warning(f"Failed to import consolidated version {cv['celex']}: {e}")

        # Only update current if a consolidated version has content; otherwise keep base
        _update_current_version_with_content(db, law)

    db.commit()

    try:
        from app.services.indexing_service import index_law_to_chroma, rebuild_bm25
        index_law_to_chroma(db, law.id)
        rebuild_bm25(db)
    except Exception as e:
        logger.warning(f"Indexing failed for EU law {celex}: {e}")

    return {
        "law_id": law.id,
        "title": law.title,
        "law_number": law_number,
        "law_year": law_year,
        "document_type": doc_type,
        "versions_imported": versions_imported,
    }


def _store_eu_version(db, law, ver_celex, date_str, content, language, is_current):
    """Store a single EU law version with full hierarchy from parsed content."""
    date_in_force = None
    if date_str:
        try:
            date_in_force = datetime.date.fromisoformat(date_str[:10])
        except ValueError:
            pass

    version = LawVersion(
        law_id=law.id, ver_id=ver_celex, date_in_force=date_in_force,
        state="actual", is_current=is_current, language=language,
    )
    db.add(version)
    db.flush()

    articles = content.get("articles", {})
    order_counter = [0]  # mutable counter for ordering
    stored_article_ids = set()

    # Store preamble as special article
    preamble = content.get("preamble", {})
    if preamble.get("citations") or preamble.get("recitals"):
        _store_preamble_article(db, version, preamble)

    # Walk hierarchy from books_data
    for book_data in content.get("books_data", []):
        for title_data in book_data.get("titles", []):
            title_el = None
            if title_data.get("title_id") and title_data["title_id"] != "default":
                title_el = StructuralElement(
                    law_version_id=version.id, element_type="title",
                    number=title_data["title_id"], title=title_data.get("title"),
                    order_index=order_counter[0],
                )
                db.add(title_el)
                db.flush()
                order_counter[0] += 1

            # Articles directly in title
            for art_id in title_data.get("articles", []):
                if art_id in articles and art_id not in stored_article_ids:
                    _store_eu_article(db, version, articles[art_id], title_el, order_counter)
                    stored_article_ids.add(art_id)

            for ch_data in title_data.get("chapters", []):
                ch_el = StructuralElement(
                    law_version_id=version.id,
                    parent_id=title_el.id if title_el else None,
                    element_type="chapter", number=ch_data["chapter_id"],
                    title=ch_data.get("title"), order_index=order_counter[0],
                )
                db.add(ch_el)
                db.flush()
                order_counter[0] += 1

                # Articles directly in chapter
                for art_id in ch_data.get("articles", []):
                    if art_id in articles and art_id not in stored_article_ids:
                        _store_eu_article(db, version, articles[art_id], ch_el, order_counter)
                        stored_article_ids.add(art_id)

                for sec_data in ch_data.get("sections", []):
                    sec_el = StructuralElement(
                        law_version_id=version.id, parent_id=ch_el.id,
                        element_type="section", number=sec_data["section_id"],
                        title=sec_data.get("title"), order_index=order_counter[0],
                    )
                    db.add(sec_el)
                    db.flush()
                    order_counter[0] += 1

                    for art_id in sec_data.get("articles", []):
                        if art_id in articles and art_id not in stored_article_ids:
                            _store_eu_article(db, version, articles[art_id], sec_el, order_counter)
                            stored_article_ids.add(art_id)

        # Articles directly in book
        for art_id in book_data.get("articles", []):
            if art_id in articles and art_id not in stored_article_ids:
                _store_eu_article(db, version, articles[art_id], None, order_counter)
                stored_article_ids.add(art_id)

    # Store any articles not in the hierarchy
    for art_id, art_data in articles.items():
        if art_id not in stored_article_ids:
            _store_eu_article(db, version, art_data, None, order_counter)

    # Store annexes
    for idx, annex_data in enumerate(content.get("annexes", [])):
        annex = Annex(
            law_version_id=version.id,
            source_id=annex_data.get("annex_id", f"annex_{idx}"),
            title=annex_data.get("title", ""),
            full_text=annex_data.get("text", ""),
            order_index=idx,
        )
        db.add(annex)

    return version


def _store_eu_article(db, version, art_data, parent_el, order_counter):
    """Store an EU article with proper article_number and label fields."""
    full_text = art_data.get("full_text", "")
    is_abrogated = bool(re.search(r"^\s*\(?\s*[Aa]brogat", full_text[:200]))

    article = Article(
        law_version_id=version.id,
        structural_element_id=parent_el.id if parent_el else None,
        article_number=art_data.get("label", ""),  # "Art. 1"
        label=art_data.get("article_title") or art_data.get("label", ""),
        full_text=full_text,
        order_index=order_counter[0],
        is_abrogated=is_abrogated,
    )
    db.add(article)
    db.flush()
    order_counter[0] += 1

    for p_idx, para in enumerate(art_data.get("paragraphs", [])):
        paragraph = Paragraph(
            article_id=article.id,
            paragraph_number=para.get("label", "").strip("()") or str(p_idx + 1),
            label=para.get("label", ""),
            text=para.get("text", ""),
            order_index=p_idx,
        )
        db.add(paragraph)
        db.flush()

        for s_idx, sub in enumerate(para.get("subparagraphs", [])):
            subparagraph = Subparagraph(
                paragraph_id=paragraph.id,
                label=sub.get("label", ""),
                text=sub.get("text", ""),
                order_index=s_idx,
            )
            db.add(subparagraph)


def _store_preamble_article(db, version, preamble):
    """Store preamble as a special article with order_index=-1."""
    paragraphs_data = []
    for cit in preamble.get("citations", []):
        paragraphs_data.append({"label": cit.get("number", ""), "text": cit.get("text", "")})
    for rct in preamble.get("recitals", []):
        paragraphs_data.append({"label": f"({rct['number']})", "text": rct.get("text", "")})

    full_parts = ["Preambul"]
    for p in paragraphs_data:
        full_parts.append(p["text"])

    article = Article(
        law_version_id=version.id,
        structural_element_id=None,
        article_number="Preambul",
        label="Preambul",
        full_text="\n".join(full_parts),
        order_index=-1,
    )
    db.add(article)
    db.flush()

    for p_idx, para in enumerate(paragraphs_data):
        paragraph = Paragraph(
            article_id=article.id,
            paragraph_number=para.get("label", "").strip("()") or str(p_idx + 1),
            label=para.get("label", ""),
            text=para.get("text", ""),
            order_index=p_idx,
        )
        db.add(paragraph)


def _update_current_version(db, law):
    versions = db.query(LawVersion).filter_by(law_id=law.id).order_by(LawVersion.date_in_force.desc()).all()
    for i, v in enumerate(versions):
        v.is_current = (i == 0)


def _update_current_version_with_content(db, law):
    """Mark the newest version WITH articles as current. Falls back to newest overall."""
    versions = db.query(LawVersion).filter_by(law_id=law.id).order_by(LawVersion.date_in_force.desc()).all()
    # First, try to find newest version that has articles
    best = None
    for v in versions:
        article_count = db.query(Article).filter_by(law_version_id=v.id).count()
        if article_count > 0:
            best = v
            break
    if not best and versions:
        best = versions[0]
    for v in versions:
        v.is_current = (v.id == best.id) if best else False


def _build_eli_url(doc_type, parsed):
    if not parsed:
        return ""
    type_map = {"regulation": "reg", "directive": "dir", "eu_decision": "dec", "treaty": "treaty"}
    eli_type = type_map.get(doc_type, "act")
    return f"http://data.europa.eu/eli/{eli_type}/{parsed['year']}/{parsed['number'].lstrip('0')}/oj"
