"""Category taxonomy seed and management service."""
import logging
from sqlalchemy import func
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
        ("eu", "eu.decision", "Decizii UE", "EU decisions", "Decizii ale Consiliului, Comisiei, BCE — obligatorii pentru destinatari", True, 5),
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
    # Tuples: (category_slug, title, law_number, law_year, document_type)
    # document_type values match KIND_MAP output from leropa_service.py:
    #   "law", "emergency_ordinance", "government_ordinance",
    #   "government_resolution", "decree", "constitution", "code",
    #   "regulation", "directive"
    mappings_data = [
        # constitutional.revision
        ("constitutional.revision", "Constituția României (1991, republicată 2003)", None, 1991, "constitution"),
        # constitutional.rights
        ("constitutional.rights", "Legea 190/2018 — implementarea GDPR în dreptul național", "190", 2018, "law"),
        ("constitutional.rights", "Legea 506/2004 — prelucrarea datelor personale în comunicații electronice", "506", 2004, "law"),
        ("constitutional.rights", "OUG 119/2006 — măsuri pentru aplicarea unor regulamente comunitare privind drepturile cetățenilor", "119", 2006, "emergency_ordinance"),
        # constitutional.electoral
        ("constitutional.electoral", "Legea 208/2015 — alegerea Senatului și Camerei Deputaților", "208", 2015, "law"),
        ("constitutional.electoral", "Legea 370/2004 — alegerea Președintelui României", "370", 2004, "law"),
        ("constitutional.electoral", "Legea 115/2015 — alegerea autorităților administrației publice locale", "115", 2015, "law"),
        ("constitutional.electoral", "Legea 334/2006 — finanțarea activității partidelor politice", "334", 2006, "law"),
        # civil.general
        ("civil.general", "Legea 287/2009 — Codul Civil (republicat)", "287", 2009, "law"),
        ("civil.general", "Legea 71/2011 — punerea în aplicare a Codului Civil", "71", 2011, "law"),
        ("civil.general", "Decretul-lege 31/1954 — persoane fizice și juridice (abrogat parțial)", "31", 1954, "decree"),
        # civil.property
        ("civil.property", "Legea 7/1996 — cadastrul și publicitatea imobiliară", "7", 1996, "law"),
        ("civil.property", "Legea 10/2001 — regimul juridic al imobilelor preluate abuziv", "10", 2001, "law"),
        ("civil.property", "Legea 18/1991 — fondul funciar", "18", 1991, "law"),
        ("civil.property", "Legea 50/1991 — autorizarea executării lucrărilor de construcții", "50", 1991, "law"),
        ("civil.property", "Legea 33/1994 — exproprierea pentru cauze de utilitate publică", "33", 1994, "law"),
        # civil.family
        ("civil.family", "Legea 272/2004 — protecția și promovarea drepturilor copilului", "272", 2004, "law"),
        ("civil.family", "Legea 273/2004 — procedura adopției", "273", 2004, "law"),
        ("civil.family", "Legea 217/2003 — prevenirea și combaterea violenței domestice", "217", 2003, "law"),
        # civil.contracts
        ("civil.contracts", "Legea 193/2000 — clauzele abuzive din contractele cu consumatorii", "193", 2000, "law"),
        ("civil.contracts", "Legea 455/2001 — semnătura electronică", "455", 2001, "law"),
        ("civil.contracts", "Legea 365/2002 — comerțul electronic", "365", 2002, "law"),
        # civil.procedure
        ("civil.procedure", "Legea 134/2010 — Codul de Procedură Civilă (republicat)", "134", 2010, "law"),
        ("civil.procedure", "Legea 85/2014 — procedurile de prevenire a insolvenței și de insolvență", "85", 2014, "law"),
        ("civil.procedure", "Legea 192/2006 — medierea și organizarea profesiei de mediator", "192", 2006, "law"),
        ("civil.procedure", "Legea 188/2000 — executorii judecătorești", "188", 2000, "law"),
        # criminal.general
        ("criminal.general", "Legea 286/2009 — Codul Penal", "286", 2009, "law"),
        ("criminal.general", "Legea 187/2012 — punerea în aplicare a Codului Penal", "187", 2012, "law"),
        # criminal.special
        ("criminal.special", "Legea 241/2005 — prevenirea și combaterea evaziunii fiscale", "241", 2005, "law"),
        ("criminal.special", "Legea 78/2000 — prevenirea, descoperirea și sancționarea faptelor de corupție", "78", 2000, "law"),
        ("criminal.special", "Legea 656/2002 — prevenirea și combaterea spălării banilor", "656", 2002, "law"),
        ("criminal.special", "Legea 143/2000 — prevenirea și combaterea traficului și consumului ilicit de droguri", "143", 2000, "law"),
        ("criminal.special", "Legea 39/2003 — prevenirea și combaterea criminalității organizate", "39", 2003, "law"),
        ("criminal.special", "OUG 43/2002 — Direcția Națională Anticorupție (DNA)", "43", 2002, "emergency_ordinance"),
        # criminal.procedure
        ("criminal.procedure", "Legea 135/2010 — Codul de Procedură Penală", "135", 2010, "law"),
        ("criminal.procedure", "Legea 254/2013 — executarea pedepselor și a măsurilor privative de libertate", "254", 2013, "law"),
        # criminal.execution
        ("criminal.execution", "Legea 253/2013 — executarea pedepselor, a măsurilor educative și a altor măsuri neprivative de libertate", "253", 2013, "law"),
        ("criminal.execution", "Legea 252/2013 — organizarea și funcționarea sistemului de probațiune", "252", 2013, "law"),
        # commercial.companies
        ("commercial.companies", "Legea 31/1990 — societățile comerciale (republicată)", "31", 1990, "law"),
        ("commercial.companies", "Legea 26/1990 — registrul comerțului (republicată)", "26", 1990, "law"),
        ("commercial.companies", "Legea 1/2005 — organizarea și funcționarea cooperației", "1", 2005, "law"),
        ("commercial.companies", "OUG 44/2008 — desfășurarea activităților economice de către persoanele fizice autorizate (PFA)", "44", 2008, "emergency_ordinance"),
        # commercial.insolvency
        ("commercial.insolvency", "Legea 85/2014 — procedurile de prevenire a insolvenței și de insolvență", "85", 2014, "law"),
        ("commercial.insolvency", "Legea 85/2006 — procedura insolvenței (abrogată, referită istoric)", "85", 2006, "law"),
        # commercial.competition
        ("commercial.competition", "Legea 21/1996 — concurența (republicată)", "21", 1996, "law"),
        ("commercial.competition", "Legea 11/1991 — combaterea concurenței neloiale", "11", 1991, "law"),
        ("commercial.competition", "OUG 117/2006 — procedurile naționale în domeniul ajutorului de stat", "117", 2006, "emergency_ordinance"),
        # commercial.ip
        ("commercial.ip", "Legea 8/1996 — dreptul de autor și drepturile conexe", "8", 1996, "law"),
        ("commercial.ip", "Legea 64/1991 — brevetele de invenție (republicată)", "64", 1991, "law"),
        ("commercial.ip", "Legea 84/1998 — mărcile și indicațiile geografice (republicată)", "84", 1998, "law"),
        ("commercial.ip", "Legea 129/1992 — protecția desenelor și modelelor industriale", "129", 1992, "law"),
        # commercial.consumer
        ("commercial.consumer", "Legea 449/2003 — vânzarea produselor și garanțiile asociate (republicată)", "449", 2003, "law"),
        ("commercial.consumer", "OUG 34/2014 — drepturile consumatorilor în contractele cu profesioniști", "34", 2014, "emergency_ordinance"),
        ("commercial.consumer", "Legea 363/2007 — combaterea practicilor incorecte ale comercianților", "363", 2007, "law"),
        # fiscal.taxes
        ("fiscal.taxes", "Legea 227/2015 — Codul Fiscal", "227", 2015, "law"),
        ("fiscal.taxes", "OUG 6/2019 — stabilirea unor măsuri privind starea de insolvabilitate", "6", 2019, "emergency_ordinance"),
        ("fiscal.taxes", "Legea 241/2005 — prevenirea și combaterea evaziunii fiscale", "241", 2005, "law"),
        ("fiscal.taxes", "HG 1/2016 — normele metodologice de aplicare a Codului Fiscal", "1", 2016, "government_resolution"),
        # fiscal.procedure
        ("fiscal.procedure", "Legea 207/2015 — Codul de Procedură Fiscală", "207", 2015, "law"),
        ("fiscal.procedure", "OUG 74/2013 — măsuri pentru îmbunătățirea și reorganizarea ANAF", "74", 2013, "emergency_ordinance"),
        # fiscal.banking
        ("fiscal.banking", "Legea 58/1998 — activitatea bancară (republicată)", "58", 1998, "law"),
        ("fiscal.banking", "Legea 237/2015 — autorizarea și supravegherea activității de asigurare", "237", 2015, "law"),
        ("fiscal.banking", "Legea 126/2018 — piețele de instrumente financiare", "126", 2018, "law"),
        ("fiscal.banking", "OUG 99/2006 — instituțiile de credit și adecvarea capitalului", "99", 2006, "emergency_ordinance"),
        ("fiscal.banking", "Legea 32/2000 — activitatea de asigurare și supravegherea asigurărilor", "32", 2000, "law"),
        # fiscal.procurement
        ("fiscal.procurement", "Legea 98/2016 — achizițiile publice", "98", 2016, "law"),
        ("fiscal.procurement", "Legea 99/2016 — achizițiile sectoriale", "99", 2016, "law"),
        ("fiscal.procurement", "Legea 100/2016 — concesiunile de lucrări și servicii", "100", 2016, "law"),
        ("fiscal.procurement", "HG 395/2016 — normele metodologice de aplicare a Legii 98/2016", "395", 2016, "government_resolution"),
        # administrative.state
        ("administrative.state", "Legea 90/2001 — organizarea și funcționarea Guvernului", "90", 2001, "law"),
        ("administrative.state", "Legea 340/2004 — prefectul și instituția prefectului (republicată)", "340", 2004, "law"),
        ("administrative.state", "Legea 188/1999 — statutul funcționarilor publici (republicată)", "188", 1999, "law"),
        # administrative.local
        ("administrative.local", "Legea 215/2001 — administrația publică locală (republicată)", "215", 2001, "law"),
        ("administrative.local", "Legea 195/2006 — descentralizarea", "195", 2006, "law"),
        ("administrative.local", "OUG 57/2019 — Codul Administrativ", "57", 2019, "emergency_ordinance"),
        # administrative.civil_service
        ("administrative.civil_service", "Legea 188/1999 — statutul funcționarilor publici (republicată)", "188", 1999, "law"),
        ("administrative.civil_service", "Legea 7/2004 — Codul de Conduită al funcționarilor publici", "7", 2004, "law"),
        ("administrative.civil_service", "Legea 477/2004 — Codul de Conduită al personalului contractual", "477", 2004, "law"),
        # administrative.litigation
        ("administrative.litigation", "Legea 554/2004 — contenciosul administrativ", "554", 2004, "law"),
        ("administrative.litigation", "OG 2/2001 — regimul juridic al contravențiilor", "2", 2001, "government_ordinance"),
        ("administrative.litigation", "Legea 101/2016 — remediile și căile de atac în achiziții publice", "101", 2016, "law"),
        # social.labour
        ("social.labour", "Legea 53/2003 — Codul Muncii (republicat)", "53", 2003, "law"),
        ("social.labour", "Legea 62/2011 — dialogul social (republicată)", "62", 2011, "law"),
        ("social.labour", "Legea 279/2005 — ucenicia la locul de muncă (republicată)", "279", 2005, "law"),
        ("social.labour", "Legea 156/2000 — protecția cetățenilor români care lucrează în străinătate", "156", 2000, "law"),
        # social.insurance
        ("social.insurance", "Legea 263/2010 — sistemul unitar de pensii publice", "263", 2010, "law"),
        ("social.insurance", "Legea 76/2002 — sistemul asigurărilor pentru șomaj", "76", 2002, "law"),
        ("social.insurance", "Legea 416/2001 — venitul minim garantat", "416", 2001, "law"),
        ("social.insurance", "Legea 292/2011 — asistența socială", "292", 2011, "law"),
        # social.health
        ("social.health", "Legea 95/2006 — reforma în domeniul sănătății (republicată)", "95", 2006, "law"),
        ("social.health", "Legea 46/2003 — drepturile pacientului", "46", 2003, "law"),
        ("social.health", "Legea 339/2005 — regimul juridic al plantelor, substanțelor și preparatelor stupefiante", "339", 2005, "law"),
        # social.education
        ("social.education", "Legea 1/2011 — educația națională", "1", 2011, "law"),
        ("social.education", "OUG 75/2005 — asigurarea calității educației (republicată)", "75", 2005, "emergency_ordinance"),
        ("social.education", "Legea 288/2004 — organizarea studiilor universitare", "288", 2004, "law"),
        # sectoral.real_estate
        ("sectoral.real_estate", "Legea 50/1991 — autorizarea executării lucrărilor de construcții (republicată)", "50", 1991, "law"),
        ("sectoral.real_estate", "Legea 350/2001 — amenajarea teritoriului și urbanismul", "350", 2001, "law"),
        ("sectoral.real_estate", "Legea 255/2010 — exproprierea pentru cauze de utilitate publică", "255", 2010, "law"),
        ("sectoral.real_estate", "Legea 7/1996 — cadastrul și publicitatea imobiliară (republicată)", "7", 1996, "law"),
        # sectoral.environment
        ("sectoral.environment", "Legea 137/1995 — protecția mediului (republicată)", "137", 1995, "law"),
        ("sectoral.environment", "OUG 195/2005 — protecția mediului", "195", 2005, "emergency_ordinance"),
        ("sectoral.environment", "Legea 211/2011 — regimul deșeurilor (republicată)", "211", 2011, "law"),
        ("sectoral.environment", "Legea 107/1996 — legea apelor", "107", 1996, "law"),
        ("sectoral.environment", "Legea 46/2008 — Codul Silvic (republicat)", "46", 2008, "law"),
        # sectoral.energy
        ("sectoral.energy", "Legea 123/2012 — energia electrică și gazele naturale", "123", 2012, "law"),
        ("sectoral.energy", "Legea 220/2008 — sistemul de promovare a producerii energiei din surse regenerabile (republicată)", "220", 2008, "law"),
        ("sectoral.energy", "Legea 132/2015 — schema de sprijin pentru energia electrică din surse regenerabile", "132", 2015, "law"),
        ("sectoral.energy", "OG 60/2000 — reglementarea activităților din sectorul gazelor naturale (referit istoric)", "60", 2000, "government_ordinance"),
        # sectoral.transport
        ("sectoral.transport", "OUG 195/2002 — circulația pe drumurile publice (republicată)", "195", 2002, "emergency_ordinance"),
        ("sectoral.transport", "Legea 38/2003 — transportul în regim de taxi și în regim de închiriere", "38", 2003, "law"),
        ("sectoral.transport", "OG 27/2011 — transporturile rutiere", "27", 2011, "government_ordinance"),
        ("sectoral.transport", "Legea 198/2015 — Codul Aerian Civil al României", "198", 2015, "law"),
        # sectoral.tech
        ("sectoral.tech", "Legea 506/2004 — prelucrarea datelor cu caracter personal în comunicații electronice", "506", 2004, "law"),
        ("sectoral.tech", "OUG 111/2011 — comunicațiile electronice", "111", 2011, "emergency_ordinance"),
        ("sectoral.tech", "Legea 455/2001 — semnătura electronică (republicată)", "455", 2001, "law"),
        ("sectoral.tech", "Legea 365/2002 — comerțul electronic (republicată)", "365", 2002, "law"),
        ("sectoral.tech", "Legea 40/2016 — modificarea Legii 506/2004", "40", 2016, "law"),
        # sectoral.agriculture
        ("sectoral.agriculture", "Legea 18/1991 — fondul funciar (republicată)", "18", 1991, "law"),
        ("sectoral.agriculture", "Legea 17/2014 — vânzarea-cumpărarea terenurilor agricole", "17", 2014, "law"),
        ("sectoral.agriculture", "Legea 145/2014 — reglementarea activității de agroturism", "145", 2014, "law"),
        ("sectoral.agriculture", "OUG 3/2015 — acordarea de sprijin financiar producătorilor agricoli", "3", 2015, "emergency_ordinance"),
        # sectoral.media
        ("sectoral.media", "Legea 504/2002 — legea audiovizualului", "504", 2002, "law"),
        ("sectoral.media", "Legea 41/1994 — organizarea și funcționarea CNA (republicată)", "41", 1994, "law"),
        ("sectoral.media", "Legea 8/1996 — dreptul de autor (inclusiv difuzare)", "8", 1996, "law"),
        # sectoral.defence
        # (no specific laws listed in source spec)
        # eu.regulation
        ("eu.regulation", "Regulamentul (UE) 2016/679 — GDPR", None, 2016, "regulation"),
        ("eu.regulation", "Regulamentul (UE) 2024/1689 — AI Act", None, 2024, "regulation"),
        ("eu.regulation", "Regulamentul (UE) 2022/2065 — DSA (Digital Services Act)", None, 2022, "regulation"),
        ("eu.regulation", "Regulamentul (UE) 2022/1925 — DMA (Digital Markets Act)", None, 2022, "regulation"),
        ("eu.regulation", "Regulamentul (UE) 2017/745 — MDR (dispozitive medicale)", None, 2017, "regulation"),
        ("eu.regulation", "Regulamentul (UE) 1215/2012 — competența judiciară în materie civilă (Bruxelles I)", None, 2012, "regulation"),
        ("eu.regulation", "Regulamentul (UE) 593/2008 — legea aplicabilă obligațiilor contractuale (Roma I)", None, 2008, "regulation"),
        ("eu.regulation", "Regulamentul (UE) 864/2007 — legea aplicabilă obligațiilor necontractuale (Roma II)", None, 2007, "regulation"),
        # eu.directive
        ("eu.directive", "Directiva 2011/83/UE — drepturile consumatorilor (transpusă prin OUG 34/2014)", None, 2011, "directive"),
        ("eu.directive", "Directiva 2019/1023/UE — restructurare și insolvență (transpusă prin Legea 216/2022)", None, 2019, "directive"),
        ("eu.directive", "Directiva 2022/2557/UE — reziliența entităților critice (CER)", None, 2022, "directive"),
        ("eu.directive", "Directiva 2022/2555/UE — NIS2", None, 2022, "directive"),
        ("eu.directive", "Directiva 2023/970/UE — transparența salarială", None, 2023, "directive"),
        ("eu.directive", "Directiva 2009/72/CE — piața internă a energiei electrice", None, 2009, "directive"),
        # eu.treaty
        ("eu.treaty", "Tratatul privind funcționarea Uniunii Europene (TFUE)", None, None, None),
        ("eu.treaty", "Tratatul privind Uniunea Europeană (TUE)", None, None, None),
        ("eu.treaty", "Carta drepturilor fundamentale a Uniunii Europene", None, None, None),
        ("eu.treaty", "Tratatul de aderare a României la UE (2005, în vigoare 2007)", None, 2005, None),
        # eu.caselaw — empty per source spec
    ]
    for cat_slug, title, law_number, law_year, document_type in mappings_data:
        cat_id = cat_map[cat_slug]
        # Skip if a matching mapping already exists, INCLUDING tombstoned ones —
        # so re-seeding never resurrects a row the user has explicitly deleted.
        # Note: seed_categories has an early-return guard above (`if existing
        # group: return`), so this is the safety net for any future "reload
        # defaults" admin path that bypasses that guard.
        existing = db.query(LawMapping).filter(
            LawMapping.category_id == cat_id,
            LawMapping.law_number == law_number,
            LawMapping.law_year == law_year,
            LawMapping.document_type == document_type,
        ).first()
        if existing:
            continue
        m = LawMapping(
            title=title,
            law_number=law_number,
            law_year=law_year,
            document_type=document_type,
            category_id=cat_id,
            source="system",
        )
        db.add(m)

    # Mark existing laws as unclassified
    db.query(Law).filter(Law.category_confidence.is_(None)).update(
        {"category_confidence": "unclassified"}, synchronize_session="fetch"
    )

    db.commit()
    logger.info("Category taxonomy seeded successfully.")


