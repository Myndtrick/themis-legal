"""Unit tests for structural_diff — label-based matching with note enrichment."""
from dataclasses import dataclass, field
from typing import Optional

from app.services.structural_diff import (
    AmendmentNoteRef,
    DiffArticleEntry,
    DiffParagraphEntry,
    diff_versions,
)


# Lightweight stand-ins for the SQLAlchemy ORM rows. The matcher only reads
# attributes, never queries the DB, so any object with the right attributes
# works. We use frozen dataclasses to keep the tests pure and deterministic.
@dataclass
class FakeNote:
    id: int = 0
    paragraph_id: Optional[int] = None
    note_source_id: Optional[str] = None
    text: Optional[str] = None
    date: Optional[str] = None
    subject: Optional[str] = None
    law_number: Optional[str] = None
    law_date: Optional[str] = None
    monitor_number: Optional[str] = None
    monitor_date: Optional[str] = None


@dataclass
class FakeParagraph:
    id: int = 0
    label: Optional[str] = None
    text: str = ""
    text_clean: Optional[str] = None
    amendment_notes: list = field(default_factory=list)


@dataclass
class FakeArticle:
    id: int = 0
    label: Optional[str] = None
    article_number: str = ""
    full_text: str = ""
    text_clean: Optional[str] = None
    is_abrogated: bool = False
    paragraphs: list = field(default_factory=list)
    amendment_notes: list = field(default_factory=list)


def _par(label: str, text_clean: str, *, par_id: int = 0, notes=None) -> FakeParagraph:
    return FakeParagraph(
        id=par_id, label=label, text=text_clean, text_clean=text_clean,
        amendment_notes=notes or [],
    )


def _art(
    label: str,
    *,
    text_clean: str | None = None,
    paragraphs: list[FakeParagraph] | None = None,
    notes=None,
    is_abrogated: bool = False,
) -> FakeArticle:
    pars = paragraphs or []
    full = text_clean if text_clean is not None else " ".join(
        (p.text_clean or "") for p in pars
    )
    return FakeArticle(
        id=hash(label) & 0xffff, label=label, article_number=label,
        full_text=full, text_clean=full, is_abrogated=is_abrogated,
        paragraphs=pars, amendment_notes=notes or [],
    )


def test_identical_versions_produce_all_unchanged():
    a = [_art("1", paragraphs=[_par("(1)", "Content of art 1 par 1.")])]
    b = [_art("1", paragraphs=[_par("(1)", "Content of art 1 par 1.")])]
    result = diff_versions(a, b)
    assert len(result) == 1
    entry = result[0]
    assert entry.article_label == "1"
    assert entry.change_type == "unchanged"
    assert entry.renumbered_from is None
    assert entry.notes == []


def test_modified_paragraph_emits_word_level_diff_html():
    a = [_art("336", paragraphs=[_par("(1)", "Operatorul economic plătește accize.")])]
    b = [_art("336", paragraphs=[_par("(1)", "Operatorul economic plătește accize și taxe.")])]
    result = diff_versions(a, b)
    assert len(result) == 1
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 1
    par = art.paragraphs[0]
    assert par.paragraph_label == "(1)"
    assert par.change_type == "modified"
    assert par.text_clean_a == "Operatorul economic plătește accize."
    assert par.text_clean_b == "Operatorul economic plătește accize și taxe."
    assert "<ins>" in par.diff_html
    assert "și taxe" in par.diff_html


