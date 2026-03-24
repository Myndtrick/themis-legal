"""Maps common Romanian legal abbreviations and popular names to search terms.

The legislatie.just.ro search engine is literal — it only matches exact words
in titles. Romanians commonly refer to laws by abbreviations (PFA, SRL, GDPR)
or popular names ("legea spalarii banilor") which don't appear in official titles.

This module expands those terms so the search actually finds what users mean.
"""

# Maps abbreviation/popular name -> (title keywords, doc_type, doc_number)
# doc_type: "1"=LEGE, "2"=HG, "18"=OUG, etc. Empty = any type.
# doc_number: "NUMBER-YEAR" format. Empty = search by title.
ALIASES: dict[str, list[dict]] = {
    # Common abbreviations
    "pfa": [
        {"title": "activitati economice persoane fizice autorizate", "type": "18", "number": "44-2008"},
    ],
    "srl": [
        {"title": "societatile comerciale", "type": "1", "number": "31-1990"},
    ],
    "sa": [
        {"title": "societatile comerciale", "type": "1", "number": "31-1990"},
    ],
    "gdpr": [
        {"title": "prelucrarea datelor cu caracter personal", "type": "1", "number": "190-2018"},
    ],
    "rgpd": [
        {"title": "prelucrarea datelor cu caracter personal", "type": "1", "number": "190-2018"},
    ],
    "anaf": [
        {"title": "Agentia Nationala de Administrare Fiscala", "type": "", "number": ""},
    ],
    "aml": [
        {"title": "prevenirea spalarii banilor", "type": "1", "number": "129-2019"},
    ],
    "kyc": [
        {"title": "prevenirea spalarii banilor", "type": "1", "number": "129-2019"},
    ],
    "casco": [
        {"title": "asigurari auto", "type": "", "number": ""},
    ],
    "rca": [
        {"title": "asigurare obligatorie raspundere civila auto", "type": "", "number": ""},
    ],
    "tva": [
        {"title": "codul fiscal taxa pe valoare adaugata", "type": "", "number": ""},
    ],
    "it": [
        {"title": "tehnologia informatiei comunicatiilor", "type": "", "number": ""},
    ],
    "gdpr": [
        {"title": "prelucrarea datelor cu caracter personal", "type": "1", "number": "190-2018"},
    ],

    # Popular names for well-known laws
    "spalarea banilor": [
        {"title": "prevenirea spalarii banilor", "type": "1", "number": "129-2019"},
    ],
    "spalare bani": [
        {"title": "prevenirea spalarii banilor", "type": "1", "number": "129-2019"},
    ],
    "legea societatilor": [
        {"title": "societatile comerciale", "type": "1", "number": "31-1990"},
    ],
    "legea societatilor comerciale": [
        {"title": "societatile comerciale", "type": "1", "number": "31-1990"},
    ],
    "codul fiscal": [
        {"title": "codul fiscal", "type": "1", "number": "227-2015"},
    ],
    "codul muncii": [
        {"title": "codul muncii", "type": "1", "number": "53-2003"},
    ],
    "codul civil": [
        {"title": "codul civil", "type": "1", "number": "287-2009"},
    ],
    "codul penal": [
        {"title": "codul penal", "type": "1", "number": "286-2009"},
    ],
    "codul de procedura civila": [
        {"title": "codul de procedura civila", "type": "1", "number": "134-2010"},
    ],
    "codul de procedura penala": [
        {"title": "codul de procedura penala", "type": "1", "number": "135-2010"},
    ],
    "legea contabilitatii": [
        {"title": "contabilitatea", "type": "1", "number": "82-1991"},
    ],
    "legea concurentei": [
        {"title": "concurenta", "type": "1", "number": "21-1996"},
    ],
    "legea insolventei": [
        {"title": "insolventa", "type": "1", "number": "85-2014"},
    ],
    "legea pensiilor": [
        {"title": "sistemul public pensii", "type": "1", "number": "263-2010"},
    ],
    "protectia consumatorului": [
        {"title": "protectia consumatorilor", "type": "18", "number": "21-1992"},
    ],
    "legea energiei": [
        {"title": "energiei electrice gazelor naturale", "type": "1", "number": "123-2012"},
    ],
    "legea educatiei": [
        {"title": "educatiei nationale", "type": "1", "number": "1-2011"},
    ],
    "legea sanatatii": [
        {"title": "reforma domeniul sanatatii", "type": "1", "number": "95-2006"},
    ],
    "legea administratiei publice": [
        {"title": "administratiei publice locale", "type": "1", "number": "215-2001"},
    ],
    "legea achizitiilor publice": [
        {"title": "achizitiile publice", "type": "1", "number": "98-2016"},
    ],
    "legea mediului": [
        {"title": "protectia mediului", "type": "18", "number": "195-2005"},
    ],
    "legea camerelor de comert": [
        {"title": "camerele de comert", "type": "1", "number": "335-2007"},
    ],
    "registrul comertului": [
        {"title": "registrul comertului", "type": "1", "number": "26-1990"},
    ],
    "piata de capital": [
        {"title": "piata de capital", "type": "1", "number": "297-2004"},
    ],
    "legea bancara": [
        {"title": "institutiile de credit adecvarea capitalului", "type": "18", "number": "99-2006"},
    ],
    "asigurari": [
        {"title": "asigurarilor reasigurarilor", "type": "1", "number": "237-2015"},
    ],

    # Constitution
    "constitutia romaniei": [
        {"title": "constitutia romaniei", "type": "", "number": ""},
    ],
    "constitutia": [
        {"title": "constitutia romaniei", "type": "", "number": ""},
    ],
    "constitutie": [
        {"title": "constitutia romaniei", "type": "", "number": ""},
    ],
}