def seed_eu_celex_mappings(db: Session) -> None:
    """Backfill celex_number on EU law mappings. Safe to run multiple times."""
    celex_map = {
        "Regulamentul (UE) 2016/679 — GDPR": "32016R0679",
        "Regulamentul (UE) 2024/1689 — AI Act": "32024R1689",
        "Regulamentul (UE) 2022/2065 — DSA (Digital Services Act)": "32022R2065",
        "Regulamentul (UE) 2022/1925 — DMA (Digital Markets Act)": "32022R1925",
        "Regulamentul (UE) 2017/745 — MDR (dispozitive medicale)": "32017R0745",
        "Regulamentul (UE) 1215/2012 — competența judiciară în materie civilă (Bruxelles I)": "32012R1215",
        "Regulamentul (UE) 593/2008 — legea aplicabilă obligațiilor contractuale (Roma I)": "32008R0593",
        "Regulamentul (UE) 864/2007 — legea aplicabilă obligațiilor necontractuale (Roma II)": "32007R0864",
        "Directiva 2011/83/UE — drepturile consumatorilor (transpusă prin OUG 34/2014)": "32011L0083",
        "Directiva 2019/1023/UE — restructurare și insolvență (transpusă prin Legea 216/2022)": "32019L1023",
        "Directiva 2022/2557/UE — reziliența entităților critice (CER)": "32022L2557",
        "Directiva 2022/2555/UE — NIS2": "32022L2555",
        "Directiva 2023/970/UE — transparența salarială": "32023L0970",
        "Directiva 2009/72/CE — piața internă a energiei electrice": "32009L0072",
    }
    updated = 0
    for title, celex in celex_map.items():
        mapping = db.query(LawMapping).filter(LawMapping.title == title, LawMapping.celex_number.is_(None)).first()
        if mapping:
            mapping.celex_number = celex
            updated += 1
    if updated:
        db.commit()
        logger.info(f"Backfilled celex_number on {updated} EU law mappings")


