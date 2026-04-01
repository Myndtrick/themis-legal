"use client";

import { useEffect, useState } from "react";
import {
  api,
  type PipelineRunDetail as RunDetailType,
  type StepLogData,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/* Step display config                                                 */
/* ------------------------------------------------------------------ */

/** Maps internal step_number → human-readable display label + sort order */
const STEP_CONFIG: Record<
  number,
  { label: string; displayNum: string; order: number }
> = {
  1: { label: "Issue Classification", displayNum: "1", order: 1 },
  2: { label: "Date Extraction", displayNum: "2", order: 2 },
  3: { label: "Law Mapping", displayNum: "3", order: 3 },
  4: { label: "Version Currency Check", displayNum: "4", order: 4 },
  5: { label: "Early Relevance Gate", displayNum: "5", order: 5 },
  6: { label: "Version Selection", displayNum: "6", order: 6 },
  7: { label: "Hybrid Retrieval", displayNum: "7", order: 7 },
  8: { label: "Graph Expansion", displayNum: "8", order: 8 },
  9: { label: "Article Selection", displayNum: "9", order: 9 },
  10: { label: "Relevance Check", displayNum: "10", order: 10 },
  11: { label: "Article Partitioning", displayNum: "11", order: 11 },
  12: { label: "Legal Reasoning", displayNum: "12", order: 12 },
  13: { label: "Conditional Retrieval", displayNum: "13", order: 13 },
  14: { label: "Answer Generation", displayNum: "14", order: 14 },
  15: { label: "Citation Validation", displayNum: "15", order: 15 },
};

/** Maps V2 step names → human-readable display label */
const V2_STEP_NAME_LABELS: Record<string, string> = {
  classify: "Classify",
  resolve: "Resolve",
  retrieve: "Retrieve",
  reasoning: "Reasoning",
  answer: "Answer",
};

function getStepConfig(step: StepLogData) {
  return (
    STEP_CONFIG[step.step_number] ?? {
      label:
        V2_STEP_NAME_LABELS[step.step_name] ??
        step.step_name.replace(/_/g, " "),
      displayNum: String(step.step_number),
      order: step.step_number,
    }
  );
}

/* ------------------------------------------------------------------ */
/* output_data renderers per step type                                 */
/* ------------------------------------------------------------------ */

function renderOutputData(step: StepLogData) {
  const d = step.output_data;
  if (!d) return null;

  switch (step.step_name) {
    case "issue_classification":
      return <ClassificationDetail data={d} />;
    case "law_mapping":
      return <LawMappingDetail data={d} />;
    case "early_relevance_gate":
      return <EarlyGateDetail data={d} />;
    case "version_selection":
      return <VersionSelectionDetail data={d} />;
    case "hybrid_retrieval":
      return <RetrievalDetail data={d} />;
    case "graph_expansion":
      return <GraphExpansionDetail data={d} />;
    case "article_selection":
      return <SelectionDetail data={d} />;
    case "relevance_check":
      return <RelevanceDetail data={d} />;
    case "answer_generation":
      return <AnswerDetail data={d} />;
    case "citation_validation":
      return <CitationDetail data={d} />;
    case "date_extraction":
      return <DateExtractionDetail data={d} />;
    case "concept_resolution":
      return <ConceptResolutionDetail data={d} />;
    case "version_currency_check":
      return <VersionCurrencyDetail data={d} />;
    case "article_partitioning":
      return <PartitioningDetail data={d} />;
    case "legal_reasoning":
      return <LegalReasoningDetail data={d} />;
    case "conditional_retrieval":
      return <ConditionalRetrievalDetail data={d} />;
    default:
      return <GenericDetail data={d} />;
  }
}

/* --- Step 1c: Concept Resolution --- */
function ConceptResolutionDetail({ data }: { data: Record<string, unknown> }) {
  const validated = (data.validated_candidates ?? []) as Array<Record<string, unknown>>;
  const rejected = (data.rejected_candidates ?? []) as Array<Record<string, unknown>>;
  const concepts = (data.concept_search_results ?? []) as Array<Record<string, unknown>>;
  const totalProtected = data.total_protected as number | undefined;

  return (
    <div className="space-y-1.5">
      <Row label="Total protected" value={String(totalProtected ?? 0)} />

      {validated.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-green-700 mb-1">Validated Candidates</div>
          {validated.map((v, i) => (
            <div key={i} className="ml-2 text-green-600">
              {String(v.law_key)} art. {String(v.article)} (id={String(v.article_id)})
            </div>
          ))}
        </div>
      )}

      {rejected.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-red-600 mb-1">Rejected Candidates</div>
          {rejected.map((r, i) => (
            <div key={i} className="ml-2 text-red-500">
              {String(r.law_key)} art. {String(r.article)} — {String(r.status)}
            </div>
          ))}
        </div>
      )}

      {concepts.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">Concept Search Results</div>
          {concepts.map((c, i) => (
            <div key={i} className="ml-2 mb-2 p-2 bg-gray-100 rounded">
              <div className="font-medium">
                {String(c.issue_id)} — {String(c.law_key)}
              </div>
              <div className="text-gray-500 text-sm italic">
                &quot;{String(c.concept)}&quot;
              </div>
              <div className="mt-0.5">
                Found: {Array.isArray(c.found) ? (c.found as string[]).join(", ") : "none"}
                {c.top_distance != null && (
                  <span className="text-gray-400 ml-2">(dist: {String(c.top_distance)})</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* --- Step 1: Classification --- */
function ClassificationDetail({ data }: { data: Record<string, unknown> }) {
  const legalIssues = (data.legal_issues ?? []) as Array<Record<string, unknown>>;
  const facts = data.facts as Record<string, unknown> | undefined;
  const primaryTarget = data.primary_target as Record<string, unknown> | undefined;

  return (
    <div className="space-y-1.5">
      <Row label="Legal topic" value={data.legal_topic as string} />
      <Row label="Domain" value={data.legal_domain as string} />
      <Row label="Question type" value={data.question_type as string} />
      <Row label="Output mode" value={data.output_mode as string} />
      <Row label="Core issue" value={data.core_issue as string} />
      <Row label="Complexity" value={data.complexity as string} />
      {Array.isArray(data.entity_types) && data.entity_types.length > 0 && (
        <Row label="Entity types" value={data.entity_types.join(", ")} />
      )}

      {/* Primary Target */}
      {primaryTarget && (
        <div className="mt-2 p-2 bg-indigo-50 rounded text-indigo-800">
          <div className="font-medium mb-1">Primary Target</div>
          <div className="ml-2">
            <Row label="Actor" value={primaryTarget.actor as string} />
            <Row label="Concern" value={primaryTarget.concern as string} />
            <Row label="Focus issue" value={primaryTarget.issue_id as string} />
          </div>
        </div>
      )}

      {/* Issue Decomposition */}
      {legalIssues.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">Issue Decomposition</div>
          {legalIssues.map((issue, i) => {
            const laws = (issue.applicable_laws ?? []) as string[];
            return (
              <div key={i} className="ml-2 mb-2 p-2 bg-gray-100 rounded">
                <div className="font-medium">
                  {issue.issue_id as string}: {issue.description as string}
                </div>
                {laws.length > 0 && (
                  <div className="text-gray-500 mt-0.5">
                    Laws: {laws.join(", ")}
                  </div>
                )}
                {issue.relevant_date ? (
                  <div className="text-gray-500">
                    Date: {String(issue.relevant_date)}
                    {issue.temporal_rule ? (
                      <span className="italic"> ({String(issue.temporal_rule)})</span>
                    ) : null}
                  </div>
                ) : null}
                <Row label="Priority" value={issue.priority as string} />
                {/* Candidate Articles */}
                {Array.isArray(issue.candidate_articles) && (issue.candidate_articles as Array<Record<string, unknown>>).length > 0 && (
                  <div className="mt-1">
                    <span className="text-gray-400 text-sm">Candidates: </span>
                    {(issue.candidate_articles as Array<Record<string, unknown>>).map((ca, j) => (
                      <span key={j} className="text-sm text-gray-600">
                        {String(ca.law_key)} art. {String(ca.article)}
                        {j < (issue.candidate_articles as Array<Record<string, unknown>>).length - 1 ? ", " : ""}
                      </span>
                    ))}
                  </div>
                )}
                {/* Concept Descriptions */}
                {Array.isArray(issue.concept_descriptions) && (issue.concept_descriptions as Array<Record<string, unknown>>).length > 0 && (
                  <div className="mt-1">
                    <span className="text-gray-400 text-sm">Concepts: </span>
                    {(issue.concept_descriptions as Array<Record<string, unknown>>).map((cd, j) => (
                      <span key={j} className="text-sm text-blue-600 italic">
                        {String(cd.law_key)}: &quot;{String((cd.concept_general as string || "").slice(0, 60))}...&quot;
                        {j < (issue.concept_descriptions as Array<Record<string, unknown>>).length - 1 ? " | " : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Facts */}
      {facts && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">Facts Extracted</div>
          {Array.isArray(facts.stated) && (facts.stated as Array<Record<string, unknown>>).length > 0 && (
            <div className="ml-2 mb-1">
              <span className="font-medium text-green-700">Stated:</span>
              {(facts.stated as Array<Record<string, unknown>>).map((f, i) => (
                <div key={i} className="ml-2">
                  {f.fact_id as string}: {f.description as string}
                  {f.date ? <span className="text-gray-400"> ({String(f.date)})</span> : null}
                </div>
              ))}
            </div>
          )}
          {Array.isArray(facts.assumed) && (facts.assumed as Array<Record<string, unknown>>).length > 0 && (
            <div className="ml-2 mb-1">
              <span className="font-medium text-yellow-700">Assumed:</span>
              {(facts.assumed as Array<Record<string, unknown>>).map((f, i) => (
                <div key={i} className="ml-2">
                  {f.fact_id as string}: {f.description as string}
                </div>
              ))}
            </div>
          )}
          {Array.isArray(facts.missing) && (facts.missing as Array<Record<string, unknown>>).length > 0 && (
            <div className="ml-2 mb-1">
              <span className="font-medium text-red-700">Missing:</span>
              {(facts.missing as Array<Record<string, unknown>>).map((f, i) => (
                <div key={i} className="ml-2">
                  {f.fact_id as string}: {f.description as string}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {Array.isArray(data.sub_issues) && data.sub_issues.length > 0 && (
        <div>
          <span className="font-medium text-gray-500">Sub-issues: </span>
          <ul className="list-disc list-inside ml-2">
            {(data.sub_issues as string[]).map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      {data.reasoning ? (
        <div className="mt-1 p-2 bg-blue-50 rounded text-blue-800">
          <span className="font-medium">Reasoning: </span>
          {String(data.reasoning)}
        </div>
      ) : null}
      <Row
        label="Classification confidence"
        value={data.classification_confidence as string}
      />
    </div>
  );
}

/* --- Step 2: Law Mapping --- */
function LawMappingDetail({ data }: { data: Record<string, unknown> }) {
  const candidates = (data.candidate_laws ?? []) as Array<Record<string, unknown>>;
  const missing = (data.missing_laws ?? []) as Array<Record<string, unknown>>;
  const tiers: Record<string, typeof candidates> = {};
  for (const c of candidates) {
    const tier = (c.tier as string) || "unknown";
    (tiers[tier] ??= []).push(c);
  }

  return (
    <div className="space-y-2">
      {Object.entries(tiers).map(([tier, laws]) => (
        <div key={tier}>
          <div className="font-medium text-gray-700 capitalize">
            {tier.replace("tier1_", "").replace("tier2_", "").replace("tier3_", "").toUpperCase()}
          </div>
          {laws.map((l, i) => (
            <div key={i} className="ml-3 flex gap-2">
              <span>
                {String(l.title)} ({String(l.law_number)}/{String(l.law_year)})
              </span>
              <span
                className={`text-xs px-1 rounded ${l.db_law_id ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}
              >
                {l.db_law_id ? "in DB" : "MISSING"}
              </span>
              {l.reason ? (
                <span className="text-gray-400">— {String(l.reason)}</span>
              ) : null}
            </div>
          ))}
        </div>
      ))}
      {missing.length > 0 && (
        <div className="mt-1 p-2 bg-red-50 rounded text-red-800">
          <span className="font-medium">Missing laws: </span>
          {missing.map((l) => `${l.title} (${l.law_number}/${l.law_year})`).join(", ")}
        </div>
      )}
    </div>
  );
}

/* --- Step 2.5: Early Relevance Gate --- */
function EarlyGateDetail({ data }: { data: Record<string, unknown> }) {
  const triggered = data.gate_triggered as boolean;
  return (
    <div className="space-y-1">
      <div
        className={`p-2 rounded ${triggered ? "bg-orange-50 text-orange-800" : "bg-green-50 text-green-800"}`}
      >
        {triggered
          ? `Gate TRIGGERED — pipeline stopped (${data.trigger_reason})`
          : "Gate passed — pipeline continues"}
      </div>
      <Row
        label="Primary laws total"
        value={String(data.primary_laws_total ?? "—")}
      />
      {triggered && (
        <>
          <Row
            label="Primary laws missing"
            value={String(data.primary_laws_missing ?? 0)}
          />
          <Row
            label="Clarification round"
            value={String(data.clarification_round ?? 0)}
          />
        </>
      )}
      {!triggered && (
        <Row
          label="Primary laws in DB"
          value={String(data.primary_laws_in_db ?? "—")}
        />
      )}
    </div>
  );
}

/* --- Step 3: Version Selection --- */
function VersionSelectionDetail({ data }: { data: Record<string, unknown> }) {
  const versions = (data.selected_versions ?? {}) as Record<
    string,
    Record<string, unknown>
  >;
  const issueVersions = (data.issue_versions ?? {}) as Record<
    string,
    Record<string, unknown>
  >;
  const notes = (data.notes ?? []) as string[];
  const amendments = (data.amendment_flags ?? []) as string[];

  // If issue_versions is available, prefer showing that (richer per-issue view)
  const hasIssueVersions = Object.keys(issueVersions).length > 0;

  return (
    <div className="space-y-1">
      <Row label="Primary date" value={data.primary_date as string} />
      <Row label="Unique versions" value={data.unique_version_count != null ? String(data.unique_version_count) : undefined} />

      {hasIssueVersions ? (
        <div className="mt-1">
          <div className="font-medium text-gray-500 mb-1">Per-issue version selection:</div>
          {Object.entries(issueVersions).map(([key, v]) => (
            <div key={key} className="ml-2 mb-1 p-1.5 bg-gray-100 rounded">
              <div className="flex gap-2 items-center flex-wrap">
                <span className="font-medium">{key}</span>
                <span>version {(v.date_in_force as string) ?? "unknown"}</span>
                <span
                  className={`text-xs px-1 rounded ${v.is_current ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}
                >
                  {v.is_current ? "current" : "historical"}
                </span>
              </div>
              {v.temporal_rule ? (
                <div className="text-gray-500 ml-2 italic">
                  Temporal rule: {String(v.temporal_rule)}
                </div>
              ) : null}
              {v.date_reasoning ? (
                <div className="text-gray-500 ml-2">
                  {String(v.date_reasoning)}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        Object.entries(versions).map(([key, v]) => (
          <div key={key} className="ml-1 flex gap-2 items-center">
            <span className="font-medium">{key}:</span>
            <span>version {(v.date_in_force as string) ?? "unknown"}</span>
            <span
              className={`text-xs px-1 rounded ${v.is_current ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}
            >
              {v.is_current ? "current" : "historical"}
            </span>
          </div>
        ))
      )}

      {amendments.length > 0 && (
        <div className="mt-1 p-2 bg-yellow-50 rounded text-yellow-800">
          {amendments.map((a, i) => (
            <div key={i}>{a}</div>
          ))}
        </div>
      )}
      {notes.length > 0 &&
        notes.map((n, i) => (
          <div key={i} className="text-gray-500 italic">
            {n}
          </div>
        ))}
    </div>
  );
}

/* --- Step 4: Hybrid Retrieval --- */
function RetrievalDetail({ data }: { data: Record<string, unknown> }) {
  const top = (data.top_articles ?? []) as Array<Record<string, unknown>>;
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="BM25" value={data.bm25_count} />
        <Stat label="Semantic" value={data.semantic_count} />
        <Stat label="Entity" value={data.entity_count} />
        <Stat label="Dupes removed" value={data.duplicates_removed} />
      </div>
      <Row
        label="Total unique"
        value={String(data.article_count ?? "—")}
      />
      {top.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">
            Top articles by score:
          </div>
          <table className="w-full text-left">
            <thead>
              <tr className="text-gray-400">
                <th className="pr-2">#</th>
                <th className="pr-2">Article</th>
                <th className="pr-2">Law</th>
                <th className="pr-2">Source</th>
                <th className="pr-2">Score</th>
              </tr>
            </thead>
            <tbody>
              {top.map((a, i) => (
                <tr key={i}>
                  <td className="pr-2 text-gray-400">{i + 1}</td>
                  <td className="pr-2">Art. {a.article_number as string}</td>
                  <td className="pr-2">{a.law as string}</td>
                  <td className="pr-2 text-gray-400">{a.source as string}</td>
                  <td className="pr-2 font-mono">
                    {a.bm25_rank != null
                      ? `bm25: ${a.bm25_rank}`
                      : a.distance != null
                        ? `dist: ${a.distance}`
                        : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* --- Step 5: Graph Expansion --- */
function GraphExpansionDetail({ data }: { data: Record<string, unknown> }) {
  const addedArticles = (data.added_articles ?? []) as Array<Record<string, unknown>>;
  const triggers = (data.expansion_triggers ?? []) as Array<Record<string, unknown>>;

  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Before" value={data.articles_before} />
        <Stat label="After" value={data.articles_after} />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Neighbors" value={data.neighbors_added} />
        <Stat label="Cross-refs" value={data.crossrefs_added} />
        <Stat label="Exceptions" value={data.exceptions_added} />
      </div>
      {addedArticles.length > 0 && (
        <div className="mt-1">
          <div className="font-medium text-gray-500 mb-0.5">Added articles:</div>
          {addedArticles.map((a, i) => (
            <div key={i} className="ml-2 flex gap-2 text-gray-600">
              <span>Art. {a.article_number as string}</span>
              <span className="text-gray-400">{a.law as string}</span>
              <span className="text-xs px-1 rounded bg-gray-100 text-gray-500">
                {a.source as string}
              </span>
            </div>
          ))}
        </div>
      )}
      {triggers.length > 0 && (
        <div className="mt-1">
          <div className="font-medium text-gray-500 mb-0.5">Expansion triggers:</div>
          {triggers.map((t, i) => (
            <div key={i} className="ml-2 text-gray-500">
              Art. {t.source_article as string} &rarr; Art. {t.target_article as string}
              {t.type ? <span className="text-xs ml-1">({String(t.type)})</span> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* --- Step 6: Article Selection --- */
function SelectionDetail({ data }: { data: Record<string, unknown> }) {
  const kept = (data.kept_articles ?? []) as Array<Record<string, unknown>>;
  const dropped = (data.dropped_articles ?? []) as Array<Record<string, unknown>>;
  const fallback = data.fallback_used as boolean;

  return (
    <div className="space-y-1.5">
      {fallback && (
        <div className="p-2 bg-orange-50 rounded text-orange-800 font-medium">
          FALLBACK reranker used — {data.fallback_reason as string}
        </div>
      )}
      <Row label="Method" value={(data.method as string) ?? "—"} />
      <Row
        label="Total candidates"
        value={String(data.total_candidates ?? "—")}
      />
      <Row label="Kept" value={String(kept.length)} />
      <Row label="Dropped" value={String(data.dropped_count ?? 0)} />

      {data.selection_reasoning ? (
        <div className="mt-1 p-2 bg-blue-50 rounded text-blue-800">
          <span className="font-medium">Claude reasoning: </span>
          {String(data.selection_reasoning)}
        </div>
      ) : null}

      {kept.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">Kept articles:</div>
          <table className="w-full text-left">
            <thead>
              <tr className="text-gray-400">
                <th className="pr-2">#</th>
                <th className="pr-2">Article</th>
                <th className="pr-2">Law</th>
                <th className="pr-2">Score</th>
              </tr>
            </thead>
            <tbody>
              {kept.map((a, i) => (
                <tr key={i}>
                  <td className="pr-2 text-gray-400">{i + 1}</td>
                  <td className="pr-2">Art. {a.article_number as string}</td>
                  <td className="pr-2">{a.law as string}</td>
                  <td className="pr-2 font-mono">{String(a.score ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dropped.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">
            Dropped articles (showing up to 20):
          </div>
          <table className="w-full text-left">
            <thead>
              <tr className="text-gray-400">
                <th className="pr-2">Article</th>
                <th className="pr-2">Law</th>
                <th className="pr-2">Score</th>
              </tr>
            </thead>
            <tbody>
              {dropped.map((a, i) => (
                <tr key={i} className="text-gray-400">
                  <td className="pr-2">Art. {a.article_number as string}</td>
                  <td className="pr-2">{a.law as string}</td>
                  <td className="pr-2 font-mono">{String(a.score ?? "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* --- Step 6.5: Relevance Check --- */
function RelevanceDetail({ data }: { data: Record<string, unknown> }) {
  const score = data.relevance_score as number;
  const gateTriggered = data.gate_triggered as boolean;
  const gateWarning = data.gate_warning as boolean;

  return (
    <div className="space-y-1.5">
      <div
        className={`p-2 rounded font-medium ${
          gateTriggered
            ? "bg-red-50 text-red-800"
            : gateWarning
              ? "bg-yellow-50 text-yellow-800"
              : "bg-green-50 text-green-800"
        }`}
      >
        Relevance score: {score != null ? score.toFixed(2) : "—"}{" "}
        {gateTriggered
          ? "— LOW (gate triggered)"
          : gateWarning
            ? "— PARTIAL"
            : "— OK"}
      </div>
      <Row
        label="Domain match"
        value={data.domain_match === false ? "NO" : "yes"}
      />
      {data.missing_coverage ? (
        <div className="mt-1 p-2 bg-yellow-50 rounded text-yellow-800">
          <span className="font-medium">Missing coverage: </span>
          {String(data.missing_coverage)}
        </div>
      ) : null}
      {data.suggested_clarification ? (
        <div className="mt-1 p-2 bg-blue-50 rounded text-blue-800">
          <span className="font-medium">Suggested clarification: </span>
          {String(data.suggested_clarification)}
        </div>
      ) : null}
    </div>
  );
}

/* --- Step 7: Answer Generation --- */
function AnswerDetail({ data }: { data: Record<string, unknown> }) {
  const sources = (data.sources ?? []) as Array<Record<string, unknown>>;
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="Articles provided" value={data.articles_provided} />
        <Stat label="Articles cited" value={data.articles_cited} />
        <Stat label="Not cited" value={data.articles_not_cited} />
        <Stat label="Confidence" value={data.confidence} />
      </div>
      <Row label="Output mode" value={data.output_mode as string} />
      {data.is_partial ? (
        <div className="p-2 bg-yellow-50 rounded text-yellow-800">
          Partial answer — some primary laws were missing
        </div>
      ) : null}
      {data.confidence_reasoning ? (
        <div className="mt-1 p-2 bg-blue-50 rounded text-blue-800">
          <span className="font-medium">Confidence reasoning: </span>
          {String(data.confidence_reasoning)}
        </div>
      ) : null}
      {Array.isArray(data.caveats) && (data.caveats as string[]).length > 0 && (
        <div className="mt-1 p-2 bg-yellow-50 rounded text-yellow-800">
          <div className="font-medium mb-0.5">Caveats:</div>
          <ul className="list-disc list-inside ml-1">
            {(data.caveats as string[]).map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}
      {sources.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">
            Sources cited ({sources.length}):
          </div>
          {sources.map((s, i) => (
            <div key={i} className="ml-2 flex gap-2">
              <span
                className={`text-xs px-1 rounded ${
                  s.label === "DB"
                    ? "bg-green-100 text-green-700"
                    : s.label === "Unverified"
                      ? "bg-red-100 text-red-700"
                      : "bg-gray-100 text-gray-600"
                }`}
              >
                {s.label as string}
              </span>
              <span>
                Art. {s.article as string} — {s.law as string}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* --- Step 7.5: Citation Validation --- */
function CitationDetail({ data }: { data: Record<string, unknown> }) {
  if (data.skipped) {
    return (
      <div className="text-gray-400 italic">
        Skipped — {data.reason as string}
      </div>
    );
  }
  const downgraded = (data.downgraded_citations ?? []) as Array<
    Record<string, unknown>
  >;
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Total DB citations" value={data.total_db_citations} />
        <Stat label="Validated" value={data.validated} />
        <Stat label="Downgraded" value={data.downgraded} />
      </div>
      {data.confidence_downgraded ? (
        <div className="p-2 bg-red-50 rounded text-red-800 font-medium">
          Confidence lowered to LOW — majority of citations unverified
        </div>
      ) : null}
      {downgraded.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">
            Downgraded citations:
          </div>
          {downgraded.map((c, i) => (
            <div key={i} className="ml-2 text-red-700">
              Art. {c.article as string} from {c.law as string}: {c.original_label as string} → {c.new_label as string}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* --- Step 2: Date Extraction --- */
function DateExtractionDetail({ data }: { data: Record<string, unknown> }) {
  const datesFound = (data.dates_found ?? []) as Array<Record<string, unknown>>;
  return (
    <div className="space-y-1.5">
      <Row label="Date type" value={data.date_type as string} />
      <Row label="Primary date" value={data.primary_date as string} />
      {datesFound.length > 0 && (
        <div>
          <span className="font-medium text-gray-500">Dates found:</span>
          {datesFound.map((d, i) => (
            <div key={i} className="ml-2">
              {d.date as string}
              {d.original_text ? (
                <span className="text-gray-400"> &mdash; &quot;{String(d.original_text)}&quot;</span>
              ) : null}
              {d.type ? (
                <span className="text-xs ml-1 px-1 rounded bg-gray-100 text-gray-600">
                  {String(d.type)}
                </span>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* --- Step 4: Version Currency Check --- */
function VersionCurrencyDetail({ data }: { data: Record<string, unknown> }) {
  const lawDetails = (data.law_details ?? []) as Array<Record<string, unknown>>;
  return (
    <div className="space-y-1.5">
      <Row label="Stale count" value={String(data.stale_count ?? 0)} />
      {lawDetails.length > 0 && (
        <div className="mt-1">
          <div className="font-medium text-gray-500 mb-1">Per-law currency:</div>
          {lawDetails.map((law, i) => {
            const status = law.currency_status as string;
            const isStale = status === "stale";
            const isCurrent = status === "current";
            return (
              <div key={i} className="ml-2 mb-1.5 p-2 bg-gray-100 rounded">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{law.law_key as string}</span>
                  {law.title ? <span className="text-gray-400 truncate">{String(law.title)}</span> : null}
                  <span className={`text-xs px-1 rounded ${
                    isCurrent ? "bg-green-100 text-green-700" :
                    isStale ? "bg-red-100 text-red-700" :
                    "bg-gray-200 text-gray-600"
                  }`}>
                    {status}
                  </span>
                  {law.role ? (
                    <span className="text-xs px-1 rounded bg-blue-100 text-blue-700">
                      {String(law.role)}
                    </span>
                  ) : null}
                </div>
                <div className="ml-2 text-gray-500">
                  {law.db_latest_date ? <div>DB version: {String(law.db_latest_date)}</div> : null}
                  {law.official_latest_date ? <div>Official latest: {String(law.official_latest_date)}</div> : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* --- Step 11: Article Partitioning --- */
function PartitioningDetail({ data }: { data: Record<string, unknown> }) {
  const breakdown = (data.issue_breakdown ?? {}) as Record<string, Array<Record<string, unknown>>>;
  const shared = (data.shared_context ?? []) as Array<Record<string, unknown>>;

  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Issues with articles" value={data.issues_with_articles} />
        <Stat label="Shared context" value={data.shared_context_count} />
      </div>
      {Object.entries(breakdown).map(([issueId, articles]) => (
        <div key={issueId} className="mt-1">
          <div className="font-medium text-gray-700">
            {issueId}: {articles.length} article{articles.length !== 1 ? "s" : ""}
          </div>
          {articles.map((a, i) => (
            <div key={i} className="ml-3 flex gap-2 text-gray-600">
              <span>Art. {a.article_number as string}</span>
              <span className="text-gray-400">{a.law as string}</span>
              {a.score != null && (
                <span className="font-mono text-gray-400">score: {String(a.score)}</span>
              )}
            </div>
          ))}
        </div>
      ))}
      {shared.length > 0 && (
        <div className="mt-1">
          <div className="font-medium text-gray-500">
            Shared context ({shared.length}):
          </div>
          {shared.map((a, i) => (
            <div key={i} className="ml-3 text-gray-400">
              Art. {a.article_number as string} &mdash; {a.law as string}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* --- Step 12: Legal Reasoning (RL-RAP) --- */
function LegalReasoningDetail({ data }: { data: Record<string, unknown> }) {
  const rlRap = data.rl_rap as Record<string, unknown> | undefined;
  const certaintyLevels = (data.certainty_levels ?? {}) as Record<string, string>;

  if (!rlRap) {
    return (
      <div className="space-y-1.5">
        <div className="font-medium text-gray-500 mb-1">Certainty Levels</div>
        {Object.entries(certaintyLevels).map(([id, level]) => (
          <div key={id} className="ml-2">
            <span className="font-medium">{id}:</span>{" "}
            <CertaintyBadge level={level} />
          </div>
        ))}
      </div>
    );
  }

  const issues = (rlRap.issues ?? []) as Array<Record<string, unknown>>;

  return (
    <div className="space-y-3">
      {issues.map((issue, idx) => (
        <div key={idx} className="border border-gray-200 rounded-lg overflow-hidden">
          {/* Issue header */}
          <div className="bg-gray-100 px-3 py-2 flex items-center gap-2">
            <span className="font-medium">{issue.issue_id as string}</span>
            <span className="text-gray-500 flex-1">{issue.description as string}</span>
            <CertaintyBadge level={issue.certainty_level as string} />
          </div>

          <div className="px-3 py-2 space-y-2">
            {/* Operative Articles */}
            {Array.isArray(issue.operative_articles) && (issue.operative_articles as Array<Record<string, unknown>>).length > 0 ? (
              <div>
                <div className="font-medium text-gray-500 mb-0.5">Operative Articles</div>
                {(issue.operative_articles as Array<Record<string, unknown>>).map((oa, i) => (
                  <div key={i} className="ml-2 flex gap-2 items-center">
                    <span>{oa.article_ref as string}</span>
                    <span className={`text-xs px-1 rounded ${
                      oa.priority === "PRIMARY" ? "bg-blue-100 text-blue-700" :
                      oa.priority === "SECONDARY" ? "bg-gray-100 text-gray-600" :
                      "bg-gray-50 text-gray-500"
                    }`}>
                      {oa.priority as string}
                    </span>
                    {oa.norm_type ? (
                      <span className="text-xs text-gray-400">{String(oa.norm_type)}</span>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}

            {/* Condition Table */}
            {Array.isArray(issue.condition_table) && (issue.condition_table as Array<Record<string, unknown>>).length > 0 ? (
              <div>
                <div className="font-medium text-gray-500 mb-0.5">Condition Table</div>
                <table className="w-full text-left">
                  <thead>
                    <tr className="text-gray-400">
                      <th className="pr-2 w-10">ID</th>
                      <th className="pr-2">Condition</th>
                      <th className="pr-2 w-28">Status</th>
                      <th className="pr-2">Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(issue.condition_table as Array<Record<string, unknown>>).map((c, i) => (
                      <tr key={i} className="border-t border-gray-100">
                        <td className="pr-2 text-gray-400">{c.condition_id as string}</td>
                        <td className="pr-2">{c.condition_text as string}</td>
                        <td className="pr-2">
                          <ConditionStatusBadge status={c.status as string} />
                        </td>
                        <td className="pr-2 text-gray-500">
                          {(c.evidence as string) || (c.missing_fact as string) || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {/* Subsumption Summary */}
            {issue.subsumption_summary ? (() => {
              const sub = issue.subsumption_summary as Record<string, unknown>;
              return (
                <div className="p-2 bg-gray-50 rounded">
                  <div className="font-medium text-gray-500 mb-0.5">Subsumption</div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <Stat label="Total" value={sub.total_conditions} />
                    <Stat label="Satisfied" value={sub.satisfied} />
                    <Stat label="Not satisfied" value={sub.not_satisfied} />
                    <Stat label="Unknown" value={sub.unknown} />
                  </div>
                  <div className="mt-1">
                    <Row label="Norm applicable" value={sub.norm_applicable as string} />
                    {Array.isArray(sub.blocking_unknowns) && (sub.blocking_unknowns as string[]).length > 0 && (
                      <div className="text-yellow-700">
                        Blocking unknowns: {(sub.blocking_unknowns as string[]).join(", ")}
                      </div>
                    )}
                  </div>
                </div>
              );
            })() : null}

            {/* Exceptions Checked */}
            {Array.isArray(issue.exceptions_checked) && (issue.exceptions_checked as Array<Record<string, unknown>>).length > 0 ? (
              <div>
                <div className="font-medium text-gray-500 mb-0.5">Exceptions Checked</div>
                {(issue.exceptions_checked as Array<Record<string, unknown>>).map((ex, i) => (
                  <div key={i} className="ml-2 mb-1 p-1.5 bg-yellow-50 rounded">
                    <div className="font-medium">{ex.exception_ref as string}</div>
                    <div className="text-gray-500">
                      {ex.type as string} &mdash; {ex.condition_status_summary as string}
                    </div>
                    {ex.impact ? <div className="text-gray-600 italic">{String(ex.impact)}</div> : null}
                  </div>
                ))}
              </div>
            ) : null}

            {/* Temporal Applicability */}
            {issue.temporal_applicability ? (() => {
              const ta = issue.temporal_applicability as Record<string, unknown>;
              return (
                <div className="flex gap-3 items-center flex-wrap">
                  <span className="font-medium text-gray-500">Temporal:</span>
                  {ta.relevant_event_date ? <span>Event: {String(ta.relevant_event_date)}</span> : null}
                  <span className={ta.version_matches ? "text-green-700" : "text-red-700"}>
                    Version {ta.version_matches ? "matches" : "MISMATCH"}
                  </span>
                  {Array.isArray(ta.temporal_risks) && (ta.temporal_risks as string[]).length > 0 ? (
                    <span className="text-yellow-700">
                      Risks: {(ta.temporal_risks as string[]).join(", ")}
                    </span>
                  ) : null}
                </div>
              );
            })() : null}

            {/* Conclusion */}
            {issue.conclusion ? (
              <div className="p-2 bg-blue-50 rounded text-blue-800">
                <span className="font-medium">Conclusion: </span>
                {String(issue.conclusion)}
              </div>
            ) : null}

            {/* Uncertainty Sources */}
            {Array.isArray(issue.uncertainty_sources) && (issue.uncertainty_sources as Array<Record<string, unknown>>).length > 0 ? (
              <div>
                <div className="font-medium text-gray-500 mb-0.5">Uncertainty Sources</div>
                {(issue.uncertainty_sources as Array<Record<string, unknown>>).map((u, i) => (
                  <div key={i} className="ml-2 mb-1 text-yellow-800 bg-yellow-50 p-1.5 rounded">
                    <span className="font-medium">{u.type as string}: </span>
                    {u.detail as string}
                    {u.impact ? <div className="text-yellow-700 italic">Impact: {String(u.impact)}</div> : null}
                    {u.resolvable_by ? (
                      <span className="text-xs ml-1 px-1 rounded bg-yellow-100">
                        {String(u.resolvable_by)}
                      </span>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function CertaintyBadge({ level }: { level: string }) {
  const cls =
    level === "HIGH" || level === "CERTAIN" ? "bg-green-100 text-green-700" :
    level === "CONDITIONAL" || level === "MEDIUM" ? "bg-yellow-100 text-yellow-700" :
    level === "LOW" || level === "UNCERTAIN" ? "bg-red-100 text-red-700" :
    "bg-gray-100 text-gray-600";
  return <span className={`text-xs px-1.5 py-0.5 rounded ${cls}`}>{level}</span>;
}

function ConditionStatusBadge({ status }: { status: string }) {
  if (status === "SATISFIED") return <span className="text-green-700">SATISFIED</span>;
  if (status === "NOT_SATISFIED") return <span className="text-red-700">NOT SATISFIED</span>;
  if (status === "UNKNOWN") return <span className="text-yellow-700">UNKNOWN</span>;
  return <span className="text-gray-500">{status}</span>;
}

/* --- Step 13: Conditional Retrieval --- */
function ConditionalRetrievalDetail({ data }: { data: Record<string, unknown> }) {
  const requestedRefs = (data.requested_refs ?? []) as string[];
  const governingNorms = (data.governing_norms_searched ?? []) as string[];
  const fetched = (data.fetched_articles ?? []) as Array<Record<string, unknown>>;

  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Requested" value={data.requested_count} />
        <Stat label="Fetched" value={data.fetched_count} />
        <Stat label="Re-ran reasoning" value={data.re_ran_reasoning ? "Yes" : "No"} />
      </div>
      {requestedRefs.length > 0 && (
        <div>
          <div className="font-medium text-gray-500">Missing articles requested:</div>
          {requestedRefs.map((ref, i) => (
            <div key={i} className="ml-2 text-gray-600">{ref}</div>
          ))}
        </div>
      )}
      {governingNorms.length > 0 && (
        <div>
          <div className="font-medium text-gray-500">Governing norm search for:</div>
          {governingNorms.map((id, i) => (
            <div key={i} className="ml-2 text-gray-600">{id}</div>
          ))}
        </div>
      )}
      {fetched.length > 0 && (
        <div>
          <div className="font-medium text-gray-500">Fetched articles:</div>
          {fetched.map((a, i) => (
            <div key={i} className="ml-2 flex gap-2">
              <span>Art. {a.article_number as string}</span>
              <span className="text-gray-400">{a.law as string}</span>
              {a.source ? <span className="text-xs px-1 rounded bg-gray-100 text-gray-500">{String(a.source)}</span> : null}
            </div>
          ))}
        </div>
      )}
      {fetched.length === 0 && requestedRefs.length > 0 && (
        <div className="p-2 bg-yellow-50 rounded text-yellow-800">
          No articles found for the requested references
        </div>
      )}
    </div>
  );
}

/* --- Generic fallback --- */
function GenericDetail({ data }: { data: Record<string, unknown> }) {
  return (
    <pre className="whitespace-pre-wrap text-xs bg-gray-100 p-2 rounded overflow-x-auto">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

/* ------------------------------------------------------------------ */
/* Reusable micro-components                                           */
/* ------------------------------------------------------------------ */

function Row({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div>
      <span className="font-medium text-gray-500">{label}: </span>
      <span>{value}</span>
    </div>
  );
}

function Stat({
  label,
  value,
}: {
  label: string;
  value?: unknown;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded px-2 py-1 text-center">
      <div className="text-gray-400 text-[10px]">{label}</div>
      <div className="font-semibold">{value != null ? String(value) : "—"}</div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */

export function RunDetail({
  runId,
  onBack,
}: {
  runId: string;
  onBack: () => void;
}) {
  const [run, setRun] = useState<RunDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());

  useEffect(() => {
    api.settings.pipeline.runDetail(runId).then((data) => {
      setRun(data);
      setLoading(false);
    });
  }, [runId]);

  if (loading) {
    return <div className="text-sm text-gray-400 py-4">Loading run...</div>;
  }

  if (!run) {
    return <div className="text-sm text-red-500 py-4">Run not found.</div>;
  }

  const totalTokensIn = run.api_calls.reduce((s, c) => s + c.tokens_in, 0);
  const totalTokensOut = run.api_calls.reduce((s, c) => s + c.tokens_out, 0);

  // Deduplicate steps by step_name (old runs may have both old and new numbers)
  // and sort by execution order
  const deduped = Object.values(
    run.steps.reduce<Record<string, StepLogData>>((acc, step) => {
      const existing = acc[step.step_name];
      if (!existing) {
        acc[step.step_name] = step;
      } else {
        // Prefer the entry that has a known STEP_CONFIG mapping
        const existingKnown = existing.step_number in STEP_CONFIG;
        const currentKnown = step.step_number in STEP_CONFIG;
        if (currentKnown && !existingKnown) {
          acc[step.step_name] = step;
        } else if (!currentKnown && existingKnown) {
          // keep existing
        } else if (step.duration_seconds && !existing.duration_seconds) {
          // prefer the one with actual data
          acc[step.step_name] = step;
        }
      }
      return acc;
    }, {})
  );
  const sortedSteps = deduped.sort(
    (a, b) => getStepConfig(a).order - getStepConfig(b).order
  );

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onBack}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          &larr; Back
        </button>
        <h3 className="text-lg font-semibold text-gray-900">
          Run {run.run_id}
        </h3>
      </div>

      {/* Summary card */}
      <div className="bg-white rounded-lg border border-gray-200 p-4 mb-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div>
          <div className="text-gray-500 text-xs">Status</div>
          <div className="font-medium">{run.overall_status}</div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">Confidence</div>
          <div className="font-medium">{run.overall_confidence || "—"}</div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">Duration</div>
          <div className="font-medium">
            {run.total_duration_seconds
              ? `${run.total_duration_seconds.toFixed(1)}s`
              : "—"}
          </div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">Cost</div>
          <div className="font-medium">
            {run.estimated_cost ? `$${run.estimated_cost.toFixed(4)}` : "—"}
          </div>
        </div>
      </div>

      {/* Question */}
      {run.question_summary && (
        <div className="bg-gray-50 rounded-lg p-3 mb-4 text-sm text-gray-700">
          <span className="text-xs font-medium text-gray-500">Question: </span>
          {run.question_summary}
        </div>
      )}

      {/* Steps accordion */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden divide-y divide-gray-100">
        {sortedSteps.map((step) => {
          const cfg = getStepConfig(step);
          const isExpanded = expandedSteps.has(step.step_number);
          const hasWarnings = !!step.warnings;
          const hasOutputData = !!step.output_data;

          return (
            <div key={step.step_number}>
              <button
                onClick={() => {
                  setExpandedSteps((prev) => {
                    const next = new Set(prev);
                    if (next.has(step.step_number)) {
                      next.delete(step.step_number);
                    } else {
                      next.add(step.step_number);
                    }
                    return next;
                  });
                }}
                className="w-full flex items-center gap-3 px-4 py-3 text-sm hover:bg-gray-50 transition-colors"
              >
                <span
                  className={`min-w-[28px] h-6 rounded-full flex items-center justify-center text-xs font-medium text-white ${
                    step.status === "done"
                      ? hasWarnings
                        ? "bg-yellow-500"
                        : "bg-green-500"
                      : step.status === "error"
                        ? "bg-red-500"
                        : "bg-gray-400"
                  }`}
                >
                  {cfg.displayNum}
                </span>
                <span className="font-medium text-gray-700 flex-1 text-left">
                  {cfg.label}
                </span>
                {step.prompt_id && (
                  <span className="text-xs text-gray-400">
                    {step.prompt_id} v{step.prompt_version}
                  </span>
                )}
                {step.duration_seconds != null && (
                  <span className="text-xs text-gray-400">
                    {step.duration_seconds.toFixed(1)}s
                  </span>
                )}
                {step.confidence && (
                  <span
                    className={`text-xs px-1.5 py-0.5 rounded ${
                      step.confidence === "HIGH"
                        ? "bg-green-100 text-green-700"
                        : step.confidence === "MEDIUM"
                          ? "bg-yellow-100 text-yellow-700"
                          : "bg-red-100 text-red-700"
                    }`}
                  >
                    {step.confidence}
                  </span>
                )}
                <span className="text-gray-400 text-xs">
                  {isExpanded ? "▲" : "▼"}
                </span>
              </button>

              {isExpanded && (
                <div className="px-4 pb-4 pt-1 text-xs text-gray-600 space-y-2 bg-gray-50">
                  {step.input_summary && (
                    <div>
                      <span className="font-medium">Input: </span>
                      {step.input_summary}
                    </div>
                  )}
                  {step.output_summary && (
                    <div>
                      <span className="font-medium">Output: </span>
                      {step.output_summary}
                    </div>
                  )}
                  {step.warnings && (
                    <div className="p-2 bg-yellow-50 rounded text-yellow-700">
                      <span className="font-medium">Warnings: </span>
                      {step.warnings}
                    </div>
                  )}
                  {/* Rich output_data rendering */}
                  {hasOutputData && (
                    <div className="mt-2 pt-2 border-t border-gray-200">
                      {renderOutputData(step)}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* API calls summary */}
      {run.api_calls.length > 0 && (
        <div className="mt-4 bg-white rounded-lg border border-gray-200 p-4">
          <h4 className="text-sm font-medium text-gray-700 mb-2">
            Claude API Calls
          </h4>
          <div className="space-y-1 text-xs text-gray-600">
            {run.api_calls.map((call, i) => (
              <div key={i} className="flex gap-4">
                <span className="w-32">
                  {call.step_name.replace(/_/g, " ")}
                </span>
                <span>
                  {call.tokens_in} in / {call.tokens_out} out
                </span>
                <span className="text-gray-400">
                  {call.duration_seconds.toFixed(1)}s
                </span>
              </div>
            ))}
            <div className="border-t border-gray-200 pt-1 mt-1 font-medium">
              Total: {totalTokensIn} in / {totalTokensOut} out
            </div>
          </div>
        </div>
      )}

      {/* Flags */}
      {run.flags && (
        <div className="mt-4 bg-yellow-50 border border-yellow-200 rounded-lg p-3">
          <div className="text-xs font-medium text-yellow-800 mb-1">
            Flags &amp; Warnings
          </div>
          {JSON.parse(run.flags).map((flag: string, i: number) => (
            <div key={i} className="text-xs text-yellow-700">
              {flag}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
