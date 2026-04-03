"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { KnownVersionData, LawVersionSummary } from "@/lib/api";

interface ImportedVersionsTableProps {
  lawId: number;
  versions: LawVersionSummary[];
  knownVersions: KnownVersionData[] | null;
  onVersionDeleted?: (versionId: number) => void;
}

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Unknown";
  const d = new Date(dateStr);
  return `${d.getDate().toString().padStart(2, "0")} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export default function ImportedVersionsTable({ lawId, versions, knownVersions, onVersionDeleted }: ImportedVersionsTableProps) {
  const [showAll, setShowAll] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  async function handleDeleteVersion(versionId: number, vNum: number) {
    if (!confirm(`Delete version v${vNum}? This cannot be undone.`)) return;
    setDeletingId(versionId);
    try {
      await api.laws.deleteVersion(lawId, versionId);
      onVersionDeleted?.(versionId);
    } catch (e) {
      alert("Failed to delete version");
    } finally {
      setDeletingId(null);
    }
  }

  if (versions.length === 0) return null;

  // Build version number map from ALL known versions (ordinal by date)
  // so imported version numbers reflect their true position in the full history.
  // Fallback to imported-only numbering if known versions aren't loaded yet.
  const versionNumberMap = new Map<string, number>();
  if (knownVersions && knownVersions.length > 0) {
    const allSortedAsc = [...knownVersions].sort((a, b) =>
      a.date_in_force.localeCompare(b.date_in_force)
    );
    allSortedAsc.forEach((v, i) => versionNumberMap.set(v.ver_id, i + 1));
  } else {
    const sortedAsc = [...versions].sort((a, b) =>
      (a.date_in_force || "").localeCompare(b.date_in_force || "")
    );
    sortedAsc.forEach((v, i) => versionNumberMap.set(v.ver_id, i + 1));
  }

  const sortedAsc = [...versions].sort((a, b) =>
    (a.date_in_force || "").localeCompare(b.date_in_force || "")
  );

  const sortedDesc = [...sortedAsc].reverse();
  const visible = showAll ? sortedDesc : sortedDesc.slice(0, 3);
  const hiddenCount = sortedDesc.length - 3;

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
        <svg className="w-5 h-5 text-blue-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h3 className="text-base font-semibold text-gray-900">Imported versions</h3>
        <span className="text-xs text-gray-500 bg-gray-100 rounded-full px-2.5 py-0.5">
          {versions.length} version{versions.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[70px_120px_1fr_150px_220px] gap-2 px-5 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
        <div>Ver.</div>
        <div>Date</div>
        <div>Changes vs previous version</div>
        <div>Status</div>
        <div></div>
      </div>

      {/* Rows */}
      {visible.map((version, idx) => {
        const vNum = versionNumberMap.get(version.ver_id) ?? 0;
        const isOlder = showAll && idx >= 3;
        return (
          <div
            key={version.id}
            className={`grid grid-cols-[70px_120px_1fr_150px_220px] gap-2 items-center px-5 py-3 border-b border-gray-50 ${
              isOlder ? "opacity-60" : ""
            }`}
          >
            <div className="text-sm font-bold text-gray-900">v{vNum}</div>
            <div className="text-sm text-gray-500">{formatDate(version.date_in_force)}</div>
            <div className="flex items-center gap-1.5 flex-wrap">
              {version.diff_summary ? (
                <>
                  {version.diff_summary.modified > 0 && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                      {version.diff_summary.modified} modified
                    </span>
                  )}
                  {version.diff_summary.added > 0 && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                      {version.diff_summary.added} added
                    </span>
                  )}
                  {version.diff_summary.removed > 0 && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-700">
                      {version.diff_summary.removed} removed
                    </span>
                  )}
                  {version.diff_summary.modified === 0 && version.diff_summary.added === 0 && version.diff_summary.removed === 0 && (
                    <span className="text-xs text-gray-400">No changes</span>
                  )}
                </>
              ) : (
                <span className="text-xs text-gray-400">&mdash;</span>
              )}
            </div>
            <div>
              {version.is_current ? (
                <span className="text-sm font-medium text-green-700">Current version</span>
              ) : (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">
                  Imported
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 justify-end">
              <a
                href={`/laws/${lawId}/versions/${version.id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1 text-sm font-medium text-blue-600 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 transition-colors"
              >
                Read
              </a>
              <a
                href={`/laws/${lawId}#diff-selector`}
                className="px-3 py-1 text-sm font-medium text-blue-600 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 transition-colors"
              >
                Compare
              </a>
              <button
                onClick={() => handleDeleteVersion(version.id, vNum)}
                disabled={deletingId === version.id}
                className="px-2 py-1 text-sm font-medium text-red-600 bg-red-50 border border-red-200 rounded-md hover:bg-red-100 transition-colors disabled:opacity-50"
                title={`Delete v${vNum}`}
              >
                {deletingId === version.id ? "…" : "Delete"}
              </button>
            </div>
          </div>
        );
      })}

      {/* Show all / collapse toggle */}
      {hiddenCount > 0 && (
        <button
          onClick={() => setShowAll((prev) => !prev)}
          className="w-full py-3 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-50 transition-colors flex items-center justify-center gap-2 border-t border-gray-100"
        >
          {showAll ? (
            "Hide older versions"
          ) : (
            <>
              {hiddenCount} older version{hiddenCount !== 1 ? "s" : ""} &mdash; Show all
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
              </svg>
            </>
          )}
        </button>
      )}
    </div>
  );
}
