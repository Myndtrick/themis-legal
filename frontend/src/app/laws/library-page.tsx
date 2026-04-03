"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { api, importAllSuggestionsSSE, importLawStreamSSE, LibraryData, LibraryLaw, SuggestedLaw, BulkImportProgress, BulkImportResult, ImportProgressEvent, NewVersionEntry } from "@/lib/api";
import Sidebar from "./components/sidebar";
import StatsCards from "./components/stats-cards";
import CategoryGroupSection from "./components/category-group-section";
import UnclassifiedSection from "./components/unclassified-section";
import CategoryModal from "./components/category-modal";
import CombinedSearch, { BackgroundImportInfo } from "./components/combined-search";
import ImportProgressSection, { ImportingEntry, FailedEntry } from "./components/import-progress-section";
import NewVersionsSection from "./components/new-versions-section";

let _importIdCounter = 0;

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

  // Pending imports from suggestions (existing flow for suggestion imports)
  const [pendingImports, setPendingImports] = useState<
    Map<number, {
      suggestion: SuggestedLaw;
      error?: string;
      errorCode?: string;
      progress?: { phase: string; current?: number; total?: number; message: string };
    }>
  >(new Map());

  // NEW: Import progress tracking
  const [importingEntries, setImportingEntries] = useState<ImportingEntry[]>([]);
  const [failedEntries, setFailedEntries] = useState<FailedEntry[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const stored = localStorage.getItem("themis_failed_imports");
      return stored ? JSON.parse(stored) : [];
    } catch { return []; }
  });
  // Track law_ids currently importing from new versions section
  const [newVersionImportingIds, setNewVersionImportingIds] = useState<Set<number>>(new Set());
  const [newVersionsRefreshKey, setNewVersionsRefreshKey] = useState(0);
  // Keep abort controllers so we can cancel if needed
  const abortControllers = useRef<Map<string, AbortController>>(new Map());

  // Category pick for suggestions without a predetermined category
  const [suggestionCategoryPick, setSuggestionCategoryPick] = useState<{
    suggestion: SuggestedLaw;
    importHistory: boolean;
  } | null>(null);

  // Bulk import state
  const [bulkImporting, setBulkImporting] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<BulkImportProgress | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkImportResult | null>(null);

  function handleImportAll(importHistory: boolean) {
    setBulkImporting(true);
    setBulkProgress(null);
    setBulkResult(null);

    importAllSuggestionsSSE(
      importHistory,
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

  // Persist failed imports to localStorage
  useEffect(() => {
    try {
      if (failedEntries.length > 0) {
        localStorage.setItem("themis_failed_imports", JSON.stringify(failedEntries));
      } else {
        localStorage.removeItem("themis_failed_imports");
      }
    } catch { /* localStorage unavailable */ }
  }, [failedEntries]);

  // Abort all in-flight imports on unmount
  useEffect(() => {
    return () => {
      for (const controller of abortControllers.current.values()) {
        controller.abort();
      }
    };
  }, []);

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

  // Group pending suggestion imports by group_slug
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
    try {
      await api.laws.assignCategory(assigningLawId, categoryId);
      setAssigningLawId(null);
      fetchData();
    } catch (err) {
      console.error("Failed to assign category:", err);
      setError(err instanceof Error ? err.message : "Failed to assign category");
      setAssigningLawId(null);
    }
  }

  // Optimistic import: immediately move suggestion to pending, run import in background
  function handleImportSuggestion(mappingId: number, importHistory: boolean) {
    const suggestion = data?.suggested_laws.find((s) => s.id === mappingId);
    if (!suggestion) return;

    if (!suggestion.category_id) {
      setSuggestionCategoryPick({ suggestion, importHistory });
      return;
    }

    startImport(suggestion, importHistory);
  }

  function startImport(suggestion: SuggestedLaw, importHistory: boolean) {
    setPendingImports((prev) => {
      const next = new Map(prev);
      next.set(suggestion.id, { suggestion });
      return next;
    });

    const controller = new AbortController();
    const timeoutMs = importHistory ? 600_000 : 120_000;
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const importPromise = suggestion.celex_number
      ? api.laws.euImport(suggestion.celex_number, importHistory, controller.signal)
      : api.laws.importSuggestion(suggestion.id, importHistory, controller.signal);

    importPromise
      .then(() => {
        clearTimeout(timer);
        setPendingImports((prev) => {
          const next = new Map(prev);
          next.delete(suggestion.id);
          return next;
        });
        fetchData();
      })
      .catch((err) => {
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

  // === NEW: Background import with streaming progress ===

  function startStreamingImport(entry: ImportingEntry) {
    const controller = new AbortController();
    abortControllers.current.set(entry.id, controller);

    // Add to importing list
    setImportingEntries((prev) => [...prev.filter(e => e.id !== entry.id), entry]);

    // EU imports don't have streaming — use simple fetch
    if (entry.source === "eu") {
      api.laws.euImport(entry.verId, entry.importHistory, controller.signal)
        .then((res) => {
          // Assign category
          if (entry.categoryId) {
            return api.laws.assignCategory(res.law_id, entry.categoryId).then(() => res);
          }
          return res;
        })
        .then(() => {
          abortControllers.current.delete(entry.id);
          setImportingEntries((prev) => prev.filter(e => e.id !== entry.id));
          fetchData();
        })
        .catch((err) => {
          abortControllers.current.delete(entry.id);
          const message = err instanceof DOMException && err.name === "AbortError"
            ? "Import timed out"
            : err instanceof Error ? err.message : "Import failed";
          // Move to failed
          setImportingEntries((prev) => prev.filter(e => e.id !== entry.id));
          setFailedEntries((prev) => [...prev, {
            id: entry.id,
            title: entry.title,
            lawNumber: entry.lawNumber,
            verId: entry.verId,
            source: entry.source,
            importHistory: entry.importHistory,
            categoryId: entry.categoryId,
            groupSlug: entry.groupSlug,
            error: message,
          }]);
        });
      return;
    }

    // RO imports — use SSE streaming
    importLawStreamSSE(
      entry.verId,
      entry.importHistory,
      entry.categoryId,
      // onProgress
      (event: ImportProgressEvent) => {
        setImportingEntries((prev) => prev.map(e => {
          if (e.id !== entry.id) return e;
          return {
            ...e,
            progress: {
              phase: event.phase,
              current: event.current ?? e.progress.current,
              total: event.total ?? e.progress.total,
              versionDate: event.version_date,
              message: event.message,
            },
          };
        }));
      },
      // onComplete
      () => {
        abortControllers.current.delete(entry.id);
        setImportingEntries((prev) => prev.filter(e => e.id !== entry.id));
        fetchData();
      },
      // onError
      (error) => {
        abortControllers.current.delete(entry.id);
        setImportingEntries((prev) => prev.filter(e => e.id !== entry.id));
        setFailedEntries((prev) => [...prev, {
          id: entry.id,
          title: entry.title,
          lawNumber: entry.lawNumber,
          verId: entry.verId,
          source: entry.source,
          importHistory: entry.importHistory,
          categoryId: entry.categoryId,
          groupSlug: entry.groupSlug,
          error: error.message,
        }]);
      },
      controller.signal,
    ).catch(async (err) => {
      // Handle network errors that occur during streaming
      abortControllers.current.delete(entry.id);

      if (err instanceof DOMException && err.name === "AbortError") {
        setImportingEntries((prev) => prev.filter(e => e.id !== entry.id));
        return; // User navigated away — don't show error
      }

      // The backend may have completed even though the SSE connection dropped.
      // Check by refreshing data — if the law appeared, it succeeded.
      try {
        const refreshed = await api.laws.library();
        setData(refreshed);
        // Check if a law with this verId now exists in the library
        const found = refreshed.laws.some(l => l.title.includes(entry.title.split(" — ")[0]?.trim() || entry.title));
        if (found) {
          setImportingEntries((prev) => prev.filter(e => e.id !== entry.id));
          return; // Import succeeded despite connection drop
        }
      } catch {
        // Could not check — fall through to error
      }

      const message = err instanceof Error ? err.message : "Network error during import";
      setImportingEntries((prev) => prev.filter(e => e.id !== entry.id));
      setFailedEntries((prev) => [...prev, {
        id: entry.id,
        title: entry.title,
        lawNumber: entry.lawNumber,
        verId: entry.verId,
        source: entry.source,
        importHistory: entry.importHistory,
        categoryId: entry.categoryId,
        groupSlug: entry.groupSlug,
        error: message,
      }]);
    });
  }

  function handleBackgroundImport(info: BackgroundImportInfo) {
    const entryId = `import-${++_importIdCounter}`;

    const entry: ImportingEntry = {
      id: entryId,
      title: info.title,
      lawNumber: "", // Will be populated from search result
      verId: info.verId,
      source: info.source,
      importHistory: info.importHistory,
      categoryId: info.categoryId,
      groupSlug: info.groupSlug,
      progress: {
        phase: "starting",
        current: 0,
        total: info.importHistory ? 0 : 1, // 0 means "unknown yet" for history imports
        message: "Starting import...",
      },
    };

    startStreamingImport(entry);
  }

  function handleRetry(failedEntry: FailedEntry) {
    // Remove from failed
    setFailedEntries((prev) => prev.filter(e => e.id !== failedEntry.id));

    // Create new importing entry from the failed one
    const newId = `import-${++_importIdCounter}`;
    const entry: ImportingEntry = {
      id: newId,
      title: failedEntry.title,
      lawNumber: failedEntry.lawNumber,
      verId: failedEntry.verId,
      source: failedEntry.source,
      importHistory: failedEntry.importHistory,
      categoryId: failedEntry.categoryId,
      groupSlug: failedEntry.groupSlug,
      progress: {
        phase: "starting",
        current: 0,
        total: failedEntry.importHistory ? 0 : 1,
        message: "Retrying import...",
      },
    };

    startStreamingImport(entry);
  }

  function handleDismiss(id: string) {
    setFailedEntries((prev) => prev.filter(e => e.id !== id));
    // Refresh new versions list so dismissed items reappear there
    setNewVersionsRefreshKey((k) => k + 1);
  }

  function importVersionsForLaw(entry: NewVersionEntry, verIds: string[]) {
    // Track this law_id as importing so it hides from new versions list
    setNewVersionImportingIds((prev) => new Set(prev).add(entry.law_id));

    // Import versions sequentially (oldest first for correct diffs)
    const sortedVerIds = entry.versions
      .filter((v) => verIds.includes(v.ver_id))
      .sort((a, b) => a.date_in_force.localeCompare(b.date_in_force))
      .map((v) => v.ver_id);

    const entryId = `newver-${entry.law_id}`;
    const importingEntry: ImportingEntry = {
      id: entryId,
      title: entry.title,
      lawNumber: entry.law_number,
      verId: sortedVerIds[0],
      source: entry.source as "ro" | "eu",
      importHistory: false,
      categoryId: null,
      groupSlug: null,
      progress: {
        phase: "version",
        current: 0,
        total: sortedVerIds.length,
        message: "Importing new version...",
      },
    };
    setImportingEntries((prev) => [...prev, importingEntry]);

    // Import sequentially
    (async () => {
      let imported = 0;
      for (const verId of sortedVerIds) {
        try {
          setImportingEntries((prev) => prev.map((e) =>
            e.id === entryId
              ? { ...e, verId, progress: { ...e.progress, current: imported, message: `Importing version ${imported + 1}/${sortedVerIds.length}...` } }
              : e
          ));
          await api.laws.importKnownVersion(entry.law_id, verId);
          imported++;
        } catch (err) {
          const message = err instanceof Error ? err.message : "Import failed";
          setImportingEntries((prev) => prev.filter((e) => e.id !== entryId));
          setNewVersionImportingIds((prev) => {
            const next = new Set(prev);
            next.delete(entry.law_id);
            return next;
          });
          setFailedEntries((prev) => [...prev, {
            id: entryId,
            title: entry.title,
            lawNumber: entry.law_number,
            verId,
            source: entry.source as "ro" | "eu",
            importHistory: false,
            categoryId: null,
            groupSlug: null,
            error: `${message} (imported ${imported}/${sortedVerIds.length})`,
          }]);
          fetchData();
          return;
        }
      }

      // All done
      setImportingEntries((prev) => prev.filter((e) => e.id !== entryId));
      setNewVersionImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(entry.law_id);
        return next;
      });
      setNewVersionsRefreshKey((k) => k + 1);
      fetchData();
    })();
  }

  function handleNewVersionImport(entry: NewVersionEntry, selectedVerIds: string[]) {
    importVersionsForLaw(entry, selectedVerIds);
  }

  function handleImportAllNewVersions(entries: NewVersionEntry[]) {
    for (const entry of entries) {
      const allVerIds = entry.versions.map((v) => v.ver_id);
      importVersionsForLaw(entry, allVerIds);
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
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Legal Library</h1>
          <p className="mt-1 text-gray-600">Browse Romanian laws with full version history</p>
        </div>
        {activeSuggestions.length > 0 && (
          <div className="flex gap-2">
            {bulkImporting ? (
              <span className="px-4 py-2 bg-indigo-100 text-indigo-700 text-sm font-medium rounded-lg">
                Importing {bulkProgress?.current || 0}/{bulkProgress?.total || activeSuggestions.length}...
              </span>
            ) : (
              <>
                <button
                  onClick={() => handleImportAll(false)}
                  className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors whitespace-nowrap"
                >
                  Import All — Current ({activeSuggestions.length})
                </button>
                <button
                  onClick={() => handleImportAll(true)}
                  className="px-4 py-2 bg-white text-indigo-600 border border-indigo-300 text-sm font-medium rounded-lg hover:bg-indigo-50 transition-colors whitespace-nowrap"
                >
                  Import All — With History
                </button>
              </>
            )}
          </div>
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
        onBackgroundImport={handleBackgroundImport}
      />

      {/* Import progress sections — between search and main list */}
      <ImportProgressSection
        importing={importingEntries}
        failed={failedEntries}
        onRetry={handleRetry}
        onDismiss={handleDismiss}
      />

      {/* New versions available for import */}
      <NewVersionsSection
        importingLawIds={newVersionImportingIds}
        onImport={handleNewVersionImport}
        onImportAll={handleImportAllNewVersions}
        refreshKey={newVersionsRefreshKey}
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
