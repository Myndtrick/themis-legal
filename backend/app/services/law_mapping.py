# backend/app/services/law_mapping.py
"""
Check identified laws against the database for availability and version status.
"""
from __future__ import annotations
from datetime import date as date_type
from sqlalchemy.orm import Session
from app.models.law import KnownVersion, Law, LawVersion


def check_laws_in_db(
    laws: list[dict],
    db: Session,
    law_date_map: dict[str, list[str] | str] | None = None,
) -> list[dict]:
    """Enrich each law dict with DB availability and version status.

    Args:
        laws: List of law dicts from the classifier (with law_number, law_year).
        db: Database session.
        law_date_map: Optional dict mapping "law_number/law_year" to a list of ISO date
                      strings (or a single string for backward compat).
                      Each law is checked against its max (most demanding) date.

    Returns the same list with added fields:
    - db_law_id: int or None
    - in_library: bool
    - availability: "available" | "wrong_version" | "missing"
    - available_version_date: str or None (the version date actually found)
    """
    for law in laws:
        law_number = str(law["law_number"])
        law_year = str(law["law_year"])
        law_key = f"{law_number}/{law_year}"

        db_law = (
            db.query(Law)
            .filter(
                Law.law_number == law_number,
                Law.law_year == int(law_year),
            )
            .first()
        )

        if not db_law:
            law["db_law_id"] = None
            law["in_library"] = False
            law["availability"] = "missing"
            law["available_version_date"] = None
            continue

        law["db_law_id"] = db_law.id
        law["in_library"] = True
        law["title"] = law.get("title") or db_law.title

        # Look up the relevant date for this specific law (max date = most demanding)
        raw_dates = law_date_map.get(law_key) if law_date_map else None
        if isinstance(raw_dates, (list, set)):
            relevant_date = max(raw_dates) if raw_dates else None
        elif isinstance(raw_dates, str):
            relevant_date = raw_dates  # backward compat: old single-date format
        else:
            relevant_date = None

        if relevant_date:
            pd = date_type.fromisoformat(relevant_date)
            version = (
                db.query(LawVersion)
                .filter(
                    LawVersion.law_id == db_law.id,
                    LawVersion.date_in_force <= pd,
                )
                .order_by(LawVersion.date_in_force.desc())
                .first()
            )
            if version:
                law["availability"] = "available"
                law["available_version_date"] = str(version.date_in_force)
            else:
                # No version for this date — check if any version exists
                any_version = (
                    db.query(LawVersion)
                    .filter(LawVersion.law_id == db_law.id)
                    .first()
                )
                if any_version:
                    law["availability"] = "wrong_version"
                    law["available_version_date"] = str(any_version.date_in_force)
                else:
                    law["availability"] = "missing"
                    law["available_version_date"] = None
        else:
            # No date specified — just check if law has any version
            any_version = (
                db.query(LawVersion)
                .filter(LawVersion.law_id == db_law.id)
                .first()
            )
            law["availability"] = "available" if any_version else "missing"
            law["available_version_date"] = str(any_version.date_in_force) if any_version else None

    # --- Version status check (uses KnownVersion) ---
    for law in laws:
        if not law.get("db_law_id"):
            law["version_status"] = "not_checked"
            continue

        known_current = (
            db.query(KnownVersion)
            .filter(
                KnownVersion.law_id == law["db_law_id"],
                KnownVersion.is_current == True,
            )
            .first()
        )

        if known_current is None:
            law["version_status"] = "not_checked"
        else:
            imported = (
                db.query(LawVersion)
                .filter(
                    LawVersion.law_id == law["db_law_id"],
                    LawVersion.ver_id == known_current.ver_id,
                )
                .first()
            )
            if imported:
                law["version_status"] = "up_to_date"
            else:
                law["version_status"] = "stale"
                law["official_current_ver_id"] = known_current.ver_id
                law["official_current_date"] = str(known_current.date_in_force)

    return laws
