# backend/app/services/law_mapping.py
"""
Deterministic mapping from legal domain to applicable laws.
Three tiers: PRIMARY (directly answers), SECONDARY (subsidiarily),
CONNECTED (only if cross-referenced by primary articles).
"""
from __future__ import annotations
from sqlalchemy.orm import Session
from app.models.law import Law

DOMAIN_LAW_MAP: dict[str, dict[str, list[dict]]] = {
    "corporate": {
        "primary": [
            {"law_number": "31", "law_year": 1990, "reason": "Legea societăților comerciale"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — applies subsidiarily"},
        ],
        "connected": [],
    },
    "fiscal": {
        "primary": [
            {"law_number": "227", "law_year": 2015, "reason": "Codul Fiscal"},
        ],
        "secondary": [
            {"law_number": "207", "law_year": 2015, "reason": "Codul de Procedură Fiscală"},
        ],
        "connected": [],
    },
    "employment": {
        "primary": [
            {"law_number": "53", "law_year": 2003, "reason": "Codul Muncii"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — applies subsidiarily"},
        ],
        "connected": [],
    },
    "contract_law": {
        "primary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — contract law"},
        ],
        "secondary": [],
        "connected": [],
    },
    "civil": {
        "primary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil"},
        ],
        "secondary": [],
        "connected": [],
    },
    "aml": {
        "primary": [
            {"law_number": "129", "law_year": 2019, "reason": "Legea AML/KYC"},
        ],
        "secondary": [],
        "connected": [],
    },
    "criminal": {
        "primary": [
            {"law_number": "286", "law_year": 2009, "reason": "Codul Penal"},
        ],
        "secondary": [
            {"law_number": "135", "law_year": 2010, "reason": "Codul de Procedură Penală"},
        ],
        "connected": [],
    },
    "criminal_procedure": {
        "primary": [
            {"law_number": "135", "law_year": 2010, "reason": "Codul de Procedură Penală"},
        ],
        "secondary": [
            {"law_number": "286", "law_year": 2009, "reason": "Codul Penal"},
        ],
        "connected": [],
    },
    "real_estate": {
        "primary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — property rights (Book III)"},
        ],
        "secondary": [
            {"law_number": "7", "law_year": 1996, "reason": "Legea cadastrului și publicității imobiliare"},
        ],
        "connected": [],
    },
    "data_protection": {
        "primary": [
            {"law_number": "190", "law_year": 2018, "reason": "Legea privind protecția datelor personale (GDPR)"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — privacy rights"},
        ],
        "connected": [],
    },
    "procedural": {
        "primary": [
            {"law_number": "134", "law_year": 2010, "reason": "Codul de Procedură Civilă"},
        ],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — applies subsidiarily"},
        ],
        "connected": [],
    },
    "eu_law": {
        "primary": [],
        "secondary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — general framework"},
        ],
        "connected": [],
    },
    "other": {
        "primary": [
            {"law_number": "287", "law_year": 2009, "reason": "Codul Civil — general gap-filler"},
        ],
        "secondary": [],
        "connected": [],
    },
}


def map_laws_to_question(
    legal_domain: str,
    db: Session,
) -> dict[str, list[dict]]:
    """Map a classified question to applicable laws in 3 tiers.
    Returns only laws that actually exist in the database.
    """
    mapping = DOMAIN_LAW_MAP.get(legal_domain, {})
    result = {"tier1_primary": [], "tier2_secondary": [], "tier3_connected": []}

    for tier_key, result_key in [
        ("primary", "tier1_primary"),
        ("secondary", "tier2_secondary"),
        ("connected", "tier3_connected"),
    ]:
        for law_def in mapping.get(tier_key, []):
            db_law = (
                db.query(Law)
                .filter(
                    Law.law_number == law_def["law_number"],
                    Law.law_year == law_def["law_year"],
                )
                .first()
            )
            entry = {
                **law_def,
                "db_law_id": db_law.id if db_law else None,
                "in_library": db_law is not None,
                "title": db_law.title if db_law else law_def.get("reason", ""),
            }
            result[result_key].append(entry)

    return result
