# Law category taxonomy — implementation instructions

## What this document is

This document tells you exactly what to build and how to behave regarding law categorization in Themis L&C. Read it fully before writing any code. Do not invent logic that is not described here. Do not auto-assign categories without user confirmation. Do not import suggested laws without explicit user action.

---

## 1. DB schema

Run these migrations:

```sql
CREATE TABLE category_groups (
  id          SERIAL PRIMARY KEY,
  slug        TEXT UNIQUE NOT NULL,
  name_ro     TEXT NOT NULL,
  name_en     TEXT NOT NULL,
  color_hex   TEXT NOT NULL,
  sort_order  INTEGER NOT NULL
);

CREATE TABLE categories (
  id          SERIAL PRIMARY KEY,
  group_id    INTEGER REFERENCES category_groups(id),
  slug        TEXT UNIQUE NOT NULL,
  name_ro     TEXT NOT NULL,
  name_en     TEXT NOT NULL,
  description TEXT,
  is_eu       BOOLEAN DEFAULT FALSE,
  sort_order  INTEGER NOT NULL
);

ALTER TABLE laws
  ADD COLUMN category_id         INTEGER REFERENCES categories(id),
  ADD COLUMN category_confidence TEXT CHECK (category_confidence IN ('manual', 'unclassified'));

CREATE TABLE law_mappings (
  id           SERIAL PRIMARY KEY,
  title        TEXT NOT NULL,
  law_number   TEXT,
  category_id  INTEGER NOT NULL REFERENCES categories(id),
  source       TEXT CHECK (source IN ('seed', 'user')) NOT NULL DEFAULT 'user',
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ON law_mappings (law_number);
CREATE INDEX ON law_mappings (category_id);
```

- `category_id` on `laws` — foreign key to `categories.id`. NULL means unclassified.
- `category_confidence` — how the category was assigned:
  - `"manual"` — user selected the category themselves in the confirmation dialog
  - `"unclassified"` — user skipped category assignment, must be assigned later
- `law_mappings` — the live lookup table used during import to pre-fill the category selector. Seeded from Section 3 at first deploy, then grows automatically as users categorize new laws. `source = 'seed'` entries come from the curated list below. `source = 'user'` entries are added automatically when a user manually categorizes a law not previously in the table. The `law_mappings` table is the single source of truth at runtime — the list in Section 3 of this document is only the initial seed.

Slug convention: `"group.subcategory"` (e.g. `"civil.property"`, `"fiscal.taxes"`). This allows filtering at group level with a simple `LIKE 'civil.%'` query.

---

## 2. Seed data

Run this seed once on first deploy (or as a migration). Do not re-run if rows already exist.

### Category groups

```sql
INSERT INTO category_groups (slug, name_ro, name_en, color_hex, sort_order) VALUES
  ('constitutional', 'Drept constituțional',          'Constitutional law',      '#534AB7', 1),
  ('civil',          'Drept civil',                   'Civil law',               '#185FA5', 2),
  ('criminal',       'Drept penal',                   'Criminal law',            '#993C1D', 3),
  ('commercial',     'Drept comercial și societar',   'Commercial law',          '#0F6E56', 4),
  ('fiscal',         'Drept fiscal și financiar',     'Fiscal & financial law',  '#854F0B', 5),
  ('administrative', 'Drept administrativ',           'Administrative law',      '#5F5E5A', 6),
  ('social',         'Drept social',                  'Social law',              '#1D9E75', 7),
  ('sectoral',       'Drept sectorial',               'Sectoral law',            '#888780', 8),
  ('eu',             'Drept european (UE)',            'EU law',                  '#185FA5', 9);
```

### Subcategories