def test_paragraph_added_in_b():
    a = [_art("5", paragraphs=[_par("(1)", "First.")])]
    b = [_art("5", paragraphs=[_par("(1)", "First."), _par("(2)", "Second, new.")])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 2
    assert art.paragraphs[0].change_type == "unchanged"
    assert art.paragraphs[1].change_type == "added"
    assert art.paragraphs[1].paragraph_label == "(2)"
    assert art.paragraphs[1].text_clean == "Second, new."


def test_paragraph_removed_in_a():
    a = [_art("5", paragraphs=[_par("(1)", "First."), _par("(2)", "Second, gone.")])]
    b = [_art("5", paragraphs=[_par("(1)", "First.")])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 2
    # B order first, then leftover A entries
    assert art.paragraphs[0].change_type == "unchanged"
    assert art.paragraphs[1].change_type == "removed"
    assert art.paragraphs[1].paragraph_label == "(2)"
    assert art.paragraphs[1].text_clean == "Second, gone."


def test_article_renumbered_pairs_by_text_similarity():
    """Article 23 in A is renumbered to 24 in B with identical content."""
    a = [_art("23", paragraphs=[_par("(1)", "Same content here.")])]
    b = [_art("24", paragraphs=[_par("(1)", "Same content here.")])]
    result = diff_versions(a, b)
    assert len(result) == 1
    art = result[0]
    assert art.article_label == "24"
    assert art.renumbered_from == "23"
    assert art.change_type == "unchanged"


def test_paragraph_renumbered_within_article():
    """Paragraph (1) in A becomes (2) in B with same text."""
    a = [_art("5", paragraphs=[_par("(1)", "Definiții comune.")])]
    b = [_art("5", paragraphs=[
        _par("(0)", "Preamble paragraph."),
        _par("(2)", "Definiții comune."),
    ])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    # B order: (0), (2)
    pars_by_label = {p.paragraph_label: p for p in art.paragraphs}
    assert pars_by_label["(0)"].change_type == "added"
    assert pars_by_label["(2)"].change_type == "unchanged"
    assert pars_by_label["(2)"].renumbered_from == "(1)"


def test_two_paragraphs_share_label_no_over_pairing():
    """When two paragraphs share label '(1)' (pathological case), pair positionally
    within the label bucket — never collapse them onto a single map entry."""
    a = [_art("5", paragraphs=[
        _par("(1)", "First text.", par_id=1),
        _par("(1)", "Second text.", par_id=2),
    ])]
    b = [_art("5", paragraphs=[
        _par("(1)", "First text.", par_id=11),
        _par("(1)", "Second text MODIFIED.", par_id=12),
    ])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 2
    assert art.paragraphs[0].change_type == "unchanged"
    assert art.paragraphs[0].text_clean == "First text."
    assert art.paragraphs[1].change_type == "modified"
    assert art.paragraphs[1].text_clean_a == "Second text."
    assert art.paragraphs[1].text_clean_b == "Second text MODIFIED."


def test_inline_annotation_does_not_affect_state():
    """If text_clean is identical between A and B, the paragraph is unchanged
    regardless of what's in raw .text. The (la …) annotation lives only in
    .text and never in .text_clean."""
    par_a = FakeParagraph(
        id=1, label="(1)",
        text="Operatorul plătește accize.",
        text_clean="Operatorul plătește accize.",
    )
    par_b = FakeParagraph(
        id=2, label="(1)",
        text="Operatorul plătește accize. (la 31-03-2026, … a fost modificat de OUG nr. 89/2025)",
        text_clean="Operatorul plătește accize.",
    )
    a = [_art("336", paragraphs=[par_a])]
    b = [_art("336", paragraphs=[par_b])]
    result = diff_versions(a, b)
    art = result[0]
    # Article-level text_clean is identical → article unchanged, no paragraph walk
    assert art.change_type == "unchanged"


def test_amendment_note_surfaces_as_enrichment_on_modified_paragraph():
    par_a = _par("(1)", "Old text.", par_id=1)
    par_b = _par(
        "(1)", "New text.", par_id=2,
        notes=[FakeNote(
            id=10, paragraph_id=2, note_source_id="src-1",
            date="31-03-2026", subject="Alineatul (1) al articolului 336",
            law_number="89", law_date="23-12-2025",
            monitor_number="1203", monitor_date="24-12-2025",
        )],
    )
    a = [_art("336", paragraphs=[par_a])]
    b = [_art("336", paragraphs=[par_b])]
    result = diff_versions(a, b)
    art = result[0]
    par = art.paragraphs[0]
    assert par.change_type == "modified"
    assert len(par.notes) == 1
    note = par.notes[0]
    assert note.date == "31-03-2026"
    assert note.law_number == "89"
    assert note.monitor_number == "1203"


def test_abrogated_article_renders_as_modified():
    """An article that becomes 'Abrogat.' in B is a normal modified pair."""
    a = [_art("99", paragraphs=[_par("(1)", "Once a real article.")])]
    b = [_art("99", text_clean="Abrogat.", paragraphs=[], is_abrogated=True)]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    # B has no paragraphs → synthetic paragraph fallback
    assert len(art.paragraphs) == 1
    par = art.paragraphs[0]
    assert par.paragraph_label is None
    assert par.change_type == "modified"
    assert par.text_clean_a == "Once a real article."
    assert par.text_clean_b == "Abrogat."
    assert "Abrogat" in par.diff_html


def test_null_text_clean_falls_back_to_raw_text():
    """If text_clean is None, _clean() falls back to .text/.full_text without crashing."""
    par_a = FakeParagraph(id=1, label="(1)", text="Real text.", text_clean=None)
    par_b = FakeParagraph(id=2, label="(1)", text="Real text modified.", text_clean=None)
    art_a_obj = FakeArticle(label="1", article_number="1", full_text="Real text.", text_clean="Real text.", paragraphs=[par_a])
    art_b_obj = FakeArticle(label="1", article_number="1", full_text="Real text modified.", text_clean="Real text modified.", paragraphs=[par_b])
    a = [art_a_obj]
    b = [art_b_obj]
    result = diff_versions(a, b)
    art = result[0]
    par = art.paragraphs[0]
    assert par.change_type == "modified"
    assert par.text_clean_a == "Real text."
    assert par.text_clean_b == "Real text modified."


def test_article_with_no_paragraphs_uses_synthetic_paragraph_diff():
    """When neither side has paragraph rows, the matcher emits one synthetic
    paragraph entry holding the whole article body."""
    a = [_art("7", text_clean="Old article body.", paragraphs=[])]
    b = [_art("7", text_clean="New article body.", paragraphs=[])]
    result = diff_versions(a, b)
    art = result[0]
    assert art.change_type == "modified"
    assert len(art.paragraphs) == 1
    par = art.paragraphs[0]
    assert par.paragraph_label is None
    assert par.change_type == "modified"
    assert par.text_clean_a == "Old article body."
    assert par.text_clean_b == "New article body."
    assert "<ins>" in par.diff_html


def test_article_added_in_b():
    a: list = []
    b = [_art("1", paragraphs=[_par("(1)", "Brand new article.")])]
    result = diff_versions(a, b)
    assert len(result) == 1
    art = result[0]
    assert art.change_type == "added"
    assert art.text_clean == "Brand new article."


def test_article_removed_in_a():
    a = [_art("1", paragraphs=[_par("(1)", "About to be removed.")])]
    b: list = []
    result = diff_versions(a, b)
    assert len(result) == 1
    art = result[0]
    assert art.change_type == "removed"
    assert art.text_clean == "About to be removed."


def test_article_level_note_surfaces_in_response():
    """Notes with paragraph_id IS NULL belong on the article entry."""
    art_b = _art(
        "1", paragraphs=[_par("(1)", "Body.")],
        notes=[FakeNote(
            id=10, paragraph_id=None, note_source_id="art-1",
            date="01-01-2024", subject="Articolul 1",
            law_number="5", law_date="01-01-2023",
        )],
    )
    a = [_art("1", paragraphs=[_par("(1)", "Body.")])]
    b = [art_b]
    result = diff_versions(a, b)
    art = result[0]
    # Article-level notes survive even when the article itself is unchanged
    assert art.change_type == "unchanged"
    assert len(art.notes) == 1
    assert art.notes[0].law_number == "5"
