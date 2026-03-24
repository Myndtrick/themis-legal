# backend/app/services/law_mapping.py
"""
Check identified laws against the database for availability and version status.
"""
from __future__ import annotations
from datetime import date as date_type
from sqlalchemy.orm import Session
from app.models.law import Law, LawVersion


def check_laws_in_db(
    laws: list[dict],
    db: Session,
    primary_date: str | None = None,
) -> list[dict]:
    """Enrich each law dict with DB availability and version status.

    Returns the same list with added fields:
    - db_law_id: int or None
    - in_library: bool
    - availability: "available" | "wrong_version" | "missing"
    - available_version_date: str or None (the version date actually found)
    """
    for law in laws:
        law_number = str(law["law_number"])
        law_year = str(law["law_year"])

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

        # Check if the correct version exists
        if primary_date:
            pd = date_type.fromisoformat(primary_date)
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

    return laws
