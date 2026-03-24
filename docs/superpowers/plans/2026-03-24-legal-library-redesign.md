# Legal Library Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Legal Library with a category-based organization system, combined local+external search, and category assignment workflow across three phases.

**Architecture:** Single API endpoint returns all library data; frontend handles grouping/filtering client-side. New SQLAlchemy models for categories with seed data. The laws page becomes a client component with sidebar filtering, stats cards, and grouped law display. Search bar searches both local library (instant) and legislatie.just.ro (async).

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), Next.js 16/React 19/TypeScript/Tailwind CSS 4 (frontend), SQLite.

**Spec:** `docs/superpowers/specs/2026-03-24-legal-library-redesign.md`
**Source spec:** `docs/law_category_mapping_prompt (3).md`

**Important codebase notes:**
- No Alembic migrations — schema created via `Base.metadata.create_all()` in `main.py` lifespan
- No test framework configured — skip TDD, verify manually
- Next.js 16: dynamic route `params` must be awaited (Promise)
- Frontend uses feature-based folder structure with local `components/` subdirectories
- SQLite database at `data/themis.db`

---

## File Structure

### Backend — New Files
- `backend/app/models/category.py` — `CategoryGroup`, `Category`, `LawMapping` models
- `backend/app/services/category_service.py` — seed logic, library data assembly, category assignment, local search
- `backend/app/routers/categories.py` — `/api/laws/library`, `/api/laws/{id}/category`, `/api/laws/local-search` endpoints

### Backend — Modified Files
- `backend/app/models/law.py` — add `category_id`, `category_confidence` to `Law`
- `backend/app/models/__init__.py` — register category models (if exists, otherwise `main.py`)
- `backend/app/main.py` — import category models, call seed on startup, include categories router

### Frontend — New Files
- `frontend/src/app/laws/library-page.tsx` — main client component (sidebar + content + stats)
- `frontend/src/app/laws/components/sidebar.tsx` — category/status sidebar with expand/collapse
- `frontend/src/app/laws/components/stats-cards.tsx` — filterable stats display
- `frontend/src/app/laws/components/law-card.tsx` — single law card (title, identifier, badge, versions)
- `frontend/src/app/laws/components/category-group-section.tsx` — grouped law display with "See all"
- `frontend/src/app/laws/components/category-modal.tsx` — category assignment modal
- `frontend/src/app/laws/components/combined-search.tsx` — local+external search with dropdown
- `frontend/src/app/laws/components/unclassified-section.tsx` — necategorizat section

### Frontend — Modified Files
- `frontend/src/app/laws/page.tsx` — becomes thin server wrapper that renders `library-page.tsx`
- `frontend/src/lib/api.ts` — add library types and API methods

---

## Phase 1: DB Schema + Seed Data + Library Page Redesign

### Task 1: Category Models

**Files:**
- Create: `backend/app/models/category.py`
- Modify: `backend/app/models/law.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create category models file**

Create `backend/app/models/category.py` with three models:

```python
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
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="user")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    category: Mapped["Category"] = relationship()
```

Note: The `Law` import in `Category.laws` relationship will be resolved via string reference after Step 2.

- [ ] **Step 2: Add category fields to Law model**

In `backend/app/models/law.py`, add these fields to the `Law` class after the `status_override` field:

```python
category_id: Mapped[int | None] = mapped_column(
    ForeignKey("categories.id"), nullable=True
)
category_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

Add the relationship:

```python
category: Mapped["Category | None"] = relationship(back_populates="laws")
```

Add the import at the top of the file: `from __future__ import annotations`

- [ ] **Step 3: Register models in main.py**

In `backend/app/main.py`, add the import alongside existing model imports:

```python
from app.models import assistant, pipeline, prompt, category  # noqa: F401
```

- [ ] **Step 4: Verify the server starts and tables are created**

Run: `cd backend && python -m uvicorn app.main:app --reload`

Expected: Server starts without errors. Check that `category_groups`, `categories`, `law_mappings` tables exist and `laws` table has new columns.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/category.py backend/app/models/law.py backend/app/main.py
git commit -m "feat: add CategoryGroup, Category, LawMapping models and category fields on Law"
```

---

### Task 2: Seed Data Service

**Files:**
- Create: `backend/app/services/category_service.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create category_service.py with seed function**

Create `backend/app/services/category_service.py`. This file will contain the `seed_categories()` function that populates groups, categories, and law_mappings from the curated data in the source spec.

The function must:
1. Check if `category_groups` already has rows — if yes, skip (never re-seed).
2. Insert 9 category groups.
3. Insert ~35 subcategories.
4. Insert ~100+ law_mappings with `source='seed'`.
5. Set all existing laws to `category_confidence='unclassified'` where `category_confidence IS NULL`.

Use the exact group/category/mapping data from `docs/law_category_mapping_prompt (3).md` Sections 2 and 3.

