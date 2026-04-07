"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { api, LibraryData, LibraryLaw, SuggestedLaw, BulkImportProgress, BulkImportResult, NewVersionEntry } from "@/lib/api";
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

  // Favorites
  const [favorites, setFavorites] = useState<Set<number>>(new Set());
  const [selectedView, setSelectedView] = useState<"all" | "favorites">("all");
  const [favoriteCategoryFilter, setFavoriteCategoryFilter] = useState<string | null>(null);

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

  // Active job-backed suggestion imports. Keyed by mapping_id so the existing
  // pendingImports map (which the UI already keys off) stays the source of
  // truth for display state — this map only tracks which job to poll.
  const [suggestionImportJobs, setSuggestionImportJobs] = useState<
    Map<number, { jobId: string; suggestion: SuggestedLaw }>
  >(new Map());

  // Import progress tracking. Entries are kept in state AND mirrored to
  // localStorage so a page refresh can rebuild the list — backend jobs survive
  // browser navigation, so the polling effect picks them right up again.
  const [importingEntries, setImportingEntries] = useState<ImportingEntry[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const stored = localStorage.getItem("themis_importing_entries");
      return stored ? (JSON.parse(stored) as ImportingEntry[]) : [];
    } catch { return []; }
  });
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
  // Abort controllers for the EU sync import path (RO imports are job-based
  // and don't need cancellation tied to the request).
  const abortControllers = useRef<Map<string, AbortController>>(new Map());

  // Category pick for suggestions without a predetermined category
  const [suggestionCategoryPick, setSuggestionCategoryPick] = useState<{
    suggestion: SuggestedLaw;
    importHistory: boolean;
  } | null>(null);

  // Add-law modal

  // Bulk import state. The job_id is what makes this resumable across page
  // refreshes — on mount we look for an active import_all_suggestions job and
  // adopt it. The polling effect below pulls live progress from /api/jobs.
  const [bulkImporting, setBulkImporting] = useState(false);
  const [bulkJobId, setBulkJobId] = useState<string | null>(null);
  const [bulkProgress, setBulkProgress] = useState<BulkImportProgress | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkImportResult | null>(null);

  function handleImportAll(importHistory: boolean) {
    setBulkResult(null);
    setBulkProgress(null);
    api.laws
      .startBulkImport(importHistory)
      .then(({ job_id, total }) => {
        setBulkJobId(job_id);
        setBulkImporting(true);
        setBulkProgress({
          current: 0,
          total,
          title: "",
          status: "starting",
        });
      })
      .catch(() => {
        setBulkImporting(false);
        setBulkProgress(null);
      });
  }

  // Resume an in-flight bulk import after a page refresh.
  useEffect(() => {
    let cancelled = false;
    api.jobs
      .list({ kind: "import_all_suggestions", active: true, limit: 1 })
      .then((res) => {
        if (cancelled || res.jobs.length === 0) return;
        setBulkJobId(res.jobs[0].id);
        setBulkImporting(true);
      })
      .catch(() => { /* ignore */ });
    return () => {
      cancelled = true;
    };
  }, []);

  // Poll the bulk-import job and reflect progress + final result into state.
  useEffect(() => {
    if (!bulkJobId) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const job = await api.jobs.get(bulkJobId);
        if (cancelled) return;
        if (job.status === "running" || job.status === "pending") {
          setBulkProgress({
            current: job.current ?? 0,
            total: job.total ?? 0,
            title: job.phase || "",
            status: "importing",
          });
          return;
        }
        if (job.status === "succeeded") {
          setBulkResult((job.result as BulkImportResult) ?? null);
        } else if (job.status === "failed") {
          setBulkResult({
            total: job.total ?? 0,
            imported: 0,
            failed: 0,
            skipped: 0,
            items: [],
          });
        }
        setBulkImporting(false);
        setBulkProgress(null);
        setBulkJobId(null);
        fetchData();
      } catch (err) {
        const statusCode = (err as { statusCode?: number }).statusCode;
        if (statusCode === 404) {
          setBulkImporting(false);
          setBulkProgress(null);
          setBulkJobId(null);
        }
      }
    };

    tick();
    const timer = setInterval(tick, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // fetchData is a stable useCallback declared below — safe to omit
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bulkJobId]);

  // Poll active suggestion-import jobs. On terminal status, drop the entry
  // from both maps and refresh the library so the new law shows up.
  const suggestionJobIds = useMemo(
    () =>
      Array.from(suggestionImportJobs.values())
        .map((v) => v.jobId)
        .sort()
        .join(","),
    [suggestionImportJobs]
  );

  useEffect(() => {
    if (!suggestionJobIds) return;
    let cancelled = false;
    const ids = suggestionJobIds.split(",").filter(Boolean);

    const tick = async () => {
      const results = await Promise.all(
        ids.map((id) =>
          api.jobs.get(id).then(
            (j) => ({ id, ok: true as const, job: j }),
            (err) => ({ id, ok: false as const, err })
          )
        )
      );
      if (cancelled) return;

      let needsRefresh = false;
      setSuggestionImportJobs((prev) => {
        const next = new Map(prev);
        for (const res of results) {
          // Find the mapping_id whose entry has this jobId.
          let mappingId: number | undefined;
          for (const [k, v] of next.entries()) {
            if (v.jobId === res.id) {
              mappingId = k;
              break;
            }
          }
          if (mappingId === undefined) continue;
          if (!res.ok) {
            const statusCode = (res.err as { statusCode?: number } | null)?.statusCode;
            if (statusCode === 404) {
              next.delete(mappingId);
              setPendingImports((p) => {
                const np = new Map(p);
                const cur = np.get(mappingId!);
                if (cur) np.set(mappingId!, { ...cur, error: "Job no longer exists" });
                return np;
              });
            }
            continue;
          }
          const job = res.job;
          if (job.status === "succeeded") {
            next.delete(mappingId);
            setPendingImports((p) => {
              const np = new Map(p);
              np.delete(mappingId!);
              return np;
            });
            needsRefresh = true;
          } else if (job.status === "failed") {
            next.delete(mappingId);
            const msg = job.error?.message || "Import failed";
            setPendingImports((p) => {
              const np = new Map(p);
              const cur = np.get(mappingId!);
              if (cur) np.set(mappingId!, { ...cur, error: msg });
              return np;
            });
          } else {
            // Running — surface phase as progress message.
            setPendingImports((p) => {
              const np = new Map(p);
              const cur = np.get(mappingId!);
              if (cur) {
                np.set(mappingId!, {
                  ...cur,
                  progress: {
                    phase: job.phase || "running",
                    current: job.current ?? undefined,
                    total: job.total ?? undefined,
                    message: job.phase || "Importing...",
                  },
                });
              }
              return np;
            });
          }
        }
        return next;
      });

      if (needsRefresh) fetchData();
    };

    tick();
    const timer = setInterval(tick, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // fetchData is a stable useCallback declared below — safe to omit
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestionJobIds]);

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

  // Mirror in-flight import entries to localStorage so a refresh can show
  // them again (the backend job is what's actually doing the work — the
  // polling effect below picks it back up).
  useEffect(() => {
    try {
      if (importingEntries.length > 0) {
        localStorage.setItem(
          "themis_importing_entries",
          JSON.stringify(importingEntries)
        );
      } else {
        localStorage.removeItem("themis_importing_entries");
      }
    } catch { /* ignore */ }
  }, [importingEntries]);

  // Centralized polling for all in-flight import jobs.
  //
  // This loop is what makes import progress survive page navigation: backend
  // Jobs are durable, so on every tick we pull each entry's latest state and
  // update the UI from it. When a job reaches a terminal state we either drop
  // the entry (success → refresh data) or move it to failedEntries.
  //
  // We extract the list of active job ids as a stable string so the effect
  // restarts only when the set of polled jobs actually changes.
  const activeJobIds = useMemo(
    () =>
      importingEntries
        .map((e) => e.jobId)
        .filter((id): id is string => id !== null)
        .sort()
        .join(","),
    [importingEntries]
  );

  useEffect(() => {
    if (!activeJobIds) return;
    let cancelled = false;
    const ids = activeJobIds.split(",").filter(Boolean);

    const tick = async () => {
      // Fetch all active jobs in parallel.
      const results = await Promise.all(
        ids.map((id) =>
          api.jobs.get(id).then(
            (j) => ({ id, ok: true as const, job: j }),
            (err) => ({ id, ok: false as const, err })
          )
        )
      );
      if (cancelled) return;

      const completed: { entryId: string; success: boolean; message: string }[] = [];

      setImportingEntries((prev) => {
        let next = prev;
        for (const res of results) {
          const entry = next.find((e) => e.jobId === res.id);
          if (!entry) continue;
          if (!res.ok) {
            const statusCode = (res.err as { statusCode?: number } | null)?.statusCode;
            if (statusCode === 404) {
              completed.push({ entryId: entry.id, success: false, message: "Job no longer exists" });
              next = next.filter((e) => e.id !== entry.id);
            }
            // Transient error: keep entry, try again next tick.
            continue;
          }
          const job = res.job;
          if (job.status === "succeeded") {
            completed.push({ entryId: entry.id, success: true, message: "" });
            next = next.filter((e) => e.id !== entry.id);
          } else if (job.status === "failed") {
            const msg = job.error?.message || "Import failed";
            completed.push({ entryId: entry.id, success: false, message: msg });
            next = next.filter((e) => e.id !== entry.id);
          } else {
            // Still running — merge progress into the entry.
            next = next.map((e) =>
              e.id === entry.id
                ? {
                    ...e,
                    progress: {
                      ...e.progress,
                      phase: job.phase || e.progress.phase,
                      current: job.current ?? e.progress.current,
                      total: job.total ?? e.progress.total,
                      message: job.phase || e.progress.message,
                    },
                  }
                : e
            );
          }
        }
        return next;
      });

      // Side effects after the state update.
      for (const c of completed) {
        if (c.success) {
          fetchData();
        } else {
          // Look up the entry's display info for the failed list.
          const entry = importingEntries.find((e) => e.id === c.entryId);
          if (entry) {
            setFailedEntries((prev) => [
              ...prev,
              {
                id: entry.id,
                title: entry.title,
                lawNumber: entry.lawNumber,
                verId: entry.verId,
                source: entry.source,
                importHistory: entry.importHistory,
                categoryId: entry.categoryId,
                groupSlug: entry.groupSlug,
                error: c.message,
              },
            ]);
          }
        }
      }
    };

    // Tick immediately, then every 1.5s.
    tick();
    const timer = setInterval(tick, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // We intentionally exclude importingEntries / fetchData from deps to keep
    // the loop stable; we use activeJobIds as the cache key.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeJobIds]);

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
      setFavorites(new Set(result.favorite_law_ids));
      setError(null);
    } catch {
      setError("Could not connect to the backend. Make sure the API server is running.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleFavorite = useCallback(async (lawId: number) => {
    const wasFavorite = favorites.has(lawId);
    // Optimistic update
    setFavorites((prev) => {
      const next = new Set(prev);
      if (wasFavorite) {
        next.delete(lawId);
      } else {
        next.add(lawId);
      }
      return next;
    });
    try {
      if (wasFavorite) {
        await api.laws.favoriteRemove(lawId);
      } else {
        await api.laws.favoriteAdd(lawId);
      }
    } catch {
      // Revert on error
      setFavorites((prev) => {
        const next = new Set(prev);
        if (wasFavorite) {
          next.add(lawId);
        } else {
          next.delete(lawId);
        }
        return next;
      });
    }
  }, [favorites]);

  function handleSelectFavorites(groupSlug: string | null) {
    setSelectedView("favorites");
    setFavoriteCategoryFilter(groupSlug);
    // Clear regular filters
    setSelectedGroup(null);
    setSelectedCategory(null);
    setSelectedStatus(null);
  }

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

  // Compute favorite counts by group slug for sidebar
  const favoriteCounts = useMemo(() => {
    if (!data) return new Map<string, number>();
    const counts = new Map<string, number>();
    for (const law of data.laws) {
      if (favorites.has(law.id) && law.category_group_slug) {
        counts.set(law.category_group_slug, (counts.get(law.category_group_slug) || 0) + 1);
      }
    }
    return counts;
  }, [data, favorites]);

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

    // EU suggestions still use the synchronous euImport endpoint — migrating
    // EU imports to jobs is a separate change.
    if (suggestion.celex_number) {
      const controller = new AbortController();
      const timeoutMs = importHistory ? 600_000 : 120_000;
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      api.laws
        .euImport(suggestion.celex_number, importHistory, controller.signal)
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
      return;
    }

    // RO suggestion: kick off a backend job. The polling effect on
    // suggestionImportJobs below transitions the pending entry on terminal
    // states, so a page refresh mid-import is safe.
    api.laws
      .startImportSuggestion(suggestion.id, importHistory)
      .then(({ job_id }) => {
        setSuggestionImportJobs((prev) => {
          const next = new Map(prev);
          next.set(suggestion.id, { jobId: job_id, suggestion });
          return next;
        });
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "Failed to start import";
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

  // === Background import — job-based for RO, sync for EU ===
  //
  // RO imports go through POST /api/laws/import/job → {job_id} and the
  // polling effect below picks them up. This is what makes the import
  // resumable across page refreshes — the work runs entirely on the backend.

  function startStreamingImport(entry: ImportingEntry) {
    // Add to importing list immediately so the user sees it.
    setImportingEntries((prev) => [...prev.filter(e => e.id !== entry.id), entry]);

    // EU imports don't have streaming — use simple fetch (still tied to the
    // request lifecycle, but with no progress to lose). Migrating EU imports
    // to jobs would be a separate change.
    if (entry.source === "eu") {
      const controller = new AbortController();
      abortControllers.current.set(entry.id, controller);
      api.laws.euImport(entry.verId, entry.importHistory, controller.signal)
        .then((res) => {
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

    // RO import: kick off a backend job and remember its id on the entry.
    api.laws
      .startImport(entry.verId, entry.importHistory, entry.categoryId)
      .then(({ job_id }) => {
        setImportingEntries((prev) =>
          prev.map((e) => (e.id === entry.id ? { ...e, jobId: job_id } : e))
        );
      })
      .catch((err) => {
        const message = err instanceof Error ? err.message : "Failed to start import";
        setImportingEntries((prev) => prev.filter((e) => e.id !== entry.id));
        setFailedEntries((prev) => [
          ...prev,
          {
            id: entry.id,
            title: entry.title,
            lawNumber: entry.lawNumber,
            verId: entry.verId,
            source: entry.source,
            importHistory: entry.importHistory,
            categoryId: entry.categoryId,
            groupSlug: entry.groupSlug,
            error: message,
          },
        ]);
      });
  }

  function handleBackgroundImport(info: BackgroundImportInfo) {
    const entryId = `import-${++_importIdCounter}`;

    const entry: ImportingEntry = {
      id: entryId,
      jobId: null,
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
      jobId: null,
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
      jobId: null,
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
          const code = (err as { code?: string } | null)?.code;
          const isPermanent = code === "eu_content_unavailable";

          if (isPermanent) {
            // CELLAR has no published text for this version yet — skip it,
            // record a non-retriable failed entry, and keep trying the rest.
            setFailedEntries((prev) => [...prev, {
              id: `${entryId}-skip-${verId}`,
              title: entry.title,
              lawNumber: entry.law_number,
              verId,
              source: entry.source as "ro" | "eu",
              importHistory: false,
              categoryId: null,
              groupSlug: null,
              error: message,
              permanent: true,
            }]);
            continue;
          }

          // Transient/unknown failure — stop the run and let the user retry.
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
        <div className="flex gap-2 items-center">
        {activeSuggestions.length > 0 && (
          <>
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
          </>
        )}
        </div>
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
          onSelectGroup={(slug) => { setSelectedView("all"); setSelectedGroup(slug); }}
          onSelectCategory={(slug) => { setSelectedView("all"); setSelectedCategory(slug); }}
          onSelectStatus={(status) => { setSelectedView("all"); setSelectedStatus(status); }}
          favoriteCounts={favoriteCounts}
          selectedView={selectedView}
          favoriteCategoryFilter={favoriteCategoryFilter}
          onSelectFavorites={handleSelectFavorites}
        />

        {/* Main content */}
        <div className="flex-1 p-5">
          <StatsCards
            totalLaws={filteredStats.total_laws}
            totalVersions={filteredStats.total_versions}
            lastImported={filteredStats.last_imported}
          />

          {selectedView === "favorites" ? (
            /* FAVORITES VIEW */
            <>
              <div className="mb-4">
                <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 text-pink-500">
                    <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0112 5.052 5.5 5.5 0 0116.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.219l-.022.012-.007.004-.003.001a.752.752 0 01-.704 0l-.003-.001z" />
                  </svg>
                  Favorites
                </h2>
                <p className="text-sm text-gray-500">
                  Showing {
                    favoriteCategoryFilter
                      ? data.laws.filter((l) => favorites.has(l.id) && l.category_group_slug === favoriteCategoryFilter).length
                      : favorites.size
                  } favorited law{(favoriteCategoryFilter
                      ? data.laws.filter((l) => favorites.has(l.id) && l.category_group_slug === favoriteCategoryFilter).length
                      : favorites.size) !== 1 ? "s" : ""}
                </p>
              </div>
              {favorites.size === 0 ? (
                <div className="text-center py-12">
                  <h3 className="text-lg font-medium text-gray-900 mb-2">No favorited laws yet</h3>
                  <p className="text-gray-600">Click the heart icon on any law to add it here.</p>
                </div>
              ) : (
                data.groups
                  .filter((g) => {
                    if (favoriteCategoryFilter && g.slug !== favoriteCategoryFilter) return false;
                    return data.laws.some((l) => favorites.has(l.id) && l.category_group_slug === g.slug);
                  })
                  .map((g) => {
                    const favLaws = data.laws.filter(
                      (l) => favorites.has(l.id) && l.category_group_slug === g.slug
                    );
                    return (
                      <CategoryGroupSection
                        key={g.slug}
                        groupSlug={g.slug}
                        groupName={g.name_en}
                        colorHex={g.color_hex}
                        categories={g.categories}
                        laws={favLaws}
                        suggestedLaws={[]}
                        pendingImports={[]}
                        defaultExpanded={true}
                        onDelete={fetchData}
                        favoriteIds={favorites}
                        onToggleFavorite={toggleFavorite}
                      />
                    );
                  })
              )}
            </>
          ) : (
            <>
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
                  categories={g.categories}
                  laws={laws}
                  suggestedLaws={suggestions}
                  pendingImports={pending}
                  defaultExpanded={!!selectedGroup || pending.length > 0}
                  onAssign={setAssigningLawId}
                  onDelete={fetchData}
                  onImportSuggestion={handleImportSuggestion}
                  onDismissPendingError={dismissPendingError}
                  favoriteIds={favorites}
                  onToggleFavorite={toggleFavorite}
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
                  categories={g.categories}
                  laws={[]}
                  suggestedLaws={suggestions}
                  pendingImports={[]}
                  defaultExpanded={true}
                  onImportSuggestion={handleImportSuggestion}
                  onDismissPendingError={dismissPendingError}
                  favoriteIds={favorites}
                  onToggleFavorite={toggleFavorite}
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
            favoriteIds={favorites}
            onToggleFavorite={toggleFavorite}
          />
            </>
          )}
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
