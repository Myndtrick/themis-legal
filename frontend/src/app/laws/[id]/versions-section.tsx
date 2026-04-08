"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { KnownVersionData, LawVersionSummary } from "@/lib/api";
import UpdateBanner from "./update-banner";
import ImportedVersionsTable from "./imported-versions-table";
import UnimportedVersionsTable from "./unimported-versions-table";
import CheckHistorySection from "./check-history-section";

interface VersionsSectionProps {
  lawId: number;
  lastCheckedAt: string | null;
  versions: LawVersionSummary[];
}

export default function VersionsSection({
  lawId,
  lastCheckedAt,
  versions: initialVersions,
}: VersionsSectionProps) {
  const router = useRouter();
  const [versions, setVersions] = useState<LawVersionSummary[]>(initialVersions);
  const [knownVersions, setKnownVersions] = useState<KnownVersionData[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [checkRefreshKey, setCheckRefreshKey] = useState(0);

  const importedVerIds = new Set(versions.map((v) => v.ver_id));

  // Load known versions on mount
  useEffect(() => {
    api.laws
      .getKnownVersions(lawId)
      .then((data) => setKnownVersions(data.versions))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [lawId]);

  const handleKnownVersionsLoaded = useCallback((loaded: KnownVersionData[]) => {
    setKnownVersions(loaded);
  }, []);

  const handleVersionImported = useCallback(async (_verId: string, _lawVersionId: number) => {
    // Re-fetch law data to get updated versions list with diff_summary
    try {
      const law = await api.laws.get(lawId);
      setVersions(law.versions);
    } catch {
      // Fallback: full page refresh
      router.refresh();
    }
  }, [lawId, router]);

  const handleVersionDeleted = useCallback((versionId: number) => {
    setVersions((prev) => prev.filter((v) => v.id !== versionId));
  }, []);

  const handleCheckComplete = useCallback(() => {
    setCheckRefreshKey((k) => k + 1);
  }, []);

  const unimportedVersions = knownVersions
    ? knownVersions.filter((v) => !importedVerIds.has(v.ver_id))
    : [];

  return (
    <div className="space-y-4 mt-8">
      <UpdateBanner
        lawId={lawId}
        lastCheckedAt={lastCheckedAt}
        importedVerIds={importedVerIds}
        knownVersions={knownVersions}
        onVersionImported={handleVersionImported}
        onKnownVersionsLoaded={handleKnownVersionsLoaded}
        onCheckComplete={handleCheckComplete}
      />

      <ImportedVersionsTable lawId={lawId} versions={versions} knownVersions={knownVersions} onVersionDeleted={handleVersionDeleted} />

      {!loading && knownVersions && unimportedVersions.length > 0 && (
        <UnimportedVersionsTable
          lawId={lawId}
          versions={unimportedVersions}
          allKnownVersions={knownVersions}
          onVersionImported={handleVersionImported}
        />
      )}

      <CheckHistorySection lawId={lawId} refreshKey={checkRefreshKey} />
    </div>
  );
}
