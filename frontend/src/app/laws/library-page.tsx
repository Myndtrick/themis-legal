"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { api, importSuggestionSSE, importAllSuggestionsSSE, LibraryData, LibraryLaw, SuggestedLaw, BulkImportProgress, BulkImportResult } from "@/lib/api";
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

  // Category modal (for existing laws)
  const [assigningLawId, setAssigningLawId] = useState<number | null>(null);

  // Pending imports: suggestion id → { suggestion, error?, errorCode?, progress? }
  const [pendingImports, setPendingImports] = useState<
    Map<number, {
      suggestion: SuggestedLaw;
      error?: string;
      errorCode?: string;
      progress?: { phase: string; current?: number; total?: number; message: string };
    }>
  >(new Map());

  // Category pick for suggestions without a predetermined category
  const [suggestionCategoryPick, setSuggestionCategoryPick] = useState<{
    suggestion: SuggestedLaw;
    importHistory: boolean;
  } | null>(null);

  // Bulk import state
  const [bulkImporting, setBulkImporting] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<BulkImportProgress | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkImportResult | null>(null);

  function handleImportAll() {
    setBulkImporting(true);
    setBulkProgress(null);
    setBulkResult(null);

    importAllSuggestionsSSE(
      (progress) => setBulkProgress(progress),
      () => { /* item done — will refresh at end */ },
      () => { /* item error — tracked in final result */ },
      (result) => {
        setBulkImporting(false);
        setBulkProgress(null);
        setBulkResult(result);
        fetchData();
      },
    ).catch(() => {
      setBulkImporting(false);
      setBulkProgress(null);
    });
  }

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

  // Filter out pending imports from suggestions
  const activeSuggestions = useMemo(() => {
    if (!data) return [];
    return data.suggested_laws.filter((s) => !pendingImports.has(s.id));
  }, [data, pendingImports]);

  // Group pending imports by group_slug
  const pendingByGroup = useMemo(() => {
    const map = new Map<string, { suggestion: SuggestedLaw; error?: string; errorCode?: string; progress?: { phase: string; current?: number; total?: number; message: string } }[]>();
    for (const [, entry] of pendingImports) {
      const key = entry.suggestion.group_slug;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(entry);
    }
    return map;
  }, [pendingImports]);

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

  // Optimistic import: immediately move suggestion to pending, run import in background
  function handleImportSuggestion(mappingId: number, importHistory: boolean) {
    const suggestion = data?.suggested_laws.find((s) => s.id === mappingId);
    if (!suggestion) return;

    // If no predetermined category, ask user to pick one first
    if (!suggestion.category_id) {
      setSuggestionCategoryPick({ suggestion, importHistory });
      return;
    }

    startImport(suggestion, importHistory);
  }

  function startImport(suggestion: SuggestedLaw, importHistory: boolean) {
    // Add to pending immediately (optimistic)
    setPendingImports((prev) => {
      const next = new Map(prev);
      next.set(suggestion.id, { suggestion });
      return next;
    });

    // Fire SSE import in background (not awaited)
    const controller = new AbortController();
    const timeoutMs = importHistory ? 600_000 : 120_000;
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    importSuggestionSSE(
      suggestion.id,
      importHistory,
      (progressEvent) => {
        setPendingImports((prev) => {
          const next = new Map(prev);
          const entry = next.get(suggestion.id);
          if (entry) {
            next.set(suggestion.id, { ...entry, progress: progressEvent });
          }
          return next;
        });
      },
      () => {
        clearTimeout(timer);
        setPendingImports((prev) => {
          const next = new Map(prev);
          next.delete(suggestion.id);
          return next;
        });
        fetchData();
      },
      (err) => {
        clearTimeout(timer);
        setPendingImports((prev) => {
          const next = new Map(prev);
          next.set(suggestion.id, { suggestion, error: err.message, errorCode: err.code });
          return next;
        });
      },
      controller.signal,
    ).catch((err) => {
      clearTimeout(timer);
      const message =
        err instanceof DOMException && err.name === "AbortError"
          ? "Import timed out — try current version only."
          : err instanceof Error
            ? err.message
            : "Import failed";
      setPendingImports((prev) => {
        const next = new Map(prev);
        next.set(suggestion.id, { suggestion, error: message });
        return next;
      });
    });
  }

  function handleSuggestionCategoryConfirm(categoryId: number) {
    if (!suggestionCategoryPick) return;
    const { suggestion, importHistory } = suggestionCategoryPick;
    // Override category on the suggestion for display purposes
    const withCategory = { ...suggestion, category_id: categoryId };
    setSuggestionCategoryPick(null);
    startImport(withCategory, importHistory);
  }

  function dismissPendingError(mappingId: number) {
    setPendingImports((prev) => {
      const next = new Map(prev);
      next.delete(mappingId);
      return next;
    });
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
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Legal Library</h1>
          <p className="mt-1 text-gray-600">Browse Romanian laws with full version history</p>
        </div>
        {activeSuggestions.length > 0 && (
          <button
            onClick={handleImportAll}
            disabled={bulkImporting}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors whitespace-nowrap"
          >
            {bulkImporting
              ? `Importing ${bulkProgress?.current || 0}/${bulkProgress?.total || activeSuggestions.length}...`
              : `Import All (${activeSuggestions.length})`}
          </button>
        )}
      </div>

      {/* Bulk import result */}
      {bulkResult && (
        <div className="mb-4 p-3 rounded-lg bg-green-50 border border-green-200 flex items-center justify-between">
          <p className="text-sm text-green-700">
            Imported {bulkResult.imported} of {bulkResult.total} laws.
            {bulkResult.failed > 0 && ` ${bulkResult.failed} failed.`}
          </p>
          <button onClick={() => setBulkResult(null)} className="text-green-600 text-xs font-medium">
            Dismiss
          </button>
        </div>
      )}

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

          {/* Grouped law sections (groups with imported laws or pending imports) */}
          {data.groups
            .filter((g) =>
              (groupedLaws.has(g.slug) && groupedLaws.get(g.slug)!.some((l) => l.category_id)) ||
              pendingByGroup.has(g.slug)
            )
            .map((g) => {
              const laws = (groupedLaws.get(g.slug) || []).filter((l) => l.category_id);
              const suggestions = activeSuggestions.filter((s) => s.group_slug === g.slug);
              const pending = pendingByGroup.get(g.slug) || [];
              return (
                <CategoryGroupSection
                  key={g.slug}
                  groupSlug={g.slug}
                  groupName={g.name_en}
                  colorHex={g.color_hex}
                  laws={laws}
                  suggestedLaws={suggestions}
                  pendingImports={pending}
                  defaultExpanded={!!selectedGroup || pending.length > 0}
                  onAssign={setAssigningLawId}
                  onDelete={fetchData}
                  onImportSuggestion={handleImportSuggestion}
                  onDismissPendingError={dismissPendingError}
                />
              );
            })}

          {/* Suggested-only groups (no imported laws, no pending imports) */}
          {data.groups
            .filter((g) =>
              g.categories.every((c) => c.law_count === 0) &&
              !pendingByGroup.has(g.slug) &&
              selectedGroup === g.slug &&
              activeSuggestions.some((s) => s.group_slug === g.slug)
            )
            .map((g) => {
              const suggestions = activeSuggestions.filter((s) => s.group_slug === g.slug);
              return (
                <CategoryGroupSection
                  key={g.slug}
                  groupSlug={g.slug}
                  groupName={g.name_en}
                  colorHex={g.color_hex}
                  laws={[]}
                  suggestedLaws={suggestions}
                  pendingImports={[]}
                  defaultExpanded={true}
                  onImportSuggestion={handleImportSuggestion}
                  onDismissPendingError={dismissPendingError}
                />
              );
            })}

          {/* Empty state */}
          {classifiedLaws.length === 0 && unclassifiedLaws.length === 0 && pendingImports.size === 0 &&
            // Don't show empty state if we're viewing a suggested group with suggestions
            !(selectedGroup && activeSuggestions.some((s) => s.group_slug === selectedGroup)) && (
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

      {/* Category modal for existing laws */}
      {assigningLawId && assigningLaw && (
        <CategoryModal
          lawTitle={assigningLaw.title}
          groups={data.groups}
          onConfirm={handleAssign}
          onSkip={() => setAssigningLawId(null)}
          onCancel={() => setAssigningLawId(null)}
        />
      )}

      {/* Category modal for suggestion imports without predetermined category */}
      {suggestionCategoryPick && (
        <CategoryModal
          lawTitle={suggestionCategoryPick.suggestion.title}
          groups={data.groups}
          onConfirm={handleSuggestionCategoryConfirm}
          onSkip={() => setSuggestionCategoryPick(null)}
          onCancel={() => setSuggestionCategoryPick(null)}
        />
      )}
    </div>
  );
}
