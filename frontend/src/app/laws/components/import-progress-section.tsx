"use client";

import { useState } from "react";

export interface ImportingEntry {
  id: string;
  /** Backend Job id once the import has been submitted (null = not yet submitted, e.g. EU sync path). */
  jobId: string | null;
  title: string;
  lawNumber: string;
  verId: string;
  source: "ro" | "eu";
  importHistory: boolean;
  categoryId: number | null;
  groupSlug: string | null;
  progress: {
    phase: string;
    current: number;
    total: number;
    versionDate?: string;
    message: string;
  };
}

export interface FailedEntry {
  id: string;
  title: string;
  lawNumber: string;
  verId: string;
  source: "ro" | "eu";
  importHistory: boolean;
  categoryId: number | null;
  groupSlug: string | null;
  error: string;
  /** When true, retrying will not help (e.g. CELLAR has no published text yet). */
  permanent?: boolean;
}

const PREVIEW_COUNT = 3;

function ImportingSection({
  entries,
}: {
  entries: ImportingEntry[];
}) {
  const [expanded, setExpanded] = useState(false);
  if (entries.length === 0) return null;

  const visible = expanded ? entries : entries.slice(0, PREVIEW_COUNT);
  const hasMore = entries.length > PREVIEW_COUNT;

  return (
    <div className="border border-blue-200 rounded-lg bg-white overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-blue-50 border-b border-blue-200">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-wider text-blue-700 uppercase">
            Importing
          </span>
          <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-blue-600 text-white text-[11px] font-bold">
            {entries.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {hasMore && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-blue-600 hover:text-blue-800 font-medium"
            >
              {expanded ? "Show less" : `Show all ${entries.length}`}
            </button>
          )}
          <span className="inline-block w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      </div>

      {/* Rows */}
      {visible.map((entry, i) => {
        const pct = entry.progress.total > 0
          ? (entry.progress.current / entry.progress.total) * 100
          : 0;

        return (
          <div
            key={entry.id}
            className={`px-4 py-3 ${i < visible.length - 1 ? "border-b border-gray-100" : ""}`}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm text-gray-900">
                  {entry.title}
                  {entry.lawNumber && (
                    <span className="text-gray-500 font-normal"> — Legea {entry.lawNumber}</span>
                  )}
                </div>
                <div className="text-xs text-gray-400 mt-0.5">
                  {entry.progress.phase === "metadata" && "Se descarcă metadatele..."}
                  {entry.progress.phase === "version" && entry.progress.versionDate && (
                    <>Se importă versiunea {entry.progress.versionDate}...</>
                  )}
                  {entry.progress.phase === "version" && !entry.progress.versionDate && (
                    <>Se importă versiunea curentă...</>
                  )}
                  {entry.progress.phase === "indexing" && "Se construiește indexul de căutare..."}
                  {!["metadata", "version", "indexing"].includes(entry.progress.phase) && (
                    <>Se importă versiunea curentă...</>
                  )}
                </div>
              </div>
              <div className="text-right flex-shrink-0 w-40">
                <div className="text-xs text-blue-700 font-medium">
                  {entry.progress.current} / {entry.progress.total} versiuni
                </div>
                <div className="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-600 rounded-full transition-all duration-500"
                    style={{ width: `${Math.max(pct, 2)}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function FailedSection({
  entries,
  onRetry,
  onDismiss,
}: {
  entries: FailedEntry[];
  onRetry: (entry: FailedEntry) => void;
  onDismiss: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (entries.length === 0) return null;

  const visible = expanded ? entries : entries.slice(0, PREVIEW_COUNT);
  const hasMore = entries.length > PREVIEW_COUNT;

  return (
    <div className="border border-red-200 rounded-lg bg-white overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-red-50 border-b border-red-200">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-wider text-red-700 uppercase">
            Failed
          </span>
          <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-red-600 text-white text-[11px] font-bold">
            {entries.length}
          </span>
        </div>
        {hasMore && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-red-600 hover:text-red-800 font-medium"
          >
            {expanded ? "Show less" : `Show all ${entries.length}`}
          </button>
        )}
      </div>

      {/* Rows */}
      {visible.map((entry, i) => (
        <div
          key={entry.id}
          className={`px-4 py-3 ${i < visible.length - 1 ? "border-b border-gray-100" : ""}`}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-sm text-gray-900">
                {entry.title}
                {entry.lawNumber && (
                  <span className="text-gray-500 font-normal"> — Legea {entry.lawNumber}</span>
                )}
              </div>
              <div className={`text-xs mt-0.5 ${entry.permanent ? "text-amber-700" : "text-red-500"}`}>
                {entry.permanent && (
                  <span className="font-semibold uppercase tracking-wide mr-1.5">Not retriable —</span>
                )}
                {entry.error}
              </div>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {!entry.permanent && (
                <button
                  onClick={() => onRetry(entry)}
                  className="px-3 py-1.5 text-xs font-medium rounded-md border border-red-300 text-red-700 hover:bg-red-50 transition-colors"
                >
                  Retry
                </button>
              )}
              <button
                onClick={() => onDismiss(entry.id)}
                className="px-3 py-1.5 text-xs font-medium rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ImportProgressSection({
  importing,
  failed,
  onRetry,
  onDismiss,
}: {
  importing: ImportingEntry[];
  failed: FailedEntry[];
  onRetry: (entry: FailedEntry) => void;
  onDismiss: (id: string) => void;
}) {
  if (importing.length === 0 && failed.length === 0) return null;

  return (
    <div className="space-y-3 mb-5">
      <ImportingSection entries={importing} />
      <FailedSection entries={failed} onRetry={onRetry} onDismiss={onDismiss} />
    </div>
  );
}
