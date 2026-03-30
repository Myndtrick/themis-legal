"""Parse EUR-Lex XHTML into structured articles, chapters, and annexes."""
import re
import logging
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_PARA_NUM_RE = re.compile(r"^(\d+)\.\s+")
_SUBPARA_RE = re.compile(r"^\(([a-z])\)\s*")
_ARTICLE_NUM_RE = re.compile(r"(?:Article|Articolul|Artikel|Articolo|Artículo)\s+(\d+[a-z]?)", re.IGNORECASE)
_CHAPTER_NUM_RE = re.compile(r"(?:CHAPTER|CAPITOLUL|CHAPITRE|KAPITEL)\s+([IVXLCDM]+)", re.IGNORECASE)
_ANNEX_RE = re.compile(r"(?:ANNEX|ANEXA|ANNEXE|ANHANG)\s*([IVXLCDM]*)", re.IGNORECASE)


def parse_eu_xhtml(html: str) -> dict:
    """Parse EUR-Lex XHTML and return {title, articles, structure, annexes}."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    structure, articles, annexes = _extract_body(soup)
    return {"title": title, "articles": articles, "structure": structure, "annexes": annexes}


def _extract_title(soup: BeautifulSoup) -> str:
    parts = []
    for p in soup.find_all("p", class_="oj-doc-ti"):
        text = p.get_text(strip=True)
        if text:
            parts.append(text)
    return " ".join(parts)


def _extract_body(soup: BeautifulSoup) -> tuple[list, list, list]:
    """Walk all oj-ti-section-1 and oj-ti-art elements in document order."""
    structure = []
    articles = []
    annexes = []
    current_chapter = None

    doc = soup.find("div", id="document1")
    if not doc:
        doc = soup.find("div", class_="eli-container")
    if not doc:
        return structure, articles, annexes

    # Collect all chapter headings and article titles in document order
    markers = doc.find_all("p", class_=["oj-ti-section-1", "oj-ti-art"])

    for marker in markers:
        text = marker.get_text(strip=True)
        classes = marker.get("class", [])

        # Chapter / section heading
        if "oj-ti-section-1" in classes:
            annex_match = _ANNEX_RE.match(text)
            if annex_match:
                # Collect annex text from the parent div
                parent = marker.find_parent("div", class_="eli-subdivision") or marker.parent
                annex_text_parts = [p.get_text(strip=True) for p in parent.find_all("p", class_="oj-normal")]
                annexes.append({
                    "title": text,
                    "source_id": f"annex_{annex_match.group(1) or '1'}",
                    "full_text": "\n".join(annex_text_parts),
                })
                continue

            chapter_num_match = _CHAPTER_NUM_RE.match(text)
            # Look for subtitle sibling
            subtitle = marker.find_next_sibling("p", class_="oj-sti-section-1")
            if not subtitle:
                # Try within same parent
                parent = marker.parent
                if parent:
                    subtitle = parent.find("p", class_="oj-sti-section-1")
            current_chapter = {
                "type": "chapter",
                "number": chapter_num_match.group(1) if chapter_num_match else text,
                "title": subtitle.get_text(strip=True) if subtitle else "",
                "article_ids": [],
            }
            structure.append(current_chapter)
            continue

        # Article title
        if "oj-ti-art" in classes:
            art_match = _ARTICLE_NUM_RE.match(text)
            if not art_match:
                continue
            art_num = art_match.group(1)

            # Find the containing div for this article's content
            art_div = marker.find_parent("div", class_="eli-subdivision") or marker.parent
            subtitle_p = art_div.find("p", class_="oj-sti-art") if art_div else None
            label = subtitle_p.get_text(strip=True) if subtitle_p else ""
            paragraphs = _extract_paragraphs(art_div) if art_div else []
            full_text = _build_full_text(text, label, paragraphs)

            article = {
                "number": art_num,
                "label": label,
                "full_text": full_text,
                "paragraphs": paragraphs,
                "chapter_number": current_chapter["number"] if current_chapter else None,
            }
            articles.append(article)
            if current_chapter:
                current_chapter["article_ids"].append(art_num)

    return structure, articles, annexes


def _extract_paragraphs(article_div: Tag) -> list[dict]:
    paragraphs = []
    current_para = None
    for p in article_div.find_all("p", class_="oj-normal"):
        text = p.get_text(strip=True)
        if not text:
            continue
        para_match = _PARA_NUM_RE.match(text)
        if para_match:
            if current_para:
                paragraphs.append(current_para)
            current_para = {"number": para_match.group(1), "text": text, "subparagraphs": []}
        elif _SUBPARA_RE.match(text) and current_para:
            sub_match = _SUBPARA_RE.match(text)
            current_para["subparagraphs"].append({"label": f"({sub_match.group(1)})", "text": text})
        elif current_para:
            current_para["text"] += " " + text
        else:
            current_para = {"number": "", "text": text, "subparagraphs": []}
    if current_para:
        paragraphs.append(current_para)
    return paragraphs


def _build_full_text(art_title: str, label: str, paragraphs: list[dict]) -> str:
    parts = [art_title]
    if label:
        parts.append(label)
    for para in paragraphs:
        parts.append(para["text"])
        for sub in para["subparagraphs"]:
            parts.append(sub["text"])
    return "\n".join(parts)
