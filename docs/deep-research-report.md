# RL-RAP.md

Romanian Legal Reasoning Analysis Protocol (RL-RAP) is the canonical reasoning framework for **Step 6.8** (the dedicated legal analysis step) in a Romanian-law legal assistant. It is designed for a **civil-law, norm-based, deductive** workflow (rule → conditions → subsumption → exceptions → conclusion), aligned with how Romanian legal reasoning is expected to operate under Romanian primary sources.

## Executive Summary

RL-RAP exists to stop the system from behaving like “document Q&A” and instead enforce a **repeatable Romanian-law analysis method** that can be audited and consumed by the answer-writing step.

**What Step 6.8 must do under RL-RAP**

- Convert “facts + retrieved legal texts” into **per-issue rule analysis**: operative articles, decomposed conditions, condition status, exceptions checked, conflict resolution, temporal applicability, conclusion, certainty, missing facts.
- Produce a **structured, machine-consumable** output so that Step 7 focuses mainly on *communication* rather than *thinking*.

**What RL-RAP prioritises**

- **No speculation**: unknown facts must remain UNKNOWN and be surfaced as missing facts.
- **Romanian-law validity checks**: non-retroactivity and EU-law priority rules must be acknowledged where relevant. citeturn8view0turn10view1  
- **Derogation discipline**: explicit “prin derogare de la…” patterns must be treated as binding derogations, consistent with legislative technique rules. citeturn5view2  
- **Procedural temporal rules**: new procedural rules apply only to processes/executions started after entry into force (where Step 6.8 is asked to reason about procedure). citeturn2view1  

**Inputs assumed by Step 6.8**

- Structured facts (from Step 1), including fact IDs and dates.
- Retrieved articles (top 20) with law/version metadata (per-issue versioning already handled by the pipeline).

**Outputs guaranteed by Step 6.8**

- A per-issue analysis object with stable keys and enums (defined in “Reasoning Output Standards”), including `missing_articles_needed` for a single conditional retrieval pass.

## Norm Decomposition

**Objective**

Turn legal text into an analysable rule structure by decomposing each relevant provision into:

- **Hypothesis**: applicability conditions (the “if”)
- **Disposition**: the rule (obligation/prohibition/permission/power)
- **Sanction/effect**: legal consequence (explicit or implicit)

This decomposition is critical because Step 6.8 must evaluate **conditions**, not “paragraph similarity”.

**Method**

For each candidate provision in the retrieved set:

- Split by **article → paragraph (alin.) → letter (lit.)** when those units carry separate normative content.
- Identify markers for conditions and modality:
  - Conditions: “dacă”, “în cazul în care”, “atunci când”, “cu condiția ca”, “în măsura în care”
  - Modality: “este obligat”, “trebuie”, “nu poate”, “este interzis”, “poate”, “se dispune”
- Identify:
  - **embedded exceptions** (“cu excepția…”, “nu se aplică…”) as separate exception blocks
  - **cross-references** (“potrivit art. …”) that must be fetched if essential

**Concrete rules**

- Treat each **lettered list** as either:
  - **alternative conditions** (OR-list) or
  - **cumulative conditions** (AND-list),
  and label it explicitly.  
  Example: the “fapte” list under **Legea nr. 85/2014 art. 169 alin. (1) lit. a–h** is structurally an OR-list of qualifying behaviours. citeturn13view2
- If a sanction is not explicit, do not invent it; mark it as **implicit** and name only the type (e.g., “patrimonial liability”, “nullity”) if the text clearly implies it.
- If a provision is mostly procedural (who may file / how it is tried), classify it as **PROCEDURAL RULE** and do not treat it as a substantive condition unless it is jurisdictional or admissibility-critical.

**Required output schema (per decomposed norm)**

