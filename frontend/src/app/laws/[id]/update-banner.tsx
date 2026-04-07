"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { KnownVersionData } from "@/lib/api";

interface UpdateBannerProps {
  lawId: number;
  lastCheckedAt: string | null;
  importedVerIds: Set<string>;
  knownVersions: KnownVersionData[] | null;
  onVersionImported: (verId: string, lawVersionId: number) => void;
  onKnownVersionsLoaded: (versions: KnownVersionData[]) => void;
}

function formatCheckedTime(lastCheckedAt: string | null): string {
  if (!lastCheckedAt) return "Never checked";
  const checked = new Date(lastCheckedAt);
  const now = new Date();
  const diffMs = now.getTime() - checked.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  if (diffHours < 24) {
    const hh = checked.getHours().toString().padStart(2, "0");
    const mm = checked.getMinutes().toString().padStart(2, "0");
    return `Last checked: today, ${hh}:${mm}`;
  }
  if (diffDays <= 7) {
    const days = Math.floor(diffDays);
    return `Last checked: ${days} day${days !== 1 ? "s" : ""} ago`;
  }
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `Last checked: ${checked.getDate()} ${months[checked.getMonth()]} ${checked.getFullYear()}`;
}

function shouldAutoCheck(lastCheckedAt: string | null): boolean {
  if (!lastCheckedAt) return true;
  const checked = new Date(lastCheckedAt);
  const now = new Date();
  return now.getTime() - checked.getTime() > 60 * 60 * 1000; // 1 hour
}