```python
"""Category taxonomy seed and management service."""
import logging
from sqlalchemy.orm import Session

from app.models.category import CategoryGroup, Category, LawMapping
from app.models.law import Law

logger = logging.getLogger(__name__)


def seed_categories(db: Session) -> None:
    """Seed category groups, categories, and law mappings. Runs once."""
    existing = db.query(CategoryGroup).first()
    if existing:
        return  # Already seeded

    logger.info("Seeding category taxonomy...")

    # --- Groups ---
    groups_data = [
        ("constitutional", "Drept constituțional", "Constitutional law", "#534AB7", 1),
        ("civil", "Drept civil", "Civil law", "#185FA5", 2),
        ("criminal", "Drept penal", "Criminal law", "#993C1D", 3),
        ("commercial", "Drept comercial și societar", "Commercial law", "#0F6E56", 4),
        ("fiscal", "Drept fiscal și financiar", "Fiscal & financial law", "#854F0B", 5),
        ("administrative", "Drept administrativ", "Administrative law", "#5F5E5A", 6),
        ("social", "Drept social", "Social law", "#1D9E75", 7),
        ("sectoral", "Drept sectorial", "Sectoral law", "#888780", 8),
        ("eu", "Drept european (UE)", "EU law", "#185FA5", 9),
    ]
    group_map = {}
    for slug, name_ro, name_en, color, sort in groups_data:
        g = CategoryGroup(slug=slug, name_ro=name_ro, name_en=name_en, color_hex=color, sort_order=sort)
        db.add(g)
        db.flush()
        group_map[slug] = g.id

    # --- Categories ---
    # Full list from source spec Section 2
    cats_data = [
        # constitutional
        ("constitutional", "constitutional.revision", "Constituție și revizuire", "Constitution & revision", "Constituția, legi de revizuire, CCR", False, 1),
        ("constitutional", "constitutional.rights", "Drepturile omului", "Human rights", "Libertăți fundamentale, protecția datelor, egalitate, CNCD", False, 2),
        ("constitutional", "constitutional.electoral", "Electoral și partide", "Electoral & parties", "Legi electorale, partide politice, referendum, finanțare", False, 3),
        # civil
        ("civil", "civil.general", "Drept civil general", "General civil law", "Codul Civil, persoane fizice/juridice, acte juridice", False, 1),
        ("civil", "civil.property", "Proprietate și bunuri", "Property & assets", "Proprietate privată/publică, uzufruct, servituți, carte funciară", False, 2),
        ("civil", "civil.family", "Familie și succesiuni", "Family & succession", "Căsătorie, divorț, adopție, tutelă, moștenire, testament", False, 3),
        ("civil", "civil.contracts", "Contracte și obligații", "Contracts", "Contracte numite/nenumite, răspundere civilă, garanții", False, 4),
        ("civil", "civil.procedure", "Procedură civilă", "Civil procedure", "Codul de Procedură Civilă, executare silită, arbitraj, mediere", False, 5),
        # criminal
        ("criminal", "criminal.general", "Drept penal general", "General criminal law", "Codul Penal, principii, răspundere penală, sancțiuni", False, 1),
        ("criminal", "criminal.special", "Infracțiuni speciale", "Special offences", "Evaziune fiscală, corupție, crimă organizată, DIICOT, DNA", False, 2),
        ("criminal", "criminal.procedure", "Procedură penală", "Criminal procedure", "Codul de Procedură Penală, urmărire, judecată, căi de atac", False, 3),
        ("criminal", "criminal.execution", "Executarea pedepselor", "Execution of sentences", "Legea executării pedepselor, probațiune, reabilitare", False, 4),
        # commercial
        ("commercial", "commercial.companies", "Societăți comerciale", "Companies", "Legea societăților, SRL/SA/SNC, registrul comerțului, ONRC", False, 1),
        ("commercial", "commercial.insolvency", "Insolvență și faliment", "Insolvency", "Procedura insolvenței, reorganizare judiciară, lichidare", False, 2),
        ("commercial", "commercial.competition", "Concurență și ajutor de stat", "Competition law", "Consiliul Concurenței, practici anticoncurențiale, ajutor de stat", False, 3),
        ("commercial", "commercial.ip", "Proprietate intelectuală", "Intellectual property", "Drepturi de autor, mărci, brevete, desene industriale, OSIM", False, 4),
        ("commercial", "commercial.consumer", "Protecția consumatorului", "Consumer protection", "ANPC, clauze abuzive, garanții comerciale, e-commerce", False, 5),
        # fiscal
        ("fiscal", "fiscal.taxes", "Impozite și taxe", "Taxes", "Codul Fiscal, TVA, impozit pe profit/venit, accize, ANAF", False, 1),
        ("fiscal", "fiscal.procedure", "Procedură fiscală", "Fiscal procedure", "Codul de Procedură Fiscală, inspecție, contestații, executare", False, 2),
        ("fiscal", "fiscal.banking", "Bancar și piețe de capital", "Banking & capital", "BNR, instituții de credit, ASF, piețe de capital, asigurări", False, 3),
        ("fiscal", "fiscal.procurement", "Achiziții publice", "Public procurement", "Legea achizițiilor, concesiuni, parteneriat public-privat, ANAP", False, 4),
        # administrative
        ("administrative", "administrative.state", "Organizarea statului", "State organization", "Guvern, ministere, autorități centrale, deconcentrate", False, 1),
        ("administrative", "administrative.local", "Administrație publică locală", "Local government", "Consilii județene/locale, primării, descentralizare", False, 2),
        ("administrative", "administrative.civil_service", "Funcție publică", "Civil service", "Statutul funcționarilor publici, ANFP, răspundere disciplinară", False, 3),
        ("administrative", "administrative.litigation", "Contencios administrativ", "Admin litigation", "Legea contenciosului, acte administrative, contravenții", False, 4),
        # social
        ("social", "social.labour", "Dreptul muncii", "Labour law", "Codul Muncii, contracte colective, sindicate, conflicte muncă", False, 1),
        ("social", "social.insurance", "Asigurări și protecție socială", "Social insurance", "Pensii, CNPP, șomaj, ajutor social, CNAS", False, 2),
        ("social", "social.health", "Sănătate", "Health", "Legea sănătății, CNAS, medicamente, răspundere medicală", False, 3),
        ("social", "social.education", "Educație", "Education", "Legea educației, învățământ superior, ARACIS, acreditare", False, 4),
        # sectoral
        ("sectoral", "sectoral.real_estate", "Imobiliar și urbanism", "Real estate", "Construcții, autorizații, cadastru, expropriere, fond funciar", False, 1),
        ("sectoral", "sectoral.environment", "Mediu", "Environment", "Legea mediului, deșeuri, ape, păduri, arii protejate, ANPM", False, 2),
        ("sectoral", "sectoral.energy", "Energie și resurse", "Energy", "ANRE, electricitate, gaz, petrol, minerale, regenerabile", False, 3),
        ("sectoral", "sectoral.transport", "Transport și infrastructură", "Transport", "Circulație rutieră, CFR, CNAIR, navigație, aviație civilă", False, 4),
        ("sectoral", "sectoral.tech", "Tehnologie și comunicații", "Tech & telecom", "ANCOM, telecomunicații, semnătură electronică, comerț electronic", False, 5),
        ("sectoral", "sectoral.agriculture", "Agricultură și alimentație", "Agriculture", "MADR, APIA, fond funciar agricol, veterinar, ANSVSA", False, 6),
        ("sectoral", "sectoral.media", "Audiovizual și media", "Media", "Legea audiovizualului, CNA, drepturi de difuzare, presă scrisă", False, 7),
        ("sectoral", "sectoral.defence", "Apărare și securitate", "Defence", "MApN, SRI, SIE, ordine publică, MAI, stare de urgență", False, 8),
        # eu
        ("eu", "eu.regulation", "Regulamente UE", "EU regulations", "Direct aplicabile — GDPR, AI Act, NIS2, MDR, DMA, DSA", True, 1),
        ("eu", "eu.directive", "Directive UE transpuse", "EU directives", "Directive transpuse în drept român — legătură lege națională ↔ directivă sursă", True, 2),
        ("eu", "eu.treaty", "Drept primar și tratate", "EU treaties", "TFUE, TUE, Carta drepturilor fundamentale, protocoale", True, 3),
        ("eu", "eu.caselaw", "Jurisprudență CJUE", "CJEU case law", "Hotărâri CJUE relevante pentru România, trimiteri preliminare", True, 4),
    ]
    cat_map = {}
    for group_slug, slug, name_ro, name_en, desc, is_eu, sort in cats_data:
        c = Category(
            group_id=group_map[group_slug], slug=slug,
            name_ro=name_ro, name_en=name_en, description=desc,
            is_eu=is_eu, sort_order=sort,
        )
        db.add(c)
        db.flush()
        cat_map[slug] = c.id

    # --- Law mappings ---
    # Full list from source spec Section 3
    mappings_data = [
        # constitutional.revision
        ("constitutional.revision", "Constituția României (1991, republicată 2003)", None),
        # constitutional.rights
        ("constitutional.rights", "Legea 190/2018 — implementarea GDPR în dreptul național", "190"),
        ("constitutional.rights", "Legea 506/2004 — prelucrarea datelor personale în comunicații electronice", "506"),
        ("constitutional.rights", "OUG 119/2006 — măsuri pentru aplicarea unor regulamente comunitare privind drepturile cetățenilor", "119"),
        # constitutional.electoral
        ("constitutional.electoral", "Legea 208/2015 — alegerea Senatului și Camerei Deputaților", "208"),
        ("constitutional.electoral", "Legea 370/2004 — alegerea Președintelui României", "370"),
        ("constitutional.electoral", "Legea 115/2015 — alegerea autorităților administrației publice locale", "115"),
        ("constitutional.electoral", "Legea 334/2006 — finanțarea activității partidelor politice", "334"),
        # civil.general
        ("civil.general", "Legea 287/2009 — Codul Civil (republicat)", "287"),
        ("civil.general", "Legea 71/2011 — punerea în aplicare a Codului Civil", "71"),
        ("civil.general", "Decretul-lege 31/1954 — persoane fizice și juridice (abrogat parțial)", "31"),
        # civil.property
        ("civil.property", "Legea 7/1996 — cadastrul și publicitatea imobiliară", "7"),
        ("civil.property", "Legea 10/2001 — regimul juridic al imobilelor preluate abuziv", "10"),
        ("civil.property", "Legea 18/1991 — fondul funciar", "18"),
        ("civil.property", "Legea 50/1991 — autorizarea executării lucrărilor de construcții", "50"),
        ("civil.property", "Legea 33/1994 — exproprierea pentru cauze de utilitate publică", "33"),
        # civil.family
        ("civil.family", "Legea 272/2004 — protecția și promovarea drepturilor copilului", "272"),
        ("civil.family", "Legea 273/2004 — procedura adopției", "273"),
        ("civil.family", "Legea 217/2003 — prevenirea și combaterea violenței domestice", "217"),
        # civil.contracts
        ("civil.contracts", "Legea 193/2000 — clauzele abuzive din contractele cu consumatorii", "193"),
        ("civil.contracts", "Legea 455/2001 — semnătura electronică", "455"),
        ("civil.contracts", "Legea 365/2002 — comerțul electronic", "365"),
        # civil.procedure
        ("civil.procedure", "Legea 134/2010 — Codul de Procedură Civilă (republicat)", "134"),
        ("civil.procedure", "Legea 85/2014 — procedurile de prevenire a insolvenței și de insolvență", "85"),
        ("civil.procedure", "Legea 192/2006 — medierea și organizarea profesiei de mediator", "192"),
        ("civil.procedure", "Legea 188/2000 — executorii judecătorești", "188"),
        # criminal.general
        ("criminal.general", "Legea 286/2009 — Codul Penal", "286"),
        ("criminal.general", "Legea 187/2012 — punerea în aplicare a Codului Penal", "187"),
        # criminal.special
        ("criminal.special", "Legea 241/2005 — prevenirea și combaterea evaziunii fiscale", "241"),
        ("criminal.special", "Legea 78/2000 — prevenirea, descoperirea și sancționarea faptelor de corupție", "78"),
        ("criminal.special", "Legea 656/2002 — prevenirea și combaterea spălării banilor", "656"),
        ("criminal.special", "Legea 143/2000 — prevenirea și combaterea traficului și consumului ilicit de droguri", "143"),
        ("criminal.special", "Legea 39/2003 — prevenirea și combaterea criminalității organizate", "39"),
        ("criminal.special", "OUG 43/2002 — Direcția Națională Anticorupție (DNA)", "43"),
        # criminal.procedure
        ("criminal.procedure", "Legea 135/2010 — Codul de Procedură Penală", "135"),
        ("criminal.procedure", "Legea 254/2013 — executarea pedepselor și a măsurilor privative de libertate", "254"),
        # criminal.execution
        ("criminal.execution", "Legea 253/2013 — executarea pedepselor, a măsurilor educative și a altor măsuri neprivative de libertate", "253"),
        ("criminal.execution", "Legea 252/2013 — organizarea și funcționarea sistemului de probațiune", "252"),
        # commercial.companies
        ("commercial.companies", "Legea 31/1990 — societățile comerciale (republicată)", "31"),
        ("commercial.companies", "Legea 26/1990 — registrul comerțului (republicată)", "26"),
        ("commercial.companies", "Legea 1/2005 — organizarea și funcționarea cooperației", "1"),
        ("commercial.companies", "OUG 44/2008 — desfășurarea activităților economice de către persoanele fizice autorizate (PFA)", "44"),
        # commercial.insolvency
        ("commercial.insolvency", "Legea 85/2014 — procedurile de prevenire a insolvenței și de insolvență", "85"),
        ("commercial.insolvency", "Legea 85/2006 — procedura insolvenței (abrogată, referită istoric)", "85"),
        # commercial.competition
        ("commercial.competition", "Legea 21/1996 — concurența (republicată)", "21"),
        ("commercial.competition", "Legea 11/1991 — combaterea concurenței neloiale", "11"),
        ("commercial.competition", "OUG 117/2006 — procedurile naționale în domeniul ajutorului de stat", "117"),
        # commercial.ip
        ("commercial.ip", "Legea 8/1996 — dreptul de autor și drepturile conexe", "8"),
        ("commercial.ip", "Legea 64/1991 — brevetele de invenție (republicată)", "64"),
        ("commercial.ip", "Legea 84/1998 — mărcile și indicațiile geografice (republicată)", "84"),
        ("commercial.ip", "Legea 129/1992 — protecția desenelor și modelelor industriale", "129"),
        # commercial.consumer
        ("commercial.consumer", "Legea 449/2003 — vânzarea produselor și garanțiile asociate (republicată)", "449"),
        ("commercial.consumer", "OUG 34/2014 — drepturile consumatorilor în contractele cu profesioniști", "34"),
        ("commercial.consumer", "Legea 363/2007 — combaterea practicilor incorecte ale comercianților", "363"),
        # fiscal.taxes
        ("fiscal.taxes", "Legea 227/2015 — Codul Fiscal", "227"),
        ("fiscal.taxes", "OUG 6/2019 — stabilirea unor măsuri privind starea de insolvabilitate", "6"),
        ("fiscal.taxes", "Legea 241/2005 — prevenirea și combaterea evaziunii fiscale", "241"),
        ("fiscal.taxes", "HG 1/2016 — normele metodologice de aplicare a Codului Fiscal", "1"),
        # fiscal.procedure
        ("fiscal.procedure", "Legea 207/2015 — Codul de Procedură Fiscală", "207"),
        ("fiscal.procedure", "OUG 74/2013 — măsuri pentru îmbunătățirea și reorganizarea ANAF", "74"),
        # fiscal.banking
        ("fiscal.banking", "Legea 58/1998 — activitatea bancară (republicată)", "58"),
        ("fiscal.banking", "Legea 237/2015 — autorizarea și supravegherea activității de asigurare", "237"),
        ("fiscal.banking", "Legea 126/2018 — piețele de instrumente financiare", "126"),
        ("fiscal.banking", "OUG 99/2006 — instituțiile de credit și adecvarea capitalului", "99"),
        ("fiscal.banking", "Legea 32/2000 — activitatea de asigurare și supravegherea asigurărilor", "32"),
        # fiscal.procurement
        ("fiscal.procurement", "Legea 98/2016 — achizițiile publice", "98"),
        ("fiscal.procurement", "Legea 99/2016 — achizițiile sectoriale", "99"),
        ("fiscal.procurement", "Legea 100/2016 — concesiunile de lucrări și servicii", "100"),
        ("fiscal.procurement", "HG 395/2016 — normele metodologice de aplicare a Legii 98/2016", "395"),
        # administrative.state
        ("administrative.state", "Legea 90/2001 — organizarea și funcționarea Guvernului", "90"),
        ("administrative.state", "Legea 340/2004 — prefectul și instituția prefectului (republicată)", "340"),
        ("administrative.state", "Legea 188/1999 — statutul funcționarilor publici (republicată)", "188"),
        # administrative.local
        ("administrative.local", "Legea 215/2001 — administrația publică locală (republicată)", "215"),
        ("administrative.local", "Legea 195/2006 — descentralizarea", "195"),
        ("administrative.local", "OUG 57/2019 — Codul Administrativ", "57"),
        # administrative.civil_service
        ("administrative.civil_service", "Legea 188/1999 — statutul funcționarilor publici (republicată)", "188"),
        ("administrative.civil_service", "Legea 7/2004 — Codul de Conduită al funcționarilor publici", "7"),
        ("administrative.civil_service", "Legea 477/2004 — Codul de Conduită al personalului contractual", "477"),
        # administrative.litigation
        ("administrative.litigation", "Legea 554/2004 — contenciosul administrativ", "554"),
        ("administrative.litigation", "OG 2/2001 — regimul juridic al contravențiilor", "2"),
        ("administrative.litigation", "Legea 101/2016 — remediile și căile de atac în achiziții publice", "101"),
        # social.labour
        ("social.labour", "Legea 53/2003 — Codul Muncii (republicat)", "53"),
        ("social.labour", "Legea 62/2011 — dialogul social (republicată)", "62"),
        ("social.labour", "Legea 279/2005 — ucenicia la locul de muncă (republicată)", "279"),
        ("social.labour", "Legea 156/2000 — protecția cetățenilor români care lucrează în străinătate", "156"),
        # social.insurance
        ("social.insurance", "Legea 263/2010 — sistemul unitar de pensii publice", "263"),
        ("social.insurance", "Legea 76/2002 — sistemul asigurărilor pentru șomaj", "76"),
        ("social.insurance", "Legea 416/2001 — venitul minim garantat", "416"),
        ("social.insurance", "Legea 292/2011 — asistența socială", "292"),
        # social.health
        ("social.health", "Legea 95/2006 — reforma în domeniul sănătății (republicată)", "95"),
        ("social.health", "Legea 46/2003 — drepturile pacientului", "46"),
        ("social.health", "Legea 339/2005 — regimul juridic al plantelor, substanțelor și preparatelor stupefiante", "339"),
        # social.education
        ("social.education", "Legea 1/2011 — educația națională", "1"),
        ("social.education", "OUG 75/2005 — asigurarea calității educației (republicată)", "75"),
        ("social.education", "Legea 288/2004 — organizarea studiilor universitare", "288"),
        # sectoral.real_estate
        ("sectoral.real_estate", "Legea 50/1991 — autorizarea executării lucrărilor de construcții (republicată)", "50"),
        ("sectoral.real_estate", "Legea 350/2001 — amenajarea teritoriului și urbanismul", "350"),
        ("sectoral.real_estate", "Legea 255/2010 — exproprierea pentru cauze de utilitate publică", "255"),
        ("sectoral.real_estate", "Legea 7/1996 — cadastrul și publicitatea imobiliară (republicată)", "7"),
        # sectoral.environment
        ("sectoral.environment", "Legea 137/1995 — protecția mediului (republicată)", "137"),
        ("sectoral.environment", "OUG 195/2005 — protecția mediului", "195"),
        ("sectoral.environment", "Legea 211/2011 — regimul deșeurilor (republicată)", "211"),
        ("sectoral.environment", "Legea 107/1996 — legea apelor", "107"),
        ("sectoral.environment", "Legea 46/2008 — Codul Silvic (republicat)", "46"),
        # sectoral.energy
        ("sectoral.energy", "Legea 123/2012 — energia electrică și gazele naturale", "123"),
        ("sectoral.energy", "Legea 220/2008 — sistemul de promovare a producerii energiei din surse regenerabile (republicată)", "220"),
        ("sectoral.energy", "Legea 132/2015 — schema de sprijin pentru energia electrică din surse regenerabile", "132"),
        ("sectoral.energy", "OG 60/2000 — reglementarea activităților din sectorul gazelor naturale (referit istoric)", "60"),
        # sectoral.transport
        ("sectoral.transport", "OUG 195/2002 — circulația pe drumurile publice (republicată)", "195"),
        ("sectoral.transport", "Legea 38/2003 — transportul în regim de taxi și în regim de închiriere", "38"),
        ("sectoral.transport", "OG 27/2011 — transporturile rutiere", "27"),
        ("sectoral.transport", "Legea 198/2015 — Codul Aerian Civil al României", "198"),
        # sectoral.tech
        ("sectoral.tech", "Legea 506/2004 — prelucrarea datelor cu caracter personal în comunicații electronice", "506"),
        ("sectoral.tech", "OUG 111/2011 — comunicațiile electronice", "111"),
        ("sectoral.tech", "Legea 455/2001 — semnătura electronică (republicată)", "455"),
        ("sectoral.tech", "Legea 365/2002 — comerțul electronic (republicată)", "365"),
        ("sectoral.tech", "Legea 40/2016 — modificarea Legii 506/2004", "40"),
        # sectoral.agriculture
        ("sectoral.agriculture", "Legea 18/1991 — fondul funciar (republicată)", "18"),
        ("sectoral.agriculture", "Legea 17/2014 — vânzarea-cumpărarea terenurilor agricole", "17"),
        ("sectoral.agriculture", "Legea 145/2014 — reglementarea activității de agroturism", "145"),
        ("sectoral.agriculture", "OUG 3/2015 — acordarea de sprijin financiar producătorilor agricoli", "3"),
        # sectoral.media
        ("sectoral.media", "Legea 504/2002 — legea audiovizualului", "504"),
        ("sectoral.media", "Legea 41/1994 — organizarea și funcționarea CNA (republicată)", "41"),
        ("sectoral.media", "Legea 8/1996 — dreptul de autor (inclusiv difuzare)", "8"),
        # sectoral.defence
        # (no specific laws listed in source spec)
        # eu.regulation
        ("eu.regulation", "Regulamentul (UE) 2016/679 — GDPR", None),
        ("eu.regulation", "Regulamentul (UE) 2024/1689 — AI Act", None),
        ("eu.regulation", "Regulamentul (UE) 2022/2065 — DSA (Digital Services Act)", None),
        ("eu.regulation", "Regulamentul (UE) 2022/1925 — DMA (Digital Markets Act)", None),
        ("eu.regulation", "Regulamentul (UE) 2017/745 — MDR (dispozitive medicale)", None),
        ("eu.regulation", "Regulamentul (UE) 1215/2012 — competența judiciară în materie civilă (Bruxelles I)", None),
        ("eu.regulation", "Regulamentul (UE) 593/2008 — legea aplicabilă obligațiilor contractuale (Roma I)", None),
        ("eu.regulation", "Regulamentul (UE) 864/2007 — legea aplicabilă obligațiilor necontractuale (Roma II)", None),
        # eu.directive
        ("eu.directive", "Directiva 2011/83/UE — drepturile consumatorilor (transpusă prin OUG 34/2014)", None),
        ("eu.directive", "Directiva 2019/1023/UE — restructurare și insolvență (transpusă prin Legea 216/2022)", None),
        ("eu.directive", "Directiva 2022/2557/UE — reziliența entităților critice (CER)", None),
        ("eu.directive", "Directiva 2022/2555/UE — NIS2", None),
        ("eu.directive", "Directiva 2023/970/UE — transparența salarială", None),
        ("eu.directive", "Directiva 2009/72/CE — piața internă a energiei electrice", None),
        # eu.treaty
        ("eu.treaty", "Tratatul privind funcționarea Uniunii Europene (TFUE)", None),
        ("eu.treaty", "Tratatul privind Uniunea Europeană (TUE)", None),
        ("eu.treaty", "Carta drepturilor fundamentale a Uniunii Europene", None),
        ("eu.treaty", "Tratatul de aderare a României la UE (2005, în vigoare 2007)", None),
        # eu.caselaw — empty per source spec
    ]
    for cat_slug, title, law_number in mappings_data:
        m = LawMapping(
            title=title,
            law_number=law_number,
            category_id=cat_map[cat_slug],
            source="seed",
        )
        db.add(m)

    # Mark existing laws as unclassified
    db.query(Law).filter(Law.category_confidence.is_(None)).update(
        {"category_confidence": "unclassified"}, synchronize_session="fetch"
    )

    db.commit()
    logger.info("Category taxonomy seeded successfully.")
```