def ensure_eu_decision_category(db: Session) -> None:
    """Add eu.decision category if missing. Safe for repeated runs."""
    existing = db.query(Category).filter_by(slug="eu.decision").first()
    if existing:
        return
    eu_group = db.query(CategoryGroup).filter_by(slug="eu").first()
    if not eu_group:
        return
    cat = Category(
        group_id=eu_group.id,
        slug="eu.decision",
        name_ro="Decizii UE",
        name_en="EU decisions",
        description="Decizii ale Consiliului, Comisiei, BCE — obligatorii pentru destinatari",
        is_eu=True,
        sort_order=5,
    )
    db.add(cat)
    db.commit()
    logger.info("Added eu.decision category")


def backfill_law_mapping_fields(db: Session) -> None:
    """Backfill law_year and document_type on existing LawMapping rows.

    Runs on every startup.  Skips if the seed mappings already have these
    fields populated (i.e. a fresh seed with the 5-tuple format).
    """
    needs_backfill = (
        db.query(LawMapping)
        .filter(
            LawMapping.source == "seed",
            LawMapping.law_year.is_(None),
            LawMapping.document_type.is_(None),
        )
        .count()
    )
    if needs_backfill == 0:
        return

    logger.info("Backfilling law_year and document_type on %d seed mappings...", needs_backfill)

    # Build a lookup from (title) → (law_year, document_type) using the
    # same canonical list that seed_categories uses.
    _TITLE_TO_FIELDS: dict[str, tuple[int | None, str | None]] = {
        "Constituția României (1991, republicată 2003)": (1991, "constitution"),
        "Legea 190/2018 — implementarea GDPR în dreptul național": (2018, "law"),
        "Legea 506/2004 — prelucrarea datelor personale în comunicații electronice": (2004, "law"),
        "OUG 119/2006 — măsuri pentru aplicarea unor regulamente comunitare privind drepturile cetățenilor": (2006, "emergency_ordinance"),
        "Legea 208/2015 — alegerea Senatului și Camerei Deputaților": (2015, "law"),
        "Legea 370/2004 — alegerea Președintelui României": (2004, "law"),
        "Legea 115/2015 — alegerea autorităților administrației publice locale": (2015, "law"),
        "Legea 334/2006 — finanțarea activității partidelor politice": (2006, "law"),
        "Legea 287/2009 — Codul Civil (republicat)": (2009, "law"),
        "Legea 71/2011 — punerea în aplicare a Codului Civil": (2011, "law"),
        "Decretul-lege 31/1954 — persoane fizice și juridice (abrogat parțial)": (1954, "decree"),
        "Legea 7/1996 — cadastrul și publicitatea imobiliară": (1996, "law"),
        "Legea 10/2001 — regimul juridic al imobilelor preluate abuziv": (2001, "law"),
        "Legea 18/1991 — fondul funciar": (1991, "law"),
        "Legea 50/1991 — autorizarea executării lucrărilor de construcții": (1991, "law"),
        "Legea 33/1994 — exproprierea pentru cauze de utilitate publică": (1994, "law"),
        "Legea 272/2004 — protecția și promovarea drepturilor copilului": (2004, "law"),
        "Legea 273/2004 — procedura adopției": (2004, "law"),
        "Legea 217/2003 — prevenirea și combaterea violenței domestice": (2003, "law"),
        "Legea 193/2000 — clauzele abuzive din contractele cu consumatorii": (2000, "law"),
        "Legea 455/2001 — semnătura electronică": (2001, "law"),
        "Legea 365/2002 — comerțul electronic": (2002, "law"),
        "Legea 134/2010 — Codul de Procedură Civilă (republicat)": (2010, "law"),
        "Legea 85/2014 — procedurile de prevenire a insolvenței și de insolvență": (2014, "law"),
        "Legea 192/2006 — medierea și organizarea profesiei de mediator": (2006, "law"),
        "Legea 188/2000 — executorii judecătorești": (2000, "law"),
        "Legea 286/2009 — Codul Penal": (2009, "law"),
        "Legea 187/2012 — punerea în aplicare a Codului Penal": (2012, "law"),
        "Legea 241/2005 — prevenirea și combaterea evaziunii fiscale": (2005, "law"),
        "Legea 78/2000 — prevenirea, descoperirea și sancționarea faptelor de corupție": (2000, "law"),
        "Legea 656/2002 — prevenirea și combaterea spălării banilor": (2002, "law"),
        "Legea 143/2000 — prevenirea și combaterea traficului și consumului ilicit de droguri": (2000, "law"),
        "Legea 39/2003 — prevenirea și combaterea criminalității organizate": (2003, "law"),
        "OUG 43/2002 — Direcția Națională Anticorupție (DNA)": (2002, "emergency_ordinance"),
        "Legea 135/2010 — Codul de Procedură Penală": (2010, "law"),
        "Legea 254/2013 — executarea pedepselor și a măsurilor privative de libertate": (2013, "law"),
        "Legea 253/2013 — executarea pedepselor, a măsurilor educative și a altor măsuri neprivative de libertate": (2013, "law"),
        "Legea 252/2013 — organizarea și funcționarea sistemului de probațiune": (2013, "law"),
        "Legea 31/1990 — societățile comerciale (republicată)": (1990, "law"),
        "Legea 26/1990 — registrul comerțului (republicată)": (1990, "law"),
        "Legea 1/2005 — organizarea și funcționarea cooperației": (2005, "law"),
        "OUG 44/2008 — desfășurarea activităților economice de către persoanele fizice autorizate (PFA)": (2008, "emergency_ordinance"),
        "Legea 85/2006 — procedura insolvenței (abrogată, referită istoric)": (2006, "law"),
        "Legea 21/1996 — concurența (republicată)": (1996, "law"),
        "Legea 11/1991 — combaterea concurenței neloiale": (1991, "law"),
        "OUG 117/2006 — procedurile naționale în domeniul ajutorului de stat": (2006, "emergency_ordinance"),
        "Legea 8/1996 — dreptul de autor și drepturile conexe": (1996, "law"),
        "Legea 64/1991 — brevetele de invenție (republicată)": (1991, "law"),
        "Legea 84/1998 — mărcile și indicațiile geografice (republicată)": (1998, "law"),
        "Legea 129/1992 — protecția desenelor și modelelor industriale": (1992, "law"),
        "Legea 449/2003 — vânzarea produselor și garanțiile asociate (republicată)": (2003, "law"),
        "OUG 34/2014 — drepturile consumatorilor în contractele cu profesioniști": (2014, "emergency_ordinance"),
        "Legea 363/2007 — combaterea practicilor incorecte ale comercianților": (2007, "law"),
        "Legea 227/2015 — Codul Fiscal": (2015, "law"),
        "OUG 6/2019 — stabilirea unor măsuri privind starea de insolvabilitate": (2019, "emergency_ordinance"),
        "HG 1/2016 — normele metodologice de aplicare a Codului Fiscal": (2016, "government_resolution"),
        "Legea 207/2015 — Codul de Procedură Fiscală": (2015, "law"),
        "OUG 74/2013 — măsuri pentru îmbunătățirea și reorganizarea ANAF": (2013, "emergency_ordinance"),
        "Legea 58/1998 — activitatea bancară (republicată)": (1998, "law"),
        "Legea 237/2015 — autorizarea și supravegherea activității de asigurare": (2015, "law"),
        "Legea 126/2018 — piețele de instrumente financiare": (2018, "law"),
        "OUG 99/2006 — instituțiile de credit și adecvarea capitalului": (2006, "emergency_ordinance"),
        "Legea 32/2000 — activitatea de asigurare și supravegherea asigurărilor": (2000, "law"),
        "Legea 98/2016 — achizițiile publice": (2016, "law"),
        "Legea 99/2016 — achizițiile sectoriale": (2016, "law"),
        "Legea 100/2016 — concesiunile de lucrări și servicii": (2016, "law"),
        "HG 395/2016 — normele metodologice de aplicare a Legii 98/2016": (2016, "government_resolution"),
        "Legea 90/2001 — organizarea și funcționarea Guvernului": (2001, "law"),
        "Legea 340/2004 — prefectul și instituția prefectului (republicată)": (2004, "law"),
        "Legea 188/1999 — statutul funcționarilor publici (republicată)": (1999, "law"),
        "Legea 215/2001 — administrația publică locală (republicată)": (2001, "law"),
        "Legea 195/2006 — descentralizarea": (2006, "law"),
        "OUG 57/2019 — Codul Administrativ": (2019, "emergency_ordinance"),
        "Legea 7/2004 — Codul de Conduită al funcționarilor publici": (2004, "law"),
        "Legea 477/2004 — Codul de Conduită al personalului contractual": (2004, "law"),
        "Legea 554/2004 — contenciosul administrativ": (2004, "law"),
        "OG 2/2001 — regimul juridic al contravențiilor": (2001, "government_ordinance"),
        "Legea 101/2016 — remediile și căile de atac în achiziții publice": (2016, "law"),
        "Legea 53/2003 — Codul Muncii (republicat)": (2003, "law"),
        "Legea 62/2011 — dialogul social (republicată)": (2011, "law"),
        "Legea 279/2005 — ucenicia la locul de muncă (republicată)": (2005, "law"),
        "Legea 156/2000 — protecția cetățenilor români care lucrează în străinătate": (2000, "law"),
        "Legea 263/2010 — sistemul unitar de pensii publice": (2010, "law"),
        "Legea 76/2002 — sistemul asigurărilor pentru șomaj": (2002, "law"),
        "Legea 416/2001 — venitul minim garantat": (2001, "law"),
        "Legea 292/2011 — asistența socială": (2011, "law"),
        "Legea 95/2006 — reforma în domeniul sănătății (republicată)": (2006, "law"),
        "Legea 46/2003 — drepturile pacientului": (2003, "law"),
        "Legea 339/2005 — regimul juridic al plantelor, substanțelor și preparatelor stupefiante": (2005, "law"),
        "Legea 1/2011 — educația națională": (2011, "law"),
        "OUG 75/2005 — asigurarea calității educației (republicată)": (2005, "emergency_ordinance"),
        "Legea 288/2004 — organizarea studiilor universitare": (2004, "law"),
        "Legea 50/1991 — autorizarea executării lucrărilor de construcții (republicată)": (1991, "law"),
        "Legea 350/2001 — amenajarea teritoriului și urbanismul": (2001, "law"),
        "Legea 255/2010 — exproprierea pentru cauze de utilitate publică": (2010, "law"),
        "Legea 7/1996 — cadastrul și publicitatea imobiliară (republicată)": (1996, "law"),
        "Legea 137/1995 — protecția mediului (republicată)": (1995, "law"),
        "OUG 195/2005 — protecția mediului": (2005, "emergency_ordinance"),
        "Legea 211/2011 — regimul deșeurilor (republicată)": (2011, "law"),
        "Legea 107/1996 — legea apelor": (1996, "law"),
        "Legea 46/2008 — Codul Silvic (republicat)": (2008, "law"),
        "Legea 123/2012 — energia electrică și gazele naturale": (2012, "law"),
        "Legea 220/2008 — sistemul de promovare a producerii energiei din surse regenerabile (republicată)": (2008, "law"),
        "Legea 132/2015 — schema de sprijin pentru energia electrică din surse regenerabile": (2015, "law"),
        "OG 60/2000 — reglementarea activităților din sectorul gazelor naturale (referit istoric)": (2000, "government_ordinance"),
        "OUG 195/2002 — circulația pe drumurile publice (republicată)": (2002, "emergency_ordinance"),
        "Legea 38/2003 — transportul în regim de taxi și în regim de închiriere": (2003, "law"),
        "OG 27/2011 — transporturile rutiere": (2011, "government_ordinance"),
        "Legea 198/2015 — Codul Aerian Civil al României": (2015, "law"),
        "OUG 111/2011 — comunicațiile electronice": (2011, "emergency_ordinance"),
        "Legea 455/2001 — semnătura electronică (republicată)": (2001, "law"),
        "Legea 365/2002 — comerțul electronic (republicată)": (2002, "law"),
        "Legea 40/2016 — modificarea Legii 506/2004": (2016, "law"),
        "Legea 18/1991 — fondul funciar (republicată)": (1991, "law"),
        "Legea 17/2014 — vânzarea-cumpărarea terenurilor agricole": (2014, "law"),
        "Legea 145/2014 — reglementarea activității de agroturism": (2014, "law"),
        "OUG 3/2015 — acordarea de sprijin financiar producătorilor agricoli": (2015, "emergency_ordinance"),
        "Legea 504/2002 — legea audiovizualului": (2002, "law"),
        "Legea 41/1994 — organizarea și funcționarea CNA (republicată)": (1994, "law"),
        "Legea 8/1996 — dreptul de autor (inclusiv difuzare)": (1996, "law"),
        "Regulamentul (UE) 2016/679 — GDPR": (2016, "regulation"),
        "Regulamentul (UE) 2024/1689 — AI Act": (2024, "regulation"),
        "Regulamentul (UE) 2022/2065 — DSA (Digital Services Act)": (2022, "regulation"),
        "Regulamentul (UE) 2022/1925 — DMA (Digital Markets Act)": (2022, "regulation"),
        "Regulamentul (UE) 2017/745 — MDR (dispozitive medicale)": (2017, "regulation"),
        "Regulamentul (UE) 1215/2012 — competența judiciară în materie civilă (Bruxelles I)": (2012, "regulation"),
        "Regulamentul (UE) 593/2008 — legea aplicabilă obligațiilor contractuale (Roma I)": (2008, "regulation"),
        "Regulamentul (UE) 864/2007 — legea aplicabilă obligațiilor necontractuale (Roma II)": (2007, "regulation"),
        "Directiva 2011/83/UE — drepturile consumatorilor (transpusă prin OUG 34/2014)": (2011, "directive"),
        "Directiva 2019/1023/UE — restructurare și insolvență (transpusă prin Legea 216/2022)": (2019, "directive"),
        "Directiva 2022/2557/UE — reziliența entităților critice (CER)": (2022, "directive"),
        "Directiva 2022/2555/UE — NIS2": (2022, "directive"),
        "Directiva 2023/970/UE — transparența salarială": (2023, "directive"),
        "Directiva 2009/72/CE — piața internă a energiei electrice": (2009, "directive"),
    }

    updated = 0
    for mapping in db.query(LawMapping).filter(LawMapping.source == "seed").all():
        fields = _TITLE_TO_FIELDS.get(mapping.title)
        if fields:
            mapping.law_year = fields[0]
            mapping.document_type = fields[1]
            updated += 1

    db.commit()
    logger.info("Backfilled %d law mappings with law_year and document_type.", updated)