```text
[NORM_DECOMP]
norm_ref: "<act> art.<n> alin.(<n>) lit.(<x>)"
law_name: "<Legea nr. ...>"
law_version_id: "<version id from pipeline>"
norm_type: RULE | DEFINITION | PROCEDURAL_RULE | REFERENCE_RULE
hypothesis_conditions:
  - id: "C1"
    text: "<atomic, testable condition>"
  - id: "C2"
    text: "<atomic, testable condition>"
disposition:
  modality: OBLIGATION | PROHIBITION | PERMISSION | POWER
  text: "<the operative rule, short>"
sanction_or_effect:
  explicit: true|false
  text: "<explicit sanction/effect or 'implicit: ...'>"
inline_exceptions:
  - id: "E1"
    trigger_text: "<exception wording>"
cross_references:
  - "<act> art.<n> alin.(<n>)"
[/NORM_DECOMP]
```

**Short Romanian example**

Issue context: *administrator responsibility in an SRL*

- **Legea nr. 31/1990 art. 72** is a reference rule: it states that administrator obligations/liability are governed by mandate rules and special provisions of the law. citeturn14view3  
- **Legea nr. 31/1990 art. 73 alin. (1)** is a substantive rule with a list of responsibility heads (a–e). citeturn14view1  

**REQUIRED BEHAVIOUR**

- Always output at least one `[NORM_DECOMP]` for each operative article used in the conclusion.
- Always extract conditions as **atomic tests** (each condition must be fact-checkable).
- Always surface **cross-references** that are necessary to understand/apply the rule.

**FORBIDDEN BEHAVIOUR**

- Treating an article as a “blob summary” without conditions.
- Collapsing exceptions into the main rule without a separate exception structure.
- Inventing sanctions, thresholds, deadlines, or procedural steps not present in the supplied text.

**Prompt snippet for Step 6.8**

```text
Decompose each operative provision into: hypothesis (conditions), disposition (rule), and sanction/effect. Extract hypothesis as atomic, fact-testable conditions. Separate inline exceptions and cross-references. Do not invent missing conditions or sanctions.
```

## Subsumption Method

**Objective**

Perform Romanian-style deductive reasoning (încadrare juridică / subsumption):

- Major premise: the legal norm (conditions + rule)
- Minor premise: structured facts
- Conclusion: applicability and consequences, with explicit uncertainty

Non-retroactivity is a constitutional baseline: law applies for the future (with explicit exceptions). citeturn8view0

**Method**

For each issue:

- Select operative norms.
- For each norm:
  - Evaluate each hypothesis condition as:
    - **SATISFIED**: supported by an explicit fact
    - **NOT_SATISFIED**: contradicted by an explicit fact
    - **UNKNOWN**: missing or insufficient information
- Produce:
  - condition-by-condition mapping to fact IDs,
  - a list of missing facts phrased as *questions the user/legal team must answer*.

**Concrete rules**

- UNKNOWN must never be “resolved” by guessing. If the fact is not present, it stays UNKNOWN.
- A single **NOT_SATISFIED** on a necessary condition makes the norm **inapplicable** (unless another alternative norm exists).
- If the norm is an OR-list (alternative), treat it as **satisfied** if at least one branch is SATISFIED; otherwise CONDITIONAL/UNKNOWN depending on missing facts.
- If a norm requires causation/connection explicitly, do not skip it.  
  Example: **Legea nr. 85/2014 art. 169 alin. (1)** caps liability by prejudice linked by causation and includes causation language; it must be treated as a condition when relevant. citeturn13view2

**Required output schema (per norm subsumption)**

```text
[SUBSUMPTION]
issue_id: "ISSUE-<n>"
norm_ref: "<act> art.<n> ..."
evaluations:
  - condition_id: "C1"
    status: SATISFIED | NOT_SATISFIED | UNKNOWN
    supporting_fact_ids: ["F1","F3"]
    missing_facts: ["<precise missing fact>"]
notes: "<1–2 lines, why this status>"
[/SUBSUMPTION]
```

