from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
import datetime

from app.database import Base


class CategoryGroup(Base):
    __tablename__ = "category_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name_ro: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    color_hex: Mapped[str] = mapped_column(String(10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    categories: Mapped[list["Category"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("category_groups.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name_ro: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_eu: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    group: Mapped["CategoryGroup"] = relationship(back_populates="categories")
    laws: Mapped[list["Law"]] = relationship(back_populates="category")


class LawMapping(Base):
    __tablename__ = "law_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    law_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    law_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    celex_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ver_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="user")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

    category: Mapped["Category"] = relationship()
