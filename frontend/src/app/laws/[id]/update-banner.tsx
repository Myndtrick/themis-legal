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
  const [importing, setImporting] = useState(false);
  const [checkedAt, setCheckedAt] = useState(lastCheckedAt);

  // Auto-check on mount if stale
  useEffect(() => {
    if (!shouldAutoCheck(lastCheckedAt)) return;
    setChecking(true);
    api.laws
      .checkUpdates(lawId)
      .then(() => api.laws.getKnownVersions(lawId))
      .then((data) => {
        onKnownVersionsLoaded(data.versions);
        setCheckedAt(data.last_checked_at);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [lawId, lastCheckedAt, onKnownVersionsLoaded]);

  const unimported = knownVersions
    ? knownVersions.filter((v) => !importedVerIds.has(v.ver_id))
    : [];

  // Find the latest unimported version (newest by date)
  const latestUnimported = unimported.length > 0
    ? unimported.reduce((a, b) => (a.date_in_force > b.date_in_force ? a : b))
    : null;

  // Compute the version number for display (ordinal position in all known versions)
  const allSortedAsc = knownVersions
    ? [...knownVersions].sort((a, b) => a.date_in_force.localeCompare(b.date_in_force))
    : [];
  const latestVersionNumber = latestUnimported
    ? allSortedAsc.findIndex((v) => v.ver_id === latestUnimported.ver_id) + 1
    : 0;

  async function handleImportLatest() {
    if (!latestUnimported) return;
    setImporting(true);
    try {
      const res = await api.laws.importKnownVersion(lawId, latestUnimported.ver_id);
      onVersionImported(latestUnimported.ver_id, res.law_version_id);
    } catch {
      alert("Failed to import version. Please try again.");
    } finally {
      setImporting(false);
    }
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
  if (unimported.length === 0 || dismissed) {
    return (
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 flex items-start gap-3">
        <svg className="w-5 h-5 text-green-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <div>
          <p className="text-sm font-medium text-green-800">No new versions</p>
          <p className="text-sm text-gray-500">{checkedText} &middot; All available versions are imported</p>
        </div>
      </div>
    );
  }

  // New versions available
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        <svg className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
        </svg>
        <div>
          <p className="text-sm font-medium text-amber-800">
            {unimported.length} new version{unimported.length !== 1 ? "s" : ""} available
          </p>
          <p className="text-sm text-amber-700/70">
            {checkedText} &middot; {unimported.length} version{unimported.length !== 1 ? "s" : ""} not yet imported
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={handleImportLatest}
          disabled={importing}
          className="px-3 py-1.5 text-sm font-medium text-white bg-amber-600 rounded-md hover:bg-amber-700 disabled:bg-amber-300 transition-colors"
        >
          {importing ? "Importing..." : `Import latest version (v${latestVersionNumber})`}
        </button>
        <button
          onClick={() => setDismissed(true)}
          className="px-3 py-1.5 text-sm font-medium text-amber-700 bg-white border border-amber-300 rounded-md hover:bg-amber-100 transition-colors"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
