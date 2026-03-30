"""Parse EUR-Lex XHTML into structured articles, chapters, and annexes.

Uses ID-driven structural parsing based on real EUR-Lex XHTML conventions:
- div.eli-container as root
- div#enc_1 as the enacting clause container
- div#cpt_I, div#cpt_II etc. for chapters
- div#tis_I, div#tis_II for titles (higher-level grouping)
- div#cpt_III.sct_1 for sections within chapters
- div#art_1, div#art_2 etc. for articles
- div#001.001, div#001.002 etc. for paragraph containers
- <table> elements with 4%/96% columns for lettered sub-clauses
- div#pbl_1 with div#cit_N and div#rct_N for preamble
"""

import re
import logging
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_ARTICLE_NUM_RE = re.compile(r"^art_(\d+[a-z]?)$")
_PARA_LABEL_RE = re.compile(r"^\((\d+)\)")
_SUBPARA_LABEL_RE = re.compile(r"^\(([a-z]+)\)")
_ROMAN_RE = re.compile(r"^\(([ivxlcdm]+)\)")
_RECITAL_NUM_RE = re.compile(r"^\((\d+)\)")


def parse_eu_xhtml(html: str) -> dict:
    """Parse EUR-Lex XHTML and return structured document data.

    Handles two EUR-Lex formats:
    - Modern (post-2012): eli-container with eli-subdivision divs, oj-* CSS classes
    - Legacy (pre-2012): flat <p> tags with ti-art, normal, ti-section-1 classes (no oj- prefix)
    """
    soup = BeautifulSoup(html, "html.parser")

    container = soup.find("div", class_="eli-container")
    if not container:
        # Try legacy format
        if soup.find("p", class_="ti-art"):
            return _parse_legacy_format(soup)
        return _empty_result()

    title = _extract_title(container)
    preamble = _extract_preamble(container)
    enc = container.find("div", id="enc_1")

    articles = {}
    books_data = []
    annexes = []

    if not enc:
        return {
            "title": title,
            "preamble": preamble,
            "books_data": books_data,
            "articles": articles,
            "annexes": annexes,
        }

    # Determine top-level structure: titles or chapters directly
    has_titles = bool(enc.find("div", id=re.compile(r"^tis_")))
    has_chapters = bool(enc.find("div", id=re.compile(r"^cpt_")))

    if has_titles:
        # Title -> Chapter -> Section -> Article hierarchy
        title_nodes = _find_direct_children(enc, r"^tis_")
        parsed_titles = []
        for tis_div in title_nodes:
            parsed_title = _parse_title_div(tis_div, articles)
            parsed_titles.append(parsed_title)

        books_data = [{
            "book_id": "default",
            "title": None,
            "description": None,
            "articles": [],
            "titles": parsed_titles,
        }]
    elif has_chapters:
        # Chapter -> Section -> Article (no titles, e.g. GDPR)
        chapter_nodes = _find_direct_children(enc, r"^cpt_")
        parsed_chapters = []
        for cpt_div in chapter_nodes:
            parsed_chapter = _parse_chapter_div(cpt_div, articles)
            parsed_chapters.append(parsed_chapter)

        books_data = [{
            "book_id": "default",
            "title": None,
            "description": None,
            "articles": [],
            "titles": [{
                "title_id": "default",
                "title": None,
                "chapters": parsed_chapters,
                "articles": [],
            }],
        }]
    else:
        # Articles directly under enc_1 (flat structure)
        art_ids = []
        for art_div in enc.find_all("div", id=re.compile(r"^art_")):
            art = _parse_article(art_div)
            if art:
                articles[art["article_id"]] = art
                art_ids.append(art["article_id"])

        if art_ids:
            books_data = [{
                "book_id": "default",
                "title": None,
                "description": None,
                "articles": art_ids,
                "titles": [],
            }]

    # Extract annexes
    for anx_div in container.find_all("div", id=re.compile(r"^anx_")):
        annexes.append(_parse_annex(anx_div))

    return {
        "title": title,
        "preamble": preamble,
        "books_data": books_data,
        "articles": articles,
        "annexes": annexes,
    }


def _empty_result() -> dict:
    return {
        "title": "",
        "preamble": {"citations": [], "recitals": []},
        "books_data": [],
        "articles": {},
        "annexes": [],
    }


def _extract_title(container: Tag) -> str:
    """Extract document title from eli-main-title."""
    title_div = container.find("div", class_="eli-main-title")
    if not title_div:
        return ""
    parts = []
    for p in title_div.find_all("p", class_="oj-doc-ti"):
        text = p.get_text(strip=True)
        if text:
            parts.append(text)
    return " ".join(parts)


