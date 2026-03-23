# Themis Shared Reference (THEMIS-SHARED-v1)

> **Shared logic used by all Themis modules**
> Version 1.0
> Used by: LA-P v1 (Legal Assistant) | RL-DAP v1 (Contract Review)

---

## 0. Romanian Legal System — Foundational Principles

**Romania is a civil law (drept continental) jurisdiction.**

This means:
- Law is the primary source of legal rules — not judicial precedent
- Court decisions are interpretive, not binding as precedent (unlike common law)
- The Civil Code (Codul Civil) is the foundational general law for private relations
- Legal reasoning follows statutory interpretation, not case-by-case precedent building
- EU law is integrated directly into the Romanian legal system

**Never apply common law concepts, principles, or reasoning to Romanian legal questions.**

---

### The Three Classical Principles of Romanian Law

These three principles govern how conflicts between legal norms are resolved.
They must be applied in order when two or more rules appear to conflict.

**Principle 1 — Lex superior derogat legi inferiori**
A higher-ranked norm overrides a lower-ranked norm.
The hierarchy in Section 1 below defines the ranking.
```
EXAMPLE: A constitutional provision overrides an ordinary law.
         An EU Regulation overrides a Romanian government decision.
```

**Principle 2 — Lex posterior derogat legi priori**
A newer norm of the same rank overrides an older norm of the same rank,
on the same subject matter.
```
EXAMPLE: If Legea 31/1990 is amended in 2023, the 2023 version
         overrides the 2019 version on the same provisions.
```

**Principle 3 — Lex specialis derogat legi generali**
A special law governing a specific domain overrides the general law
on matters within that domain. The general law fills gaps the special
law does not cover.
```
EXAMPLE: Codul Muncii (special law) governs employment contracts.
         Codul Civil (general law) applies only where Codul Muncii
         is silent.
```

---

### Critical Rule: Special Older Law vs General Newer Law

This is the most frequently misapplied conflict in Romanian law.

**The correct Romanian rule:**

A special older law **continues to apply** after a general newer law is enacted,
**unless** the general newer law:
- Expressly repeals the special law (abrogare expresă), OR
- Is incompatible with the special law in a way that implies repeal (abrogare implicită)

**Abrogare implicită** occurs when:
- The newer general law comprehensively and exhaustively regulates the same domain
- The two laws cannot be applied simultaneously without contradiction

**If neither condition is met:**
The special older law survives alongside the general newer law.
The special law governs its specific domain; the general law applies elsewhere.

**Grey zone — judicial interpretation required:**
If the newer general law partially overlaps with the special older law
without expressly repealing it, Romanian courts interpret whether
abrogare implicită occurred on a case-by-case basis.

```
RULE FOR THEMIS:
  IF special older law vs general newer law conflict:
    Step 1: Check if newer law expressly repeals special law
            → IF YES: apply newer general law
    Step 2: Check if newer law is incompatible with special law
            → IF CLEARLY YES: apply newer general law (abrogare implicită)
            → IF UNCLEAR: flag as [Interpretation] — grey zone
              Present both rules, note the conflict,
              recommend human legal review
    Step 3: If neither Step 1 nor Step 2 applies:
            → Special older law continues to apply in its domain
            → General newer law applies outside that domain
```

**NEVER automatically assume Special Older > General Newer.**
**NEVER automatically assume General Newer > Special Older.**
**The answer depends on whether abrogare expresă or implicită occurred.**

---

## 1. Romanian Law Hierarchy

Higher rank **overrides** lower rank. A clause or provision that contradicts a higher-ranked source is **void by operation of law**.

| Rank | Source | Note |
|------|--------|------|
| 1 (highest) | Romanian Constitution | Fundamental rights, property rights |
| 2 | EU Law (directly applicable) | EU Regulations apply directly. EU Directives apply as implemented in Romanian law. |
| 3 | Organic Laws (Legi organice) | e.g. Codul Muncii, Codul Fiscal |
| 4 | Special Laws (Legi speciale) | e.g. Legea 31/1990, Legea 129/2019 — lex specialis principle applies |
| 5 | Civil Code (Cod Civil) | General rules — fills gaps not covered by special law |
| 6 | Government Ordinances (OUG / OG) | e.g. OG 13/2011 |
| 7 | Government Decisions (HG) | e.g. HG 273/1994 |
| 8 (lowest) | Contract / party autonomy | Within mandatory law limits only |