**Short Romanian example**

Facts (structured, simplified):

- F1: „Administratorul a dispus plata de dividende.”
- F2: „Nu există profit distribuibil (conform ultimului bilanț).” (assume this fact is stated)

Norm:

- Legea nr. 31/1990 art. 73 alin. (1) lit. b) — administrators are jointly liable for the **real existence of paid dividends**. citeturn14view1

Subsumption:

- C1: Administrator capacity → UNKNOWN if not stated
- C2: Dividends were paid → SATISFIED (F1)
- C3: Dividends lacked real basis → SATISFIED (F2)

Conclusion should be **CONDITIONAL** if C1 is UNKNOWN; **PROBABLE/CERTAIN** only if C1 is SATISFIED and no exception/conflict.

**REQUIRED BEHAVIOUR**

- Every conclusion must be traceable to condition statuses.
- UNKNOWN must always generate at least one `missing_facts` item.
- Use the exact enum values: SATISFIED / NOT_SATISFIED / UNKNOWN.

**FORBIDDEN BEHAVIOUR**

- “Probably true” phrasing instead of UNKNOWN + missing fact.
- Skipping conditions because they are hard (e.g., causation, intent).
- Concluding legal liability without verifying standing/admissibility conditions when the law makes them relevant.

**Prompt snippet for Step 6.8**

```text
For each issue, evaluate each hypothesis condition as SATISFIED / NOT_SATISFIED / UNKNOWN strictly based on provided facts. UNKNOWN must produce a precise missing_facts entry. Do not speculate or fill gaps.
```

## Exception and Derogation Handling

**Objective**

Prevent the most common legal failure: stating the general rule while missing the exception/derogation.

Romanian legislative technique explicitly standardises derogations using “prin derogare de la …” and requires derogation to be made by an act of at least equal rank. citeturn5view2

**Method**

For each norm that is applicable or conditionally applicable:

- Check, in order:
  - Inline exceptions in the same provision
  - Derogations elsewhere in the same act
  - Special rules in another act (lex specialis)
- Treat each exception/derogation as its own mini-norm:
  - conditions
  - status evaluation
  - impact on the base norm

**Concrete rules**

- If derogation language exists (“prin derogare de la”), treat it as controlling and explicitly point to the derogated norm. citeturn5view2  
- If an exception applies, the conclusion must flip or narrow accordingly.
- If an exception is **procedural** (standing, deadline, forum), apply it before substantive conclusion if it blocks the claim.

**Required output schema**

```text
[EXCEPTIONS]
issue_id: "ISSUE-<n>"
base_norm_ref: "<act> art.<n> ..."
exceptions_checked:
  - exception_ref: "<act> art.<n> alin.(...)"
    type: INLINE_EXCEPTION | DEROGATION | SPECIAL_RULE
    condition_status_summary: SATISFIED | NOT_SATISFIED | UNKNOWN
    impact: "narrows rule | excludes liability | changes procedure | other"
    missing_facts: ["..."]
[/EXCEPTIONS]
```

**Short Romanian example**

Base norm: **Legea nr. 85/2014 art. 169 alin. (1)** (liability for insolvency entry). citeturn13view2  

Exception: **art. 169 alin. (5)** excludes liability if a member of a collegial body opposed/was absent and ensured the opposition was recorded. citeturn13view3  

Operationally: Step 6.8 must test:
- Was the person a member of a collegial management body?
- Did they oppose or was absent?
- Was opposition recorded later?

If unknown → the conclusion must remain CONDITIONAL.

**REQUIRED BEHAVIOUR**

- Always run an exception pass before finalising a conclusion.
- Explicitly list which exceptions were checked (even if “not applicable”).
- Use the derogation rule as written (do not treat “prin derogare” as decorative). citeturn5view2  

**FORBIDDEN BEHAVIOUR**