def _extract_preamble(container: Tag) -> dict:
    """Extract citations and recitals from div#pbl_1."""
    pbl = container.find("div", id="pbl_1")
    if not pbl:
        return {"citations": [], "recitals": []}

    citations = []
    for cit_div in pbl.find_all("div", id=re.compile(r"^cit_\d+")):
        cit_id = cit_div.get("id", "")
        text = cit_div.get_text(strip=True)
        citations.append({"number": cit_id, "text": text})

    recitals = []
    for rct_div in pbl.find_all("div", id=re.compile(r"^rct_\d+")):
        # Recital number from the first td
        num_match = None
        first_td = rct_div.find("td")
        if first_td:
            td_text = first_td.get_text(strip=True)
            num_match = _RECITAL_NUM_RE.match(td_text)

        # Recital text from the second td
        tds = rct_div.find_all("td")
        text = ""
        if len(tds) >= 2:
            text = tds[1].get_text(strip=True)

        number = num_match.group(1) if num_match else rct_div.get("id", "").replace("rct_", "")
        recitals.append({"number": number, "text": text})

    return {"citations": citations, "recitals": recitals}


def _find_direct_children(parent: Tag, id_pattern: str) -> list[Tag]:
    """Find direct child divs whose id matches pattern."""
    results = []
    compiled = re.compile(id_pattern)
    for child in parent.children:
        if isinstance(child, Tag) and child.name == "div":
            child_id = child.get("id", "")
            if compiled.match(child_id):
                results.append(child)
    return results


def _parse_title_div(tis_div: Tag, articles: dict) -> dict:
    """Parse a Title-level div (tis_I, tis_II, etc.)."""
    tis_id = tis_div.get("id", "")
    # Extract roman numeral: tis_I -> I, tis_II -> II
    title_id = tis_id.split("_", 1)[1] if "_" in tis_id else tis_id

    title_text = _extract_section_title(tis_div)

    # Find chapters within this title
    chapter_divs = []
    for child in tis_div.children:
        if isinstance(child, Tag) and child.name == "div":
            child_id = child.get("id", "")
            if ".cpt_" in child_id or (child_id.startswith("cpt_") and child_id != tis_id):
                chapter_divs.append(child)

    parsed_chapters = []
    for cpt_div in chapter_divs:
        parsed_chapter = _parse_chapter_div(cpt_div, articles)
        parsed_chapters.append(parsed_chapter)

    # Articles directly in this title (not in a chapter)
    direct_art_ids = []
    for child in tis_div.children:
        if isinstance(child, Tag) and child.name == "div":
            child_id = child.get("id", "")
            if child_id.startswith("art_"):
                art = _parse_article(child)
                if art:
                    articles[art["article_id"]] = art
                    direct_art_ids.append(art["article_id"])

    return {
        "title_id": title_id,
        "title": title_text,
        "chapters": parsed_chapters,
        "articles": direct_art_ids,
    }


def _parse_chapter_div(cpt_div: Tag, articles: dict) -> dict:
    """Parse a Chapter-level div (cpt_I, tis_II.cpt_I, etc.)."""
    cpt_id = cpt_div.get("id", "")
    # Extract chapter roman numeral from id
    # e.g. cpt_I -> I, tis_II.cpt_I -> I, cpt_III -> III
    chapter_id = ""
    cpt_match = re.search(r"cpt_([IVXLCDM]+)", cpt_id)
    if cpt_match:
        chapter_id = cpt_match.group(1)

    title_text = _extract_section_title(cpt_div)

    # Find sections within this chapter
    section_divs = []
    for child in cpt_div.children:
        if isinstance(child, Tag) and child.name == "div":
            child_id = child.get("id", "")
            if ".sct_" in child_id or child_id.startswith("sct_"):
                section_divs.append(child)

    parsed_sections = []
    for sct_div in section_divs:
        parsed_section = _parse_section_div(sct_div, articles)
        parsed_sections.append(parsed_section)

    # Articles directly in this chapter (not in a section)
    direct_art_ids = []
    for child in cpt_div.children:
        if isinstance(child, Tag) and child.name == "div":
            child_id = child.get("id", "")
            if child_id.startswith("art_"):
                art = _parse_article(child)
                if art:
                    articles[art["article_id"]] = art
                    direct_art_ids.append(art["article_id"])

    return {
        "chapter_id": chapter_id,
        "title": title_text,
        "description": None,
        "sections": parsed_sections,
        "articles": direct_art_ids,
    }


