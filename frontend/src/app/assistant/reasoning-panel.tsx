"use client";

import { useState } from "react";
import type { StepProgress } from "./use-chat";

const STEP_NAMES: Record<string, string> = {
  issue_classification: "Issue Classification",
  date_extraction: "Date Extraction",
  law_mapping: "Law Mapping",
  version_currency_check: "Version Currency Check",
  early_relevance_gate: "Early Relevance Gate",
  version_selection: "Version Selection",
  hybrid_retrieval: "Hybrid Retrieval",
  graph_expansion: "Graph Expansion",
  article_selection: "Article Selection",
  relevance_check: "Relevance Check",
  article_partitioning: "Article Partitioning",
  legal_reasoning: "Legal Reasoning",
  conditional_retrieval: "Conditional Retrieval",
  answer_generation: "Answer Generation",
  citation_validation: "Citation Validation",
};

function StepIcon({ status }: { status: string }) {
  if (status === "running") {
    return <span className="animate-spin inline-block w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full" />;
  }
  if (status === "done") {
    return <span className="text-green-600 text-sm">&#10003;</span>;
  }
  if (status === "paused") {
    return <span className="text-yellow-600 text-sm">&#9208;</span>;
  }
  return <span className="text-gray-400 text-sm">&#9675;</span>;
}

export function ReasoningPanel({
  steps,
  reasoningData,
  isStreaming,
}: {
  steps: StepProgress[];
  reasoningData: string | null;
  isStreaming: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);

  const reasoning = reasoningData ? JSON.parse(reasoningData) : null;

  if (steps.length === 0 && !reasoning) return null;

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
      >
        <span>{isOpen ? "Hide" : "Show"} full reasoning and sources</span>
        <span className="text-gray-400">{isOpen ? "▲" : "▼"}</span>
      </button>

      {isOpen && (
        <div className="border-t border-gray-200 divide-y divide-gray-100">
          {/* Live steps during streaming */}
          {steps.map((step) => (
            <div key={step.step} className="px-3 py-2">
              <button
                onClick={() =>
                  setExpandedStep(expandedStep === step.step ? null : step.step)
                }
                className="w-full flex items-center gap-2 text-left text-sm"
              >
                <StepIcon status={step.status} />
                <span className="font-medium text-gray-700">
                  Step {step.step}: {STEP_NAMES[step.name] || step.name}
                </span>
                {step.duration != null && (
                  <span className="text-xs text-gray-400 ml-auto">
                    {step.duration.toFixed(1)}s
                  </span>
                )}
              </button>

              {expandedStep === step.step && step.data && (
                <pre className="mt-1 ml-6 text-xs text-gray-500 bg-gray-50 rounded p-2 overflow-x-auto">
                  {JSON.stringify(step.data, null, 2)}
                </pre>
              )}
            </div>
          ))}

          {/* Static reasoning data from completed messages */}
          {reasoning && !isStreaming && (
            <div className="px-3 py-2 text-xs text-gray-500 space-y-2">
              {reasoning.step3_law_mapping?.candidate_laws?.length > 0 && (
                <div>
                  <div className="font-medium text-gray-700 mb-1">Laws Identified</div>
                  {reasoning.step3_law_mapping.candidate_laws.map(
                    (law: Record<string, string>, i: number) => (
                      <div key={i} className="flex items-center gap-2">
                        <span
                          className={`px-1.5 py-0.5 rounded text-xs ${
                            law.source === "DB"
                              ? "bg-green-100 text-green-700"
                              : "bg-yellow-100 text-yellow-700"
                          }`}
                        >
                          {law.source}
                        </span>
                        <span>
                          {law.law_number}/{law.law_year}
                        </span>
                        <span className="text-gray-400">({law.role})</span>
                      </div>
                    )
                  )}
                </div>
              )}
              {reasoning.step6_versions?.selected_versions &&
                Object.keys(reasoning.step6_versions.selected_versions).length >
                  0 && (
                  <div>
                    <div className="font-medium text-gray-700 mb-1">
                      Versions Selected
                    </div>
                    {Object.entries(
                      reasoning.step6_versions.selected_versions as Record<
                        string,
                        Record<string, unknown>
                      >
                    ).map(([key, v]) => (
                      <div key={key} className="text-gray-600">
                        {key}: version{" "}
                        {(v.date_in_force as string) || "unknown"}{" "}
                        {v.is_current ? "(current)" : "(historical)"}
                      </div>
                    ))}
                  </div>
                )}
              {reasoning.step4_version_currency?.results &&
                Object.keys(reasoning.step4_version_currency.results).length > 0 && (
                  <div>
                    <div className="font-medium text-gray-700 mb-1">
                      Version Currency
                    </div>
                    {Object.entries(
                      reasoning.step4_version_currency.results as Record<
                        string,
                        Record<string, unknown>
                      >
                    ).map(([key, v]) => (
                      <div key={key} className="flex items-center gap-1 text-gray-600">
                        <span>
                          {v.currency_status === "current"
                            ? "\u2705"
                            : v.currency_status === "stale"
                            ? "\uD83D\uDD04"
                            : v.currency_status === "source_unavailable"
                            ? "\u2753"
                            : "\u2014"}
                        </span>
                        <span>{key}</span>
                        {v.currency_status === "stale" && (
                          <span className="text-amber-600 text-[10px]">
                            (DB: {(v.db_latest_date as string) || "?"} &rarr; official: {(v.official_latest_date as string) || "?"})
                          </span>
                        )}
                        {v.currency_status === "current" && (
                          <span className="text-green-600 text-[10px]">(verified)</span>
                        )}
                        {v.currency_status === "source_unavailable" && (
                          <span className="text-gray-400 text-[10px]">(unverified)</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              {reasoning.step14_answer?.articles_retrieved != null && (
                <div className="text-gray-500">
                  Articles retrieved: {reasoning.step14_answer.articles_retrieved}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
