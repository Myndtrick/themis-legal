"use client";

import { useState } from "react";
import type { PauseData } from "./use-chat";

export function ImportPrompt({
  pauseData,
  onDecision,
}: {
  pauseData: PauseData;
  onDecision: (decisions: Record<string, string>) => void;
}) {
  const [loading, setLoading] = useState(false);

  const handleImport = () => {
    setLoading(true);
    const decisions: Record<string, string> = {};
    for (const law of pauseData.missing_laws) {
      decisions[`${law.law_number}/${law.law_year}`] = "import";
    }
    onDecision(decisions);
  };

  const handleSkip = () => {
    setLoading(true);
    const decisions: Record<string, string> = {};
    for (const law of pauseData.missing_laws) {
      decisions[`${law.law_number}/${law.law_year}`] = "skip";
    }
    onDecision(decisions);
  };

  return (
    <div className="my-3 mx-auto max-w-xl bg-amber-50 border border-amber-200 rounded-lg p-4">
      <div className="flex items-start gap-2 mb-3">
        <span className="text-amber-600 text-lg mt-0.5">&#9888;</span>
        <div className="text-sm text-amber-900">{pauseData.message}</div>
      </div>

      {pauseData.missing_laws.length > 0 && (
        <div className="mb-3 space-y-1">
          {pauseData.missing_laws.map((law) => (
            <div
              key={`${law.law_number}/${law.law_year}`}
              className="text-xs text-amber-800 bg-amber-100 rounded px-2 py-1"
            >
              <span className="font-medium">
                {law.title || `${law.law_number}/${law.law_year}`}
              </span>
              {law.reason && (
                <span className="text-amber-600"> — {law.reason}</span>
              )}
            </div>
          ))}
        </div>
      )}

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
    </div>
  );
}