- “There may be exceptions” without identifying or checking them.
- Ignoring explicit exclusions like “nu va putea fi angajată” where present. citeturn13view3  
- Treating exception conditions as optional or “minor”.

**Prompt snippet for Step 6.8**

```text
Before concluding, check exceptions and derogations. Treat “prin derogare de la …” as a controlling derogation and identify the derogated norm. Model each exception as a mini-norm with conditions and SATISFIED/NOT_SATISFIED/UNKNOWN.
```

## Norm Hierarchy and Conflict Resolution

**Objective**

When multiple norms appear applicable but lead to different outcomes, Step 6.8 must either resolve the tension or declare it UNCERTAIN.

Romanian legislative technique requires acts be developed according to their hierarchy and competence, and addresses hierarchy explicitly. citeturn2view3  
It also regulates derogations and abrogations when provisions conflict with later norms of the same or higher level. citeturn5view2  

Romanian constitutional text establishes EU-law priority for binding EU rules over conflicting internal laws (within the accession framework). citeturn10view1  

**Method**

- Identify whether the situation is:
  - **No conflict** (general + special coexist)
  - **True conflict** (two rules prescribe incompatible outcomes for the same fact-pattern)
- Resolve in this order:
  - **Lex superior** (higher rank prevails)
  - **Lex specialis** (special prevails over general)
  - **Lex posterior** (later prevails within comparable rank), while being careful about special vs general interplay (supported in Romanian judicial reasoning). citeturn15search5turn15search1  
- If EU law is implicated:
  - mark the issue as EU-relevant and apply the constitutional priority rule for binding EU law. citeturn10view1  

**Concrete rules**

- A special rule does not need to say “I am special”; the legal system recognises the special-over-general approach when the special norm derogates in its domain. citeturn15search1turn15search5  
- If an older special norm and a newer general norm appear to clash, do not automatically pick the newer general norm; treat it as a conflict requiring explicit resolution and, if unclear, mark UNCERTAIN. citeturn15search5turn15search2  
- If a derogation exists, treat it as explicit conflict resolution (see legislative technique norm on derogation). citeturn5view2

**Required output schema**

```text
[CONFLICT_RESOLUTION]
issue_id: "ISSUE-<n>"
candidate_norms:
  - "<act1> art.<n> ..."
  - "<act2> art.<n> ..."
conflict_detected: true|false
resolution_rule: LEX_SUPERIOR | LEX_SPECIALIS | LEX_POSTERIOR | EU_PRIORITY | UNRESOLVED
chosen_norm: "<act> art.<n> ..."
rationale: "<2–4 lines in plain English>"
[/CONFLICT_RESOLUTION]
```

**Short Romanian example**

Scenario: A company in insolvency, and the question concerns administrator liability.

- General corporate liability heads may be discussed under **Legea nr. 31/1990 art. 72–73**. citeturn14view3turn14view1  
- Insolvency-specific patrimonial liability is governed by **Legea nr. 85/2014 art. 169**, which is tailored to insolvency entry and has its own conditions and exceptions. citeturn13view2turn13view3  

Step 6.8 should treat Legea 85/2014 as a **special framework** for the insolvent context (LEX_SPECIALIS), and then apply its condition/exceptions structure first.

**REQUIRED BEHAVIOUR**

- Declare conflicts explicitly when they exist; do not silently cite both.
- Provide a rule-based rationale (LEX_SUPERIOR / LEX_SPECIALIS / LEX_POSTERIOR / EU_PRIORITY).
- If unresolved, set certainty_level to UNCERTAIN and explain why.

**FORBIDDEN BEHAVIOUR**

- “Both apply” conclusions when outcomes are incompatible.
- Using LEX_POSTERIOR as a shortcut without checking special vs general.
- Ignoring EU priority when binding EU rules are explicitly relevant. citeturn10view1  

**Prompt snippet for Step 6.8**

