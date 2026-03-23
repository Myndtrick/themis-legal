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

interface StructuredData {
  structured: {
    legal_basis: string | null;
    version_logic: string | null;
    nuances: string | null;
    changes_over_time: string | null;
    missing_info: string | null;
    confidence: string;
    confidence_reason: string | null;
    sources: SourceEntry[];
  } | null;
  reasoning: Record<string, unknown> | null;
  confidence: string | null;
  flags: string[];
}

const LABEL_COLORS: Record<string, string> = {
  DB: "bg-green-100 text-green-700",
  General: "bg-gray-100 text-gray-600",
  Interpretation: "bg-blue-100 text-blue-700",
  Unverified: "bg-red-100 text-red-700",
};

function Section({
  title,
  content,
}: {
  title: string;
  content: string | null | undefined;
}) {
  if (!content) return null;
  return (
    <div className="mb-4">
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
        {title}
      </h4>
      <div className="text-sm text-gray-700 prose prose-sm max-w-none">
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  );
}

function SourcesTable({ sources }: { sources: SourceEntry[] }) {
  if (!sources || sources.length === 0) return null;
  return (
    <div className="mb-4">
      <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
        Sources
      </h4>
      <div className="space-y-1">
        {sources.map((s, i) => (
          <div
            key={i}
            className="flex items-start gap-2 text-xs text-gray-600"
          >
            <span
              className={`shrink-0 px-1.5 py-0.5 rounded font-medium ${
                LABEL_COLORS[s.label] || "bg-gray-100 text-gray-500"
              }`}
            >
              {s.label}
            </span>
            <span className="flex-1">{s.statement}</span>
            {s.law && (
              <span className="shrink-0 text-gray-400">
                {s.law}
                {s.article ? ` ${s.article}` : ""}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function AnswerDetail({
  reasoningData,
}: {
  reasoningData: string | null;
}) {
  const [isOpen, setIsOpen] = useState(false);

  if (!reasoningData) return null;

  let data: StructuredData;
  try {
    data = JSON.parse(reasoningData);
  } catch {
    return null;
  }

  const s = data.structured;
  const hasDetail =
    s?.legal_basis || s?.version_logic || s?.nuances || s?.sources?.length;

  if (!hasDetail) return null;

  return (
    <div className="mt-2">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors"
      >
        {isOpen ? "Hide details" : "Show details"}
      </button>

      {isOpen && (
        <div className="mt-2 pt-3 border-t border-gray-100">
          <Section title="Legal Basis" content={s?.legal_basis} />
          <Section title="Version Logic" content={s?.version_logic} />
          <Section title="Nuances" content={s?.nuances} />
          <Section title="Changes Over Time" content={s?.changes_over_time} />
          <Section title="Missing Information" content={s?.missing_info} />
          {s?.sources && <SourcesTable sources={s.sources} />}

          {data.flags && data.flags.length > 0 && (
            <div className="mb-4">
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
                Flags
              </h4>
              {data.flags.map((f, i) => (
                <div key={i} className="text-xs text-yellow-700">
                  {f}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
