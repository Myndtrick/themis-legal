"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { KnownVersionData } from "@/lib/api";

interface UnimportedVersionsTableProps {
  lawId: number;
  versions: KnownVersionData[];
  allKnownVersions: KnownVersionData[];
  onVersionImported: (verId: string, lawVersionId: number) => void;
}

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return `${d.getDate().toString().padStart(2, "0")} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export default function UnimportedVersionsTable({
  lawId,
  versions,
  allKnownVersions,
  onVersionImported,
}: UnimportedVersionsTableProps) {
  const [importing, setImporting] = useState<Set<string>>(new Set());

  if (versions.length === 0) return null;

  // Version numbers based on ordinal position in ALL known versions (sorted asc by date)
  const allSortedAsc = [...allKnownVersions].sort((a, b) =>
    a.date_in_force.localeCompare(b.date_in_force)
  );
  const versionNumberMap = new Map<string, number>();
  allSortedAsc.forEach((v, i) => versionNumberMap.set(v.ver_id, i + 1));

  // Sort unimported newest first for display
  const sortedDesc = [...versions].sort((a, b) =>
    b.date_in_force.localeCompare(a.date_in_force)
  );

  async function handleImport(verId: string) {
    setImporting((prev) => new Set(prev).add(verId));
    try {
      const res = await api.laws.importKnownVersion(lawId, verId);
      onVersionImported(verId, res.law_version_id);
    } catch {
      alert(`Failed to import version. Please try again.`);
    } finally {
      setImporting((prev) => {
        const next = new Set(prev);
        next.delete(verId);
        return next;
      });
    }
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/50">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-amber-200/50">
        <svg className="w-5 h-5 text-amber-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <h3 className="text-base font-semibold text-gray-900">Not imported from legislatie.just.ro</h3>
        <span className="text-xs text-amber-700 bg-amber-100 rounded-full px-2.5 py-0.5">
          {versions.length} version{versions.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[70px_120px_1fr_150px_120px] gap-2 px-5 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-amber-200/30">
        <div>Ver.</div>
        <div>Date</div>
        <div>Changes vs previous version</div>
        <div>Status</div>
        <div></div>
      </div>

      {/* Rows */}
      {sortedDesc.map((version) => {
        const vNum = versionNumberMap.get(version.ver_id) ?? 0;
        const isImporting = importing.has(version.ver_id);
        return (
          <div
            key={version.ver_id}
            className="grid grid-cols-[70px_120px_1fr_150px_120px] gap-2 items-center px-5 py-3 border-b border-amber-200/20"
          >
            <div className="text-sm font-bold text-gray-900">v{vNum}</div>
            <div className="text-sm text-gray-500">{formatDate(version.date_in_force)}</div>
            <div>
              <span className="text-xs text-gray-400">&mdash;</span>
            </div>
            <div>
              <span className="text-sm text-amber-700">Not imported</span>
            </div>
            <div className="flex justify-end">
              <button
                onClick={() => handleImport(version.ver_id)}
                disabled={isImporting}
                className="px-3 py-1 text-sm font-medium text-amber-700 bg-white border border-amber-300 rounded-md hover:bg-amber-100 disabled:bg-gray-100 disabled:text-gray-400 transition-colors"
              >
                {isImporting ? "Importing..." : "+ Import"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