```text
If norms lead to incompatible outcomes, declare a conflict and resolve using: lex superior, then lex specialis, then lex posterior (careful with special-vs-general). If EU binding law is implicated, apply EU priority per Constitution art.148(2).
```

## Temporal Applicability Rules

**Objective**

Ensure Step 6.8 reasons with the correct “law in time” logic *per issue* and explains temporal risks instead of silently applying the current rule.

Constitutional baseline: law applies only for the future, except the more favourable criminal/contraventional law. citeturn8view0  
Civil-law baseline: acts/facts occurring before entry into force of a new law cannot generate other effects than those under the old law (codified transitional logic). citeturn11view2  
Procedural baseline (civil procedure): new procedural rules apply only to proceedings/executions started after entry into force. citeturn2view1  

**Method**

For each issue:

- Identify the legally relevant event date(s) from structured facts.
- Confirm that the law version supplied by the pipeline is in force at the relevant date.
- Apply:
  - **Non-retroactivity** for substantive norms
  - **Immediate/prospective application** rules for procedural norms (where relevant)
- If a fallback occurred (e.g., only current version available):
  - flag temporal risk and downgrade certainty.

**Concrete rules**

- Never treat a post-event amendment as applicable unless:
  - it is procedural and the procedure began after entry into force, or
  - there is an explicit retroactivity rule (rare), or
  - it falls within the constitutional exception (penal/contraventional more favourable law). citeturn8view0turn2view1  
- If the issue spans time (e.g., legal relationship continues), split into phases and apply per-phase dates; if facts insufficient, make conclusion CONDITIONAL.
- If the norm references transitional provisions and they are not in the retrieved set, request them as missing articles.

**Required output schema**

```text
[TEMPORAL_APPLICABILITY]
issue_id: "ISSUE-<n>"
relevant_event_date: "YYYY-MM-DD"
law_versions_used:
  - law_name: "<Legea nr. ...>"
    law_version_id: "<id>"
    in_force_from: "YYYY-MM-DD"
    in_force_to: "YYYY-MM-DD | null"
rules_applied:
  - NON_RETROACTIVITY_CONSTITUTION_ART15
  - CIVIL_CODE_ART6
  - PROCEDURAL_CPC_ART24
temporal_risks:
  - "<fallback to current version>"
  - "<missing transitional provisions>"
[/TEMPORAL_APPLICABILITY]
```

**Short Romanian example**

Facts: “Fapta relevantă a avut loc în 2019.”  
Risk: the only available article text is from a 2024 amended version.

Step 6.8 must flag this as a temporal mismatch risk because *law applies prospectively* (Constitution art. 15(2)) and civil transitional rules prevent older acts from producing new-law effects. citeturn8view0turn11view2  

**REQUIRED BEHAVIOUR**

- Always include a temporal block for each issue.
- If the pipeline used fallback versions, explicitly state it and lower certainty.
- Distinguish procedural vs substantive temporal rules when relevant. citeturn2view1  

**FORBIDDEN BEHAVIOUR**

- Applying the current law text to past events without warnings.
- Assuming “same rule existed” without evidence.
- Ignoring the explicit constitutional non-retroactivity baseline. citeturn8view0  

**Prompt snippet for Step 6.8**

```text
For each issue, confirm the norm version is in force at the relevant event date. Apply non-retroactivity (Constitution art.15(2)) and civil transitional logic (Civil Code art.6). For procedure, apply CPC art.24. If fallback to current version occurred, flag temporal risk and downgrade certainty.
```

## Reasoning Output Standards

**Objective**

Define the output contract of Step 6.8 so Step 7 primarily formats and explains, rather than re-deriving legal applicability.

This standard also enforces “no false certainty” and enables downstream validation.

**Certainty levels**

