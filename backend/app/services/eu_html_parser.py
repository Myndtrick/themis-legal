"""Parse EUR-Lex XHTML into structured articles, chapters, and annexes."""
import re
import logging
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_PARA_NUM_RE = re.compile(r"^(\d+)\.\s+")
_SUBPARA_RE = re.compile(r"^\(([a-z])\)\s*")
_ARTICLE_NUM_RE = re.compile(r"Article\s+(\d+[a-z]?)", re.IGNORECASE)
_CHAPTER_NUM_RE = re.compile(r"CHAPTER\s+([IVXLCDM]+)", re.IGNORECASE)
_ANNEX_RE = re.compile(r"ANNEX\s*([IVXLCDM]*)", re.IGNORECASE)


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
    structure = []
    articles = []
    annexes = []
    current_chapter = None

    doc = soup.find("div", id="document1")
    if not doc:
        return structure, articles, annexes

    for element in doc.children:
        if not isinstance(element, Tag):
            continue

        chapter_title_p = element.find("p", class_="oj-ti-section-1")
        if chapter_title_p and not element.find("p", class_="oj-ti-art"):
            chapter_text = chapter_title_p.get_text(strip=True)
            annex_match = _ANNEX_RE.match(chapter_text)
            if annex_match:
                annex_text_parts = []
                for p in element.find_all("p", class_="oj-normal"):
                    annex_text_parts.append(p.get_text(strip=True))
                annexes.append({
                    "title": chapter_text,
                    "source_id": f"annex_{annex_match.group(1) or '1'}",
                    "full_text": "\n".join(annex_text_parts),
                })
                continue

            chapter_num_match = _CHAPTER_NUM_RE.match(chapter_text)
            subtitle_p = element.find("p", class_="oj-sti-section-1")
            current_chapter = {
                "type": "chapter",
                "number": chapter_num_match.group(1) if chapter_num_match else chapter_text,
                "title": subtitle_p.get_text(strip=True) if subtitle_p else "",
                "article_ids": [],
            }
            structure.append(current_chapter)
            continue

        art_title_p = element.find("p", class_="oj-ti-art")
        if art_title_p:
            art_text = art_title_p.get_text(strip=True)
            art_match = _ARTICLE_NUM_RE.match(art_text)
            if not art_match:
                continue
            art_num = art_match.group(1)
            subtitle_p = element.find("p", class_="oj-sti-art")
            label = subtitle_p.get_text(strip=True) if subtitle_p else ""
            paragraphs = _extract_paragraphs(element)
            full_text = _build_full_text(art_text, label, paragraphs)
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

    for div in doc.find_all("div", class_="eli-subdivision"):
        div_id = div.get("id", "")
        if div_id.startswith("anx_"):
            title_p = div.find("p", class_="oj-ti-section-1")
            if title_p and _ANNEX_RE.match(title_p.get_text(strip=True)):
                annex_title = title_p.get_text(strip=True)
                if any(a["title"] == annex_title for a in annexes):
                    continue
                text_parts = [p.get_text(strip=True) for p in div.find_all("p", class_="oj-normal")]
                annex_match = _ANNEX_RE.match(annex_title)
                annexes.append({
                    "title": annex_title,
                    "source_id": f"annex_{annex_match.group(1) if annex_match else '1'}",
                    "full_text": "\n".join(text_parts),
                })

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