- [ ] **Step 2: Call seed on startup in main.py**

In `backend/app/main.py`, add the seed call in the `lifespan` function, after the existing `seed_defaults(db)` call:

```python
from app.services.category_service import seed_categories
seed_categories(db)
```

- [ ] **Step 3: Verify seed runs on server start**

Run: `cd backend && python -m uvicorn app.main:app --reload`

Expected: Log message "Seeding category taxonomy..." on first start. On second start, no seed message (already seeded). Verify data exists: run a quick query via Python shell or SQLite CLI.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/category_service.py backend/app/main.py
git commit -m "feat: seed category groups, subcategories, and law mappings on startup"
```

---

### Task 3: Library API Endpoint

**Files:**
- Create: `backend/app/routers/categories.py`
- Modify: `backend/app/services/category_service.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add library data assembly function to category_service.py**

Add to `backend/app/services/category_service.py`:

```python
from sqlalchemy import func


def get_library_data(db: Session) -> dict:
    """Assemble all data needed for the Legal Library page."""
    from app.models.law import LawVersion

    # Groups with categories and law counts
    groups = (
        db.query(CategoryGroup)
        .order_by(CategoryGroup.sort_order)
        .all()
    )
    groups_out = []
    for g in groups:
        cats_out = []
        for c in sorted(g.categories, key=lambda x: x.sort_order):
            count = db.query(func.count(Law.id)).filter(Law.category_id == c.id).scalar()
            cats_out.append({
                "id": c.id,
                "slug": c.slug,
                "name_ro": c.name_ro,
                "name_en": c.name_en,
                "description": c.description,
                "law_count": count,
            })
        groups_out.append({
            "id": g.id,
            "slug": g.slug,
            "name_ro": g.name_ro,
            "name_en": g.name_en,
            "color_hex": g.color_hex,
            "sort_order": g.sort_order,
            "categories": cats_out,
        })

    # All imported laws
    laws = db.query(Law).order_by(Law.law_year.desc(), Law.law_number).all()
    laws_out = []
    for law in laws:
        current = next((v for v in law.versions if v.is_current), None)
        cat = law.category
        group_slug = cat.group.slug if cat else None
        laws_out.append({
            "id": law.id,
            "title": law.title,
            "law_number": law.law_number,
            "law_year": law.law_year,
            "document_type": law.document_type,
            "version_count": len(law.versions),
            "status": law.status,
            "category_id": law.category_id,
            "category_group_slug": group_slug,
            "category_confidence": law.category_confidence,
            "current_version": {
                "id": current.id,
                "state": current.state,
            } if current else None,
        })

    # Stats
    total_versions = db.query(func.count(LawVersion.id)).scalar()
    last_imported = (
        db.query(func.max(LawVersion.date_imported)).scalar()
    )

    # Suggested laws from law_mappings (not yet imported)
    all_mappings = db.query(LawMapping).all()
    imported_numbers = {law.law_number for law in laws}
    imported_titles = {law.title.lower() for law in laws}
    suggested = []
    for m in all_mappings:
        # Skip if already imported (match by law_number or title substring)
        if m.law_number and m.law_number in imported_numbers:
            continue
        if any(t in m.title.lower() or m.title.lower() in t for t in imported_titles):
            continue
        cat = db.query(Category).filter(Category.id == m.category_id).first()
        if cat:
            suggested.append({
                "id": m.id,
                "title": m.title,
                "law_number": m.law_number,
                "category_id": m.category_id,
                "category_slug": cat.slug,
                "group_slug": cat.group.slug,
            })

    return {
        "groups": groups_out,
        "laws": laws_out,
        "stats": {
            "total_laws": len(laws),
            "total_versions": total_versions,
            "last_imported": str(last_imported.date()) if last_imported else None,
        },
        "suggested_laws": suggested,
    }


def assign_category(db: Session, law_id: int, category_id: int) -> dict:
    """Assign a category to a law and update law_mappings."""
    law = db.query(Law).filter(Law.id == law_id).first()
    if not law:
        raise ValueError("Law not found")

    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise ValueError("Category not found")

    law.category_id = category_id
    law.category_confidence = "manual"

    # Add to law_mappings if not already there for this category
    existing = (
        db.query(LawMapping)
        .filter(
            LawMapping.category_id == category_id,
            (LawMapping.law_number == law.law_number) | (LawMapping.title.ilike(law.title))
        )
        .first()
    )
    if not existing:
        mapping = LawMapping(
            title=law.title,
            law_number=law.law_number,
            category_id=category_id,
            source="user",
        )
        db.add(mapping)

    db.commit()
    return {"category_id": category_id, "category_confidence": "manual"}


def local_search(db: Session, query: str) -> list[dict]:
    """Search imported laws by title or law_number."""
    q = f"%{query}%"
    laws = (
        db.query(Law)
        .filter((Law.title.ilike(q)) | (Law.law_number.ilike(q)))
        .order_by(Law.law_year.desc())
        .limit(10)
        .all()
    )
    results = []
    for law in laws:
        current = next((v for v in law.versions if v.is_current), None)
        cat = law.category
        results.append({
            "id": law.id,
            "title": law.title,
            "law_number": law.law_number,
            "law_year": law.law_year,
            "version_count": len(law.versions),
            "category_name": cat.group.name_en if cat else None,
            "current_version": {
                "id": current.id,
                "state": current.state,
            } if current else None,
        })
    return results
```

