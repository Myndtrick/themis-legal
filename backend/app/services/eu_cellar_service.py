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

    if doc_type and doc_type in EU_DOC_TYPE_TO_RESOURCE:
        type_clause = f"?work cdm:work_has_resource-type <{EU_DOC_TYPE_TO_RESOURCE[doc_type]}> ."
    else:
        type_values = " ".join(f"<{uri}>" for uri in EU_DOC_TYPE_TO_RESOURCE.values())
        type_clause = f"VALUES ?type {{ {type_values} }}\n  ?work cdm:work_has_resource-type ?type ."

    if keyword:
        escaped = keyword.replace('"', '\\"')
        filters.append(f'FILTER(CONTAINS(LCASE(?title), LCASE("{escaped}")))')

    if year:
        filters.append(f'FILTER(CONTAINS(STR(?celex), "{year}"))')

    if number:
        # Pad to 4 digits for CELEX matching (679 → 0679)
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
SELECT ?work ?title ?date ?inForce WHERE {{
  ?work cdm:resource_legal_id_celex "{celex}" .
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
  FILTER(STRSTARTS(?celex, "{base_pattern}"))
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
                _store_eu_version(db, law, cv["celex"], cv["date"], cv_content, cv_lang, is_current=False)
                versions_imported += 1
            except Exception as e:
                logger.warning(f"Failed to import consolidated version {cv['celex']}: {e}")

        _update_current_version(db, law)

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

    chapter_element_map = {}
    for idx, ch in enumerate(content.get("structure", [])):
        se = StructuralElement(
            law_version_id=version.id, element_type="chapter",
            number=ch["number"], title=ch.get("title", ""), order_index=idx,
        )
        db.add(se)
        db.flush()
        chapter_element_map[ch["number"]] = se

    for idx, art_data in enumerate(content.get("articles", [])):
        parent_se = chapter_element_map.get(art_data.get("chapter_number"))
        article = Article(
            law_version_id=version.id,
            structural_element_id=parent_se.id if parent_se else None,
            article_number=f"Art. {art_data['number']}",
            label=art_data.get("label", ""),
            full_text=art_data.get("full_text", ""),
            order_index=idx,
        )
        db.add(article)
        db.flush()

        for p_idx, para in enumerate(art_data.get("paragraphs", [])):
            paragraph = Paragraph(
                article_id=article.id, paragraph_number=para.get("number", ""),
                text=para.get("text", ""), order_index=p_idx,
            )
            db.add(paragraph)
            db.flush()

            for s_idx, sub in enumerate(para.get("subparagraphs", [])):
                subparagraph = Subparagraph(
                    paragraph_id=paragraph.id, label=sub.get("label", ""),
                    text=sub.get("text", ""), order_index=s_idx,
                )
                db.add(subparagraph)

    for idx, annex_data in enumerate(content.get("annexes", [])):
        annex = Annex(
            law_version_id=version.id,
            source_id=annex_data.get("source_id", f"annex_{idx}"),
            title=annex_data.get("title", ""),
            full_text=annex_data.get("full_text", ""),
            order_index=idx,
        )
        db.add(annex)

    return version


def _update_current_version(db, law):
    versions = db.query(LawVersion).filter_by(law_id=law.id).order_by(LawVersion.date_in_force.desc()).all()
    for i, v in enumerate(versions):
        v.is_current = (i == 0)


def _build_eli_url(doc_type, parsed):
    if not parsed:
        return ""
    type_map = {"regulation": "reg", "directive": "dir", "eu_decision": "dec", "treaty": "treaty"}
    eli_type = type_map.get(doc_type, "act")
    return f"http://data.europa.eu/eli/{eli_type}/{parsed['year']}/{parsed['number'].lstrip('0')}/oj"
