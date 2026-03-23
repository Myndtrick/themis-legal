import datetime
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.database import Base


class DocumentType(str, enum.Enum):
    CODE = "code"
    LAW = "law"
    GOVERNMENT_ORDINANCE = "government_ordinance"
    GOVERNMENT_RESOLUTION = "government_resolution"
    DECREE = "decree"
    ORDER = "order"
    RESOLUTION = "resolution"
    REGULATION = "regulation"
    PROCEDURE = "procedure"
    NORM = "norm"
    DECISION = "decision"
    OTHER = "other"


class DocumentState(str, enum.Enum):
    ACTUAL = "actual"
    REPUBLISHED = "republished"
    AMENDED = "amended"
    DEPRECATED = "deprecated"


class StructuralElementType(str, enum.Enum):
    BOOK = "book"
    TITLE = "title"
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"


class Law(Base):
    __tablename__ = "laws"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    law_number: Mapped[str] = mapped_column(String(50), nullable=False)
    law_year: Mapped[int] = mapped_column(Integer, nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(50), default=DocumentType.LAW.value
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    versions: Mapped[list["LawVersion"]] = relationship(
        back_populates="law", cascade="all, delete-orphan"
    )


class LawVersion(Base):
    __tablename__ = "law_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_id: Mapped[int] = mapped_column(ForeignKey("laws.id"), nullable=False)
    ver_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    date_in_force: Mapped[datetime.date | None] = mapped_column(nullable=True)
    date_imported: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    state: Mapped[str] = mapped_column(
        String(50), default=DocumentState.ACTUAL.value
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)

    law: Mapped["Law"] = relationship(back_populates="versions")
    structural_elements: Mapped[list["StructuralElement"]] = relationship(
        back_populates="law_version", cascade="all, delete-orphan"
    )
    articles: Mapped[list["Article"]] = relationship(
        back_populates="law_version", cascade="all, delete-orphan"
    )


class StructuralElement(Base):
    __tablename__ = "structural_elements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_version_id: Mapped[int] = mapped_column(
        ForeignKey("law_versions.id"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("structural_elements.id"), nullable=True
    )
    element_type: Mapped[str] = mapped_column(String(50), nullable=False)
    number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    law_version: Mapped["LawVersion"] = relationship(
        back_populates="structural_elements"
    )
    parent: Mapped["StructuralElement | None"] = relationship(
        remote_side="StructuralElement.id", backref="children"
    )
    articles: Mapped[list["Article"]] = relationship(
        back_populates="structural_element"
    )


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    law_version_id: Mapped[int] = mapped_column(
        ForeignKey("law_versions.id"), nullable=False
    )
    structural_element_id: Mapped[int | None] = mapped_column(
        ForeignKey("structural_elements.id"), nullable=True
    )
    article_number: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    law_version: Mapped["LawVersion"] = relationship(back_populates="articles")
    structural_element: Mapped["StructuralElement | None"] = relationship(
        back_populates="articles"
    )
    paragraphs: Mapped[list["Paragraph"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    amendment_notes: Mapped[list["AmendmentNote"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )


class Paragraph(Base):
    __tablename__ = "paragraphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), nullable=False
    )
    paragraph_number: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    article: Mapped["Article"] = relationship(back_populates="paragraphs")
    subparagraphs: Mapped[list["Subparagraph"]] = relationship(
        back_populates="paragraph", cascade="all, delete-orphan"
    )


class Subparagraph(Base):
    __tablename__ = "subparagraphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paragraph_id: Mapped[int] = mapped_column(
        ForeignKey("paragraphs.id"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    paragraph: Mapped["Paragraph"] = relationship(back_populates="subparagraphs")


class AmendmentNote(Base):
    __tablename__ = "amendment_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id"), nullable=False
    )
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    law_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    law_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    monitor_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    monitor_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    replacement_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    article: Mapped["Article"] = relationship(back_populates="amendment_notes")