export default function UpdateBanner({
  lawId,
  lastCheckedAt,
  importedVerIds,
  knownVersions,
  onVersionImported,
  onKnownVersionsLoaded,
}: UpdateBannerProps) {
  const [dismissed, setDismissed] = useState(false);
  const [checking, setChecking] = useState(false);
  const [importingVerId, setImportingVerId] = useState<string | null>(null);
  const [importingAll, setImportingAll] = useState(false);
  const [checkedAt, setCheckedAt] = useState(lastCheckedAt);
  const [checkError, setCheckError] = useState<string | null>(null);

  // Auto-check on mount if stale
  useEffect(() => {
    if (!shouldAutoCheck(lastCheckedAt)) return;
    setChecking(true);
    setCheckError(null);
    api.laws
      .checkUpdates(lawId)
      .then(() => api.laws.getKnownVersions(lawId))
      .then((data) => {
        onKnownVersionsLoaded(data.versions);
        setCheckedAt(data.last_checked_at);
      })
      .catch((e: unknown) => {
        setCheckError(e instanceof Error ? e.message : "Failed to check for updates");
      })
      .finally(() => setChecking(false));
  }, [lawId, lastCheckedAt, onKnownVersionsLoaded]);

  // Build version number map: ordinal position by date across ALL known versions
  const allSortedAsc = knownVersions
    ? [...knownVersions].sort((a, b) => a.date_in_force.localeCompare(b.date_in_force))
    : [];
  const versionNumberMap = new Map<string, number>();
  allSortedAsc.forEach((v, i) => versionNumberMap.set(v.ver_id, i + 1));

  // Find the highest version number that is imported
  let highestImportedNum = 0;
  for (const verId of importedVerIds) {
    const num = versionNumberMap.get(verId) ?? 0;
    if (num > highestImportedNum) highestImportedNum = num;
  }

  // Only show versions NEWER than the highest imported version (not historical gaps)
  const newVersions = knownVersions
    ? knownVersions.filter((v) => {
        if (importedVerIds.has(v.ver_id)) return false;
        const num = versionNumberMap.get(v.ver_id) ?? 0;
        return num > highestImportedNum;
      })
    : [];

  // Sort new versions by date descending (newest first)
  const newVersionsSorted = [...newVersions].sort((a, b) =>
    b.date_in_force.localeCompare(a.date_in_force)
  );

  async function handleCheckNow() {
    setChecking(true);
    setCheckError(null);
    // Clear any prior dismissal — the user is explicitly asking for a fresh
    // check, so if new versions are found they should surface again even if
    // the user had dismissed the banner earlier in this session.
    setDismissed(false);
    try {
      await api.laws.checkUpdates(lawId);
      const data = await api.laws.getKnownVersions(lawId);
      onKnownVersionsLoaded(data.versions);
      setCheckedAt(data.last_checked_at);
    } catch (e: unknown) {
      setCheckError(e instanceof Error ? e.message : "Failed to check for updates");
    } finally {
      setChecking(false);
    }
  }

  async function handleImportVersion(version: KnownVersionData) {
    setImportingVerId(version.ver_id);
    try {
      const res = await api.laws.importKnownVersion(lawId, version.ver_id);
      onVersionImported(version.ver_id, res.law_version_id);
    } catch {
      alert("Failed to import version. Please try again.");
    } finally {
      setImportingVerId(null);
    }
  }

  async function handleImportAll() {
    setImportingAll(true);
    // Import oldest first so diffs are computed correctly
    const oldestFirst = [...newVersionsSorted].reverse();
    for (const version of oldestFirst) {
      try {
        const res = await api.laws.importKnownVersion(lawId, version.ver_id);
        onVersionImported(version.ver_id, res.law_version_id);
      } catch {
        alert(`Failed to import v${versionNumberMap.get(version.ver_id) ?? "?"}. Stopping.`);
        break;
      }
    }
    setImportingAll(false);
  }

  const checkedText = formatCheckedTime(checkedAt);

  // Still loading known versions or actively checking — show spinner
  if (checking || knownVersions === null) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 flex items-center gap-3">
        <div className="w-5 h-5 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
        <span className="text-sm text-gray-600">Checking legislatie.just.ro for updates...</span>
      </div>
    );
  }

  // Up to date
  if (newVersions.length === 0 || dismissed) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-green-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <p className="text-sm font-medium text-green-800">No new versions</p>
              <p className="text-sm text-gray-500">{checkedText} &middot; All available versions are imported</p>
              {checkError && (
                <p className="text-sm text-red-600 mt-1">
                  Check failed: {checkError}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={handleCheckNow}
            className="px-3 py-1.5 text-sm font-medium text-gray-600 bg-white border border-gray-300 rounded-md hover:bg-gray-100 transition-colors shrink-0"
          >
            {checkError ? "Retry" : "Check now"}
          </button>
        </div>
      </div>
    );
  }

  // New versions available
  const isAnyImporting = importingVerId !== null || importingAll;

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <svg className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
          <div>
            <p className="text-sm font-medium text-amber-800">
              {newVersions.length} new version{newVersions.length !== 1 ? "s" : ""} available
            </p>
            <p className="text-sm text-amber-700/70">
              {checkedText} &middot; {newVersions.length} version{newVersions.length !== 1 ? "s" : ""} not yet imported
            </p>
            {checkError && (
              <p className="text-sm text-red-600 mt-1">
                Check failed: {checkError}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {newVersionsSorted.length > 1 && (
            <button
              onClick={handleImportAll}
              disabled={isAnyImporting}
              className="px-3 py-1.5 text-sm font-medium text-white bg-amber-600 rounded-md hover:bg-amber-700 disabled:bg-amber-300 transition-colors"
            >
              {importingAll ? "Importing..." : `Import all (${newVersionsSorted.length})`}
            </button>
          )}
          <button
            onClick={() => setDismissed(true)}
            className="px-3 py-1.5 text-sm font-medium text-amber-700 bg-white border border-amber-300 rounded-md hover:bg-amber-100 transition-colors"
          >
            Dismiss
          </button>
        </div>
      </div>

      {/* List of individual new versions */}
      <div className="mt-3 space-y-2">
        {newVersionsSorted.map((version) => {
          const vNum = versionNumberMap.get(version.ver_id) ?? 0;
          const isThisImporting = importingVerId === version.ver_id;
          return (
            <div
              key={version.ver_id}
              className="flex items-center justify-between bg-white/60 rounded-md px-3 py-2 border border-amber-100"
            >
              <div className="flex items-center gap-3">
                <span className="text-sm font-bold text-gray-900">v{vNum}</span>
                <span className="text-sm text-gray-500">
                  {(() => {
                    const d = new Date(version.date_in_force);
                    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
                    return `${d.getDate().toString().padStart(2, "0")} ${months[d.getMonth()]} ${d.getFullYear()}`;
                  })()}
                </span>
              </div>
              <button
                onClick={() => handleImportVersion(version)}
                disabled={isAnyImporting}
                className="px-3 py-1 text-sm font-medium text-amber-700 bg-white border border-amber-300 rounded-md hover:bg-amber-100 disabled:opacity-50 transition-colors"
              >
                {isThisImporting ? "Importing..." : `Import v${vNum}`}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