```sql
INSERT INTO categories (group_id, slug, name_ro, name_en, description, is_eu, sort_order) VALUES
-- constitutional
((SELECT id FROM category_groups WHERE slug='constitutional'), 'constitutional.revision',  'Constituție și revizuire',        'Constitution & revision',       'Constituția, legi de revizuire, CCR', false, 1),
((SELECT id FROM category_groups WHERE slug='constitutional'), 'constitutional.rights',    'Drepturile omului',               'Human rights',                  'Libertăți fundamentale, protecția datelor, egalitate, CNCD', false, 2),
((SELECT id FROM category_groups WHERE slug='constitutional'), 'constitutional.electoral', 'Electoral și partide',            'Electoral & parties',           'Legi electorale, partide politice, referendum, finanțare', false, 3),
-- civil
((SELECT id FROM category_groups WHERE slug='civil'), 'civil.general',   'Drept civil general',    'General civil law',   'Codul Civil, persoane fizice/juridice, acte juridice', false, 1),
((SELECT id FROM category_groups WHERE slug='civil'), 'civil.property',  'Proprietate și bunuri',  'Property & assets',   'Proprietate privată/publică, uzufruct, servituți, carte funciară', false, 2),
((SELECT id FROM category_groups WHERE slug='civil'), 'civil.family',    'Familie și succesiuni',  'Family & succession', 'Căsătorie, divorț, adopție, tutelă, moștenire, testament', false, 3),
((SELECT id FROM category_groups WHERE slug='civil'), 'civil.contracts', 'Contracte și obligații', 'Contracts',           'Contracte numite/nenumite, răspundere civilă, garanții', false, 4),
((SELECT id FROM category_groups WHERE slug='civil'), 'civil.procedure', 'Procedură civilă',       'Civil procedure',     'Codul de Procedură Civilă, executare silită, arbitraj, mediere', false, 5),
-- criminal
((SELECT id FROM category_groups WHERE slug='criminal'), 'criminal.general',   'Drept penal general',      'General criminal law',  'Codul Penal, principii, răspundere penală, sancțiuni', false, 1),
((SELECT id FROM category_groups WHERE slug='criminal'), 'criminal.special',   'Infracțiuni speciale',     'Special offences',      'Evaziune fiscală, corupție, crimă organizată, DIICOT, DNA', false, 2),
((SELECT id FROM category_groups WHERE slug='criminal'), 'criminal.procedure', 'Procedură penală',         'Criminal procedure',    'Codul de Procedură Penală, urmărire, judecată, căi de atac', false, 3),
((SELECT id FROM category_groups WHERE slug='criminal'), 'criminal.execution', 'Executarea pedepselor',    'Execution of sentences','Legea executării pedepselor, probațiune, reabilitare', false, 4),
-- commercial
((SELECT id FROM category_groups WHERE slug='commercial'), 'commercial.companies',   'Societăți comerciale',          'Companies',             'Legea societăților, SRL/SA/SNC, registrul comerțului, ONRC', false, 1),
((SELECT id FROM category_groups WHERE slug='commercial'), 'commercial.insolvency',  'Insolvență și faliment',        'Insolvency',            'Procedura insolvenței, reorganizare judiciară, lichidare', false, 2),
((SELECT id FROM category_groups WHERE slug='commercial'), 'commercial.competition', 'Concurență și ajutor de stat',  'Competition law',       'Consiliul Concurenței, practici anticoncurențiale, ajutor de stat', false, 3),
((SELECT id FROM category_groups WHERE slug='commercial'), 'commercial.ip',          'Proprietate intelectuală',      'Intellectual property', 'Drepturi de autor, mărci, brevete, desene industriale, OSIM', false, 4),
((SELECT id FROM category_groups WHERE slug='commercial'), 'commercial.consumer',    'Protecția consumatorului',      'Consumer protection',   'ANPC, clauze abuzive, garanții comerciale, e-commerce', false, 5),
-- fiscal
((SELECT id FROM category_groups WHERE slug='fiscal'), 'fiscal.taxes',       'Impozite și taxe',            'Taxes',                'Codul Fiscal, TVA, impozit pe profit/venit, accize, ANAF', false, 1),
((SELECT id FROM category_groups WHERE slug='fiscal'), 'fiscal.procedure',   'Procedură fiscală',           'Fiscal procedure',     'Codul de Procedură Fiscală, inspecție, contestații, executare', false, 2),
((SELECT id FROM category_groups WHERE slug='fiscal'), 'fiscal.banking',     'Bancar și piețe de capital',  'Banking & capital',    'BNR, instituții de credit, ASF, piețe de capital, asigurări', false, 3),
((SELECT id FROM category_groups WHERE slug='fiscal'), 'fiscal.procurement', 'Achiziții publice',           'Public procurement',   'Legea achizițiilor, concesiuni, parteneriat public-privat, ANAP', false, 4),
-- administrative
((SELECT id FROM category_groups WHERE slug='administrative'), 'administrative.state',         'Organizarea statului',            'State organization', 'Guvern, ministere, autorități centrale, deconcentrate', false, 1),
((SELECT id FROM category_groups WHERE slug='administrative'), 'administrative.local',         'Administrație publică locală',    'Local government',   'Consilii județene/locale, primării, descentralizare', false, 2),
((SELECT id FROM category_groups WHERE slug='administrative'), 'administrative.civil_service', 'Funcție publică',                 'Civil service',      'Statutul funcționarilor publici, ANFP, răspundere disciplinară', false, 3),
((SELECT id FROM category_groups WHERE slug='administrative'), 'administrative.litigation',    'Contencios administrativ',        'Admin litigation',   'Legea contenciosului, acte administrative, contravenții', false, 4),
-- social
((SELECT id FROM category_groups WHERE slug='social'), 'social.labour',    'Dreptul muncii',                'Labour law',       'Codul Muncii, contracte colective, sindicate, conflicte muncă', false, 1),
((SELECT id FROM category_groups WHERE slug='social'), 'social.insurance', 'Asigurări și protecție socială','Social insurance', 'Pensii, CNPP, șomaj, ajutor social, CNAS', false, 2),
((SELECT id FROM category_groups WHERE slug='social'), 'social.health',    'Sănătate',                      'Health',           'Legea sănătății, CNAS, medicamente, răspundere medicală', false, 3),
((SELECT id FROM category_groups WHERE slug='social'), 'social.education', 'Educație',                      'Education',        'Legea educației, învățământ superior, ARACIS, acreditare', false, 4),
-- sectoral
((SELECT id FROM category_groups WHERE slug='sectoral'), 'sectoral.real_estate',  'Imobiliar și urbanism',       'Real estate',     'Construcții, autorizații, cadastru, expropriere, fond funciar', false, 1),
((SELECT id FROM category_groups WHERE slug='sectoral'), 'sectoral.environment',  'Mediu',                       'Environment',     'Legea mediului, deșeuri, ape, păduri, arii protejate, ANPM', false, 2),
((SELECT id FROM category_groups WHERE slug='sectoral'), 'sectoral.energy',       'Energie și resurse',          'Energy',          'ANRE, electricitate, gaz, petrol, minerale, regenerabile', false, 3),
((SELECT id FROM category_groups WHERE slug='sectoral'), 'sectoral.transport',    'Transport și infrastructură', 'Transport',       'Circulație rutieră, CFR, CNAIR, navigație, aviație civilă', false, 4),
((SELECT id FROM category_groups WHERE slug='sectoral'), 'sectoral.tech',         'Tehnologie și comunicații',   'Tech & telecom',  'ANCOM, telecomunicații, semnătură electronică, comerț electronic', false, 5),
((SELECT id FROM category_groups WHERE slug='sectoral'), 'sectoral.agriculture',  'Agricultură și alimentație',  'Agriculture',     'MADR, APIA, fond funciar agricol, veterinar, ANSVSA', false, 6),
((SELECT id FROM category_groups WHERE slug='sectoral'), 'sectoral.media',        'Audiovizual și media',        'Media',           'Legea audiovizualului, CNA, drepturi de difuzare, presă scrisă', false, 7),
((SELECT id FROM category_groups WHERE slug='sectoral'), 'sectoral.defence',      'Apărare și securitate',       'Defence',         'MApN, SRI, SIE, ordine publică, MAI, stare de urgență', false, 8),
-- eu
((SELECT id FROM category_groups WHERE slug='eu'), 'eu.regulation', 'Regulamente UE',          'EU regulations', 'Direct aplicabile — GDPR, AI Act, NIS2, MDR, DMA, DSA', true, 1),
((SELECT id FROM category_groups WHERE slug='eu'), 'eu.directive',  'Directive UE transpuse',  'EU directives',  'Directive transpuse în drept român — legătură lege națională ↔ directivă sursă', true, 2),
((SELECT id FROM category_groups WHERE slug='eu'), 'eu.treaty',     'Drept primar și tratate', 'EU treaties',    'TFUE, TUE, Carta drepturilor fundamentale, protocoale', true, 3),
((SELECT id FROM category_groups WHERE slug='eu'), 'eu.caselaw',    'Jurisprudență CJUE',      'CJEU case law',  'Hotărâri CJUE relevante pentru România, trimiteri preliminare', true, 4);
```