- [ ] **Step 2: Create the categories router**

Create `backend/app/routers/categories.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/api/laws", tags=["library"])


@router.get("/library")
def get_library(db: Session = Depends(get_db)):
    """Return all data needed for the Legal Library page."""
    from app.services.category_service import get_library_data
    return get_library_data(db)


class CategoryAssignment(BaseModel):
    category_id: int


@router.patch("/{law_id}/category")
def assign_law_category(law_id: int, req: CategoryAssignment, db: Session = Depends(get_db)):
    """Assign a category to a law."""
    from app.services.category_service import assign_category
    try:
        return assign_category(db, law_id, req.category_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/local-search")
def search_local(q: str = "", db: Session = Depends(get_db)):
    """Search imported laws by title or number."""
    if len(q.strip()) < 2:
        return {"results": []}
    from app.services.category_service import local_search
    return {"results": local_search(db, q.strip())}
```

- [ ] **Step 3: Register the router in main.py**

In `backend/app/main.py`, add the import and include:

```python
from app.routers import categories
```

```python
app.include_router(categories.router)
```

**Important**: Add this router BEFORE the `laws.router` include, because both share the `/api/laws` prefix and the `/api/laws/library` route must not be caught by the `/{law_id}` catch-all in `laws.py`.

- [ ] **Step 4: Test the endpoints**

Run the server, then test:

```bash
curl http://localhost:8000/api/laws/library | python -m json.tool | head -50
curl http://localhost:8000/api/laws/local-search?q=fiscal | python -m json.tool
```

Expected: Library endpoint returns groups, laws, stats, suggested_laws. Local search returns matching laws.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/categories.py backend/app/services/category_service.py backend/app/main.py
git commit -m "feat: add /api/laws/library, /api/laws/local-search, and PATCH /api/laws/{id}/category endpoints"
```

---

### Task 4: Frontend Types and API Client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add library types to api.ts**

Add these interfaces after the existing `LawSummary` interface in `frontend/src/lib/api.ts`:

```typescript
export interface CategoryData {
  id: number;
  slug: string;
  name_ro: string;
  name_en: string;
  description: string | null;
  law_count: number;
}

export interface CategoryGroupData {
  id: number;
  slug: string;
  name_ro: string;
  name_en: string;
  color_hex: string;
  sort_order: number;
  categories: CategoryData[];
}

export interface LibraryLaw {
  id: number;
  title: string;
  law_number: string;
  law_year: number;
  document_type: string;
  version_count: number;
  status: string;
  category_id: number | null;
  category_group_slug: string | null;
  category_confidence: string | null;
  current_version: {
    id: number;
    state: string;
  } | null;
}

export interface SuggestedLaw {
  id: number;
  title: string;
  law_number: string | null;
  category_id: number;
  category_slug: string;
  group_slug: string;
}

export interface LibraryData {
  groups: CategoryGroupData[];
  laws: LibraryLaw[];
  stats: {
    total_laws: number;
    total_versions: number;
    last_imported: string | null;
  };
  suggested_laws: SuggestedLaw[];
}

export interface LocalSearchResult {
  id: number;
  title: string;
  law_number: string;
  law_year: number;
  version_count: number;
  category_name: string | null;
  current_version: {
    id: number;
    state: string;
  } | null;
}
```

- [ ] **Step 2: Add API methods**

Add to the `api.laws` object in `frontend/src/lib/api.ts`:

```typescript
library: () => apiFetch<LibraryData>("/api/laws/library"),
localSearch: (q: string) =>
  apiFetch<{ results: LocalSearchResult[] }>(`/api/laws/local-search?q=${encodeURIComponent(q)}`),
assignCategory: (lawId: number, categoryId: number) =>
  apiFetch<{ category_id: number; category_confidence: string }>(
    `/api/laws/${lawId}/category`,
    {
      method: "PATCH",
      body: JSON.stringify({ category_id: categoryId }),
    }
  ),
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add library types and API methods for category system"
```

---

### Task 5: Sidebar Component

**Files:**
- Create: `frontend/src/app/laws/components/sidebar.tsx`

- [ ] **Step 1: Create the sidebar component**

Create `frontend/src/app/laws/components/sidebar.tsx`:

```typescript
"use client";

import { useState } from "react";
import { CategoryGroupData, LibraryLaw } from "@/lib/api";

interface SidebarProps {
  groups: CategoryGroupData[];
  laws: LibraryLaw[];
  selectedGroup: string | null;
  selectedCategory: string | null;
  selectedStatus: string | null;
  onSelectGroup: (slug: string | null) => void;
  onSelectCategory: (slug: string | null) => void;
  onSelectStatus: (status: string | null) => void;
}

const STATUS_LABELS: Record<string, string> = {
  actual: "Actual",
  republished: "Republished",
  amended: "Amended",
  deprecated: "Deprecated",
};

