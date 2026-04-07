"""Shared helpers for keeping LawVersion.is_current and KnownVersion.is_current
in sync.

Both the RO version_discovery service and the EU eu_version_discovery service
need the same self-heal logic at the end of every successful run, regardless
of whether new versions were discovered. Keeping the implementation here
prevents the two pipelines from drifting.
"""
from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from app.models.law import KnownVersion, LawVersion

SENTINEL_DATE = datetime.date(1900, 1, 1)


def recalculate_current_version(db: Session, law_id: int) -> None:
    """Set is_current on imported versions based on KnownVersion source of truth.

    Only the imported version whose ver_id matches the KnownVersion that
    upstream considers current gets is_current=True. If that version
    is not imported, no imported version is marked current.

    Also backfills missing date_in_force from KnownVersion data.
    """
    all_known = db.query(KnownVersion).filter(KnownVersion.law_id == law_id).all()
    known_map = {kv.ver_id: kv for kv in all_known}

    current_known = next((kv for kv in all_known if kv.is_current), None)

    all_imported = db.query(LawVersion).filter(LawVersion.law_id == law_id).all()
    for v in all_imported:
        v.is_current = (
            current_known is not None and v.ver_id == current_known.ver_id
        )
        # Backfill missing or sentinel date_in_force from KnownVersion data.
        # The SENTINEL_DATE branch heals rows that were created by the old
        # broken DD.MM.YYYY-unaware parser.
        if v.ver_id in known_map:
            kv_date = known_map[v.ver_id].date_in_force
            if kv_date is not None and kv_date != SENTINEL_DATE and (
                v.date_in_force is None or v.date_in_force == SENTINEL_DATE
            ):
                v.date_in_force = kv_date
