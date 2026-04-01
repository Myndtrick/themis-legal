"""
Validation: Per-issue concept-based retrieval for redesigned pipeline.
Tests 20 queries to measure governing norm recall.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

import sqlite3
from app.models.category import Category, CategoryGroup  # must import before SessionLocal
from app.database import SessionLocal
from app.services.chroma_service import query_articles
from app.services.bm25_service import search_bm25

N_SEMANTIC = 10  # semantic results per concept
N_BM25 = 10      # BM25 results per query

# ──────────────────────────────────────────────────────────────────
# 20 TEST CASES with simulated Step 1 output
# ──────────────────────────────────────────────────────────────────
TEST_CASES = [
    # ── Q01: REAL — Shareholder 40% loan + insolvency (COMPLEX) ──
    {
        "id": "Q01", "complexity": "COMPLEX", "domain": "corporate+insolvency+criminal",
        "question": "daca un actionar care detine 40% intr o companie a imprumutat firma cu 100.000 euro pe 01.01.2025, iar pe 01.03.2026 i se restituie banii, iar 4 luni mai tarziu, compania intra in insolventa, administratoul companiei este afectat intr-un fel?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Răspunderea personală a administratorului în insolvență",
                "entity_perspective": "administrator societate comercială",
                "laws": ["85/2014"],
                "concepts": [
                    "răspunderea membrilor organelor de conducere și supraveghere ale debitorului pentru ajungerea în stare de insolvență, inclusiv prin folosirea bunurilor sau creditelor persoanei juridice în scop propriu sau în interesul altei persoane"
                ],
                "bm25_terms": ["raspundere membrii organelor conducere insolventa"],
                "governing_norms": {"85/2014": ["169"]},
            },
            {
                "id": "ISSUE-2",
                "description": "Anularea actelor frauduloase în perioada suspectă",
                "entity_perspective": "creditor / administrator judiciar",
                "laws": ["85/2014"],
                "concepts": [
                    "acțiuni pentru anularea actelor sau operațiunilor frauduloase ale debitorului în dauna drepturilor creditorilor în perioada anterioară deschiderii procedurii, inclusiv transferuri și plăți preferențiale către persoane interesate"
                ],
                "bm25_terms": ["anulare acte frauduloase debitor perioada suspecta creditori"],
                "governing_norms": {"85/2014": ["117", "118"]},
            },
            {
                "id": "ISSUE-3",
                "description": "Obligațiile și răspunderea administratorului față de societate",
                "entity_perspective": "administrator SRL",
                "laws": ["31/1990"],
                "concepts": [
                    "obligațiile administratorilor de a exercita mandatul cu prudența și diligența unui bun administrator, răspunderea solidară față de societate pentru stricta îndeplinire a îndatoririlor impuse de lege și actul constitutiv"
                ],
                "bm25_terms": ["administrator raspundere solidara societate obligatii mandat"],
                "governing_norms": {"31/1990": ["72", "73"]},
            },
            {
                "id": "ISSUE-4",
                "description": "Bancrută simplă și frauduloasă",
                "entity_perspective": "reprezentant legal persoană juridică debitoare",
                "laws": ["286/2009"],
                "concepts": [
                    "bancruta simplă constând în neintroducerea sau introducerea tardivă a cererii de deschidere a procedurii de insolvență de către debitorul persoană fizică ori de reprezentantul legal al persoanei juridice debitoare",
                    "bancruta frauduloasă constând în falsificarea, sustragerea sau distrugerea evidențelor debitorului ori ascunderea unei părți din activul averii acestuia"
                ],
                "bm25_terms": ["bancruta simpla neintroducere cerere insolventa", "bancruta frauduloasa falsificare evidente debitor"],
                "governing_norms": {"286/2009": ["240", "241"]},
            },
        ]
    },

    # ── Q02: REAL — SRL admin transfer + insolvency (COMPLEX) ──
    {
        "id": "Q02", "complexity": "COMPLEX", "domain": "corporate+insolvency+criminal",
        "question": "Dacă un administrator al unui SRL transferă bani din firmă către o altă firmă pe care o controlează indirect, fără aprobarea asociaților, iar firma intră în insolvență după un an, poate răspunde personal? Există și riscuri penale?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Răspunderea administratorului SRL în insolvență",
                "entity_perspective": "administrator SRL",
                "laws": ["85/2014"],
                "concepts": [
                    "răspunderea membrilor organelor de conducere pentru ajungerea debitorului în stare de insolvență prin folosirea bunurilor sau creditelor persoanei juridice în folosul propriu sau al altei persoane"
                ],
                "bm25_terms": ["raspundere membrii organelor conducere insolventa bunuri credite"],
                "governing_norms": {"85/2014": ["169"]},
            },
            {
                "id": "ISSUE-2",
                "description": "Anularea transferurilor în perioada suspectă",
                "entity_perspective": "administrator judiciar / creditor",
                "laws": ["85/2014"],
                "concepts": [
                    "acțiuni pentru anularea transferurilor și operațiunilor încheiate de debitor în dauna creditorilor în cei doi ani anteriori deschiderii procedurii de insolvență, inclusiv acte cu persoane interesate"
                ],
                "bm25_terms": ["anulare transferuri acte debitor perioada suspecta doi ani"],
                "governing_norms": {"85/2014": ["117", "118"]},
            },
            {
                "id": "ISSUE-3",
                "description": "Obligații administrator SRL și operațiuni fără aprobare",
                "entity_perspective": "administrator SRL",
                "laws": ["31/1990"],
                "concepts": [
                    "administratorii societății cu răspundere limitată nu pot primi mandatul de administrator în alte societăți concurente, nici să facă același fel de comerț pe cont propriu sau pe contul altei persoane fizice sau juridice fără autorizarea adunării asociaților",
                    "obligațiile administratorilor de a exercita mandatul cu prudența și diligența unui bun administrator, răspunderea solidară față de societate pentru stricta îndeplinire a îndatoririlor"
                ],
                "bm25_terms": ["administrator raspundere limitata autorizare adunare asociati mandat", "administrator raspundere solidara societate obligatii"],
                "governing_norms": {"31/1990": ["197", "72", "73"]},
            },
            {
                "id": "ISSUE-4",
                "description": "Riscuri penale — bancrută, abuz de încredere",
                "entity_perspective": "administrator SRL potențial inculpat",
                "laws": ["286/2009"],
                "concepts": [
                    "bancruta frauduloasă constând în falsificarea, sustragerea sau distrugerea evidențelor debitorului ori ascunderea activelor în frauda creditorilor",
                    "abuz de încredere prin însușirea, dispunerea sau folosirea pe nedrept a unui bun mobil al altuia de către cel căruia i-a fost încredințat"
                ],
                "bm25_terms": ["bancruta frauduloasa debitor creditori", "abuz incredere insusire folosire bun"],
                "governing_norms": {"286/2009": ["240", "241", "238"]},
            },
        ]
    },

    # ── Q03: REAL — VAT rate change (STANDARD) ──
    {
        "id": "Q03", "complexity": "STANDARD", "domain": "fiscal",
        "question": "de ce o factura emisa pe 23.05.2025 are tva de 19% iar una emisa pe 23.08.2025 il are diferit?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Cota TVA standard aplicabilă operațiunilor impozabile",
                "entity_perspective": "contribuabil persoană impozabilă",
                "laws": ["227/2015"],
                "concepts": [
                    "nivelul cotei standard a taxei pe valoarea adăugată aplicabilă operațiunilor impozabile care nu sunt scutite de taxă, și cotele reduse de TVA"
                ],
                "bm25_terms": ["cota standard taxa valoarea adaugata operatiuni impozabile", "cotele TVA nivelul"],
                "governing_norms": {"227/2015": ["291"]},
            },
        ]
    },

    # ── Q04: REAL — SRL capital + associates (SIMPLE) ──
    {
        "id": "Q04", "complexity": "SIMPLE", "domain": "corporate",
        "question": "exista limite maxime sau minime de capital social pentru un SRL la infiintare? dar de nr de asociati?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Capital social minim și număr maxim asociați SRL",
                "entity_perspective": "fondator/asociat SRL",
                "laws": ["31/1990"],
                "concepts": [
                    "capitalul social al societății cu răspundere limitată se divide în părți sociale egale, iar numărul asociaților nu poate fi mai mare de 50"
                ],
                "bm25_terms": ["capital social raspundere limitata parti sociale", "numar asociati raspundere limitata"],
                "governing_norms": {"31/1990": ["11", "12"]},
            },
        ]
    },

    # ── Q05: SRL vs SA admin duties (STANDARD) ──
    {
        "id": "Q05", "complexity": "STANDARD", "domain": "corporate",
        "question": "Care sunt diferențele între răspunderea administratorului unui SRL și cea a administratorului unui SA?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Răspunderea administratorului SRL",
                "entity_perspective": "administrator SRL",
                "laws": ["31/1990"],
                "concepts": [
                    "administratorii societății cu răspundere limitată nu pot primi mandatul de administrator în alte societăți concurente fără autorizarea adunării asociaților, sub sancțiunea revocării și răspunderii pentru daune",
                    "răspunderea solidară a administratorilor față de societate pentru stricta îndeplinire a îndatoririlor pe care legea și actul constitutiv le impun"
                ],
                "bm25_terms": ["administrator raspundere limitata obligatii mandatul", "administrator raspundere solidara societate indatoriri"],
                "governing_norms": {"31/1990": ["197", "72", "73"]},
            },
            {
                "id": "ISSUE-2",
                "description": "Răspunderea administratorului SA",
                "entity_perspective": "administrator SA / consiliu de administrație",
                "laws": ["31/1990"],
                "concepts": [
                    "membrii consiliului de administrație își exercită mandatul cu prudența și diligența unui bun administrator, răspunderea pentru îndeplinirea obligațiilor conform art. 72 și 73",
                    "administratorul societății pe acțiuni care are interese contrare intereselor societății într-o anumită operațiune trebuie să înștiințeze consiliul și să se abțină de la vot"
                ],
                "bm25_terms": ["consiliu administratie mandat prudenta diligenta", "administrator interese contrare societate actiuni"],
                "governing_norms": {"31/1990": ["144^1", "144^2", "144^3", "72", "73"]},
            },
        ]
    },

    # ── Q06: Criminal — admin uses company money (STANDARD) ──
    {
        "id": "Q06", "complexity": "STANDARD", "domain": "criminal",
        "question": "Un administrator de SRL a folosit banii firmei pentru cheltuieli personale. Ce infracțiuni poate fi acuzat?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Abuz de încredere",
                "entity_perspective": "administrator SRL ca inculpat",
                "laws": ["286/2009"],
                "concepts": [
                    "infracțiunea de abuz de încredere constând în însușirea, dispunerea sau folosirea pe nedrept a unui bun mobil al altuia de către cel căruia i-a fost încredințat în baza unui titlu și cu un anumit scop"
                ],
                "bm25_terms": ["abuz incredere insusire folosire bun mobil incredintare"],
                "governing_norms": {"286/2009": ["238"]},
            },
            {
                "id": "ISSUE-2",
                "description": "Delapidare (dacă funcționar public)",
                "entity_perspective": "funcționar public / administrator societate de stat",
                "laws": ["286/2009"],
                "concepts": [
                    "delapidarea constând în însușirea, folosirea sau traficarea de bani, valori sau alte bunuri de către un funcționar public în interesul propriu sau pentru altul"
                ],
                "bm25_terms": ["delapidare functionar public insusire bani valori"],
                "governing_norms": {"286/2009": ["295"]},
            },
        ]
    },

    # ── Q07: Insolvency opening conditions (STANDARD) ──
    {
        "id": "Q07", "complexity": "STANDARD", "domain": "insolvency",
        "question": "Care sunt condițiile pentru deschiderea procedurii de insolvență? Ce cuantum minim are creanța?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Cererea creditorului de deschidere a procedurii",
                "entity_perspective": "creditor solicitant",
                "laws": ["85/2014"],
                "concepts": [
                    "creditor îndreptățit să solicite deschiderea procedurii de insolvență poate introduce cerere împotriva unui debitor prezumat în insolvență, precizând cuantumul și temeiul creanței"
                ],
                "bm25_terms": ["creditor cerere deschidere procedura insolventa debitor cuantum creanta"],
                "governing_norms": {"85/2014": ["70"]},
            },
            {
                "id": "ISSUE-2",
                "description": "Obligația debitorului de a solicita deschiderea insolvenței",
                "entity_perspective": "debitor în stare de insolvență",
                "laws": ["85/2014"],
                "concepts": [
                    "debitorul aflat în stare de insolvență este obligat să adreseze tribunalului o cerere pentru a fi supus procedurii de insolvență în termen de maximum 45 de zile"
                ],
                "bm25_terms": ["debitor obligat cerere insolventa tribunal termen"],
                "governing_norms": {"85/2014": ["66"]},
            },
        ]
    },

    # ── Q08: GDPR — right to erasure (STANDARD) ──
    {
        "id": "Q08", "complexity": "STANDARD", "domain": "eu_law",
        "question": "Ce drepturi are o persoană vizată să solicite ștergerea datelor personale conform GDPR?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Dreptul la ștergerea datelor (dreptul de a fi uitat)",
                "entity_perspective": "persoană vizată",
                "laws": ["679/2016"],
                "concepts": [
                    "dreptul persoanei vizate de a obține din partea operatorului ștergerea datelor cu caracter personal care o privesc fără întârzieri nejustificate și obligația operatorului de a șterge datele în condițiile prevăzute"
                ],
                "bm25_terms": ["dreptul stergere date personale persoana vizata operator"],
                "governing_norms": {"679/2016": ["17"]},
            },
            {
                "id": "ISSUE-2",
                "description": "Sancțiuni GDPR pentru nerespectarea drepturilor",
                "entity_perspective": "operator date personale",
                "laws": ["679/2016"],
                "concepts": [
                    "amenzi administrative pentru încălcarea dispozițiilor privind drepturile persoanelor vizate, criteriile de stabilire a cuantumului amenzii și pragurile maxime aplicabile"
                ],
                "bm25_terms": ["amenzi administrative incalcare drepturi persoana vizata"],
                "governing_norms": {"679/2016": ["83"]},
            },
        ]
    },

    # ── Q09: Civil Code — contract termination (STANDARD) ──
    {
        "id": "Q09", "complexity": "STANDARD", "domain": "civil",
        "question": "În ce condiții se poate rezilia un contract de prestări servicii conform Codului Civil?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Rezoluțiunea și rezilierea contractelor pentru neexecutare",
                "entity_perspective": "parte contractantă prejudiciată",
                "laws": ["287/2009"],
                "concepts": [
                    "dreptul creditorului obligației neexecutate de a cere rezoluțiunea sau rezilierea contractului sinalagmatic, și modul de operare a rezoluțiunii: de drept, prin declarație unilaterală sau prin hotărâre judecătorească"
                ],
                "bm25_terms": ["rezolutiune reziliere contract neexecutare creditor", "rezolutiune declaratie unilaterala instanta"],
                "governing_norms": {"287/2009": ["1.549", "1.550"]},
            },
        ]
    },

    # ── Q10: Fiscal — dividend tax (SIMPLE) ──
    {
        "id": "Q10", "complexity": "SIMPLE", "domain": "fiscal",
        "question": "Care este cota de impozit pe dividende pentru un asociat persoană fizică la un SRL?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Impozitarea dividendelor persoane fizice",
                "entity_perspective": "asociat persoană fizică",
                "laws": ["227/2015"],
                "concepts": [
                    "impozitul pe veniturile din dividende distribuite persoanelor fizice, inclusiv cota de impozitare și modul de reținere la sursă de către plătitorul de dividende"
                ],
                "bm25_terms": ["impozit dividende persoana fizica cota retinere sursa"],
                "governing_norms": {"227/2015": ["97"]},
            },
        ]
    },

    # ── Q11: SA — extraordinary general assembly quorum (SIMPLE) ──
    {
        "id": "Q11", "complexity": "SIMPLE", "domain": "corporate",
        "question": "Care este cvorumul necesar pentru adunarea generală extraordinară a acționarilor la un SA?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Cvorum AGA extraordinară SA",
                "entity_perspective": "acționar SA",
                "laws": ["31/1990"],
                "concepts": [
                    "condițiile de cvorum și majoritate pentru hotărârile adunării generale extraordinare a acționarilor societății pe acțiuni, la prima și a doua convocare"
                ],
                "bm25_terms": ["adunare generala extraordinara actionar cvorum majoritate convocare"],
                "governing_norms": {"31/1990": ["115"]},
            },
        ]
    },

    # ── Q12: Insolvency — creditor ranking (STANDARD) ──
    {
        "id": "Q12", "complexity": "STANDARD", "domain": "insolvency",
        "question": "Care este ordinea de prioritate a creanțelor în procedura de insolvență?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Ordinea de plată a creanțelor în faliment",
                "entity_perspective": "creditor în procedura de insolvență",
                "laws": ["85/2014"],
                "concepts": [
                    "creanțele se plătesc în cazul falimentului în ordinea de prioritate prevăzută de lege, inclusiv fondurile obținute din vânzarea bunurilor și drepturilor din averea debitorului"
                ],
                "bm25_terms": ["creante platesc faliment ordine prioritate", "distribuire sume faliment ordine creante"],
                "governing_norms": {"85/2014": ["159", "161"]},
            },
        ]
    },

    # ── Q13: Civil Code — prescription (SIMPLE) ──
    {
        "id": "Q13", "complexity": "SIMPLE", "domain": "civil",
        "question": "Care este termenul general de prescripție extinctivă în dreptul civil?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Termenul general de prescripție extinctivă",
                "entity_perspective": "titular drept la acțiune",
                "laws": ["287/2009"],
                "concepts": [
                    "termenul prescripției extinctive este de 3 ani dacă legea nu prevede un alt termen, și termenele speciale de prescripție extinctivă"
                ],
                "bm25_terms": ["termen prescriptie extinctiva ani drept actiune"],
                "governing_norms": {"287/2009": ["2.517"]},
            },
        ]
    },

    # ── Q14: EU AI Act — high risk obligations (STANDARD) ──
    {
        "id": "Q14", "complexity": "STANDARD", "domain": "eu_law",
        "question": "Ce obligații au furnizorii de sisteme AI cu risc ridicat conform EU AI Act?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Obligații furnizori sisteme AI risc ridicat",
                "entity_perspective": "furnizor sistem AI",
                "laws": ["1689/2024"],
                "concepts": [
                    "obligations of providers of high-risk artificial intelligence systems including risk management system, data governance, technical documentation, transparency and human oversight requirements"
                ],
                "bm25_terms": ["provider high risk artificial intelligence obligations", "risk management system high-risk"],
                "governing_norms": {"1689/2024": ["16", "9"]},
            },
        ]
    },

    # ── Q15: Company merger (STANDARD) ──
    {
        "id": "Q15", "complexity": "STANDARD", "domain": "corporate",
        "question": "Care sunt pașii legali pentru fuziunea a două SRL-uri?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Procedura de fuziune a societăților",
                "entity_perspective": "SRL participant la fuziune",
                "laws": ["31/1990"],
                "concepts": [
                    "fuziunea este operațiunea prin care una sau mai multe societăți sunt dizolvate fără a intra în lichidare și transferă totalitatea patrimoniului lor unei alte societăți",
                    "proiectul de fuziune întocmit de administratorii societăților implicate și aprobarea fuziunii de către adunarea generală"
                ],
                "bm25_terms": ["fuziune societate dizolvare patrimoniu", "proiect fuziune administratori adunare generala"],
                "governing_norms": {"31/1990": ["238", "241"]},
            },
        ]
    },

    # ── Q16: Tort liability (STANDARD) ──
    {
        "id": "Q16", "complexity": "STANDARD", "domain": "civil",
        "question": "Care sunt condițiile răspunderii civile delictuale pentru fapta proprie?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Răspunderea civilă delictuală fapta proprie",
                "entity_perspective": "victimă a faptei ilicite",
                "laws": ["287/2009"],
                "concepts": [
                    "condițiile răspunderii civile delictuale pentru fapta proprie: fapta ilicită, prejudiciul, raportul de cauzalitate și vinovăția, și obligația de reparare integrală"
                ],
                "bm25_terms": ["raspundere delictuala fapta proprie prejudiciu cauzalitate vinovatie"],
                "governing_norms": {"287/2009": ["1.349", "1.357"]},
            },
        ]
    },

    # ── Q17: GDPR principles (SIMPLE) ──
    {
        "id": "Q17", "complexity": "SIMPLE", "domain": "eu_law",
        "question": "Care sunt principiile prelucrării datelor personale conform GDPR?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Principiile prelucrării datelor personale",
                "entity_perspective": "operator date personale",
                "laws": ["679/2016"],
                "concepts": [
                    "principiile prelucrării datelor cu caracter personal: legalitate, echitate, transparență, limitarea scopului, reducerea la minimum a datelor, exactitate, limitarea stocării, integritate și confidențialitate"
                ],
                "bm25_terms": ["principii prelucrare date personale legalitate echitate transparenta"],
                "governing_norms": {"679/2016": ["5"]},
            },
        ]
    },

    # ── Q18: Insolvency — judicial administrator powers (STANDARD) ──
    {
        "id": "Q18", "complexity": "STANDARD", "domain": "insolvency",
        "question": "Ce atribuții are administratorul judiciar în procedura de insolvență?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Atribuțiile administratorului judiciar",
                "entity_perspective": "administrator judiciar",
                "laws": ["85/2014"],
                "concepts": [
                    "atribuțiile principale ale administratorului judiciar în procedura generală de insolvență, inclusiv administrarea activității debitorului, examinarea creanțelor, întocmirea tabelului de creanțe și formularea de acțiuni în anulare"
                ],
                "bm25_terms": ["administrator judiciar atributii insolventa creante administrare"],
                "governing_norms": {"85/2014": ["58"]},
            },
        ]
    },

    # ── Q19: Criminal — fraud (SIMPLE) ──
    {
        "id": "Q19", "complexity": "SIMPLE", "domain": "criminal",
        "question": "Care sunt elementele constitutive ale infracțiunii de înșelăciune?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Infracțiunea de înșelăciune",
                "entity_perspective": "potențial inculpat / parte vătămată",
                "laws": ["286/2009"],
                "concepts": [
                    "infracțiunea de înșelăciune constând în inducerea în eroare a unei persoane prin prezentarea ca adevărată a unei fapte mincinoase sau ca mincinoasă a unei fapte adevărate, în scopul de a obține un folos patrimonial injust"
                ],
                "bm25_terms": ["inselaciune inducere eroare folos patrimonial injust"],
                "governing_norms": {"286/2009": ["244"]},
            },
        ]
    },

    # ── Q20: Digital Services Act — platform obligations (STANDARD) ──
    {
        "id": "Q20", "complexity": "STANDARD", "domain": "eu_law",
        "question": "Ce obligații de moderare a conținutului au platformele online foarte mari conform DSA?",
        "issues": [
            {
                "id": "ISSUE-1",
                "description": "Obligații platforme online foarte mari (VLOP)",
                "entity_perspective": "platformă online foarte mare",
                "laws": ["2065/2022"],
                "concepts": [
                    "additional obligations for very large online platforms regarding assessment and mitigation of systemic risks, including independent audit requirements, transparency of recommender systems, and risk management"
                ],
                "bm25_terms": ["very large online platform systemic risk assessment mitigation audit"],
                "governing_norms": {"2065/2022": ["34", "37"]},
            },
        ]
    },
]


def run_validation():
    db = SessionLocal()

    # Build law version lookup
    conn = sqlite3.connect('data/themis.db')
    law_versions = {}
    rows = conn.execute('''
        SELECT l.law_number || '/' || l.law_year as law_key, lv.id
        FROM law_versions lv JOIN laws l ON lv.law_id = l.id
        WHERE lv.is_current = 1
    ''').fetchall()
    for r in rows:
        law_versions[r[0]] = r[1]
    conn.close()

    total_norms = 0
    found_norms = 0
    all_results = []

    for tc in TEST_CASES:
        print(f"\n{'='*70}")
        print(f"  {tc['id']}: {tc['question'][:75]}...")
        print(f"  Complexity: {tc['complexity']} | Domain: {tc['domain']}")
        print(f"{'='*70}")

        for issue in tc["issues"]:
            print(f"\n  {issue['id']}: {issue['description']}")
            print(f"  Entity: {issue['entity_perspective']}")

            found_articles = {}  # "law:art" -> {source, distance}

            for law_key in issue["laws"]:
                if law_key not in law_versions:
                    print(f"    [SKIP] {law_key} not in DB")
                    continue
                vid = law_versions[law_key]

                # === SEMANTIC SEARCH ===
                for concept in issue["concepts"]:
                    try:
                        results = query_articles(
                            query_text=concept,
                            law_version_ids=[vid],
                            n_results=N_SEMANTIC
                        )
                        arts = []
                        for r in results:
                            an = r.get("article_number", "?")
                            d = r.get("distance", 999)
                            key = f"{law_key}:art.{an}"
                            if key not in found_articles or d < found_articles[key]["dist"]:
                                found_articles[key] = {"source": "sem", "dist": d}
                            arts.append(f"{an}({d:.2f})")
                        print(f"    Sem [{law_key}]: {' '.join(arts[:8])}")
                    except Exception as e:
                        print(f"    Sem ERROR: {e}")

                # === BM25 SEARCH ===
                for bq in issue["bm25_terms"]:
                    try:
                        results = search_bm25(
                            db=db,
                            query=bq,
                            law_version_ids=[vid],
                            limit=N_BM25
                        )
                        arts = []
                        for r in results:
                            an = r.get("article_number", "?")
                            key = f"{law_key}:art.{an}"
                            if key not in found_articles:
                                found_articles[key] = {"source": "bm25", "dist": 999}
                            arts.append(an)
                        print(f"    BM25[{law_key}]: {' '.join(arts[:8])}")
                    except Exception as e:
                        print(f"    BM25 ERROR: {e}")

            # === CHECK GOVERNING NORMS ===
            issue_total = 0
            issue_found = 0
            missing = []
            for law_key, expected in issue["governing_norms"].items():
                for art in expected:
                    issue_total += 1
                    total_norms += 1
                    key = f"{law_key}:art.{art}"
                    if key in found_articles:
                        src = found_articles[key]["source"]
                        d = found_articles[key]["dist"]
                        print(f"    ✓ {key} [{src}]" + (f" dist={d:.2f}" if d < 999 else ""))
                        issue_found += 1
                        found_norms += 1
                    else:
                        print(f"    ✗ {key} MISSING")
                        missing.append(key)

            pct = (issue_found / issue_total * 100) if issue_total else 0
            print(f"    Recall: {issue_found}/{issue_total} ({pct:.0f}%)")

            all_results.append({
                "qid": tc["id"], "iid": issue["id"],
                "desc": issue["description"][:55],
                "found": issue_found, "total": issue_total,
                "pct": pct, "missing": missing,
                "n_articles": len(found_articles),
            })

    # ── SUMMARY ──
    overall = (found_norms / total_norms * 100) if total_norms else 0
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    print(f"  Governing norms expected: {total_norms}")
    print(f"  Governing norms found:    {found_norms}")
    print(f"  Overall recall:           {overall:.1f}%")
    print(f"  Threshold:                85%")
    print(f"  Verdict:                  {'PASS' if overall >= 85 else 'FAIL'}")

    print(f"\n  Per-query:")
    cur_q = None
    for r in all_results:
        if r["qid"] != cur_q:
            cur_q = r["qid"]
            print()
        mark = "✓" if r["pct"] == 100 else ("~" if r["pct"] >= 50 else "✗")
        print(f"  {mark} {r['qid']}/{r['iid']}: {r['found']}/{r['total']} | {r['desc']}")
        for m in r["missing"]:
            print(f"      MISSING: {m}")

    failures = [r for r in all_results if r["missing"]]
    if failures:
        print(f"\n  FAILURES ({len(failures)} issues with gaps):")
        for r in failures:
            print(f"    {r['qid']}/{r['iid']}: {', '.join(r['missing'])}")

    db.close()
    return overall


if __name__ == "__main__":
    run_validation()