def _parse_section_div(sct_div: Tag, articles: dict) -> dict:
    """Parse a Section-level div (cpt_III.sct_1, etc.)."""
    sct_id = sct_div.get("id", "")
    # Extract section number: cpt_III.sct_1 -> 1, tis_II.cpt_I.sct_1 -> 1
    section_id = ""
    sct_match = re.search(r"sct_(\d+)", sct_id)
    if sct_match:
        section_id = sct_match.group(1)

    title_text = _extract_section_title(sct_div)

    # Collect articles in this section
    art_ids = []
    for art_div in sct_div.find_all("div", id=re.compile(r"^art_")):
        art = _parse_article(art_div)
        if art:
            articles[art["article_id"]] = art
            art_ids.append(art["article_id"])

    return {
        "section_id": section_id,
        "title": title_text,
        "description": None,
        "articles": art_ids,
        "subsections": [],
    }


def _extract_section_title(div: Tag) -> str | None:
    """Extract title from eli-title > oj-ti-section-2 or oj-sti-art."""
    title_div = div.find("div", class_="eli-title", recursive=False)
    if not title_div:
        # Also check direct children
        for child in div.children:
            if isinstance(child, Tag) and child.name == "div" and "eli-title" in (child.get("class") or []):
                title_div = child
                break

    if title_div:
        p = title_div.find("p", class_="oj-ti-section-2")
        if p:
            return p.get_text(strip=True)
    return None


def _parse_article(art_div: Tag) -> dict | None:
    """Parse an article div (art_1, art_2, etc.)."""
    art_id = art_div.get("id", "")
    art_num_match = _ARTICLE_NUM_RE.match(art_id)
    if not art_num_match:
        return None

    art_num = art_num_match.group(1)

    # Article title from oj-sti-art
    article_title = ""
    sti_p = art_div.find("p", class_="oj-sti-art")
    if sti_p:
        article_title = sti_p.get_text(strip=True)

    # Parse paragraphs from div#NNN.MMM children
    paragraphs = _extract_paragraphs(art_div)

    # Build full text
    full_text = _build_full_text(art_num, article_title, paragraphs)

    return {
        "article_id": art_num,
        "label": art_num,
        "article_title": article_title,
        "full_text": full_text,
        "paragraphs": paragraphs,
        "notes": [],
    }


def _extract_paragraphs(art_div: Tag) -> list[dict]:
    """Extract paragraphs from div#NNN.MMM containers within an article.

    Falls back to collecting direct <p> text and direct <table> sub-clauses
    for articles without NNN.MMM divs (e.g., Art. 4 Definiții in GDPR).
    """
    paragraphs = []

    # Find paragraph containers: divs with id like "001.001", "001.002", etc.
    para_divs = []
    for child in art_div.children:
        if isinstance(child, Tag) and child.name == "div":
            child_id = child.get("id", "")
            if re.match(r"\d+\.\d+", child_id):
                para_divs.append(child)

    if para_divs:
        for para_div in para_divs:
            para = _parse_paragraph(para_div)
            if para:
                paragraphs.append(para)
    else:
        # Fallback: collect direct <p class="oj-normal"> and direct <table> sub-clauses
        # This handles articles like Art. 4 (Definiții) that have tables directly in the article div
        text_parts = []
        for child in art_div.children:
            if isinstance(child, Tag) and child.name == "p" and "oj-normal" in (child.get("class") or []):
                text_parts.append(child.get_text(strip=True))

        intro_text = " ".join(text_parts).strip()
        subparagraphs = _extract_table_subclauses(art_div)

        if intro_text or subparagraphs:
            paragraphs.append({
                "label": "",
                "text": intro_text,
                "subparagraphs": subparagraphs,
            })

    return paragraphs


def _parse_paragraph(para_div: Tag) -> dict | None:
    """Parse a single paragraph container (div#NNN.MMM)."""
    # Get the main text from oj-normal p (not inside tables)
    text_parts = []
    for child in para_div.children:
        if isinstance(child, Tag):
            if child.name == "p" and "oj-normal" in (child.get("class") or []):
                text_parts.append(child.get_text(strip=True))

    main_text = " ".join(text_parts).strip()

    # Extract paragraph label
    label = ""
    label_match = _PARA_LABEL_RE.match(main_text)
    if label_match:
        label = f"({label_match.group(1)})"

    # Extract sub-clauses from tables
    subparagraphs = _extract_table_subclauses(para_div)

    # Build the full paragraph text including subclauses
    full_para_text = main_text
    for sub in subparagraphs:
        full_para_text += "\n" + sub["text"]

    return {
        "label": label,
        "text": main_text,
        "subparagraphs": subparagraphs,
    }


