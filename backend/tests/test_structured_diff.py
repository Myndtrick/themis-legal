"""Tests for structured version diff service."""
from app.services.structured_diff import word_diff_html


def test_word_diff_html_marks_replacement():
    a = "pensiile facultative din fonduri"
    b = "pensiile ocupaționale din fonduri"
    html = word_diff_html(a, b)
    assert "<del>facultative</del>" in html
    assert "<ins>ocupaționale</ins>" in html
    assert "pensiile" in html
    assert "fonduri" in html


def test_word_diff_html_identical_returns_plain():
    text = "același text neschimbat"
    assert word_diff_html(text, text) == text


def test_word_diff_html_pure_insertion():
    html = word_diff_html("a b", "a b c d")
    assert html == "a b <ins>c d</ins>"


def test_word_diff_html_pure_deletion():
    html = word_diff_html("a b c d", "a b")
    assert html == "a b <del>c d</del>"


from dataclasses import dataclass, field
from app.services.structured_diff import diff_paragraph


@dataclass
class FakeSub:
    label: str | None
    text: str
    order_index: int = 0


@dataclass
class FakePara:
    label: str | None
    text: str
    order_index: int = 0
    subparagraphs: list[FakeSub] = field(default_factory=list)


def test_diff_paragraph_unchanged_subparagraph():
    a = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "lit a text")])
    b = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "lit a text")])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "unchanged"
    assert result["subparagraphs"][0]["change_type"] == "unchanged"
    assert "text_a" not in result["subparagraphs"][0]
    assert "text_b" not in result["subparagraphs"][0]


def test_diff_paragraph_modified_subparagraph_carries_diff_html():
    a = FakePara(label="(1)", text="", subparagraphs=[FakeSub("k)", "fonduri facultative")])
    b = FakePara(label="(1)", text="", subparagraphs=[FakeSub("k)", "fonduri ocupaționale")])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "modified"
    leaf = result["subparagraphs"][0]
    assert leaf["change_type"] == "modified"
    assert leaf["text_a"] == "fonduri facultative"
    assert leaf["text_b"] == "fonduri ocupaționale"
    assert "<del>facultative</del>" in leaf["diff_html"]
    assert "<ins>ocupaționale</ins>" in leaf["diff_html"]


def test_diff_paragraph_added_subparagraph():
    a = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "x")])
    b = FakePara(label="(1)", text="", subparagraphs=[
        FakeSub("a)", "x"),
        FakeSub("b)", "brand new"),
    ])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "modified"
    labels = [s["label"] for s in result["subparagraphs"]]
    assert labels == ["a)", "b)"]
    assert result["subparagraphs"][1]["change_type"] == "added"
    assert result["subparagraphs"][1]["text_b"] == "brand new"
    assert "text_a" not in result["subparagraphs"][1]


def test_diff_paragraph_removed_subparagraph():
    a = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "x"), FakeSub("b)", "old")])
    b = FakePara(label="(1)", text="", subparagraphs=[FakeSub("a)", "x")])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "modified"
    removed = [s for s in result["subparagraphs"] if s["change_type"] == "removed"]
    assert len(removed) == 1
    assert removed[0]["label"] == "b)"
    assert removed[0]["text_a"] == "old"


def test_diff_paragraph_intro_text_modified():
    """Paragraph itself has an intro line above its subparagraphs."""
    a = FakePara(label="(5)", text="Intro vechi:", subparagraphs=[FakeSub("a)", "x")])
    b = FakePara(label="(5)", text="Intro nou:", subparagraphs=[FakeSub("a)", "x")])
    result = diff_paragraph(a, b)
    assert result["change_type"] == "modified"
    assert result["text_a"] == "Intro vechi:"
    assert result["text_b"] == "Intro nou:"
    assert "<del>vechi:</del>" in result["diff_html"]


from app.services.structured_diff import diff_article


@dataclass
class FakeArt:
    article_number: str
    full_text: str
    label: str | None = None
    paragraphs: list[FakePara] = field(default_factory=list)