export default function Sidebar({
  groups,
  laws,
  selectedGroup,
  selectedCategory,
  selectedStatus,
  onSelectGroup,
  onSelectCategory,
  onSelectStatus,
}: SidebarProps) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [showSuggested, setShowSuggested] = useState(false);

  const totalLaws = laws.length;

  // Groups that have at least one imported law
  const activeGroups = groups.filter((g) =>
    g.categories.some((c) => c.law_count > 0)
  );
  const suggestedGroups = groups.filter((g) =>
    g.categories.every((c) => c.law_count === 0)
  );

  // Status counts based on current_version.state
  const statusCounts: Record<string, number> = {};
  for (const law of laws) {
    const state = law.current_version?.state;
    if (state) {
      statusCounts[state] = (statusCounts[state] || 0) + 1;
    }
  }

  function toggleGroup(slug: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  }

  const isAllSelected = !selectedGroup && !selectedCategory;

  return (
    <div className="w-56 border-r border-gray-200 p-4 text-sm flex-shrink-0">
      {/* CATEGORIES */}
      <div className="text-[10px] font-bold text-gray-500 tracking-wider mb-2">
        CATEGORIES
      </div>

      {/* All laws */}
      <button
        onClick={() => { onSelectGroup(null); onSelectCategory(null); }}
        className={`w-full text-left px-2 py-1.5 rounded flex justify-between items-center mb-1 ${
          isAllSelected ? "bg-amber-50 font-semibold text-amber-900" : "hover:bg-gray-50"
        }`}
      >
        <span>All laws</span>
        <span className={`text-xs px-1.5 rounded-full ${
          isAllSelected ? "bg-amber-900 text-white" : "text-gray-400"
        }`}>
          {totalLaws}
        </span>
      </button>

      {/* Active groups */}
      {activeGroups.map((g) => {
        const groupLawCount = g.categories.reduce((sum, c) => sum + c.law_count, 0);
        const isExpanded = expandedGroups.has(g.slug);
        const isSelected = selectedGroup === g.slug && !selectedCategory;

        return (
          <div key={g.slug} className="mb-0.5">
            <div className="flex items-center">
              <button
                onClick={() => toggleGroup(g.slug)}
                className="text-xs text-gray-400 w-4 flex-shrink-0"
              >
                {isExpanded ? "▾" : "▸"}
              </button>
              <button
                onClick={() => { onSelectGroup(g.slug); onSelectCategory(null); }}
                className={`flex-1 text-left px-1 py-1.5 rounded flex justify-between items-center ${
                  isSelected ? "font-semibold text-gray-900" : "hover:bg-gray-50 text-gray-700"
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: g.color_hex }} />
                  {g.name_en}
                </span>
                <span className="text-xs text-gray-400">{groupLawCount}</span>
              </button>
            </div>

            {/* Subcategories */}
            {isExpanded && (
              <div className="pl-5">
                {g.categories.map((c) => {
                  const isCatSelected = selectedCategory === c.slug;
                  return (
                    <button
                      key={c.slug}
                      onClick={() => { onSelectGroup(g.slug); onSelectCategory(c.slug); }}
                      className={`w-full text-left px-2 py-1 rounded flex justify-between items-center text-xs ${
                        isCatSelected
                          ? "font-semibold text-gray-900 bg-gray-100"
                          : "text-gray-500 hover:bg-gray-50"
                      }`}
                    >
                      <span>{c.name_en}</span>
                      <span className="text-gray-400">{c.law_count}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {/* STATUS */}
      <div className="border-t border-gray-200 mt-3 pt-3">
        <div className="text-[10px] font-bold text-gray-500 tracking-wider mb-2">
          STATUS
        </div>
        {Object.entries(STATUS_LABELS).map(([value, label]) => {
          const count = statusCounts[value] || 0;
          if (count === 0) return null;
          const isSelected = selectedStatus === value;
          return (
            <button
              key={value}
              onClick={() => onSelectStatus(isSelected ? null : value)}
              className={`w-full text-left px-2 py-1.5 rounded flex justify-between items-center ${
                isSelected ? "font-semibold text-gray-900 bg-gray-100" : "hover:bg-gray-50 text-gray-700"
              }`}
            >
              <span>{label}</span>
              <span className="text-xs text-gray-400">{count}</span>
            </button>
          );
        })}
      </div>

      {/* SUGGESTED CATEGORIES */}
      {suggestedGroups.length > 0 && (
        <div className="border-t border-gray-200 mt-3 pt-3">
          <button
            onClick={() => setShowSuggested(!showSuggested)}
            className="w-full text-left px-2 py-1.5 text-xs text-gray-400 italic hover:text-gray-600"
          >
            {showSuggested ? "▾" : "▸"} Sugestii neimportate ({suggestedGroups.length})
          </button>
          {showSuggested && (
            <div className="pl-4">
              {suggestedGroups.map((g) => (
                <div key={g.slug} className="px-2 py-1 text-xs text-gray-400 italic">
                  {g.name_en}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/laws/components/sidebar.tsx
git commit -m "feat: add Legal Library sidebar component with categories and status filters"
```

---

### Task 6: Stats Cards, Law Card, and Category Group Section Components

**Files:**
- Create: `frontend/src/app/laws/components/stats-cards.tsx`
- Create: `frontend/src/app/laws/components/law-card.tsx`
- Create: `frontend/src/app/laws/components/category-group-section.tsx`
- Create: `frontend/src/app/laws/components/unclassified-section.tsx`

- [ ] **Step 1: Create stats-cards.tsx**

Create `frontend/src/app/laws/components/stats-cards.tsx`:

```typescript
interface StatsCardsProps {
  totalLaws: number;
  totalVersions: number;
  lastImported: string | null;
}

export default function StatsCards({ totalLaws, totalVersions, lastImported }: StatsCardsProps) {
  const formatted = lastImported
    ? new Date(lastImported).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
    : "—";

  return (
    <div className="flex gap-3 mb-5">
      <div className="flex-1 border border-gray-200 rounded-lg p-3 bg-white">
        <div className="text-xs text-gray-500">Total laws</div>
        <div className="text-2xl font-bold">{totalLaws}</div>
      </div>
      <div className="flex-1 border border-gray-200 rounded-lg p-3 bg-white">
        <div className="text-xs text-gray-500">Total versions</div>
        <div className="text-2xl font-bold">{totalVersions}</div>
      </div>
      <div className="flex-1 border border-gray-200 rounded-lg p-3 bg-white">
        <div className="text-xs text-gray-500">Last imported</div>
        <div className="text-2xl font-bold">{formatted}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create law-card.tsx**

Create `frontend/src/app/laws/components/law-card.tsx`:

```typescript
import Link from "next/link";
import { LibraryLaw } from "@/lib/api";

const STATE_COLORS: Record<string, string> = {
  actual: "bg-green-100 text-green-800",
  republished: "bg-blue-100 text-blue-800",
  amended: "bg-yellow-100 text-yellow-800",
  deprecated: "bg-red-100 text-red-800",
};

interface LawCardProps {
  law: LibraryLaw;
  showAssignButton?: boolean;
  onAssign?: (lawId: number) => void;
}

const DOC_TYPE_PREFIX: Record<string, string> = {
  law: "Legea",
  code: "Codul",
  government_ordinance: "OG",
  government_resolution: "HG",
  decree: "Decretul",
  order: "Ordinul",
  regulation: "Regulamentul",
  norm: "Norma",
  decision: "Decizia",
  other: "Legea",
};

export default function LawCard({ law, showAssignButton, onAssign }: LawCardProps) {
  const state = law.current_version?.state;
  const colorClass = state ? STATE_COLORS[state] || "bg-gray-100 text-gray-600" : "";
  const prefix = DOC_TYPE_PREFIX[law.document_type] || "Legea";

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-3 flex justify-between items-center hover:bg-gray-50 transition-colors">
      <Link href={`/laws/${law.id}`} className="flex-1 min-w-0">
        <div className="font-semibold text-sm text-gray-900">{law.title}</div>
        <div className="text-xs text-gray-500 mt-0.5">
          {prefix} {law.law_number}/{law.law_year}
          {state && (
            <span className={`ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${colorClass}`}>
              {state}
            </span>
          )}
        </div>
      </Link>
      <div className="flex items-center gap-2 ml-3 flex-shrink-0">
        <span className="text-xs text-gray-400">
          {law.version_count} version{law.version_count !== 1 ? "s" : ""}
        </span>
        {showAssignButton && onAssign && (
          <button
            onClick={(e) => { e.preventDefault(); onAssign(law.id); }}
            className="text-xs border border-amber-500 text-amber-600 px-2.5 py-1 rounded hover:bg-amber-50 transition-colors"
          >
            Assign category
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create category-group-section.tsx**

Create `frontend/src/app/laws/components/category-group-section.tsx`:

```typescript
"use client";

import { useState } from "react";
import { LibraryLaw, SuggestedLaw } from "@/lib/api";
import LawCard from "./law-card";

interface CategoryGroupSectionProps {
  groupSlug: string;
  groupName: string;
  colorHex: string;
  laws: LibraryLaw[];
  suggestedLaws: SuggestedLaw[];
  defaultExpanded?: boolean;
  onAssign?: (lawId: number) => void;
}

const PREVIEW_COUNT = 3;

export default function CategoryGroupSection({
  groupSlug,
  groupName,
  colorHex,
  laws,
  suggestedLaws,
  defaultExpanded = false,
  onAssign,
}: CategoryGroupSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const visibleLaws = expanded ? laws : laws.slice(0, PREVIEW_COUNT);
  const hasMore = laws.length > PREVIEW_COUNT;

  return (
    <div className="mb-5">
      {/* Group header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: colorHex }}
          />
          <span className="font-bold text-sm">{groupName}</span>
          <span className="text-xs text-gray-400">
            {laws.length} law{laws.length !== 1 ? "s" : ""}
          </span>
        </div>
        {hasMore && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            className="text-xs text-amber-700 hover:text-amber-900"
          >
            See all →
          </button>
        )}
      </div>

      {/* Law cards */}
      <div className="space-y-1.5">
        {visibleLaws.map((law) => (
          <LawCard key={law.id} law={law} onAssign={onAssign} />
        ))}
      </div>

      {expanded && hasMore && (
        <button
          onClick={() => setExpanded(false)}
          className="text-xs text-gray-400 hover:text-gray-600 mt-2"
        >
          Show less
        </button>
      )}

      {/* Per-category suggestions */}
      {suggestedLaws.length > 0 && expanded && (
        <div className="mt-3 border-t border-dashed border-gray-200 pt-3">
          <div className="text-xs text-gray-400 mb-2 italic">
            Sugestii pentru această categorie
          </div>
          {suggestedLaws.map((s) => (
            <div
              key={s.id}
              className="border border-dashed border-gray-200 rounded-lg p-3 mb-1.5 opacity-60 flex justify-between items-center"
            >
              <div className="text-sm text-gray-600">{s.title}</div>
              <button className="text-xs border border-blue-500 text-blue-600 px-2.5 py-1 rounded hover:bg-blue-50">
                + Importă
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create unclassified-section.tsx**

Create `frontend/src/app/laws/components/unclassified-section.tsx`:

```typescript
import { LibraryLaw } from "@/lib/api";
import LawCard from "./law-card";

interface UnclassifiedSectionProps {
  laws: LibraryLaw[];
  onAssign: (lawId: number) => void;
}

export default function UnclassifiedSection({ laws, onAssign }: UnclassifiedSectionProps) {
  if (laws.length === 0) return null;

  return (
    <div className="mt-8 border-t-2 border-dashed border-gray-200 pt-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="font-bold text-sm text-amber-700">Necategorizat</span>
        <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
          {laws.length} law{laws.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="space-y-1.5">
        {laws.map((law) => (
          <LawCard key={law.id} law={law} showAssignButton onAssign={onAssign} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/laws/components/
git commit -m "feat: add stats cards, law card, category group section, and unclassified section components"
```

---

### Task 7: Category Assignment Modal

**Files:**
- Create: `frontend/src/app/laws/components/category-modal.tsx`

- [ ] **Step 1: Create category-modal.tsx**

Create `frontend/src/app/laws/components/category-modal.tsx`:

```typescript
"use client";

import { useState, useMemo } from "react";
import { CategoryGroupData } from "@/lib/api";

interface CategoryModalProps {
  lawTitle: string;
  groups: CategoryGroupData[];
  prefillCategoryId?: number | null;
  onConfirm: (categoryId: number) => void;
  onSkip: () => void;
  onCancel: () => void;
}

export default function CategoryModal({
  lawTitle,
  groups,
  prefillCategoryId,
  onConfirm,
  onSkip,
  onCancel,
}: CategoryModalProps) {
  const [selectedId, setSelectedId] = useState<number | null>(prefillCategoryId ?? null);
  const [search, setSearch] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => {
    // Auto-expand the group containing the pre-filled category
    if (prefillCategoryId) {
      for (const g of groups) {
        if (g.categories.some((c) => c.id === prefillCategoryId)) {
          return new Set([g.slug]);
        }
      }
    }
    return new Set();
  });

  const filteredGroups = useMemo(() => {
    if (!search) return groups;
    const q = search.toLowerCase();
    return groups
      .map((g) => ({
        ...g,
        categories: g.categories.filter(
          (c) =>
            c.name_en.toLowerCase().includes(q) ||
            c.name_ro.toLowerCase().includes(q) ||
            (c.description || "").toLowerCase().includes(q)
        ),
      }))
      .filter((g) => g.categories.length > 0);
  }, [groups, search]);

  function toggleGroup(slug: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-200">
          <h3 className="font-bold text-lg">Assign Category</h3>
          <p className="text-sm text-gray-500 mt-1 truncate">{lawTitle}</p>
        </div>

        {/* Search */}
        <div className="px-4 pt-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search categories..."
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
        </div>

        {/* Category list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-1">
          {filteredGroups.map((g) => {
            const isExpanded = expandedGroups.has(g.slug) || !!search;
            return (
              <div key={g.slug}>
                <button
                  onClick={() => toggleGroup(g.slug)}
                  className="w-full text-left px-2 py-1.5 rounded flex items-center gap-2 hover:bg-gray-50 font-medium text-sm"
                >
                  <div
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: g.color_hex }}
                  />
                  <span className="text-xs text-gray-400">{isExpanded ? "▾" : "▸"}</span>
                  <span>{g.name_en}</span>
                </button>
                {isExpanded && (
                  <div className="pl-7 space-y-0.5">
                    {g.categories.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => setSelectedId(c.id)}
                        className={`w-full text-left px-3 py-2 rounded text-sm flex items-center gap-2 ${
                          selectedId === c.id
                            ? "bg-blue-50 border border-blue-200 text-blue-900"
                            : "hover:bg-gray-50 text-gray-700"
                        }`}
                      >
                        <div className={`w-3.5 h-3.5 rounded-full border flex-shrink-0 flex items-center justify-center text-[9px] ${
                          selectedId === c.id
                            ? "bg-blue-600 border-blue-600 text-white"
                            : "border-gray-300"
                        }`}>
                          {selectedId === c.id && "✓"}
                        </div>
                        <div>
                          <div>{c.name_en}</div>
                          {c.description && (
                            <div className="text-xs text-gray-400 mt-0.5">{c.description}</div>
                          )}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-200 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-md"
          >
            Cancel
          </button>
          <button
            onClick={onSkip}
            className="px-4 py-2 text-sm text-amber-700 border border-amber-300 hover:bg-amber-50 rounded-md"
          >
            Skip
          </button>
          <button
            onClick={() => selectedId && onConfirm(selectedId)}
            disabled={!selectedId}
            className="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed rounded-md"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/laws/components/category-modal.tsx
git commit -m "feat: add category assignment modal component"
```

---

### Task 8: Combined Search Component

**Files:**
- Create: `frontend/src/app/laws/components/combined-search.tsx`

- [ ] **Step 1: Create combined-search.tsx**

Create `frontend/src/app/laws/components/combined-search.tsx`. This component handles:
- Local search (instant, as-you-type)
- External search (on Enter/click Search)
- URL detection for direct import
- Advanced filters dropdown (reuses existing filter logic from `search-import-form.tsx`)

```typescript
"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { LocalSearchResult } from "@/lib/api";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SearchResult {
  ver_id: string;
  title: string;
  doc_type: string;
  number: string;
  date: string;
  date_iso: string | null;
  issuer: string;
  description: string;
  already_imported: boolean;
  local_law_id: number | null;
}

interface FilterOption {
  value: string;
  label: string;
}

const DEFAULT_ACT_TYPES: FilterOption[] = [
  { label: "LEGE", value: "1" },
  { label: "ORDONANȚĂ DE URGENȚĂ", value: "18" },
  { label: "ORDONANȚĂ", value: "13" },
  { label: "HOTĂRÂRE", value: "2" },
  { label: "ORDIN", value: "5" },
];

const DOC_TYPE_COLORS: Record<string, string> = {
  LEGE: "bg-blue-100 text-blue-800",
  "ORDONANȚĂ DE URGENȚĂ": "bg-amber-100 text-amber-800",
  OUG: "bg-amber-100 text-amber-800",
  "ORDONANȚĂ": "bg-orange-100 text-orange-800",
  OG: "bg-orange-100 text-orange-800",
  "HOTĂRÂRE": "bg-indigo-100 text-indigo-800",
  HG: "bg-indigo-100 text-indigo-800",
  ORDIN: "bg-purple-100 text-purple-800",
  DECIZIE: "bg-teal-100 text-teal-800",
  DECRET: "bg-rose-100 text-rose-800",
  "CONSTITUȚIE": "bg-red-100 text-red-800",
  COD: "bg-emerald-100 text-emerald-800",
};

const STATE_COLORS: Record<string, string> = {
  actual: "bg-green-100 text-green-800",
  republished: "bg-blue-100 text-blue-800",
  amended: "bg-yellow-100 text-yellow-800",
  deprecated: "bg-red-100 text-red-800",
};

interface CombinedSearchProps {
  onImportComplete: () => void;
}

export default function CombinedSearch({ onImportComplete }: CombinedSearchProps) {
  const router = useRouter();
  const [keyword, setKeyword] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Local search
  const [localResults, setLocalResults] = useState<LocalSearchResult[]>([]);
  const localTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // External search
  const [externalResults, setExternalResults] = useState<SearchResult[]>([]);
  const [externalTotal, setExternalTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Filters
  const [selectedDocType, setSelectedDocType] = useState("");
  const [lawNumber, setLawNumber] = useState("");
  const [year, setYear] = useState("");

  // Import state
  const [pendingImportId, setPendingImportId] = useState<string | null>(null);
  const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
  const [importedIds, setImportedIds] = useState<Set<string>>(new Set());

  // URL detection
  const detectedUrl = keyword.match(
    /legislatie\.just\.ro\/Public\/DetaliiDocument(?:Afis)?\/(\d+)/
  );

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowResults(false);
        setPendingImportId(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Local search as you type
  const doLocalSearch = useCallback(async (q: string) => {
    if (q.length < 3) {
      setLocalResults([]);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/laws/local-search?q=${encodeURIComponent(q)}`);
      if (res.ok) {
        const data = await res.json();
        setLocalResults(data.results);
      }
    } catch { /* silent */ }
  }, []);

  function handleInputChange(value: string) {
    setKeyword(value);
    setShowResults(true);
    if (localTimeout.current) clearTimeout(localTimeout.current);
    localTimeout.current = setTimeout(() => doLocalSearch(value), 300);
  }

  // External search
  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!keyword.trim() && !lawNumber && !year) return;
    setSearching(true);
    setSearchError(null);
    setShowResults(true);

    const params = new URLSearchParams();
    if (keyword) params.set("keyword", keyword);
    if (selectedDocType) params.set("doc_type", selectedDocType);
    if (lawNumber) params.set("number", lawNumber);
    if (year) params.set("year", year);
    params.set("include_repealed", "only_in_force");

    try {
      const res = await fetch(`${API_BASE}/api/laws/advanced-search?${params}`);
      if (!res.ok) throw new Error(`Search failed (${res.status})`);
      const data = await res.json();
      setExternalResults(data.results);
      setExternalTotal(data.total);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Search failed");
      setExternalResults([]);
      setExternalTotal(0);
    } finally {
      setSearching(false);
    }
  }

  async function handleImport(verId: string, importHistory: boolean) {
    setPendingImportId(null);
    setImportingIds((prev) => new Set(prev).add(verId));
    try {
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
      });
      if (!res.ok) throw new Error("Import failed");
      setImportedIds((prev) => new Set(prev).add(verId));
      onImportComplete();
    } catch { /* silent */ } finally {
      setImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(verId);
        return next;
      });
    }
  }

  // URL import state
  const [urlImporting, setUrlImporting] = useState(false);

  async function handleUrlImport(importHistory: boolean) {
    if (!detectedUrl) return;
    const verId = detectedUrl[1];
    setUrlImporting(true);
    try {
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
      });
      if (!res.ok) throw new Error("Import failed");
      setImportedIds((prev) => new Set(prev).add(verId));
      onImportComplete();
    } catch { /* silent */ } finally {
      setUrlImporting(false);
    }
  }

  const hasResults = localResults.length > 0 || externalResults.length > 0;

  return (
    <div ref={dropdownRef} className="relative mb-5">
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={keyword}
          onChange={(e) => handleInputChange(e.target.value)}
          onFocus={() => { if (keyword.length >= 3 || externalResults.length > 0) setShowResults(true); }}
          placeholder="Search by keyword, name, or paste a legislatie.just.ro link..."
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
        />
        {detectedUrl ? (
          <div className="relative" data-import-dropdown>
            <button
              type="button"
              onClick={() => setPendingImportId(detectedUrl[1])}
              disabled={urlImporting}
              className="rounded-md bg-green-600 px-5 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:bg-gray-300 whitespace-nowrap"
            >
              {urlImporting ? "Importing..." : "Import from link"}
            </button>
            {pendingImportId === detectedUrl[1] && !urlImporting && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg border border-gray-200 shadow-lg p-3 w-52">
                <p className="text-xs text-gray-500 mb-2">What to import?</p>
                <button onClick={() => handleUrlImport(false)} className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700">Current version only</button>
                <button onClick={() => handleUrlImport(true)} className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700">All historical versions</button>
                <button onClick={() => setPendingImportId(null)} className="w-full text-left px-3 py-1 text-xs rounded-md hover:bg-gray-50 text-gray-400 mt-1">Cancel</button>
              </div>
            )}
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={() => setShowFilters(!showFilters)}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm bg-white hover:bg-gray-50"
            >
              Filters {showFilters ? "▴" : "▾"}
            </button>
            <button
              type="submit"
              disabled={searching}
              className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
            >
              {searching ? "Searching..." : "Search"}
            </button>
          </>
        )}
      </form>

      {/* Filters */}
      {showFilters && (
        <div className="mt-2 p-3 bg-gray-50 rounded-lg border border-gray-200 grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Act Type</label>
            <select
              value={selectedDocType}
              onChange={(e) => setSelectedDocType(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            >
              <option value="">All types</option>
              {DEFAULT_ACT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Number</label>
            <input
              type="text"
              value={lawNumber}
              onChange={(e) => setLawNumber(e.target.value.replace(/\D/g, ""))}
              placeholder="e.g. 31"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Year</label>
            <input
              type="text"
              value={year}
              onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
              placeholder="e.g. 2015"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
        </div>
      )}

      {/* Results dropdown */}
      {showResults && hasResults && (
        <div className="absolute z-40 left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-[60vh] overflow-y-auto">
          {/* Local results */}
          {localResults.length > 0 && (
            <>
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
                <span className="text-[11px] font-bold text-gray-500 tracking-wider">IN YOUR LIBRARY</span>
                <span className="text-[11px] text-gray-400 ml-2">{localResults.length} match{localResults.length !== 1 ? "es" : ""}</span>
              </div>
              {localResults.map((r) => {
                const stateClass = r.current_version?.state ? STATE_COLORS[r.current_version.state] || "" : "";
                return (
                  <Link
                    key={r.id}
                    href={`/laws/${r.id}`}
                    className="block px-4 py-2.5 border-b border-gray-100 hover:bg-gray-50"
                    onClick={() => setShowResults(false)}
                  >
                    <div className="font-semibold text-sm">{r.title}</div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      Legea {r.law_number}/{r.law_year}
                      {r.current_version?.state && (
                        <span className={`ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${stateClass}`}>
                          {r.current_version.state}
                        </span>
                      )}
                      {r.category_name && (
                        <span className="ml-2 text-gray-400">{r.category_name}</span>
                      )}
                    </div>
                  </Link>
                );
              })}
            </>
          )}

          {/* External results */}
          {externalResults.length > 0 && (
            <>
              <div className="px-4 py-2 bg-amber-50 border-b border-gray-200">
                <span className="text-[11px] font-bold text-amber-700 tracking-wider">FROM LEGISLATIE.JUST.RO</span>
                <span className="text-[11px] text-amber-600 ml-2">{externalTotal} result{externalTotal !== 1 ? "s" : ""}</span>
              </div>
              {externalResults.map((r) => {
                const colorClass = DOC_TYPE_COLORS[r.doc_type] || "bg-gray-100 text-gray-600";
                const isImporting = importingIds.has(r.ver_id);
                const isImported = importedIds.has(r.ver_id) || r.already_imported;

                return (
                  <div key={r.ver_id} className="px-4 py-2.5 border-b border-gray-100 flex justify-between items-center">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold ${colorClass}`}>
                          {r.doc_type || "DOC"}
                        </span>
                        <span className="text-sm font-semibold">nr. {r.number} din {r.date}</span>
                      </div>
                      <p className="text-xs text-gray-500 truncate">{r.description || r.title}</p>
                    </div>
                    <div className="ml-3 flex-shrink-0">
                      {isImported ? (
                        <span className="text-xs text-green-600 bg-green-50 border border-green-200 px-2.5 py-1 rounded">
                          Imported
                        </span>
                      ) : (
                        <div className="relative" data-import-dropdown>
                          <button
                            onClick={() => setPendingImportId(r.ver_id)}
                            disabled={isImporting}
                            className="rounded-md bg-blue-600 px-3.5 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
                          >
                            {isImporting ? "..." : "Import"}
                          </button>
                          {pendingImportId === r.ver_id && !isImporting && (
                            <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg border border-gray-200 shadow-lg p-3 w-52">
                              <p className="text-xs text-gray-500 mb-2">What to import?</p>
                              <button
                                onClick={() => handleImport(r.ver_id, false)}
                                className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                              >
                                Current version only
                              </button>
                              <button
                                onClick={() => handleImport(r.ver_id, true)}
                                className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                              >
                                All historical versions
                              </button>
                              <button
                                onClick={() => setPendingImportId(null)}
                                className="w-full text-left px-3 py-1 text-xs rounded-md hover:bg-gray-50 text-gray-400 mt-1"
                              >
                                Cancel
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </>
          )}

          {/* Loading indicator */}
          {searching && (
            <div className="px-4 py-3 text-center text-xs text-gray-400">
              Searching legislatie.just.ro...
            </div>
          )}
        </div>
      )}

      {searchError && (
        <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded-md">
          <p className="text-sm text-red-700">{searchError}</p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/laws/components/combined-search.tsx
git commit -m "feat: add combined local+external search component"
```

---

### Task 9: Library Page — Main Component and Server Wrapper

**Files:**
- Create: `frontend/src/app/laws/library-page.tsx`
- Modify: `frontend/src/app/laws/page.tsx`

- [ ] **Step 1: Create library-page.tsx (main client component)**

Create `frontend/src/app/laws/library-page.tsx`:

```typescript
"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { api, LibraryData, LibraryLaw, CategoryGroupData } from "@/lib/api";
import Sidebar from "./components/sidebar";
import StatsCards from "./components/stats-cards";
import CategoryGroupSection from "./components/category-group-section";
import UnclassifiedSection from "./components/unclassified-section";
import CategoryModal from "./components/category-modal";
import CombinedSearch from "./components/combined-search";

export default function LibraryPage() {
  const [data, setData] = useState<LibraryData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Filters
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null);

  // Category modal
  const [assigningLawId, setAssigningLawId] = useState<number | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const result = await api.laws.library();
      setData(result);
      setError(null);
    } catch {
      setError("Could not connect to the backend. Make sure the API server is running.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Filter laws
  const filteredLaws = useMemo(() => {
    if (!data) return [];
    let laws = data.laws;

    if (selectedGroup) {
      laws = laws.filter((l) => l.category_group_slug === selectedGroup);
    }
    if (selectedCategory) {
      // Find category id from slug
      const catId = data.groups
        .flatMap((g) => g.categories)
        .find((c) => c.slug === selectedCategory)?.id;
      if (catId) {
        laws = laws.filter((l) => l.category_id === catId);
      }
    }
    if (selectedStatus) {
      laws = laws.filter((l) => l.current_version?.state === selectedStatus);
    }

    return laws;
  }, [data, selectedGroup, selectedCategory, selectedStatus]);

  // Compute filtered stats
  const filteredStats = useMemo(() => {
    if (!data) return { total_laws: 0, total_versions: 0, last_imported: null };
    const isFiltered = selectedGroup || selectedCategory || selectedStatus;
    if (!isFiltered) return data.stats;
    return {
      total_laws: filteredLaws.length,
      total_versions: filteredLaws.reduce((sum, l) => sum + l.version_count, 0),
      last_imported: data.stats.last_imported,
    };
  }, [data, filteredLaws, selectedGroup, selectedCategory, selectedStatus]);

  // Group laws by category_group_slug
  const groupedLaws = useMemo(() => {
    if (!data) return new Map<string, LibraryLaw[]>();
    const map = new Map<string, LibraryLaw[]>();
    for (const law of filteredLaws) {
      const key = law.category_group_slug || "__unclassified__";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(law);
    }
    return map;
  }, [data, filteredLaws]);

  const unclassifiedLaws = useMemo(() => {
    return filteredLaws.filter((l) => !l.category_id);
  }, [filteredLaws]);

  const classifiedLaws = useMemo(() => {
    return filteredLaws.filter((l) => l.category_id);
  }, [filteredLaws]);

  // Category assignment
  const assigningLaw = data?.laws.find((l) => l.id === assigningLawId);

  async function handleAssign(categoryId: number) {
    if (!assigningLawId) return;
    await api.laws.assignCategory(assigningLawId, categoryId);
    setAssigningLawId(null);
    fetchData();
  }

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading library...</div>;
  }

  if (error) {
    return (
      <div className="rounded-md bg-red-50 border border-red-200 p-4 mb-6">
        <p className="text-sm text-red-700">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div>
      {/* Header */}
      <div className="mb-4">
        <h1 className="text-3xl font-bold text-gray-900">Legal Library</h1>
        <p className="mt-1 text-gray-600">Browse Romanian laws with full version history</p>
      </div>

      {/* Combined search */}
      <CombinedSearch onImportComplete={fetchData} />

      {/* Main layout: sidebar + content */}
      <div className="flex border border-gray-200 rounded-lg bg-white min-h-[500px]">
        <Sidebar
          groups={data.groups}
          laws={data.laws}
          selectedGroup={selectedGroup}
          selectedCategory={selectedCategory}
          selectedStatus={selectedStatus}
          onSelectGroup={setSelectedGroup}
          onSelectCategory={setSelectedCategory}
          onSelectStatus={setSelectedStatus}
        />

        {/* Main content */}
        <div className="flex-1 p-5">
          <StatsCards
            totalLaws={filteredStats.total_laws}
            totalVersions={filteredStats.total_versions}
            lastImported={filteredStats.last_imported}
          />

          {/* Grouped law sections */}
          {data.groups
            .filter((g) => groupedLaws.has(g.slug) && groupedLaws.get(g.slug)!.some((l) => l.category_id))
            .map((g) => {
              const laws = groupedLaws.get(g.slug)!.filter((l) => l.category_id);
              const suggestions = data.suggested_laws.filter((s) => s.group_slug === g.slug);
              return (
                <CategoryGroupSection
                  key={g.slug}
                  groupSlug={g.slug}
                  groupName={g.name_en}
                  colorHex={g.color_hex}
                  laws={laws}
                  suggestedLaws={suggestions}
                  defaultExpanded={!!selectedGroup}
                  onAssign={setAssigningLawId}
                />
              );
            })}

          {/* Empty state */}
          {classifiedLaws.length === 0 && unclassifiedLaws.length === 0 && (
            <div className="text-center py-12">
              <h3 className="text-lg font-medium text-gray-900 mb-2">No laws found</h3>
              <p className="text-gray-600">
                {selectedGroup || selectedCategory || selectedStatus
                  ? "Try changing your filters."
                  : "Laws will appear here once they are imported."}
              </p>
            </div>
          )}

          {/* Unclassified */}
          <UnclassifiedSection
            laws={unclassifiedLaws}
            onAssign={setAssigningLawId}
          />
        </div>
      </div>

      {/* Category modal */}
      {assigningLawId && assigningLaw && (
        <CategoryModal
          lawTitle={assigningLaw.title}
          groups={data.groups}
          onConfirm={handleAssign}
          onSkip={() => setAssigningLawId(null)}
          onCancel={() => setAssigningLawId(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Update page.tsx to use the new library page**

Replace the contents of `frontend/src/app/laws/page.tsx` with:

```typescript
import LibraryPage from "./library-page";

export const dynamic = "force-dynamic";

export default function LawsPage() {
  return <LibraryPage />;
}
```

The old `search-import-form.tsx` and `delete-law-button.tsx` are no longer used by this page (but keep them — `delete-law-button.tsx` is still used on the law detail page).

- [ ] **Step 3: Verify the page renders**

Run the frontend dev server and navigate to `/laws`.

Expected: The redesigned Legal Library page with sidebar, stats cards, and laws grouped by category (all in "Necategorizat" since no categories are assigned yet). Search bar should work for both local and external search.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/laws/library-page.tsx frontend/src/app/laws/page.tsx
git commit -m "feat: redesign Legal Library page with category sidebar, stats cards, and combined search"
```

---

### Task 10: End-to-End Verification of Phase 1

- [ ] **Step 1: Start backend and frontend**

```bash
cd backend && python -m uvicorn app.main:app --reload &
cd frontend && npm run dev &
```

- [ ] **Step 2: Verify the library page loads**

Navigate to `http://localhost:3000/laws`. Check:
- Sidebar shows "All laws" with correct count
- CATEGORIES section shows only groups that exist (if no laws have categories, sidebar shows no groups — only "All laws" and suggested categories)
- STATUS section shows status counts
- Stats cards show correct totals
- "Necategorizat" section shows all existing laws with "Assign category" buttons

- [ ] **Step 3: Test category assignment**

Click "Assign category" on any law. Verify:
- Modal opens with grouped category list
- Search filter works
- Selecting a category and clicking "Confirm" assigns it
- The law moves from "Necategorizat" to the correct category group
- Stats cards and sidebar counts update

- [ ] **Step 4: Test combined search**

Type a keyword (≥3 chars) in the search bar. Verify:
- Local results appear instantly
- Click "Search" — external results load below
- Import button works

- [ ] **Step 5: Test sidebar filtering**

Click a category group in the sidebar. Verify:
- Main content filters to show only that group's laws
- Stats cards update
- "See all →" expands in-place

- [ ] **Step 6: Commit any fixes**

If any issues found during verification, fix and commit.

---

## Phase 2: Import Flow with Category Confirmation

### Task 11: Update Import to Show Category Modal

**Files:**
- Modify: `frontend/src/app/laws/components/combined-search.tsx`

- [ ] **Step 1: Add category modal to import flow**

Update `combined-search.tsx` to:
1. Accept `groups` prop (CategoryGroupData[])
2. After a successful import, instead of just calling `onImportComplete`, open the category modal with the imported law's ID
3. Look up `law_mappings` match via a new API call or by matching against the `suggested_laws` data passed from the parent
4. Modal buttons: "Confirmă și importă" (assigns category), "Importă fără categorie" (leaves unclassified), "Anulează" (deletes the just-imported law)

Add the following props to `CombinedSearchProps`:

```typescript
interface CombinedSearchProps {
  groups: CategoryGroupData[];
  suggestedLaws: SuggestedLaw[];
  onImportComplete: () => void;
}
```

After successful import response (which returns `{ law_id: number }`), show the category modal:

```typescript
const [importedLawForCategory, setImportedLawForCategory] = useState<{
  lawId: number;
  title: string;
  prefillCategoryId: number | null;
} | null>(null);
```

In `handleImport`, after success:
```typescript
const data = await res.json();
// Find matching suggestion for pre-fill
const match = suggestedLaws.find(s =>
  s.law_number === r.number || s.title.toLowerCase().includes(r.description?.toLowerCase() || "")
);
setImportedLawForCategory({
  lawId: data.law_id,
  title: r.description || r.title,
  prefillCategoryId: match?.category_id ?? null,
});
```

Add the modal render and handlers:
```typescript
async function handleImportCategoryConfirm(categoryId: number) {
  if (!importedLawForCategory) return;
  await api.laws.assignCategory(importedLawForCategory.lawId, categoryId);
  setImportedLawForCategory(null);
  onImportComplete();
}

function handleImportCategorySkip() {
  setImportedLawForCategory(null);
  onImportComplete();
}

async function handleImportCategoryCancel() {
  if (!importedLawForCategory) return;
  // Delete the just-imported law
  await api.laws.delete(importedLawForCategory.lawId);
  setImportedLawForCategory(null);
  onImportComplete();
}
```

- [ ] **Step 2: Update library-page.tsx to pass groups and suggestedLaws to CombinedSearch**

In `library-page.tsx`, update the CombinedSearch usage:

```typescript
<CombinedSearch
  groups={data.groups}
  suggestedLaws={data.suggested_laws}
  onImportComplete={fetchData}
/>
```

- [ ] **Step 3: Verify import flow**

Import a new law. After import:
- Category modal should appear
- If the law is in `law_mappings`, category should be pre-filled
- "Confirmă și importă" assigns category
- "Importă fără categorie" leaves unclassified
- "Anulează" deletes the law

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/laws/components/combined-search.tsx frontend/src/app/laws/library-page.tsx
git commit -m "feat: add category confirmation modal to import flow"
```

---

## Phase 3: Law Detail Breadcrumb + Settings Page

### Task 12: Law Detail Page — Category Breadcrumb

**Files:**
- Modify: `backend/app/routers/laws.py` (get_law endpoint — add category info to response)
- Modify: `frontend/src/app/laws/[id]/page.tsx`

- [ ] **Step 1: Add category info to get_law response**

In `backend/app/routers/laws.py`, modify the `get_law` endpoint to include category data:

```python
# After fetching the law, add:
category_info = None
if law.category_id and law.category:
    cat = law.category
    category_info = {
        "id": cat.id,
        "slug": cat.slug,
        "name_ro": cat.name_ro,
        "name_en": cat.name_en,
        "group_name_ro": cat.group.name_ro,
        "group_name_en": cat.group.name_en,
        "group_color_hex": cat.group.color_hex,
    }
```

Add `"category": category_info, "category_confidence": law.category_confidence,` to the returned dict.

- [ ] **Step 2: Add breadcrumb to the law detail page**

Read `frontend/src/app/laws/[id]/page.tsx` to understand its current structure, then add a breadcrumb above the law title:

```typescript
{law.category ? (
  <div className="flex items-center gap-2 text-sm mb-2">
    <div
      className="w-2.5 h-2.5 rounded-full"
      style={{ backgroundColor: law.category.group_color_hex }}
    />
    <span className="text-gray-500">{law.category.group_name_en}</span>
    <span className="text-gray-300">›</span>
    <span className="text-gray-700">{law.category.name_en}</span>
  </div>
) : (
  <div className="flex items-center gap-2 text-sm mb-2">
    <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded text-xs">Necategorizat</span>
  </div>
)}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/laws.py frontend/src/app/laws/\[id\]/page.tsx
git commit -m "feat: add category breadcrumb to law detail page"
```

---

### Task 13: Settings / Categories Page

**Files:**
- Create: `frontend/src/app/settings/categories/page.tsx`
- Create: `backend/app/routers/settings_categories.py`

- [ ] **Step 1: Create backend endpoint for categories list**

Create `backend/app/routers/settings_categories.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.category import CategoryGroup, Category
from app.models.law import Law

router = APIRouter(prefix="/api/settings/categories", tags=["settings"])


@router.get("/")
def list_categories(db: Session = Depends(get_db)):
    """List all categories with law counts for the settings page."""
    groups = db.query(CategoryGroup).order_by(CategoryGroup.sort_order).all()
    result = []
    for g in groups:
        for c in sorted(g.categories, key=lambda x: x.sort_order):
            count = db.query(Law).filter(Law.category_id == c.id).count()
            result.append({
                "id": c.id,
                "slug": c.slug,
                "name_ro": c.name_ro,
                "name_en": c.name_en,
                "description": c.description,
                "group_name": g.name_en,
                "group_slug": g.slug,
                "group_color": g.color_hex,
                "law_count": count,
            })
    return result


class NewSubcategoryRequest(BaseModel):
    group_slug: str
    name_ro: str
    name_en: str
    description: str = ""


@router.post("/subcategory")
def add_subcategory(req: NewSubcategoryRequest, db: Session = Depends(get_db)):
    """Add a new subcategory to an existing group."""
    group = db.query(CategoryGroup).filter(CategoryGroup.slug == req.group_slug).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    max_sort = max((c.sort_order for c in group.categories), default=0)
    slug = f"{req.group_slug}.{req.name_en.lower().replace(' ', '_')}"

    existing = db.query(Category).filter(Category.slug == slug).first()
    if existing:
        raise HTTPException(status_code=409, detail="Subcategory already exists")

    cat = Category(
        group_id=group.id,
        slug=slug,
        name_ro=req.name_ro,
        name_en=req.name_en,
        description=req.description,
        sort_order=max_sort + 1,
    )
    db.add(cat)
    db.commit()
    return {"id": cat.id, "slug": cat.slug}
```

Register in `main.py`:
```python
from app.routers import settings_categories
app.include_router(settings_categories.router)
```

- [ ] **Step 2: Add "Categories" tab to settings**

The settings page uses a tab system in `frontend/src/app/settings/settings-tabs.tsx`. Add a new tab:

In `frontend/src/app/settings/settings-tabs.tsx`, add to the `TABS` array:
```typescript
{ id: "categories", label: "Categories" },
```

The `TabId` type updates automatically.

- [ ] **Step 3: Create categories table component**

Create `frontend/src/app/settings/categories/categories-table.tsx`:

```typescript
"use client";

import { useState, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface CategoryRow {
  id: number;
  slug: string;
  name_ro: string;
  name_en: string;
  description: string | null;
  group_name: string;
  group_slug: string;
  group_color: string;
  law_count: number;
}

export function CategoriesTable() {
  const [categories, setCategories] = useState<CategoryRow[]>([]);
  const [loading, setLoading] = useState(true);

  // Add subcategory form
  const [showForm, setShowForm] = useState(false);
  const [formGroup, setFormGroup] = useState("");
  const [formNameRo, setFormNameRo] = useState("");
  const [formNameEn, setFormNameEn] = useState("");
  const [formDesc, setFormDesc] = useState("");

  async function fetchCategories() {
    try {
      const res = await fetch(`${API_BASE}/api/settings/categories`);
      if (res.ok) setCategories(await res.json());
    } catch { /* silent */ }
    setLoading(false);
  }

  useEffect(() => { fetchCategories(); }, []);

  async function handleAddSubcategory(e: React.FormEvent) {
    e.preventDefault();
    const res = await fetch(`${API_BASE}/api/settings/categories/subcategory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        group_slug: formGroup,
        name_ro: formNameRo,
        name_en: formNameEn,
        description: formDesc,
      }),
    });
    if (res.ok) {
      setShowForm(false);
      setFormGroup("");
      setFormNameRo("");
      setFormNameEn("");
      setFormDesc("");
      fetchCategories();
    }
  }

  // Get unique groups for the dropdown
  const groupSlugs = [...new Set(categories.map((c) => c.group_slug))];

  if (loading) return <div className="text-gray-400 py-4">Loading categories...</div>;

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Category Management</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
        >
          + Add subcategory
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <form onSubmit={handleAddSubcategory} className="mb-4 p-4 bg-gray-50 rounded-lg border space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Group</label>
              <select
                value={formGroup}
                onChange={(e) => setFormGroup(e.target.value)}
                required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
              >
                <option value="">Select group...</option>
                {groupSlugs.map((slug) => (
                  <option key={slug} value={slug}>
                    {categories.find((c) => c.group_slug === slug)?.group_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Name (EN)</label>
              <input type="text" value={formNameEn} onChange={(e) => setFormNameEn(e.target.value)} required className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Name (RO)</label>
              <input type="text" value={formNameRo} onChange={(e) => setFormNameRo(e.target.value)} required className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Description</label>
              <input type="text" value={formDesc} onChange={(e) => setFormDesc(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
          </div>
          <div className="flex gap-2">
            <button type="submit" className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded-md">Save</button>
            <button type="button" onClick={() => setShowForm(false)} className="text-sm text-gray-600 px-3 py-1.5">Cancel</button>
          </div>
        </form>
      )}

      {/* Table */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-4 py-2.5 font-semibold text-gray-600">Group</th>
              <th className="px-4 py-2.5 font-semibold text-gray-600">Subcategory</th>
              <th className="px-4 py-2.5 font-semibold text-gray-600">Description</th>
              <th className="px-4 py-2.5 font-semibold text-gray-600 text-right">Laws</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {categories.map((c) => (
              <tr key={c.id} className={c.law_count === 0 ? "opacity-50" : ""}>
                <td className="px-4 py-2.5">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: c.group_color }} />
                    {c.group_name}
                  </span>
                </td>
                <td className="px-4 py-2.5">{c.name_en}</td>
                <td className="px-4 py-2.5 text-gray-500 text-xs">{c.description}</td>
                <td className="px-4 py-2.5 text-right">{c.law_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire the tab in settings page**

In `frontend/src/app/settings/page.tsx`, add the import and tab case:

```typescript
import { CategoriesTable } from "./categories/categories-table";
```

Add inside the `SettingsTabs` children function:
```typescript
if (activeTab === "categories") {
  return <CategoriesTable />;
}
```

- [ ] **Step 5: Verify the settings page**

Navigate to `/settings?tab=categories`. Check:
- All categories listed with group, name, description, law count
- Categories with 0 laws shown with reduced opacity
- "Add subcategory" form works

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/settings_categories.py backend/app/main.py frontend/src/app/settings/categories/ frontend/src/app/settings/settings-tabs.tsx frontend/src/app/settings/page.tsx
git commit -m "feat: add Settings > Categories management tab"
```

---

### Task 14: Final End-to-End Verification

- [ ] **Step 1: Complete walkthrough**

Test the full flow:
1. Open `/laws` — library page with categories, sidebar, stats
2. Assign categories to a few unclassified laws via modal
3. Verify sidebar updates, filtering works, stats update
4. Import a new law via search — verify category modal appears
5. Navigate to a law detail page — verify breadcrumb
6. Open `/settings/categories` — verify management table

- [ ] **Step 2: Final commit and cleanup**

Review all changes, fix any issues, and commit.

```bash
git add -A
git commit -m "chore: Legal Library redesign - final polish"
```
