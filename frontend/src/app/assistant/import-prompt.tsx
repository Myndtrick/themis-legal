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
    (l) =>
      l.availability !== "available" || l.currency_status === "stale"
  );

  const handleImport = () => {
    setLoading(true);
    const decisions: Record<string, string> = {};
    for (const law of pauseData.laws) {
      if (law.availability === "missing") {
        decisions[`${law.law_number}/${law.law_year}`] = "import";
      } else if (law.availability === "wrong_version") {
        decisions[`${law.law_number}/${law.law_year}`] = "import_version";
      } else if (law.currency_status === "stale") {
        decisions[`${law.law_number}/${law.law_year}`] = "update";
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

  const getStatusStyle = (law: (typeof pauseData.laws)[0]) => {
    if (law.currency_status === "stale") {
      return "bg-blue-50 text-blue-800 border border-blue-200";
    }
    if (law.availability === "available") {
      if (law.currency_status === "source_unavailable") {
        return "bg-gray-50 text-gray-700 border border-gray-200";
      }
      return "bg-green-50 text-green-800 border border-green-200";
    }
    if (law.availability === "wrong_version") {
      return "bg-amber-50 text-amber-800 border border-amber-200";
    }
    return "bg-red-50 text-red-800 border border-red-200";
  };

  const getStatusIcon = (law: (typeof pauseData.laws)[0]) => {
    if (law.currency_status === "stale") return "\uD83D\uDD04";
    if (law.availability === "available") {
      if (law.currency_status === "source_unavailable") return "\u2753";
      return "\u2705";
    }
    if (law.availability === "wrong_version") return "\u26A0\uFE0F";
    return "\u274C";
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
            className={`text-xs rounded px-2 py-1.5 flex items-center gap-2 ${getStatusStyle(law)}`}
          >
            <span>{getStatusIcon(law)}</span>
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
              {law.currency_status === "stale" && (
                <div className="text-[10px] opacity-70 mt-0.5">
                  Biblioteca: {law.db_latest_date || "?"} &rarr; legislatie.just.ro: {law.official_latest_date || "?"}
                </div>
              )}
              {law.currency_status === "source_unavailable" && (
                <div className="text-[10px] opacity-70 mt-0.5">
                  Nu s-a putut verifica versiunea curent\u0103
                </div>
              )}
              {law.availability === "wrong_version" && law.version_info && (
                <div className="text-[10px] opacity-70 mt-0.5">
                  Available: {law.version_info} (wrong version)
                </div>
              )}
              {law.needed_for_date && (
                <div className="text-[10px] opacity-70 mt-0.5">
                  Needed for: {law.date_reason || law.needed_for_date}
                </div>
              )}
            </div>
            {(law.availability !== "available" || law.currency_status === "stale") && (
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
            {loading
              ? "Importing..."
              : needsAction.some((l) => l.currency_status === "stale")
              ? "Update and continue"
              : "Import and continue"}
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
