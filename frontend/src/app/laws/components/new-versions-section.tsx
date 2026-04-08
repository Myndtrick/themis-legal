"use client";

import { useState, useEffect, useCallback } from "react";
import { api, NewVersionEntry, NewVersionDetail } from "@/lib/api";

function formatDate(iso: string): string {
  const d = new Date(iso);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d.getDate().toString().padStart(2, "0")} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

interface NewVersionsSectionProps {
  importingLawIds: Set<number>;
  onImport: (entry: NewVersionEntry, selectedVerIds: string[]) => void;
  onImportAll: (entries: NewVersionEntry[]) => void;
  refreshKey: number;
}

function LawRow({
  entry,
  importingLawIds,
  onImport,
}: {
  entry: NewVersionEntry;
  importingLawIds: Set<number>;
  onImport: (entry: NewVersionEntry, selectedVerIds: string[]) => void;
}) {
  const [showVersions, setShowVersions] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(
    () => new Set(entry.versions.map((v) => v.ver_id))
  );

  const isImporting = importingLawIds.has(entry.law_id);
  const hasMultiple = entry.versions.length > 1;
  const checkedCount = checked.size;

  function toggleCheck(verId: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(verId)) next.delete(verId);
      else next.add(verId);
      return next;
    });
  }

  function handleImport() {
    if (hasMultiple) {
      onImport(entry, Array.from(checked));
    } else {
      onImport(entry, [entry.versions[0].ver_id]);
    }
  }

  // Single version — simple row
  if (!hasMultiple) {
    const v = entry.versions[0];
    const vNum = entry.version_number_offset + 1;
    return (
      <div className="px-4 py-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm text-gray-900">{entry.title}</div>
            <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
              <span>v{vNum} — {formatDate(v.date_in_force)}</span>
              {v.is_latest && (
                <span className="px-1.5 py-0.5 text-[10px] font-semibold rounded bg-indigo-100 text-indigo-700 uppercase">
                  Latest
                </span>
              )}
            </div>
          </div>
          <button
            onClick={handleImport}
            disabled={isImporting}
            className="px-3 py-1.5 text-xs font-medium rounded-full text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 transition-colors shrink-0"
          >
            Import
          </button>
        </div>
      </div>
    );
  }

  // Multiple versions — expandable with checkboxes
  return (
    <div className="px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm text-gray-900">{entry.title}</div>
          <div className="text-xs text-gray-500 mt-0.5">
            {entry.versions.length} new versions available
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setShowVersions(!showVersions)}
            className="px-3 py-1.5 text-xs font-medium rounded-full border border-gray-300 text-gray-700 bg-white hover:bg-gray-50 transition-colors"
          >
            {showVersions ? "Hide versions" : "Show versions"}
          </button>
          <button
            onClick={handleImport}
            disabled={isImporting || checkedCount === 0}
            className="px-3 py-1.5 text-xs font-medium rounded-full text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 transition-colors"
          >
            Import {checkedCount} version{checkedCount !== 1 ? "s" : ""}
          </button>
        </div>
      </div>

      {/* Expanded version list with checkboxes */}
      {showVersions && (
        <div className="mt-3 space-y-2">
          {entry.versions.map((v, idx) => {
            const isChecked = checked.has(v.ver_id);
            const vNum = entry.version_number_offset + idx + 1;
            return (
              <label
                key={v.ver_id}
                className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 cursor-pointer transition-colors ${
                  v.is_latest
                    ? "border-indigo-200 bg-indigo-50/50"
                    : "border-gray-200 bg-gray-50/50"
                } ${isChecked ? "" : "opacity-60"}`}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggleCheck(v.ver_id)}
                  className="w-4 h-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-900">
                      v{vNum} — {formatDate(v.date_in_force)}
                    </span>
                    {v.is_latest && (
                      <span className="px-1.5 py-0.5 text-[10px] font-semibold rounded bg-indigo-100 text-indigo-700 uppercase">
                        Latest
                      </span>
                    )}
                  </div>
                </div>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function NewVersionsSection({
  importingLawIds,
  onImport,
  onImportAll,
  refreshKey,
}: NewVersionsSectionProps) {
  const [entries, setEntries] = useState<NewVersionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  const fetchNewVersions = useCallback(async () => {
    try {
      const data = await api.laws.newVersions();
      setEntries(data.new_versions);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNewVersions();
  }, [fetchNewVersions, refreshKey]);

  const visible = entries.filter((e) => !importingLawIds.has(e.law_id));

  if (loading || visible.length === 0) return null;

  const PREVIEW_COUNT = 5;
  const shown = expanded ? visible : visible.slice(0, PREVIEW_COUNT);
  const hasMore = visible.length > PREVIEW_COUNT;
  const totalVersionCount = visible.reduce((sum, e) => sum + e.versions.length, 0);

  return (
    <div className="border border-pink-200 rounded-lg bg-white overflow-hidden mb-5">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-pink-50 border-b border-pink-200">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-wider text-rose-800 uppercase">
            New versions available
          </span>
          <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full border border-rose-300 text-rose-700 text-[11px] font-bold">
            {visible.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {hasMore && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="text-xs text-rose-600 hover:text-rose-800 font-medium"
            >
              {expanded ? "Show less" : `Show all ${visible.length}`}
            </button>
          )}
          <button
            onClick={() => onImportAll(visible)}
            className="px-3 py-1.5 text-xs font-medium rounded-full border border-gray-300 text-gray-700 bg-white hover:bg-gray-50 transition-colors"
          >
            Import all
          </button>
        </div>
      </div>

      {/* Rows */}
      {shown.map((entry, i) => (
        <div
          key={entry.law_id}
          className={i < shown.length - 1 ? "border-b border-gray-100" : ""}
        >
          <LawRow
            entry={entry}
            importingLawIds={importingLawIds}
            onImport={onImport}
          />
        </div>
      ))}
    </div>
  );
}