def _extract_table_subclauses(container: Tag) -> list[dict]:
    """Extract (a), (b), (c) sub-clauses from table elements.

    Tables have 4%/96% columns. First <td> = label, second <td> = text.
    Nested tables inside second <td> = sub-sub-clauses (i), (ii).
    """
    subparagraphs = []

    # Only process direct child tables (not nested ones)
    for child in container.children:
        if isinstance(child, Tag) and child.name == "table":
            rows = child.find_all("tr")
            for row in rows:
                tds = row.find_all("td", recursive=False)
                if len(tds) < 2:
                    continue

                label_text = tds[0].get_text(strip=True)
                content_td = tds[1]

                # Get text from p.oj-normal in the content td (not from nested tables)
                content_parts = []
                for p in content_td.find_all("p", class_="oj-normal", recursive=False):
                    content_parts.append(p.get_text(strip=True))

                content_text = " ".join(content_parts).strip()

                # Check for nested sub-sub-clauses (i), (ii) in tables within this td
                nested_subs = _extract_table_subclauses(content_td)
                if nested_subs:
                    # Include nested subclauses in the text
                    nested_text = "\n".join(f"{s['label']} {s['text']}" for s in nested_subs)
                    full_text = f"{label_text} {content_text}\n{nested_text}" if content_text else f"{label_text}\n{nested_text}"
                else:
                    full_text = f"{label_text} {content_text}"

                subparagraphs.append({
                    "label": label_text,
                    "text": full_text,
                })

    return subparagraphs


def _build_full_text(art_num: str, article_title: str, paragraphs: list[dict]) -> str:
    """Assemble full article text."""
    parts = [f"Articolul {art_num}"]
    if article_title:
        parts.append(article_title)
    for para in paragraphs:
        parts.append(para["text"])
        for sub in para["subparagraphs"]:
            parts.append(sub["text"])
    return "\n".join(parts)


def _parse_annex(anx_div: Tag) -> dict:
    """Parse an annex div."""
    anx_id = anx_div.get("id", "")
    title_p = anx_div.find("p", class_="oj-ti-section-1")
    title_text = title_p.get_text(strip=True) if title_p else anx_id

    text_parts = []
    for p in anx_div.find_all("p", class_="oj-normal"):
        text = p.get_text(strip=True)
        if text:
            text_parts.append(text)

    return {
        "annex_id": anx_id,
        "title": title_text,
        "text": "\n".join(text_parts),
    }


# --- Legacy format parser (pre-2012 EUR-Lex, no eli-container) ---

_LEGACY_ART_RE = re.compile(
    r"(?:Article|Articolul|Artikel|Articolo|Artículo)\s+(\d+[a-z]?)", re.IGNORECASE
)
_LEGACY_TITLE_RE = re.compile(
    r"(?:TITLUL|TITLE|TITRE)\s+([IVXLCDM]+)", re.IGNORECASE
)
_LEGACY_CHAPTER_RE = re.compile(
    r"(?:CAPITOLUL|CHAPTER|CHAPITRE)\s+(\d+|[IVXLCDM]+)", re.IGNORECASE
)
_LEGACY_SECTION_RE = re.compile(
    r"(?:Secțiunea|Section|Sektion)\s+(\d+)", re.IGNORECASE
)