def test_diff_article_unchanged():
    a = FakeArt("62", "same", paragraphs=[FakePara("(1)", "", subparagraphs=[FakeSub("a)", "x")])])
    b = FakeArt("62", "same", paragraphs=[FakePara("(1)", "", subparagraphs=[FakeSub("a)", "x")])])
    result = diff_article(a, b)
    assert result["change_type"] == "unchanged"


def test_diff_article_modified_in_one_litera():
    a = FakeArt("62", "x", paragraphs=[FakePara("(1)", "", subparagraphs=[
        FakeSub("a)", "alpha"),
        FakeSub("k)", "fonduri facultative"),
    ])])
    b = FakeArt("62", "x", paragraphs=[FakePara("(1)", "", subparagraphs=[
        FakeSub("a)", "alpha"),
        FakeSub("k)", "fonduri ocupaționale"),
    ])])
    result = diff_article(a, b)
    assert result["article_number"] == "62"
    assert result["change_type"] == "modified"
    assert len(result["paragraphs"]) == 1
    para = result["paragraphs"][0]
    assert para["label"] == "(1)"
    assert para["change_type"] == "modified"
    leaves = para["subparagraphs"]
    assert leaves[0]["change_type"] == "unchanged"
    assert leaves[1]["change_type"] == "modified"
    assert "<ins>ocupaționale</ins>" in leaves[1]["diff_html"]


def test_diff_article_added_paragraph():
    a = FakeArt("76", "x", paragraphs=[FakePara("(1)", "intro")])
    b = FakeArt("76", "x", paragraphs=[
        FakePara("(1)", "intro"),
        FakePara("(4^1)", "noul alineat"),
    ])
    result = diff_article(a, b)
    assert result["change_type"] == "modified"
    labels = [p["label"] for p in result["paragraphs"]]
    assert labels == ["(1)", "(4^1)"]
    assert result["paragraphs"][1]["change_type"] == "added"
    assert result["paragraphs"][1]["text_b"] == "noul alineat"


from app.services.structured_diff import diff_articles


def _art(num: str, text: str = "", paras: list[FakePara] | None = None) -> FakeArt:
    return FakeArt(article_number=num, full_text=text, paragraphs=paras or [])


def test_diff_articles_pure_add_and_remove():
    a = [_art("1", "a"), _art("2", "b")]
    b = [_art("1", "a"), _art("3", "c")]  # 2 removed, 3 added — texts unrelated
    changes = diff_articles(a, b)
    types = {c["article_number"]: c["change_type"] for c in changes}
    assert types == {"2": "removed", "3": "added"}


def test_diff_articles_renumbering_pair_threshold():
    """Article 73 was renumbered to 74; same body. Should pair as one modified."""
    body = "lorem ipsum dolor sit amet consectetur adipiscing elit"
    a = [_art("73", body)]
    b = [_art("74", body)]
    changes = diff_articles(a, b)
    assert len(changes) == 1
    c = changes[0]
    assert c["change_type"] == "modified"
    assert c["article_number"] == "74"
    assert c["renumbered_from"] == "73"


def test_diff_articles_unrelated_texts_do_not_pair():
    a = [_art("5", "complete unrelated text about taxes")]
    b = [_art("6", "totally different content about pensions and stuff")]
    changes = diff_articles(a, b)
    types = sorted(c["change_type"] for c in changes)
    assert types == ["added", "removed"]


def test_diff_articles_unchanged_articles_excluded():
    a = [_art("1", "same", paras=[FakePara("(1)", "intro", subparagraphs=[FakeSub("a)", "x")])]),
         _art("2", "different", paras=[FakePara("(1)", "intro", subparagraphs=[FakeSub("a)", "y")])])]
    b = [_art("1", "same", paras=[FakePara("(1)", "intro", subparagraphs=[FakeSub("a)", "x")])]),
         _art("2", "different changed", paras=[FakePara("(1)", "intro", subparagraphs=[FakeSub("a)", "z")])])]
    changes = diff_articles(a, b)
    nums = [c["article_number"] for c in changes]
    assert "1" not in nums  # unchanged article excluded
    assert "2" in nums