| certainty_level | When allowed | Meaning in user-facing terms |
|---|---|---|
| CERTAIN | All necessary conditions SATISFIED; exceptions NOT_SATISFIED; no unresolved conflict; no major temporal risk | “Clear rule application on stated facts” |
| PROBABLE | Minor factual dependencies that do not normally change the outcome; no major conflict/temporal mismatch | “Likely, but verify a small factual point” |
| CONDITIONAL | At least one material condition/exception is UNKNOWN | “Outcome depends on missing facts” |
| UNCERTAIN | Missing critical law text, unresolved conflict, or severe temporal/version risk | “Cannot responsibly conclude without more inputs” |

(Design mapping; the legal baselines that motivate these cautions are rooted in the non-retroactivity and temporal-application rules above. citeturn8view0turn11view2turn2view1)

**Global REQUIRED BEHAVIOUR**

- Output must be machine-parseable with stable keys and enums.
- Every conclusion must cite **operative_articles** and rely on condition statuses.
- UNKNOWN must always produce `missing_facts` entries and push certainty to CONDITIONAL/UNCERTAIN.
- If cross-references are essential and absent, populate `missing_articles_needed`.

**Global FORBIDDEN BEHAVIOUR**

- Stating conclusions without specifying which rule/paragraph they come from.
- “Filling gaps” with assumptions instead of UNKNOWN.
- Ignoring explicit exclusions (e.g., “nu va putea fi angajată…”) when present. citeturn13view3  

**Machine-friendly Markdown block (primary output)**

```text
[RL_RAP_OUTPUT]
protocol_version: "RL-RAP-1.0"
generated_at: "YYYY-MM-DDTHH:MM:SS+02:00"
issues:
  - issue_id: "ISSUE-1"
    issue_label: "<short label>"
    operative_articles:
      - law_name: "<Legea nr. ...>"
        law_version_id: "<id>"
        article_ref: "art.<n> alin.(<n>) lit.(<x>)"
        doc_id: "<retrieved-article-id-if-available>"
    decomposed_conditions:
      - condition_id: "C1"
        norm_ref: "<...>"
        condition_text: "<atomic condition>"
        condition_status: SATISFIED | NOT_SATISFIED | UNKNOWN
        supporting_fact_ids: ["F1"]
        missing_facts: ["<precise missing fact>"]
    exceptions_checked:
      - exception_ref: "<...>"
        type: INLINE_EXCEPTION | DEROGATION | SPECIAL_RULE
        condition_status_summary: SATISFIED | NOT_SATISFIED | UNKNOWN
        missing_facts: ["..."]
        impact: "<short impact>"
    conflicts:
      - conflict_detected: true|false
        resolution_rule: LEX_SUPERIOR | LEX_SPECIALIS | LEX_POSTERIOR | EU_PRIORITY | UNRESOLVED
        chosen_norm: "<...>"
        rationale: "<short>"
    temporal_applicability:
      relevant_event_date: "YYYY-MM-DD"
      rules_applied: ["NON_RETROACTIVITY_CONSTITUTION_ART15","CIVIL_CODE_ART6"]
      temporal_risks: ["..."]
    conclusion: "<2–6 lines; conditional branches allowed>"
    certainty_level: CERTAIN | PROBABLE | CONDITIONAL | UNCERTAIN
    missing_facts: ["..."]
    missing_articles_needed: ["<act> art.<n> ..."]
[/RL_RAP_OUTPUT]
```

**Compact JSON schema example (for Step 7 consumption)**

