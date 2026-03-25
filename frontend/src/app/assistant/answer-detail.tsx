"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";

interface SourceEntry {
  statement: string;
  label: string;
  law: string | null;
  article: string | null;
  version_date: string | null;
}

interface CombinedData {
  structured?: {
    short_answer?: string;
    legal_basis?: string | null;
    version_logic?: string | null;
    nuances?: string | null;
    changes_over_time?: string | null;
    missing_info?: string | null;
    confidence?: string;
    confidence_reason?: string | null;
    sources?: SourceEntry[];
  } | null;
  reasoning?: {
    step1_classification?: { legal_domain?: string; legal_topic?: string; entity_types?: string[]; output_mode?: string; core_issue?: string };
    step2_law_mapping?: { candidate_laws?: Array<{ law_number: string; law_year: number; source: string; role: string; title?: string; tier?: string }>; coverage_status?: Record<string, string> };
    step3_versions?: { selected_versions?: Record<string, { date_in_force?: string; is_current?: boolean }> };
    step4_retrieval?: { articles_found?: number };
    step5_expansion?: { articles_after_expansion?: number };
    step6_reranking?: { top_articles?: Array<{ article_number: string; score: number; law: string }> };
    step7_answer?: { articles_used?: number; confidence?: string; flags?: string[] };
  } | null;
  confidence?: string | null;
  flags?: string[];
}

const LABEL_COLORS: Record<string, string> = {
  DB: "bg-green-100 text-green-700",
  General: "bg-gray-100 text-gray-600",
  Interpretation: "bg-blue-100 text-blue-700",
  Unverified: "bg-red-100 text-red-700",
};