---

## 3. Initial law mappings seed

This is the initial curated list of known Romanian laws and their categories. At first deploy, seed all entries below into the `law_mappings` table with `source = 'seed'`.

After first deploy, `law_mappings` is the live source of truth — it grows automatically as users import and manually categorize new laws (see Section 4). Do not re-seed this list on subsequent deploys. Do not edit `law_mappings` rows at runtime — the DB is the owner.

**Laws listed here that are not yet imported by the user are shown as suggestions in the UI. They are never auto-imported. The user must click Import on each one individually.**

```
constitutional.revision
  Constituția României (1991, republicată 2003)

constitutional.rights
  Legea 190/2018 — implementarea GDPR în dreptul național
  Legea 506/2004 — prelucrarea datelor personale în comunicații electronice
  OUG 119/2006 — măsuri pentru aplicarea unor regulamente comunitare privind drepturile cetățenilor

constitutional.electoral
  Legea 208/2015 — alegerea Senatului și Camerei Deputaților
  Legea 370/2004 — alegerea Președintelui României
  Legea 115/2015 — alegerea autorităților administrației publice locale
  Legea 334/2006 — finanțarea activității partidelor politice

civil.general
  Legea 287/2009 — Codul Civil (republicat)
  Legea 71/2011 — punerea în aplicare a Codului Civil
  Decretul-lege 31/1954 — persoane fizice și juridice (abrogat parțial)

civil.property
  Legea 7/1996 — cadastrul și publicitatea imobiliară
  Legea 10/2001 — regimul juridic al imobilelor preluate abuziv
  Legea 18/1991 — fondul funciar
  Legea 50/1991 — autorizarea executării lucrărilor de construcții
  Legea 33/1994 — exproprierea pentru cauze de utilitate publică

civil.family
  Legea 272/2004 — protecția și promovarea drepturilor copilului
  Legea 273/2004 — procedura adopției
  Legea 217/2003 — prevenirea și combaterea violenței domestice

civil.contracts
  Legea 193/2000 — clauzele abuzive din contractele cu consumatorii
  Legea 455/2001 — semnătura electronică
  Legea 365/2002 — comerțul electronic

civil.procedure
  Legea 134/2010 — Codul de Procedură Civilă (republicat)
  Legea 85/2014 — procedurile de prevenire a insolvenței și de insolvență
  Legea 192/2006 — medierea și organizarea profesiei de mediator
  Legea 188/2000 — executorii judecătorești

criminal.general
  Legea 286/2009 — Codul Penal
  Legea 187/2012 — punerea în aplicare a Codului Penal

criminal.special
  Legea 241/2005 — prevenirea și combaterea evaziunii fiscale
  Legea 78/2000 — prevenirea, descoperirea și sancționarea faptelor de corupție
  Legea 656/2002 — prevenirea și combaterea spălării banilor
  Legea 143/2000 — prevenirea și combaterea traficului și consumului ilicit de droguri
  Legea 39/2003 — prevenirea și combaterea criminalității organizate
  OUG 43/2002 — Direcția Națională Anticorupție (DNA)

criminal.procedure
  Legea 135/2010 — Codul de Procedură Penală
  Legea 254/2013 — executarea pedepselor și a măsurilor privative de libertate

criminal.execution
  Legea 253/2013 — executarea pedepselor, a măsurilor educative și a altor măsuri neprivative de libertate
  Legea 252/2013 — organizarea și funcționarea sistemului de probațiune

commercial.companies
  Legea 31/1990 — societățile comerciale (republicată)
  Legea 26/1990 — registrul comerțului (republicată)
  Legea 1/2005 — organizarea și funcționarea cooperației
  OUG 44/2008 — desfășurarea activităților economice de către persoanele fizice autorizate (PFA)

commercial.insolvency
  Legea 85/2014 — procedurile de prevenire a insolvenței și de insolvență
  Legea 85/2006 — procedura insolvenței (abrogată, referită istoric)

commercial.competition
  Legea 21/1996 — concurența (republicată)
  Legea 11/1991 — combaterea concurenței neloiale
  OUG 117/2006 — procedurile naționale în domeniul ajutorului de stat

commercial.ip
  Legea 8/1996 — dreptul de autor și drepturile conexe
  Legea 64/1991 — brevetele de invenție (republicată)
  Legea 84/1998 — mărcile și indicațiile geografice (republicată)
  Legea 129/1992 — protecția desenelor și modelelor industriale

commercial.consumer
  Legea 449/2003 — vânzarea produselor și garanțiile asociate (republicată)
  OUG 34/2014 — drepturile consumatorilor în contractele cu profesioniști
  Legea 363/2007 — combaterea practicilor incorecte ale comercianților

fiscal.taxes
  Legea 227/2015 — Codul Fiscal
  OUG 6/2019 — stabilirea unor măsuri privind starea de insolvabilitate
  Legea 241/2005 — prevenirea și combaterea evaziunii fiscale
  HG 1/2016 — normele metodologice de aplicare a Codului Fiscal

fiscal.procedure
  Legea 207/2015 — Codul de Procedură Fiscală
  OUG 74/2013 — măsuri pentru îmbunătățirea și reorganizarea ANAF

fiscal.banking
  Legea 58/1998 — activitatea bancară (republicată)
  Legea 237/2015 — autorizarea și supravegherea activității de asigurare
  Legea 126/2018 — piețele de instrumente financiare
  OUG 99/2006 — instituțiile de credit și adecvarea capitalului
  Legea 32/2000 — activitatea de asigurare și supravegherea asigurărilor

fiscal.procurement
  Legea 98/2016 — achizițiile publice
  Legea 99/2016 — achizițiile sectoriale
  Legea 100/2016 — concesiunile de lucrări și servicii
  HG 395/2016 — normele metodologice de aplicare a Legii 98/2016

administrative.state
  Legea 90/2001 — organizarea și funcționarea Guvernului
  Legea 340/2004 — prefectul și instituția prefectului (republicată)
  Legea 188/1999 — statutul funcționarilor publici (republicată)

administrative.local
  Legea 215/2001 — administrația publică locală (republicată)
  Legea 195/2006 — descentralizarea
  OUG 57/2019 — Codul Administrativ

administrative.civil_service
  Legea 188/1999 — statutul funcționarilor publici (republicată)
  Legea 7/2004 — Codul de Conduită al funcționarilor publici
  Legea 477/2004 — Codul de Conduită al personalului contractual

administrative.litigation
  Legea 554/2004 — contenciosul administrativ
  OG 2/2001 — regimul juridic al contravențiilor
  Legea 101/2016 — remediile și căile de atac în achiziții publice

social.labour
  Legea 53/2003 — Codul Muncii (republicat)
  Legea 62/2011 — dialogul social (republicată)
  Legea 279/2005 — ucenicia la locul de muncă (republicată)
  Legea 156/2000 — protecția cetățenilor români care lucrează în străinătate

social.insurance
  Legea 263/2010 — sistemul unitar de pensii publice
  Legea 76/2002 — sistemul asigurărilor pentru șomaj
  Legea 416/2001 — venitul minim garantat
  Legea 292/2011 — asistența socială

social.health
  Legea 95/2006 — reforma în domeniul sănătății (republicată)
  Legea 46/2003 — drepturile pacientului
  Legea 339/2005 — regimul juridic al plantelor, substanțelor și preparatelor stupefiante

social.education
  Legea 1/2011 — educația națională
  OUG 75/2005 — asigurarea calității educației (republicată)
  Legea 288/2004 — organizarea studiilor universitare

sectoral.real_estate
  Legea 50/1991 — autorizarea executării lucrărilor de construcții (republicată)
  Legea 350/2001 — amenajarea teritoriului și urbanismul
  Legea 255/2010 — exproprierea pentru cauze de utilitate publică
  Legea 7/1996 — cadastrul și publicitatea imobiliară (republicată)

sectoral.environment
  Legea 137/1995 — protecția mediului (republicată)
  OUG 195/2005 — protecția mediului
  Legea 211/2011 — regimul deșeurilor (republicată)
  Legea 107/1996 — legea apelor
  Legea 46/2008 — Codul Silvic (republicat)

sectoral.energy
  Legea 123/2012 — energia electrică și gazele naturale
  Legea 220/2008 — sistemul de promovare a producerii energiei din surse regenerabile (republicată)
  Legea 132/2015 — schema de sprijin pentru energia electrică din surse regenerabile
  OG 60/2000 — reglementarea activităților din sectorul gazelor naturale (referit istoric)

sectoral.transport
  OUG 195/2002 — circulația pe drumurile publice (republicată)
  Legea 38/2003 — transportul în regim de taxi și în regim de închiriere
  OG 27/2011 — transporturile rutiere
  Legea 198/2015 — Codul Aerian Civil al României

sectoral.tech
  Legea 506/2004 — prelucrarea datelor cu caracter personal în comunicații electronice
  OUG 111/2011 — comunicațiile electronice
  Legea 455/2001 — semnătura electronică (republicată)
  Legea 365/2002 — comerțul electronic (republicată)
  Legea 40/2016 — modificarea Legii 506/2004

sectoral.agriculture
  Legea 18/1991 — fondul funciar (republicată)
  Legea 17/2014 — vânzarea-cumpărarea terenurilor agricole
  Legea 145/2014 — reglementarea activității de agroturism
  OUG 3/2015 — acordarea de sprijin financiar producătorilor agricoli

sectoral.media
  Legea 504/2002 — legea audiovizualului
  Legea 41/1994 — organizarea și funcționarea CNA (republicată)
  Legea 8/1996 — dreptul de autor (inclusiv difuzare)

eu.regulation
  Regulamentul (UE) 2016/679 — GDPR
  Regulamentul (UE) 2024/1689 — AI Act
  Regulamentul (UE) 2022/2065 — DSA (Digital Services Act)
  Regulamentul (UE) 2022/1925 — DMA (Digital Markets Act)
  Regulamentul (UE) 2017/745 — MDR (dispozitive medicale)
  Regulamentul (UE) 1215/2012 — competența judiciară în materie civilă (Bruxelles I)
  Regulamentul (UE) 593/2008 — legea aplicabilă obligațiilor contractuale (Roma I)
  Regulamentul (UE) 864/2007 — legea aplicabilă obligațiilor necontractuale (Roma II)

eu.directive
  Directiva 2011/83/UE — drepturile consumatorilor (transpusă prin OUG 34/2014)
  Directiva 2019/1023/UE — restructurare și insolvență (transpusă prin Legea 216/2022)
  Directiva 2022/2557/UE — reziliența entităților critice (CER)
  Directiva 2022/2555/UE — NIS2
  Directiva 2023/970/UE — transparența salarială
  Directiva 2009/72/CE — piața internă a energiei electrice

eu.treaty
  Tratatul privind funcționarea Uniunii Europene (TFUE)
  Tratatul privind Uniunea Europeană (TUE)
  Carta drepturilor fundamentale a Uniunii Europene
  Tratatul de aderare a României la UE (2005, în vigoare 2007)

eu.caselaw
  (adăugate manual la import, caz cu caz)
```