```json
{
  "protocol_version": "RL-RAP-1.0",
  "issues": [
    {
      "issue_id": "ISSUE-1",
      "issue_label": "Insolvency-related patrimonial liability of administrator",
      "operative_articles": [
        {
          "law_name": "Legea nr. 85/2014",
          "law_version_id": "L85_2018-10-02+",
          "article_ref": "art.169 alin.(1) lit.(g)",
          "doc_id": "doc_85_169_1_g"
        },
        {
          "law_name": "Legea nr. 85/2014",
          "law_version_id": "L85_2018-10-02+",
          "article_ref": "art.169 alin.(6)",
          "doc_id": "doc_85_169_6"
        }
      ],
      "decomposed_conditions": [
        {
          "condition_id": "C1",
          "norm_ref": "Legea nr. 85/2014 art.169(1)(g)",
          "condition_text": "În luna precedentă încetării plăților s-a plătit cu preferință un creditor, în dauna celorlalți",
          "condition_status": "UNKNOWN",
          "supporting_fact_ids": ["F12"],
          "missing_facts": [
            "Data exactă a încetării plăților și dacă plata a fost în luna precedentă",
            "Dacă plata a fost preferențială față de alți creditori (contextul masei credale)"
          ]
        }
      ],
      "exceptions_checked": [
        {
          "exception_ref": "Legea nr. 85/2014 art.169 alin.(6)",
          "type": "INLINE_EXCEPTION",
          "condition_status_summary": "UNKNOWN",
          "missing_facts": [
            "Există un acord cu creditorii pentru restructurare? A existat bună-credință?"
          ],
          "impact": "If SATISFIED, liability under lit.(g) may be excluded for the payment described."
        }
      ],
      "conclusion": "CONDITIONAL: If the payment was made preferentially in the month preceding cessation of payments and no art.169(6) exception applies, liability under art.169(1)(g) is plausible. If the art.169(6) conditions are met (good-faith payments under a restructuring agreement), liability may be excluded for that conduct.",
      "certainty_level": "CONDITIONAL",
      "missing_facts": [
        "Cessation-of-payments date",
        "Payment timeline and creditor comparison",
        "Existence and content of restructuring agreement"
      ],
      "missing_articles_needed": []
    }
  ]
}
```

Legal anchor for the example’s operative structure (article and exception text existence): Legea nr. 85/2014 art. 169 alin. (1) lit. g) and alin. (6). citeturn13view2turn13view3  

**Compact YAML schema example (alternative)**

```yaml
protocol_version: RL-RAP-1.0
issues:
  - issue_id: ISSUE-2
    issue_label: "Administrator joint liability for company records"
    operative_articles:
      - law_name: "Legea nr. 31/1990"
        law_version_id: "L31_current"
        article_ref: "art.73 alin.(1) lit.(c)"
        doc_id: "doc_31_73_1_c"
    decomposed_conditions:
      - condition_id: C1
        norm_ref: "Legea nr. 31/1990 art.73(1)(c)"
        condition_text: "Există registrele cerute de lege și sunt ținute corect"
        condition_status: UNKNOWN
        supporting_fact_ids: []
        missing_facts:
          - "Ce registre lipsesc sau sunt ținute incorect și în ce perioadă?"
    exceptions_checked: []
    conflicts: []
    temporal_applicability:
      relevant_event_date: "2023-05-12"
      rules_applied: ["NON_RETROACTIVITY_CONSTITUTION_ART15"]
      temporal_risks: []
    conclusion: "CONDITIONAL: Dacă se confirmă lipsa/ținerea incorectă a registrelor cerute de lege în perioada mandatului, poate fi incidentă răspunderea solidară a administratorilor."
    certainty_level: CONDITIONAL
    missing_facts:
      - "Perioada mandatului administratorului"
      - "Documente/registre concrete și starea lor"
    missing_articles_needed: []
```

Legal anchor for the example’s base rule (administrator joint liability heads): Legea nr. 31/1990 art. 73 alin. (1) lit. c) and related structure. citeturn14view1  

**Prompt snippet for Step 6.8 (output enforcement)**

```text
Return output in RL-RAP format only.
For each issue include: operative_articles, decomposed_conditions with condition_status (SATISFIED/NOT_SATISFIED/UNKNOWN), exceptions_checked, conflicts, temporal_applicability, conclusion, certainty_level, missing_facts, missing_articles_needed.
UNKNOWN must remain UNKNOWN and must generate missing_facts. Do not speculate.
```