def _parse_legacy_format(soup: BeautifulSoup) -> dict:
    """Parse the legacy EUR-Lex format (flat <p> tags, no eli-container).

    Used for older regulations (pre-2012) where:
    - Articles are <p class="ti-art">
    - Subtitles are <p class="sti-art">
    - Paragraphs are <p class="normal">
    - Sub-clauses are <table> elements
    - Chapters are <p class="ti-section-1"> / <p class="ti-section-2">
    """
    # Extract title
    title_parts = []
    for p in soup.find_all("p", class_="doc-ti"):
        t = p.get_text(strip=True)
        if t:
            title_parts.append(t)
    title = " ".join(title_parts)

    # Walk all elements in document order to build structure
    body = soup.find("body") or soup
    articles = {}
    structure_stack = []  # [(type, id, title, articles)]
    current_title = None
    current_chapter = None
    current_section = None

    # Collect all markers in order
    markers = body.find_all("p", class_=["ti-section-1", "ti-section-2", "ti-art", "sti-art", "normal"])

    i = 0
    while i < len(markers):
        p = markers[i]
        cls = p.get("class", [])
        text = p.get_text(strip=True)

        if "ti-section-1" in cls:
            # Peek at next element for the section title (ti-section-2)
            section_title = ""
            if i + 1 < len(markers) and "ti-section-2" in markers[i + 1].get("class", []):
                section_title = markers[i + 1].get_text(strip=True)
                i += 1

            title_match = _LEGACY_TITLE_RE.match(text)
            chapter_match = _LEGACY_CHAPTER_RE.match(text)
            section_match = _LEGACY_SECTION_RE.match(text)

            if title_match:
                current_title = {
                    "title_id": title_match.group(1),
                    "title": section_title,
                    "chapters": [],
                    "articles": [],
                }
                structure_stack.append(("title", current_title))
                current_chapter = None
                current_section = None
            elif chapter_match:
                current_chapter = {
                    "chapter_id": chapter_match.group(1),
                    "title": section_title,
                    "description": None,
                    "sections": [],
                    "articles": [],
                }
                if current_title:
                    current_title["chapters"].append(current_chapter)
                else:
                    structure_stack.append(("chapter", current_chapter))
                current_section = None
            elif section_match:
                current_section = {
                    "section_id": section_match.group(1),
                    "title": section_title,
                    "description": None,
                    "articles": [],
                    "subsections": [],
                }
                if current_chapter:
                    current_chapter["sections"].append(current_section)

            i += 1
            continue

        if "ti-section-2" in cls:
            # Already consumed above, skip
            i += 1
            continue

        if "ti-art" in cls:
            art_match = _LEGACY_ART_RE.match(text)
            if art_match:
                art_num = art_match.group(1)

                # Get subtitle (sti-art)
                article_title = ""
                if i + 1 < len(markers) and "sti-art" in markers[i + 1].get("class", []):
                    article_title = markers[i + 1].get_text(strip=True)
                    i += 1

                # Collect paragraphs and tables until next article or section heading
                paragraphs = []
                current_para_text = ""
                current_para_label = ""
                current_subs = []

                j = i + 1
                while j < len(markers):
                    next_p = markers[j]
                    next_cls = next_p.get("class", [])
                    if "ti-art" in next_cls or "ti-section-1" in next_cls:
                        break
                    if "sti-art" in next_cls:
                        j += 1
                        continue
                    if "normal" in next_cls:
                        next_text = next_p.get_text(strip=True)
                        para_match = _PARA_LABEL_RE.match(next_text)
                        if para_match:
                            # Save previous paragraph
                            if current_para_text or current_subs:
                                paragraphs.append({
                                    "label": current_para_label,
                                    "text": current_para_text,
                                    "subparagraphs": current_subs,
                                })
                            current_para_label = f"({para_match.group(1)})"
                            current_para_text = next_text
                            current_subs = []

                            # Collect table sub-clauses after this <p>
                            sibling = next_p.find_next_sibling()
                            while sibling and isinstance(sibling, Tag) and sibling.name == "table":
                                tds = sibling.find_all("td")
                                if len(tds) >= 2:
                                    sub_label = tds[0].get_text(strip=True)
                                    sub_text = tds[1].get_text(strip=True)
                                    current_subs.append({"label": sub_label, "text": sub_text})
                                sibling = sibling.find_next_sibling()
                        else:
                            if not current_para_text:
                                current_para_text = next_text
                                current_para_label = ""
                            else:
                                current_para_text += " " + next_text
                    j += 1

                # Save last paragraph
                if current_para_text or current_subs:
                    paragraphs.append({
                        "label": current_para_label,
                        "text": current_para_text,
                        "subparagraphs": current_subs,
                    })

                full_text = _build_full_text(art_num, article_title, paragraphs)
                articles[art_num] = {
                    "article_id": art_num,
                    "label": art_num,
                    "article_title": article_title,
                    "full_text": full_text,
                    "paragraphs": paragraphs,
                    "notes": [],
                }

                # Add to current structural element
                target = current_section or current_chapter or current_title
                if target:
                    target["articles"].append(art_num)

            i += 1
            continue

        i += 1

    # Build books_data
    titles_list = []
    chapters_list = []
    for stype, sdata in structure_stack:
        if stype == "title":
            titles_list.append(sdata)
        elif stype == "chapter":
            chapters_list.append(sdata)

    if titles_list:
        books_data = [{
            "book_id": "default", "title": None, "description": None,
            "articles": [], "titles": titles_list,
        }]
    elif chapters_list:
        books_data = [{
            "book_id": "default", "title": None, "description": None,
            "articles": [],
            "titles": [{"title_id": "default", "title": None, "chapters": chapters_list, "articles": []}],
        }]
    else:
        books_data = [{
            "book_id": "default", "title": None, "description": None,
            "articles": list(articles.keys()), "titles": [],
        }] if articles else []

    return {
        "title": title,
        "preamble": {"citations": [], "recitals": []},
        "books_data": books_data,
        "articles": articles,
        "annexes": [],
    }