---

## 4. How to handle an imported law — decision tree

When a law is imported (scraped or pasted), follow this exact process. **Never silently assign a category and save. Always show the user a confirmation step. There is no keyword matching — if the law is not found in `law_mappings`, the user picks the category manually.**

```
STEP 1 — Look up in law_mappings table
  Query: SELECT category_id FROM law_mappings
         WHERE law_number = $imported_law_number
            OR title ILIKE $imported_law_title
         LIMIT 1

  MATCH FOUND → pre-fill the category selector with the matched category
                → go to STEP 2
  NO MATCH    → open the category selector with nothing pre-filled
                → go to STEP 2

STEP 2 — Always show the user a category confirmation dialog
  Show a modal with:
    - The law title
    - The category selector pre-filled if matched in STEP 1, empty otherwise
    - The full list of categories as selectable options, grouped by parent group
    - A search/filter input to find a category quickly
    - "Confirmă și importă" button → go to STEP 3
    - "Importă fără categorie" button → saves law with category_id = NULL,
                                        category_confidence = "unclassified". STOP.
    - "Anulează" button → cancels the import entirely. STOP.

  The user MUST interact with this dialog. Do not skip it.
  Do not auto-save the law without user confirmation.

STEP 3 — Save the law and update law_mappings
  Save the law row with:
    - category_id = user's selection
    - category_confidence = "manual"

  Then check if this law already exists in law_mappings:
    IF NOT EXISTS (SELECT 1 FROM law_mappings WHERE law_number = $law_number OR title ILIKE $title):
      INSERT INTO law_mappings (title, law_number, category_id, source)
      VALUES ($title, $law_number, $category_id, 'user')

  This means the next time anyone imports the same law, it will be pre-filled automatically.
  Do NOT insert if the law was already in law_mappings (source = 'seed' or 'user') — never duplicate.
```

