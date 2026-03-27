"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import type { KnownVersionData } from "@/lib/api";

interface VersionsSectionProps {
  lawId: number;
  lastCheckedAt: string | null;
  importedVerIds: Set<string>;
}

function formatLastChecked(lastCheckedAt: string | null): {
  text: string;
  className: string;
} {
  if (!lastCheckedAt) {
    return { text: "Not yet checked", className: "text-gray-400" };
  }

  const checked = new Date(lastCheckedAt);
  const now = new Date();
  const diffMs = now.getTime() - checked.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);
  const diffDays = diffMs / (1000 * 60 * 60 * 24);

  let text: string;
  if (diffHours < 24) {
    const hh = checked.getHours().toString().padStart(2, "0");
    const mm = checked.getMinutes().toString().padStart(2, "0");
    text = `Last checked: today at ${hh}:${mm}`;
  } else if (diffDays <= 7) {
    const days = Math.floor(diffDays);
    text = `Last checked: ${days} day${days !== 1 ? "s" : ""} ago`;
  } else {
    const months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    text = `Last checked: ${checked.getDate()} ${months[checked.getMonth()]} ${checked.getFullYear()}`;
  }

  return { text, className: "text-gray-500" };
}

function twoYearsAgo(): Date {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 2);
  return d;
}

export default function VersionsSection({
  lawId,
  lastCheckedAt,
  importedVerIds,
}: VersionsSectionProps) {
  const [versions, setVersions] = useState<KnownVersionData[] | null>(null);
  const [importedIds, setImportedIds] = useState<Set<string>>(importedVerIds);
  const [loading, setLoading] = useState(true);
  const [showOlder, setShowOlder] = useState(false);
  const [importing, setImporting] = useState<Set<string>>(new Set());
  const [bulkImporting, setBulkImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { text: lastCheckedText, className: lastCheckedClass } =
    formatLastChecked(lastCheckedAt);

  useEffect(() => {
    api.laws
      .getKnownVersions(lawId)
      .then((data) => {
        setVersions(data.versions);
        // Sync imported status from server response
        const imported = new Set<string>();
        for (const v of data.versions) {
          if (v.is_imported) imported.add(v.ver_id);
        }
        setImportedIds(imported);
      })
      .catch(() => {
        setError("Failed to load version history.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [lawId]);

  async function handleImportVersion(verId: string) {
    setImporting((prev) => new Set(prev).add(verId));
    try {
      await api.laws.importKnownVersion(lawId, verId);
      setImportedIds((prev) => {
        const next = new Set(prev);
        next.add(verId);
        return next;
      });
      setVersions((prev) =>
        prev
          ? prev.map((v) =>
              v.ver_id === verId ? { ...v, is_imported: true } : v
            )
          : prev
      );
    } catch {
      alert(`Failed to import version ${verId}. Please try again.`);
    } finally {
      setImporting((prev) => {
        const next = new Set(prev);
        next.delete(verId);
        return next;
      });
    }
  }

  async function handleImportAll() {
    if (!versions) return;
    const missing = versions.filter((v) => !importedIds.has(v.ver_id));
    if (missing.length === 0) return;

    if (missing.length > 10) {
      const confirmed = window.confirm(
        `This will import ${missing.length} versions. Are you sure?`
      );
      if (!confirmed) return;
    }

    setBulkImporting(true);
    try {
      const result = await api.laws.importAllMissing(lawId);
      // Refresh the full list after bulk import
      const data = await api.laws.getKnownVersions(lawId);
      setVersions(data.versions);
      const imported = new Set<string>();
      for (const v of data.versions) {
        if (v.is_imported) imported.add(v.ver_id);
      }
      setImportedIds(imported);
      if (result.errors && result.errors.length > 0) {
        alert(
          `Imported ${result.imported} version(s). ${result.errors.length} error(s) occurred.`
        );
      }
    } catch {
      alert("Failed to import all versions. Please try again.");
    } finally {
      setBulkImporting(false);
    }
  }

  const cutoff = twoYearsAgo();
  const recentVersions = versions
    ? versions.filter(
        (v) => !v.date_in_force || new Date(v.date_in_force) >= cutoff
      )
    : [];
  const olderVersions = versions
    ? versions.filter(
        (v) => v.date_in_force && new Date(v.date_in_force) < cutoff
      )
    : [];

  const unimportedCount = versions
    ? versions.filter((v) => !importedIds.has(v.ver_id)).length
    : 0;
  const missingCount = versions
    ? versions.filter((v) => !importedIds.has(v.ver_id)).length
    : 0;

  const displayedVersions = showOlder
    ? versions ?? []
    : recentVersions;

  return (
    <div className="mt-8">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-semibold text-gray-900">Official Versions</h2>
        {!loading && versions && missingCount > 0 && (
          <button
            onClick={handleImportAll}
            disabled={bulkImporting}
            className="px-3 py-1.5 text-sm font-medium text-amber-700 bg-amber-50 rounded hover:bg-amber-100 disabled:bg-gray-100 disabled:text-gray-400 transition-colors"
          >
            {bulkImporting
              ? "Importing..."
              : `Import all missing (${missingCount})`}
          </button>
        )}
      </div>

      <p className={`text-sm mb-4 ${lastCheckedClass}`}>{lastCheckedText}</p>

      {!loading && unimportedCount > 0 && (
        <p className="text-sm text-amber-600 mb-3">
          {unimportedCount} version{unimportedCount !== 1 ? "s" : ""} not imported
        </p>
      )}

      <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-200">
        {loading && (
          <div className="p-4 text-sm text-gray-500">
            Loading version history...
          </div>
        )}

        {!loading && error && (
          <div className="p-4 text-sm text-red-500">{error}</div>
        )}

        {!loading && !error && versions && versions.length === 0 && (
          <div className="p-4 text-sm text-gray-500">
            No version history discovered yet.
          </div>
        )}

        {!loading &&
          !error &&
          displayedVersions.map((version) => {
            const isImported = importedIds.has(version.ver_id);
            const isImporting = importing.has(version.ver_id);

            return (
              <div
                key={version.ver_id}
                className="flex items-center justify-between p-4"
              >
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="font-medium text-gray-900 text-sm">
                    {version.date_in_force || "Date unknown"}
                  </span>
                  <span className="text-sm text-gray-500">
                    (ver_id: {version.ver_id})
                  </span>
                  {version.is_current && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                      CURRENT
                    </span>
                  )}
                  {isImported ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                      IMPORTED
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-500">
                      NOT IMPORTED
                    </span>
                  )}
                </div>
                {!isImported && (
                  <button
                    onClick={() => handleImportVersion(version.ver_id)}
                    disabled={isImporting}
                    className="ml-4 px-3 py-1 text-sm font-medium text-blue-600 bg-blue-50 rounded hover:bg-blue-100 disabled:bg-gray-100 disabled:text-gray-400 transition-colors whitespace-nowrap"
                  >
                    {isImporting ? "Importing..." : "Import"}
                  </button>
                )}
              </div>
            );
          })}

        {!loading && !error && olderVersions.length > 0 && (
          <button
            onClick={() => setShowOlder((prev) => !prev)}
            className="w-full p-3 text-sm text-gray-500 hover:text-gray-700 hover:bg-gray-50 transition-colors text-left"
          >
            {showOlder
              ? "Hide older versions"
              : `Show ${olderVersions.length} older version${olderVersions.length !== 1 ? "s" : ""}`}
          </button>
        )}
      </div>
    </div>
  );
}