function Section({ title, content }: { title: string; content: string | null | undefined }) {
  if (!content) return null;
  return (
    <div className="mb-3">
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{title}</h4>
      <div className="text-sm text-gray-700 prose prose-sm max-w-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  );
}

export function AnswerDetail({ reasoningData }: { reasoningData: string | null }) {
  const [isOpen, setIsOpen] = useState(false);

  if (!reasoningData) return null;

  let data: CombinedData;
  try {
    data = JSON.parse(reasoningData);
  } catch {
    return null;
  }

  const s = data.structured;
  const r = data.reasoning;
  const hasStructured = s?.version_logic || s?.sources?.length;
  const hasReasoning = r?.step2_law_mapping?.candidate_laws?.length;
  const hasFlags = data.flags && data.flags.length > 0;

  if (!hasStructured && !hasReasoning && !hasFlags) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors"
      >
        {isOpen ? "▲ Ascunde detalii tehnice" : "▼ Detalii tehnice"}
      </button>

      {isOpen && (
        <div className="mt-2 pt-3 border-t border-gray-100 space-y-1">
          {/* Structured answer sections */}
          <Section title="Legal Basis" content={s?.legal_basis} />
          {s?.version_logic && (
            <div className="mb-3">
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Version Logic</h4>
              <div className={`text-sm leading-relaxed prose prose-sm max-w-none ${
                s.version_logic.toLowerCase().includes("fallback") ||
                s.version_logic.toLowerCase().includes("no version found") ||
                s.version_logic.toLowerCase().includes("nu s-a gasit")
                  ? "bg-amber-50 border border-amber-200 rounded-lg p-2 text-amber-900"
                  : "text-gray-700"
              }`}>
                <ReactMarkdown>{s.version_logic}</ReactMarkdown>
              </div>
            </div>
          )}
          <Section title="Nuances" content={s?.nuances} />
          <Section title="Changes Over Time" content={s?.changes_over_time} />
          <Section title="Missing Information" content={s?.missing_info} />

          {/* Sources table */}
          {s?.sources && s.sources.length > 0 && (
            <div className="mb-3">
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Sources</h4>
              <div className="space-y-1">
                {s.sources.map((src, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-gray-600">
                    <span
                      className={`shrink-0 px-1.5 py-0.5 rounded font-medium ${LABEL_COLORS[src.label] || "bg-gray-100 text-gray-500"}`}
                      title={
                        src.label === "General"
                          ? "This information comes from AI training data, not from verified law text. It may be outdated or incorrect."
                          : src.label === "Unverified"
                          ? "This claim could not be verified against current law text. Do not rely on it without manual verification."
                          : src.label === "DB"
                          ? "Verified against law text in the Legal Library."
                          : undefined
                      }
                    >
                      {src.label === "General" ? "\u26A0 General" : src.label === "Unverified" ? "\u26D4 Unverified" : src.label}
                    </span>
                    <span className="flex-1">{src.statement}</span>
                    {src.law && (
                      <span className="shrink-0 text-gray-400 font-mono text-[10px]">
                        {src.law} {src.article ? `Art.${src.article}` : ""}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Pipeline reasoning */}
          {r && (
            <div className="mb-3 pt-2 border-t border-gray-100">
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Pipeline Reasoning</h4>

              {/* Laws mapped (Step 2) */}
              {r.step2_law_mapping?.candidate_laws && r.step2_law_mapping.candidate_laws.length > 0 && (
                <div className="mb-2">
                  <div className="text-xs font-medium text-gray-600 mb-1">Applicable Laws</div>
                  {r.step2_law_mapping.candidate_laws.map((law, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs text-gray-600 ml-2">
                      <span className={`px-1.5 py-0.5 rounded font-medium ${
                        law.source === "DB" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
                      }`}>
                        {law.source}
                      </span>
                      <span>{law.law_number}/{law.law_year}</span>
                      <span className="text-gray-400">({law.role})</span>
                      {law.title && <span className="text-gray-400 truncate max-w-[200px]">{law.title}</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* Coverage (Step 2) */}
              {r.step2_law_mapping?.coverage_status && Object.keys(r.step2_law_mapping.coverage_status as Record<string, string>).length > 0 && (
                <div className="mb-2">
                  <div className="text-xs font-medium text-gray-600 mb-1">Library Coverage</div>
                  {Object.entries(r.step2_law_mapping.coverage_status as Record<string, string>).map(([key, status]) => (
                    <div key={key} className="flex items-center gap-2 text-xs text-gray-600 ml-2">
                      <span>{status === "full" ? "✅" : status === "partial" ? "⚠️" : "❌"}</span>
                      <span>{key}</span>
                      <span className="text-gray-400">— {status}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Versions (Step 3) */}
              {r.step3_versions?.selected_versions && Object.keys(r.step3_versions.selected_versions as Record<string, Record<string, unknown>>).length > 0 && (
                <div className="mb-2">
                  <div className="text-xs font-medium text-gray-600 mb-1">Versions Selected</div>
                  {Object.entries(r.step3_versions.selected_versions as Record<string, Record<string, unknown>>).map(([key, v]) => (
                    <div key={key} className="text-xs text-gray-600 ml-2">
                      {key}: version {(v.date_in_force as string) || "unknown"}{" "}
                      {v.is_current ? "(current)" : "(historical)"}
                    </div>
                  ))}
                </div>
              )}

              {/* Top articles from reranking (Step 6) */}
              {r.step6_reranking?.top_articles && (r.step6_reranking.top_articles as Array<Record<string, unknown>>).length > 0 && (
                <div className="mb-2">
                  <div className="text-xs font-medium text-gray-600 mb-1">Top Articles (by relevance)</div>
                  {(r.step6_reranking.top_articles as Array<Record<string, unknown>>).map((art, i) => (
                    <div key={i} className="text-xs text-gray-600 ml-2">
                      Art. {art.article_number as string} ({art.law as string}) — score: {(art.score as number)?.toFixed(3)}
                    </div>
                  ))}
                </div>
              )}

              {/* Summary stats */}
              {r.step4_retrieval?.articles_found != null && (
                <div className="text-xs text-gray-400 ml-2">
                  Articles found: {r.step4_retrieval.articles_found as number}
                  {r.step5_expansion?.articles_after_expansion != null &&
                    ` → ${r.step5_expansion.articles_after_expansion as number} after expansion`}
                  {r.step7_answer?.articles_used != null &&
                    ` → ${r.step7_answer.articles_used as number} sent to Claude`}
                </div>
              )}
            </div>
          )}

          {/* Flags */}
          {data.flags && data.flags.length > 0 && (
            <div className="mb-3 bg-yellow-50 rounded p-2">
              <h4 className="text-xs font-semibold text-yellow-800 mb-1">Flags</h4>
              {data.flags.map((f, i) => (
                <div key={i} className="text-xs text-yellow-700">{f}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