---

## 5. UI — Legal Library sidebar

The sidebar has two sections separated by a visual divider:

### Section A — Active categories (laws already imported by the user)
- Show only category groups that contain at least one imported law
- Each group is expandable to show its subcategories with law counts
- Clicking a subcategory filters the main law list
- Clicking a group header shows all laws across its subcategories

### Section B — Suggested categories (not yet imported)
- Shown below a divider labeled "Sugestii neimportate"
- Lists category groups from Section 3 that have zero imported laws
- Displayed in italic, muted style — informational only
- Clicking a suggested category opens a panel showing which predefined laws belong there, each with an individual Import button
- No law count badge on suggested categories
- Do NOT mix these with active categories

---

## 6. UI — Suggested laws within an active category

When viewing a category that has imported laws, show a secondary section below titled "Sugestii pentru această categorie" listing predefined laws from Section 3 that belong here but are not yet imported.

- Visually distinct: dashed border, reduced opacity
- Each has an individual "+ Importă" button
- Clicking "+ Importă" triggers the full import flow (Section 4, STEP 3) with the category pre-filled
- Never auto-import. Never show these mixed with real imported laws.

---

## 7. UI — Unclassified laws

Laws with `category_confidence = "unclassified"`:

- Shown in a dedicated "Necategorizat" section at the bottom of the library
- Amber badge: "Fără categorie"
- Each card has an "Asignează categorie" button that opens the category selector modal
- Never hidden — always visible and actionable