def get_library_data(db: Session, user_id: int | None = None) -> dict:
    """Assemble all data needed for the Legal Library page."""
    from sqlalchemy import text
    from app.models.law import LawVersion

    # 1. Category law counts in a single query
    law_counts = dict(
        db.query(Law.category_id, func.count(Law.id))
        .filter(Law.category_id.isnot(None))
        .group_by(Law.category_id)
        .all()
    )

    # 2. Groups + categories (eager-loaded)
    groups = (
        db.query(CategoryGroup)
        .order_by(CategoryGroup.sort_order)
        .all()
    )

    # Pre-load all categories with their groups for suggestion lookup
    all_categories = {c.id: c for g in groups for c in g.categories}

    groups_out = []
    for g in groups:
        cats_out = []
        for c in sorted(g.categories, key=lambda x: x.sort_order):
            cats_out.append({
                "id": c.id, "slug": c.slug, "name_ro": c.name_ro,
                "name_en": c.name_en, "description": c.description,
                "law_count": law_counts.get(c.id, 0),
            })
        groups_out.append({
            "id": g.id, "slug": g.slug, "name_ro": g.name_ro, "name_en": g.name_en,
            "color_hex": g.color_hex, "sort_order": g.sort_order, "categories": cats_out,
        })

    # 3. Laws with version counts and current version in bulk queries
    # Get version counts per law
    version_counts = dict(
        db.query(LawVersion.law_id, func.count(LawVersion.id))
        .group_by(LawVersion.law_id)
        .all()
    )

    # Get current versions per law
    current_versions = {
        v.law_id: v
        for v in db.query(LawVersion).filter(LawVersion.is_current == True).all()
    }

    laws = db.query(Law).order_by(Law.law_year.desc(), Law.law_number).all()
    laws_out = []
    for law in laws:
        current = current_versions.get(law.id)
        cat = all_categories.get(law.category_id)
        group_slug = cat.group.slug if cat else None
        laws_out.append({
            "id": law.id, "title": law.title, "law_number": law.law_number,
            "law_year": law.law_year, "document_type": law.document_type,
            "description": law.description, "issuer": law.issuer,
            "version_count": version_counts.get(law.id, 0), "status": law.status,
            "category_id": law.category_id, "category_group_slug": group_slug,
            "category_confidence": law.category_confidence,
            "unimported_version_count": 0,
            "source": getattr(law, "source", "ro"),
            "current_version": {"id": current.id, "state": current.state} if current else None,
        })

    total_versions = sum(version_counts.values())
    last_imported = db.query(func.max(LawVersion.date_imported)).scalar()

    # 4. Suggestions — use pre-loaded categories, no per-mapping queries
    all_mappings = db.query(LawMapping).filter(LawMapping.deleted_at.is_(None)).all()
    imported_keys = {(law.law_number, law.law_year) for law in laws}
    # Track seen (law_number, law_year) to deduplicate mappings
    seen_keys: set[tuple[str | None, int | None]] = set()
    suggested = []
    for m in all_mappings:
        key = (m.law_number, m.law_year)
        # Skip if this law is already imported (by number + year)
        if m.law_number and key in imported_keys:
            continue
        # Skip duplicate mappings (same law_number + year already in suggestions)
        if m.law_number and key in seen_keys:
            continue
        cat = all_categories.get(m.category_id)
        if cat:
            suggested.append({
                "id": m.id, "title": m.title, "law_number": m.law_number,
                "celex_number": m.celex_number,
                "category_id": m.category_id, "category_slug": cat.slug,
                "group_slug": cat.group.slug,
            })
            if m.law_number:
                seen_keys.add(key)

    # 5. Favorites for the current user
    favorite_law_ids = []
    if user_id is not None:
        from app.models.favorite import LawFavorite
        favorite_law_ids = [
            r[0] for r in db.query(LawFavorite.law_id)
            .filter(LawFavorite.user_id == user_id)
            .all()
        ]

    return {
        "groups": groups_out, "laws": laws_out,
        "stats": {
            "total_laws": len(laws), "total_versions": total_versions,
            "last_imported": str(last_imported.date()) if last_imported else None,
        },
        "suggested_laws": suggested,
        "favorite_law_ids": favorite_law_ids,
    }