# Maps abbreviated code references found in cross-references to (law_number, law_year)
CODE_ABBREVIATIONS: dict[str, tuple[str, int]] = {
    "c.civ.": ("287", 2009),
    "cod civ.": ("287", 2009),
    "codul civil": ("287", 2009),
    "c.pen.": ("286", 2009),
    "cod pen.": ("286", 2009),
    "codul penal": ("286", 2009),
    "c.proc.civ.": ("134", 2010),
    "cod procedura civila": ("134", 2010),
    "codul de procedura civila": ("134", 2010),
    "c.proc.pen.": ("135", 2010),
    "cod procedura penala": ("135", 2010),
    "codul de procedura penala": ("135", 2010),
    "c.fisc.": ("227", 2015),
    "codul fiscal": ("227", 2015),
    "c.muncii": ("53", 2003),
    "codul muncii": ("53", 2003),
    "c.proc.fisc.": ("207", 2015),
    "codul de procedura fiscala": ("207", 2015),
    "legea societatilor": ("31", 1990),
    "legea societatilor comerciale": ("31", 1990),
}


def _normalize_for_alias(text: str) -> str:
    """Normalize text for alias matching — strip diacritics and definite articles."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Remove common definite article suffixes so "codul" matches "cod",
    # "legea" matches "lege", etc.
    words = stripped.split()
    normalized = []
    for w in words:
        for suffix in ("ul", "ul", "a", "ea", "ua", "ului", "ei", "iei", "elor"):
            base = w[: -len(suffix)] if w.endswith(suffix) and len(w) > len(suffix) + 1 else None
            if base:
                normalized.append(base)
                break
        else:
            normalized.append(w)
    return " ".join(normalized)


def expand_query(query: str) -> list[dict] | None:
    """Check if query matches a known alias and return search parameters.

    Returns a list of search parameter dicts, or None if no alias matches.
    Uses fuzzy matching: "cod penal" matches "codul penal", "lege societati"
    matches "legea societatilor", etc.
    """
    q = query.strip().lower()

    # Remove common prefixes like "lege ", "legea ", "oug " for alias matching
    stripped = q
    for prefix in ["legea ", "lege ", "oug ", "hg ", "og ", "ordin ", "ordinul ",
                    "hotarare ", "hotararea ", "ordonanta ", "decizie ", "decizia "]:
        if q.startswith(prefix):
            stripped = q[len(prefix):].strip()
            break

    # Try exact match first, then stripped version
    if q in ALIASES:
        return ALIASES[q]
    if stripped in ALIASES:
        return ALIASES[stripped]

    # Try normalized match: strip definite articles from both query and keys
    # so "cod penal" matches "codul penal", "lege societati" matches "legea societatilor"
    q_norm = _normalize_for_alias(q)
    stripped_norm = _normalize_for_alias(stripped)
    for key, params in ALIASES.items():
        key_norm = _normalize_for_alias(key)
        if key_norm == q_norm or key_norm == stripped_norm:
            return params

    # Try partial match: if any alias key is contained in the query
    for key, params in ALIASES.items():
        if key in q and len(key) >= 3:
            return params

    return None
