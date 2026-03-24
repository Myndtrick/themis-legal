"use client";

import { useState } from "react";
import Link from "next/link";
import type { PauseData } from "./use-chat";

export function ImportPrompt({
  pauseData,
  onDecision,
}: {
  pauseData: PauseData;
  onDecision: (decisions: Record<string, string>) => void;
}) {
  const [loading, setLoading] = useState(false);

  const needsAction = pauseData.laws.filter(
    (l) => l.availability !== "available"
  );

  const handleImport = () => {
    setLoading(true);
    const decisions: Record<string, string> = {};
    for (const law of pauseData.laws) {
      if (law.availability === "missing") {
        decisions[`${law.law_number}/${law.law_year}`] = "import";
      } else if (law.availability === "wrong_version") {
        decisions[`${law.law_number}/${law.law_year}`] = "import_version";
      }
    }
    onDecision(decisions);
  };

  const handleSkip = () => {
    setLoading(true);
    const decisions: Record<string, string> = {};
    for (const law of needsAction) {
      decisions[`${law.law_number}/${law.law_year}`] = "skip";
    }
    onDecision(decisions);
  };

  return (
    <div className="my-3 mx-auto max-w-xl bg-slate-50 border border-slate-200 rounded-lg p-4">
      <div className="text-sm text-slate-700 mb-3 font-medium">
        {pauseData.message}
      </div>

      <div className="mb-3 space-y-1.5">
        {pauseData.laws.map((law) => (
          <div
            key={`${law.law_number}/${law.law_year}`}
            className={`text-xs rounded px-2 py-1.5 flex items-center gap-2 ${
              law.availability === "available"
                ? "bg-green-50 text-green-800 border border-green-200"
                : law.availability === "wrong_version"
                ? "bg-amber-50 text-amber-800 border border-amber-200"
                : "bg-red-50 text-red-800 border border-red-200"
            }`}
          >
            <span>
              {law.availability === "available"
                ? "\u2705"
                : law.availability === "wrong_version"
                ? "\u26A0\uFE0F"
                : "\u274C"}
            </span>
            <div className="flex-1">
              <span className="font-medium">
                {law.title || `${law.law_number}/${law.law_year}`}
              </span>
              <span className="text-[10px] ml-1 opacity-70">
                ({law.law_number}/{law.law_year})
              </span>
              {law.role === "PRIMARY" && (
                <span className="ml-1 text-[10px] font-semibold uppercase opacity-60">
                  primary
                </span>
              )}
              {law.availability === "wrong_version" && law.version_info && (
                <div className="text-[10px] opacity-70 mt-0.5">
                  Available: {law.version_info} (wrong version)
                </div>
              )}
            </div>
            {law.availability !== "available" && (
              <Link
                href={`/laws?number=${encodeURIComponent(law.law_number)}&year=${encodeURIComponent(law.law_year)}`}
                target="_blank"
                className="shrink-0 text-[10px] text-indigo-600 hover:text-indigo-800 underline"
              >
                Search in Library
              </Link>
            )}
          </div>
        ))}
      </div>

      {needsAction.length > 0 && (
        <div className="flex gap-2">
          <button
            onClick={handleImport}
            disabled={loading}
            className="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Importing..." : "Import and continue"}
          </button>
          <button
            onClick={handleSkip}
            disabled={loading}
            className="px-3 py-1.5 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:bg-gray-100 disabled:cursor-not-allowed transition-colors"
          >
            Continue without
          </button>
        </div>
      )}
    </div>
  );
}