---

## 8. UI — Law detail page

Show the category as a breadcrumb above the law title:

```
[colored dot]  Group name  ›  Subcategory name
```

Example: `● Drept fiscal și financiar › Impozite și taxe`

Dot color = `category_groups.color_hex`. If unclassified, show a muted "Necategorizat" badge instead.

---

## 9. UI — Settings / Categories management

Add a "Categorii" page in Settings:

- Table of all categories: name, group, law count, actions
- "Reassign" action: opens modal to move a law to a different category
- Admin can add new subcategories to existing groups (name_ro, name_en, description, group)
- Admin cannot create new top-level groups from the UI — that requires a code change
- Flag categories with 0 laws as potentially safe to hide from the sidebar

---

## 10. Hard rules — do not deviate from these

- **Never auto-import a law.** The user must always trigger import explicitly.
- **Never silently assign a category.** Always show the confirmation dialog (Section 4, STEP 2).
- **No keyword matching.** The only automatic behavior is a pre-fill when the law matches a row in `law_mappings`. Everything else is manual user selection.
- **Always insert into `law_mappings` after a manual categorization** (STEP 3), unless the law is already there. This is how the table grows over time.
- **Never duplicate `law_mappings` rows.** Check before inserting. One row per law (matched by `law_number` or `title`).
- **Never mix suggested laws with imported laws** in the main list. Always visually separate them.
- **`law_mappings` is the runtime source of truth.** The list in Section 3 is only the initial seed. Do not re-seed on subsequent deploys.
- **The taxonomy in Section 2 is the only allowed set of categories.** Do not create categories dynamically. If a law fits nothing the user selects, it goes to `unclassified`.
- **`category_confidence` must always be set on save.** Never NULL. Values: `"manual"` | `"unclassified"`.