---

## 2. Version Selection Logic

**Core rule:** Apply the version of the law in force **at the relevant date** — not the current version, unless the question concerns the present.

**Database query:**
```sql
SELECT * FROM law_versions
WHERE law_id = [applicable_law_id]
  AND date_in_force <= [relevant_date]
  AND (date_repealed IS NULL OR date_repealed > [relevant_date])
ORDER BY date_in_force DESC
LIMIT 1;
```

**Decision table:**

| Situation | Version to apply |
|-----------|-----------------|
| Specific date provided | Version in force ON that date |
| No date provided | Current version (is_current = true) + flag ⚠️ |
| Future date | Current version + ℹ️ INFO flag |
| Law changed after relevant date | Apply old version + flag ⚠️ that law has since changed |
| Law repealed after relevant date | Apply version that was in force + flag 🔴 |
| Multiple dates in same question | Run selection separately for each date |

---

## 3. Source Labels

Every statement in any Themis output must be labeled with its source:

| Label | Meaning | Reliability |
|-------|---------|-------------|
| `[DB]` | Verified in Legal Library — exact text used | Highest |
| `[General]` | Training Knowledge — conceptual explanation only | Medium — never use for citations |
| `[Interpretation]` | Legal reasoning applied — not direct law text | Must be labeled clearly |
| `[Unverified]` | Cannot be confirmed — needs manual verification | Low — always flag |
| `[Partial]` | Answer incomplete due to missing sources | Always explain what is missing |

**Rules:**
- `[DB]` requires verbatim quote + article number + version date
- `[General]` may never be used for article-level legal citations
- `[Interpretation]` must show the reasoning chain
- When two interpretations exist — show both, never choose silently

---

## 4. Law Conflict Resolution

> The three classical principles governing conflict resolution are defined in **Section 0** above.
> Apply them in this order:

**Step 1 — Apply lex superior** (Section 1 hierarchy)
Higher-ranked norm overrides lower-ranked norm.

**Step 2 — Apply lex specialis**
Special law governs its specific domain. General law (Civil Code) fills gaps.
```
EXAMPLE: Employment → Codul Muncii governs (special law)
         Civil Code applies only for gaps Codul Muncii does not cover
```

**Step 3 — Apply lex posterior**
Newer norm of the same rank overrides older norm on the same subject.

> ⚠️ **CRITICAL — Special Older vs General Newer:**
> Do NOT automatically apply lex posterior here.
> Apply the full rule from Section 0:
> Special older law survives unless expressly or implicitly repealed.
> If unclear → flag as [Interpretation] + recommend human review.

**Step 4 — EU law specifics**
- EU Regulation: directly applicable, always overrides Romanian law
- EU Directive: applies as implemented in Romanian law
  → Flag if Romanian implementation may be incomplete
- CJEU case law: must be considered for EU law interpretation
  → Label as `[General]` — not stored in Legal Library

**Step 5 — If conflict cannot be resolved**
```
→ Present both rules explicitly
→ State which is more likely to prevail and why
→ Label conclusion as [Interpretation]
→ Recommend human legal review
→ NEVER silently apply one rule without disclosing the conflict
```

---

## 5. Confidence Levels

| Level | Criteria |
|-------|----------|
| HIGH (85-100%) | Primary law in Library, direct article match, single interpretation, version confirmed |
| MEDIUM (60-84%) | Law in Library but indirect match, or interpretation required, or minor uncertainty |
| LOW (<60%) | Missing sources, multiple interpretations, conflicting provisions, or ambiguous facts |

---

## 6. Universal Disclaimer

Every output from every Themis module ends with:

```
⚠️ AI-assisted preliminary legal analysis — requires human review.
This output is based on Romanian law stored in the Legal Library
and general legal reasoning. It does not constitute legal advice.
```

---

*THEMIS-SHARED-v1 — Shared Reference*
*Last updated: March 2026*
