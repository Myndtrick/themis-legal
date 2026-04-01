"""Weekly version discovery for EU legislation."""
import logging
import time
import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.law import Law, KnownVersion
from app.services.eu_cellar_service import fetch_consolidated_versions, parse_celex

logger = logging.getLogger(__name__)


def discover_eu_versions_for_law(db: Session, law: Law) -> int:
    """Discover new consolidated versions for a single EU law. Returns count of new versions."""
    if not law.celex_number:
        return 0

    consol_versions = fetch_consolidated_versions(law.celex_number)
    if not consol_versions:
        return 0

    new_count = 0
    existing_ver_ids = {kv.ver_id for kv in db.query(KnownVersion).filter_by(law_id=law.id).all()}

    for cv in consol_versions:
        celex = cv["celex"]
        if celex in existing_ver_ids:
            continue

        date_in_force = None
        if cv.get("date"):
            try:
                date_in_force = datetime.date.fromisoformat(cv["date"][:10])
            except ValueError:
                date_in_force = datetime.date(1900, 1, 1)

        if date_in_force is None:
            parsed = parse_celex(celex)
            if parsed and "consol_date" in parsed:
                ds = parsed["consol_date"]
                try:
                    date_in_force = datetime.date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
                except ValueError:
                    date_in_force = datetime.date(1900, 1, 1)

        if date_in_force is None:
            date_in_force = datetime.date(1900, 1, 1)

        kv = KnownVersion(
            law_id=law.id, ver_id=celex, date_in_force=date_in_force,
            is_current=False, discovered_at=datetime.datetime.utcnow(),
        )
        db.add(kv)
        new_count += 1

    if new_count:
        all_known = db.query(KnownVersion).filter_by(law_id=law.id).order_by(KnownVersion.date_in_force.desc()).all()
        for i, kv in enumerate(all_known):
            kv.is_current = (i == 0)
        law.last_checked_at = datetime.datetime.utcnow()
        db.commit()

    return new_count


def run_eu_weekly_discovery(rate_limit_delay: float = 2.0) -> dict:
    """Run version discovery for all EU laws. Called by scheduler."""
    db = SessionLocal()
    try:
        eu_laws = db.query(Law).filter(Law.source == "eu").all()
        checked = 0
        discovered = 0
        errors = 0

        for law in eu_laws:
            try:
                new = discover_eu_versions_for_law(db, law)
                discovered += new
                checked += 1
                if rate_limit_delay:
                    time.sleep(rate_limit_delay)
            except Exception as e:
                logger.error(f"EU version discovery failed for law {law.id} ({law.celex_number}): {e}")
                errors += 1
                db.rollback()

        logger.info(f"EU weekly discovery: checked={checked}, discovered={discovered}, errors={errors}")
        return {"checked": checked, "discovered": discovered, "errors": errors}
    finally:
        db.close()
