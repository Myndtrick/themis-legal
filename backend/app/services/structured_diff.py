"""Backwards-compatible shim around structural_diff.

The router (`backend/app/routers/laws.py`) imports `diff_articles` from this
module. Spec 2 replaced the matching algorithm with structural_diff.diff_versions,
but we keep this entry point so the router doesn't change.

The shim's job is to:
  1. Call structural_diff.diff_versions() with the SQLAlchemy Article rows
  2. Convert the returned dataclass tree into plain dicts for JSON serialization

It is intentionally trivial. All real work lives in structural_diff.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.services.structural_diff import (
    DiffArticleEntry,
    diff_versions,
)


def diff_articles(articles_a, articles_b) -> list[dict[str, Any]]:
    """Return the diff as a list of plain dicts (one per article).

    Each dict has the shape produced by `dataclasses.asdict(DiffArticleEntry)`,
    with `paragraphs` nested as a list of dicts and `notes` as a list of dicts.
    """
    entries: list[DiffArticleEntry] = diff_versions(articles_a, articles_b)
    return [asdict(e) for e in entries]
