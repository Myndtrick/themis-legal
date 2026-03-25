"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { api, LibraryData, LibraryLaw, CategoryGroupData } from "@/lib/api";
import Sidebar from "./components/sidebar";
import StatsCards from "./components/stats-cards";
import CategoryGroupSection from "./components/category-group-section";
import UnclassifiedSection from "./components/unclassified-section";
import CategoryModal from "./components/category-modal";
import CombinedSearch from "./components/combined-search";

export default function LibraryPage() {
  const [data, setData] = useState<LibraryData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Filters
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null);

  // Category modal
  const [assigningLawId, setAssigningLawId] = useState<number | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const result = await api.laws.library();
      setData(result);
      setError(null);
    } catch {
      setError("Could not connect to the backend. Make sure the API server is running.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Filter laws
  const filteredLaws = useMemo(() => {
    if (!data) return [];
    let laws = data.laws;

    if (selectedGroup) {
      laws = laws.filter((l) => l.category_group_slug === selectedGroup);
    }
    if (selectedCategory) {
      // Find category id from slug
      const catId = data.groups
        .flatMap((g) => g.categories)
        .find((c) => c.slug === selectedCategory)?.id;
      if (catId) {
        laws = laws.filter((l) => l.category_id === catId);
      }
    }
    if (selectedStatus) {
      laws = laws.filter((l) => l.current_version?.state === selectedStatus);
    }

    return laws;
  }, [data, selectedGroup, selectedCategory, selectedStatus]);

  // Compute filtered stats
  const filteredStats = useMemo(() => {
    if (!data) return { total_laws: 0, total_versions: 0, last_imported: null };
    const isFiltered = selectedGroup || selectedCategory || selectedStatus;
    if (!isFiltered) return data.stats;
    return {
      total_laws: filteredLaws.length,
      total_versions: filteredLaws.reduce((sum, l) => sum + l.version_count, 0),
      last_imported: data.stats.last_imported,
    };
  }, [data, filteredLaws, selectedGroup, selectedCategory, selectedStatus]);

  // Group laws by category_group_slug
  const groupedLaws = useMemo(() => {
    if (!data) return new Map<string, LibraryLaw[]>();
    const map = new Map<string, LibraryLaw[]>();
    for (const law of filteredLaws) {
      const key = law.category_group_slug || "__unclassified__";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(law);
    }
    return map;
  }, [data, filteredLaws]);

  const unclassifiedLaws = useMemo(() => {
    return filteredLaws.filter((l) => !l.category_id);
  }, [filteredLaws]);

  const classifiedLaws = useMemo(() => {
    return filteredLaws.filter((l) => l.category_id);
  }, [filteredLaws]);

  // Category assignment
  const assigningLaw = data?.laws.find((l) => l.id === assigningLawId);

  async function handleAssign(categoryId: number) {
    if (!assigningLawId) return;
    await api.laws.assignCategory(assigningLawId, categoryId);
    setAssigningLawId(null);
    fetchData();
  }

  async function handleImportSuggestion(mappingId: number, importHistory: boolean) {
    const controller = new AbortController();
    const timeoutMs = importHistory ? 600_000 : 120_000;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      await api.laws.importSuggestion(mappingId, importHistory, controller.signal);
      clearTimeout(timer);
      fetchData();
    } catch (err) {
      clearTimeout(timer);
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new Error("Import timed out — try importing current version only.");
      }
      throw err;
    }
  }

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading library...</div>;
  }

  if (error) {
    return (
      <div className="rounded-md bg-red-50 border border-red-200 p-4 mb-6">
        <p className="text-sm text-red-700">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div>
      {/* Header */}
      <div className="mb-4">
        <h1 className="text-3xl font-bold text-gray-900">Legal Library</h1>
        <p className="mt-1 text-gray-600">Browse Romanian laws with full version history</p>
      </div>

      {/* Combined search */}
      <CombinedSearch
        groups={data.groups}
        suggestedLaws={data.suggested_laws}
        onImportComplete={fetchData}
      />

      {/* Main layout: sidebar + content */}
      <div className="flex border border-gray-200 rounded-lg bg-white min-h-[500px]">
        <Sidebar
          groups={data.groups}
          laws={data.laws}
          selectedGroup={selectedGroup}
          selectedCategory={selectedCategory}
          selectedStatus={selectedStatus}
          onSelectGroup={setSelectedGroup}
          onSelectCategory={setSelectedCategory}
          onSelectStatus={setSelectedStatus}
        />

        {/* Main content */}
        <div className="flex-1 p-5">
          <StatsCards
            totalLaws={filteredStats.total_laws}
            totalVersions={filteredStats.total_versions}
            lastImported={filteredStats.last_imported}
          />

          {/* Grouped law sections */}
          {data.groups
            .filter((g) => groupedLaws.has(g.slug) && groupedLaws.get(g.slug)!.some((l) => l.category_id))
            .map((g) => {
              const laws = groupedLaws.get(g.slug)!.filter((l) => l.category_id);
              const suggestions = data.suggested_laws.filter((s) => s.group_slug === g.slug);
              return (
                <CategoryGroupSection
                  key={g.slug}
                  groupSlug={g.slug}
                  groupName={g.name_en}
                  colorHex={g.color_hex}
                  laws={laws}
                  suggestedLaws={suggestions}
                  defaultExpanded={!!selectedGroup}
                  onAssign={setAssigningLawId}
                  onDelete={fetchData}
                  onImportSuggestion={handleImportSuggestion}
                />
              );
            })}

          {/* Empty state */}
          {classifiedLaws.length === 0 && unclassifiedLaws.length === 0 && (
            <div className="text-center py-12">
              <h3 className="text-lg font-medium text-gray-900 mb-2">No laws found</h3>
              <p className="text-gray-600">
                {selectedGroup || selectedCategory || selectedStatus
                  ? "Try changing your filters."
                  : "Laws will appear here once they are imported."}
              </p>
            </div>
          )}

          {/* Unclassified */}
          <UnclassifiedSection
            laws={unclassifiedLaws}
            onAssign={setAssigningLawId}
            onDelete={fetchData}
          />
        </div>
      </div>

      {/* Category modal */}
      {assigningLawId && assigningLaw && (
        <CategoryModal
          lawTitle={assigningLaw.title}
          groups={data.groups}
          onConfirm={handleAssign}
          onSkip={() => setAssigningLawId(null)}
          onCancel={() => setAssigningLawId(null)}
        />
      )}
    </div>
  );
}