def get_unimported_suggestions(db: Session) -> list[LawMapping]:
    """Return LawMapping entries that haven't been imported yet (deduplicated)."""
    laws = db.query(Law).all()
    imported_keys = {(law.law_number, law.law_year) for law in laws}

    all_mappings = db.query(LawMapping).filter(LawMapping.deleted_at.is_(None)).all()
    seen_keys: set[tuple[str | None, int | None]] = set()
    unimported = []
    for m in all_mappings:
        key = (m.law_number, m.law_year)
        if m.law_number and key in imported_keys:
            continue
        if m.law_number and key in seen_keys:
            continue
        unimported.append(m)
        if m.law_number:
            seen_keys.add(key)
    return unimported


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

    existing = (
        db.query(LawMapping)
        .filter(
            LawMapping.category_id == category_id,
            (LawMapping.law_number == law.law_number) | (LawMapping.title.ilike(law.title))
        )
        .first()
    )
    if not existing:
        mapping = LawMapping(title=law.title, law_number=law.law_number,
                            category_id=category_id, source="user")
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
            "id": law.id, "title": law.title, "law_number": law.law_number,
            "law_year": law.law_year, "version_count": len(law.versions),
            "category_name": cat.group.name_en if cat else None,
            "current_version": {"id": current.id, "state": current.state} if current else None,
        })
    return results
