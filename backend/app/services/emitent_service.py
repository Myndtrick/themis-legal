"""Emitent (issuer) autocomplete service."""

PINNED_EMITENTS = [
    "Parlamentul României",
    "Guvernul României",
    "Ministerul Finanțelor",
    "Banca Națională a României (BNR)",
    "Autoritatea de Supraveghere Financiară (ASF)",
    "ANAF",
    "Ministerul Justiției",
    "Oficiul Național de Prevenire și Combatere a Spălării Banilor (ONPCSB)",
    "Comisia Europeană / Parlamentul European",
]


def search_emitents(query: str) -> list[str]:
    """Return emitents matching the query.

    Filters the pinned list by case-insensitive partial match.
    Returns all pinned emitents if query is empty.
    """
    if not query or len(query) < 2:
        return PINNED_EMITENTS

    q_lower = query.lower()
    return [e for e in PINNED_EMITENTS if q_lower in e.lower()]
