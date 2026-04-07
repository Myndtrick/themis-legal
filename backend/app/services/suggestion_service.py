"""User-editable suggestion list orchestration.

Turns a public source URL (legislatie.just.ro for RO laws,
eur-lex.europa.eu for EU laws) into a draft `LawMapping` row with
`source='user'`. Title is auto-fetched from the upstream document
unless the caller provides one. The function is idempotent: posting
the same URL twice returns the existing mapping.

Also exposes `fork_to_user_if_needed`, the single helper every edit
endpoint should call so that mutating a system-managed mapping flips
its source to 'user' (forking it from the seed list).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.category import LawMapping
from app.services.eu_cellar_service import fetch_eu_metadata
from app.services.fetcher import fetch_document
from app.services.source_url import probe_url


def create_user_mapping_from_url(
    db: Session,
    *,
    url: str,
    category_id: int,
    title: str | None = None,
) -> LawMapping:
    """Create (or return) a user-source LawMapping for the given URL.

    Steps:
      1. Idempotency: if a row already exists with the same `source_url`,
         return it without contacting upstream.
      2. Parse the URL via `probe_url`. Reject unknown hosts and
         missing identifiers with `ValueError`.
      3. If no title was supplied, fetch the upstream metadata for that
         identifier (legislatie.just.ro for RO, EU Cellar for EU).
      4. Insert and commit.
    """
    existing = (
        db.query(LawMapping)
        .filter(LawMapping.source_url == url)
        .first()
    )
    if existing is not None:
        return existing

    probe = probe_url(url)
    if probe["kind"] == "unknown":
        raise ValueError(f"Unsupported URL host: {url!r}")
    if not probe["identifier"]:
        raise ValueError(f"Could not extract identifier from URL: {url!r}")

    kind = probe["kind"]
    identifier = probe["identifier"]

    resolved_title = title
    source_ver_id: str | None = None
    celex_number: str | None = None

    if kind == "ro":
        source_ver_id = identifier
        if resolved_title is None:
            doc = fetch_document(identifier)
            resolved_title = (doc.get("document") or {}).get("title")
    elif kind == "eu":
        celex_number = identifier
        if resolved_title is None:
            meta = fetch_eu_metadata(identifier)
            resolved_title = (meta or {}).get("title")

    if not resolved_title:
        raise ValueError(
            f"Could not determine title for {url!r} — please provide one explicitly"
        )

    mapping = LawMapping(
        title=resolved_title,
        category_id=category_id,
        source="user",
        source_url=url,
        source_ver_id=source_ver_id,
        celex_number=celex_number,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def fork_to_user_if_needed(mapping: LawMapping) -> None:
    """Flip a system-managed mapping to user-managed.

    Call this from any endpoint that mutates a LawMapping. After this
    runs, the next seed push will leave the row alone (because the
    seed code only touches `source='system'` rows).
    """
    if mapping.source == "system":
        mapping.source = "user"
