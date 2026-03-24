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
        ("sectoral", "sectoral.real_estate", "Imobiliar și urbanism", "Real estate", "Construcții, autorizări, cadastru, expropriere, fond funciar", False, 1),
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
