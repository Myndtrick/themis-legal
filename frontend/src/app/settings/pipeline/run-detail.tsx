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
  2: { label: "Law Mapping", displayNum: "2", order: 2 },
  15: { label: "Date Extraction", displayNum: "2a", order: 2.5 },
  25: { label: "Early Relevance Gate", displayNum: "2.5", order: 3 },
  3: { label: "Version Selection", displayNum: "3", order: 4 },
  4: { label: "Hybrid Retrieval", displayNum: "4", order: 5 },
  5: { label: "Article Expansion", displayNum: "5", order: 6 },
  55: { label: "Exception Retrieval", displayNum: "5.5", order: 7 },
  6: { label: "Article Selection", displayNum: "6", order: 8 },
  7: { label: "Relevance Check", displayNum: "6.5", order: 9 },
  8: { label: "Answer Generation", displayNum: "7", order: 10 },
  85: { label: "Citation Validation", displayNum: "7.5", order: 11 },
};

function getStepConfig(step: StepLogData) {
  return (
    STEP_CONFIG[step.step_number] ?? {
      label: step.step_name.replace(/_/g, " "),
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
    case "expansion":
      return <ExpansionDetail data={d} />;
    case "exception_retrieval":
      return <ExceptionDetail data={d} />;
    case "article_selection":
      return <SelectionDetail data={d} />;
    case "relevance_check":
      return <RelevanceDetail data={d} />;
    case "answer_generation":
      return <AnswerDetail data={d} />;
    case "citation_validation":
      return <CitationDetail data={d} />;
    default:
      return <GenericDetail data={d} />;
  }
}

/* --- Step 1: Classification --- */
function ClassificationDetail({ data }: { data: Record<string, unknown> }) {
  return (
    <div className="space-y-1.5">
      <Row label="Legal topic" value={data.legal_topic as string} />
      <Row label="Domain" value={data.legal_domain as string} />
      <Row label="Question type" value={data.question_type as string} />
      <Row label="Output mode" value={data.output_mode as string} />
      <Row label="Core issue" value={data.core_issue as string} />
      {Array.isArray(data.entity_types) && data.entity_types.length > 0 && (
        <Row label="Entity types" value={data.entity_types.join(", ")} />
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
  const notes = (data.notes ?? []) as string[];
  const amendments = (data.amendment_flags ?? []) as string[];

  return (
    <div className="space-y-1">
      <Row label="Primary date" value={data.primary_date as string} />
      {Object.entries(versions).map(([key, v]) => (
        <div key={key} className="ml-1 flex gap-2 items-center">
          <span className="font-medium">{key}:</span>
          <span>version {(v.date_in_force as string) ?? "unknown"}</span>
          <span
            className={`text-xs px-1 rounded ${v.is_current ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}
          >
            {v.is_current ? "current" : "historical"}
          </span>
        </div>
      ))}
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

/* --- Step 5: Expansion --- */
function ExpansionDetail({ data }: { data: Record<string, unknown> }) {
  const triggers = (data.expansion_triggers ?? []) as Array<
    Record<string, unknown>
  >;
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Before" value={data.articles_before} />
        <Stat label="After" value={data.articles_after} />
        <Stat label="Added" value={data.added} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Neighbors" value={data.neighbors_added} />
        <Stat label="Cross-refs" value={data.crossrefs_added} />
      </div>
      {triggers.length > 0 && (
        <div className="mt-2">
          <div className="font-medium text-gray-500 mb-1">
            Expansion triggers:
          </div>
          {triggers.map((t, i) => (
            <div key={i} className="ml-2">
              Art. {t.source_article as string} ({t.source_law as string}) →{" "}
              +{t.added_count as number} ({t.type as string})
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* --- Step 5.5: Exception Retrieval --- */
function ExceptionDetail({ data }: { data: Record<string, unknown> }) {
  const forward = (data.forward_matches ?? []) as Array<Record<string, unknown>>;
  const reverse = (data.reverse_matches ?? []) as Array<Record<string, unknown>>;
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Added" value={data.added} />
        <Stat label="Forward" value={data.forward_count} />
        <Stat label="Reverse" value={data.reverse_count} />
      </div>
      {forward.length > 0 && (
        <div>
          <div className="font-medium text-gray-500">Forward matches:</div>
          {forward.map((m, i) => (
            <div key={i} className="ml-2">
              Art. {m.found_article as string} references Art.{" "}
              {m.references_article as string} in exception context
            </div>
          ))}
        </div>
      )}
      {reverse.length > 0 && (
        <div>
          <div className="font-medium text-gray-500">Reverse matches:</div>
          {reverse.map((m, i) => (
            <div key={i} className="ml-2">
              Art. {m.source_article as string} has exception language → Art.{" "}
              {m.referenced_article as string}
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

  // Sort steps by execution order instead of raw step_number
  const sortedSteps = [...run.steps].sort(
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
