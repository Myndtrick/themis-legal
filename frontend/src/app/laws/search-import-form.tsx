"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SearchResult {
  ver_id: string;
  title: string;
  doc_type: string;
  number: string;
  date: string;
  date_iso: string | null;
  issuer: string;
  description: string;
  already_imported: boolean;
  local_law_id: number | null;
  source?: string;
}

interface FilterOption {
  value: string;
  label: string;
}

const EU_DOC_TYPES: FilterOption[] = [
  { value: "directive", label: "Directive" },
  { value: "regulation", label: "Regulation" },
  { value: "eu_decision", label: "Decision" },
  { value: "treaty", label: "Treaty" },
];

// Fallback doc types used until the dynamic list loads from the API
const DEFAULT_ACT_TYPES: FilterOption[] = [
  { label: "LEGE", value: "1" },
  { label: "ORDONANȚĂ DE URGENȚĂ", value: "18" },
  { label: "ORDONANȚĂ", value: "13" },
  { label: "HOTĂRÂRE", value: "2" },
  { label: "ORDIN", value: "5" },
  { label: "DECIZIE", value: "17" },
  { label: "DECRET", value: "3" },
  { label: "CONSTITUȚIE", value: "22" },
  { label: "COD", value: "170" },
  { label: "NORMĂ", value: "11" },
  { label: "REGULAMENT", value: "12" },
  { label: "DIRECTIVĂ", value: "113" },
];

const STATUS_OPTIONS = [
  { label: "In force only", value: "only_in_force" },
  { label: "All (incl. repealed)", value: "all" },
  { label: "Only repealed", value: "only_repealed" },
];

const DOC_TYPE_COLORS: Record<string, string> = {
  CONSTITUTIE: "bg-red-100 text-red-800",
  "CONSTITUȚIE": "bg-red-100 text-red-800",
  COD: "bg-emerald-100 text-emerald-800",
  LEGE: "bg-blue-100 text-blue-800",
  OG: "bg-orange-100 text-orange-800",
  "ORDONANȚĂ": "bg-orange-100 text-orange-800",
  OUG: "bg-amber-100 text-amber-800",
  "ORDONANȚĂ DE URGENȚĂ": "bg-amber-100 text-amber-800",
  HG: "bg-indigo-100 text-indigo-800",
  "HOTĂRÂRE": "bg-indigo-100 text-indigo-800",
  DECRET: "bg-rose-100 text-rose-800",
  ORDIN: "bg-purple-100 text-purple-800",
  NORMA: "bg-cyan-100 text-cyan-800",
  "NORMĂ": "bg-cyan-100 text-cyan-800",
  DECIZIE: "bg-teal-100 text-teal-800",
};

export default function SearchImportForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Pre-fill from URL query params (e.g. /laws?number=85&year=2014)
  const initialNumber = searchParams.get("number") || "";
  const initialYear = searchParams.get("year") || "";

  // Source toggle: all | ro | eu
  const [source, setSource] = useState<"all" | "ro" | "eu">("all");

  // Filter options fetched from the API
  const [actTypes, setActTypes] = useState<FilterOption[]>(DEFAULT_ACT_TYPES);

  // Search state
  const [selectedDocTypes, setSelectedDocTypes] = useState<Set<string>>(new Set());
  const [docTypeSearch, setDocTypeSearch] = useState("");
  const [showDocTypeDropdown, setShowDocTypeDropdown] = useState(false);
  const docTypeRef = useRef<HTMLDivElement>(null);

  const [keyword, setKeyword] = useState("");
  const [lawNumber, setLawNumber] = useState(initialNumber);
  const [year, setYear] = useState(initialYear);
  const [emitent, setEmitent] = useState("");
  const [emitentLabel, setEmitentLabel] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [includeRepealed, setIncludeRepealed] = useState("only_in_force");
  const [showFilters, setShowFilters] = useState(!!(initialNumber || initialYear));

  // Results state
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Import state
  const [pendingImportId, setPendingImportId] = useState<string | null>(null);
  const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
  const [importedIds, setImportedIds] = useState<Map<string, number>>(new Map());
  const [importErrors, setImportErrors] = useState<Map<string, string>>(new Map());

  // Direct URL import
  const [urlImporting, setUrlImporting] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [urlImportedId, setUrlImportedId] = useState<number | null>(null);
  const [urlPendingChoice, setUrlPendingChoice] = useState(false);

  const detectedUrl = keyword.match(
    /legislatie\.just\.ro\/Public\/DetaliiDocument(?:Afis)?\/(\d+)/
  );

  // Emitent autocomplete
  const [emitentSuggestions, setEmitentSuggestions] = useState<FilterOption[]>([]);
  const [showEmitentDropdown, setShowEmitentDropdown] = useState(false);
  const emitentTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emitentRef = useRef<HTMLDivElement>(null);

  // Fetch filter options on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/laws/filter-options`)
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (data?.doc_types?.length) {
          setActTypes(data.doc_types);
        }
      })
      .catch(() => { /* keep defaults */ });
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (emitentRef.current && !emitentRef.current.contains(e.target as Node)) {
        setShowEmitentDropdown(false);
      }
      if (docTypeRef.current && !docTypeRef.current.contains(e.target as Node)) {
        setShowDocTypeDropdown(false);
      }
      // Close import dropdown if clicking outside
      if (pendingImportId) {
        const target = e.target as HTMLElement;
        if (!target.closest("[data-import-dropdown]")) {
          setPendingImportId(null);
        }
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [pendingImportId]);

  const fetchEmitents = useCallback(async (q: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/laws/emitents?q=${encodeURIComponent(q)}`);
      if (res.ok) {
        const data = await res.json();
        setEmitentSuggestions(data.emitents);
        setShowEmitentDropdown(true);
      }
    } catch {
      // Silently fail
    }
  }, []);

  function handleEmitentChange(value: string) {
    setEmitentLabel(value);
    // If user clears the field, clear the code too
    if (!value) setEmitent("");
    if (emitentTimeout.current) clearTimeout(emitentTimeout.current);
    emitentTimeout.current = setTimeout(() => fetchEmitents(value), 500);
  }

  function toggleDocType(value: string) {
    setSelectedDocTypes((prev) => {
      const next = new Set(prev);
      if (next.has(value)) {
        next.delete(value);
      } else {
        next.add(value);
      }
      return next;
    });
  }

  // Visible doc types based on source selection
  const visibleDocTypes: FilterOption[] =
    source === "eu" ? EU_DOC_TYPES :
    source === "ro" ? actTypes :
    [...actTypes, ...EU_DOC_TYPES];

  // Filtered doc types list based on search
  const filteredActTypes = docTypeSearch
    ? visibleDocTypes.filter((t) => t.label.toLowerCase().includes(docTypeSearch.toLowerCase()))
    : visibleDocTypes;

  // Labels for selected types (for displaying chips)
  const selectedDocTypeLabels = visibleDocTypes.filter((t) => selectedDocTypes.has(t.value));

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    setSearching(true);
    setSearchError(null);

    try {
      if (source === "eu") {
        const euResults = await api.laws.euSearch({
          keyword: keyword || undefined,
          doc_type: selectedDocTypes.size === 1 ? [...selectedDocTypes][0] : undefined,
          year: year || undefined,
          number: lawNumber || undefined,
        });
        setResults(euResults.map((r) => ({
          ver_id: r.celex,
          title: r.title,
          doc_type: r.doc_type,
          number: r.celex,
          date: r.date,
          date_iso: r.date,
          issuer: "European Union",
          description: "",
          already_imported: r.already_imported,
          local_law_id: null,
          source: "eu" as const,
        })));
        setTotal(euResults.length);
        setSearching(false);
        return;
      }

      const params = new URLSearchParams();
      if (keyword) params.set("keyword", keyword);
      if (selectedDocTypes.size > 0) {
        params.set("doc_type", Array.from(selectedDocTypes).join(","));
      }
      if (lawNumber) params.set("number", lawNumber);
      if (year) params.set("year", year);
      if (emitent) params.set("emitent", emitent);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      params.set("include_repealed", includeRepealed);
      if (source === "ro") params.append("source", "ro");

      const res = await fetch(`${API_BASE}/api/laws/advanced-search?${params}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Search failed (${res.status})`);
      }
      const data = await res.json();
      setResults(data.results);
      setTotal(data.total);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Search failed");
      setResults([]);
      setTotal(0);
    } finally {
      setSearching(false);
    }
  }

  // Auto-search when pre-filled from URL query params
  const autoSearched = useRef(false);
  useEffect(() => {
    if (!autoSearched.current && (initialNumber || initialYear)) {
      autoSearched.current = true;
      handleSearch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialNumber, initialYear]);

  async function handleImport(verId: string, importHistory: boolean) {
    setPendingImportId(null);

    const result = results.find((r) => r.ver_id === verId);
    if (result && result.source === "eu") {
      setImportingIds((prev) => new Set(prev).add(verId));
      try {
        const res = await api.laws.euImport(verId, importHistory);
        setImportedIds((prev) => new Map(prev).set(verId, res.law_id));
        router.refresh();
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : "Import failed";
        setImportErrors((prev) => new Map(prev).set(verId, message));
      } finally {
        setImportingIds((prev) => { const next = new Set(prev); next.delete(verId); return next; });
      }
      return;
    }

    setImportingIds((prev) => new Set(prev).add(verId));
    setImportErrors((prev) => {
      const next = new Map(prev);
      next.delete(verId);
      return next;
    });

    try {
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Import failed");
      }
      setImportedIds((prev) => new Map(prev).set(verId, data.law_id));
      router.refresh();
    } catch (err) {
      setImportErrors((prev) => {
        const next = new Map(prev);
        next.set(verId, err instanceof Error ? err.message : "Import failed");
        return next;
      });
    } finally {
      setImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(verId);
        return next;
      });
    }
  }

  async function handleUrlImport(importHistory: boolean) {
    if (!detectedUrl) return;
    const verId = detectedUrl[1];
    setUrlPendingChoice(false);
    setUrlImporting(true);
    setUrlError(null);
    setUrlImportedId(null);

    try {
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Import failed");
      setUrlImportedId(data.law_id);
      router.refresh();
    } catch (err) {
      setUrlError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setUrlImporting(false);
    }
  }

  function handleClearFilters() {
    setKeyword("");
    setSelectedDocTypes(new Set());
    setDocTypeSearch("");
    setLawNumber("");
    setYear("");
    setEmitent("");
    setEmitentLabel("");
    setDateFrom("");
    setDateTo("");
    setIncludeRepealed("only_in_force");
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Search & Import Laws</h2>

      {/* Source toggle */}
      <div className="flex gap-1 mb-3 p-1 bg-neutral-100 dark:bg-neutral-800 rounded-lg w-fit">
        {(["all", "ro", "eu"] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => { setSource(s); setResults([]); }}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${
              source === s
                ? "bg-white dark:bg-neutral-700 shadow-sm font-medium"
                : "text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300"
            }`}
          >
            {s === "all" ? "All" : s === "ro" ? "Romanian" : "EU"}
          </button>
        ))}
      </div>

      {/* Keyword bar */}
      <form onSubmit={handleSearch} className="space-y-3">
        <div className="flex gap-3">
          <input
            type="text"
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value);
              setUrlImportedId(null);
              setUrlError(null);
              setUrlPendingChoice(false);
            }}
            placeholder='Search by keyword, name, or paste a legislatie.just.ro link...'
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            disabled={searching || urlImporting}
          />
          {detectedUrl ? (
            <div className="relative" data-import-dropdown>
              <button
                type="button"
                onClick={() => setUrlPendingChoice(true)}
                disabled={urlImporting}
                className="rounded-md bg-green-600 px-5 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
              >
                {urlImporting ? "Importing..." : "Import from link"}
              </button>
              {urlPendingChoice && !urlImporting && (
                <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg border border-gray-200 shadow-lg p-3 w-56">
                  <p className="text-xs text-gray-500 mb-2">What to import?</p>
                  <button
                    type="button"
                    onClick={() => handleUrlImport(false)}
                    className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                  >
                    Current version only
                  </button>
                  <button
                    type="button"
                    onClick={() => handleUrlImport(true)}
                    className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                  >
                    All historical versions
                  </button>
                  <button
                    type="button"
                    onClick={() => setUrlPendingChoice(false)}
                    className="w-full text-left px-3 py-1.5 text-xs rounded-md hover:bg-gray-50 text-gray-400 mt-1"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button
              type="submit"
              disabled={searching}
              className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
            >
              {searching ? "Searching..." : "Search"}
            </button>
          )}
        </div>

        {/* URL import feedback */}
        {detectedUrl && urlImportedId && (
          <div className="flex items-center gap-3 p-3 bg-green-50 border border-green-200 rounded-md">
            <span className="text-sm text-green-700">Imported successfully!</span>
            <a
              href={`/laws/${urlImportedId}`}
              className="text-sm text-blue-600 hover:text-blue-800 font-medium"
            >
              View law
            </a>
          </div>
        )}
        {detectedUrl && urlError && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-700">{urlError}</p>
          </div>
        )}

        {/* Advanced filters toggle */}
        <button
          type="button"
          onClick={() => setShowFilters(!showFilters)}
          className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
        >
          <span className="text-xs">{showFilters ? "▲" : "▼"}</span>
          Advanced Filters
          {selectedDocTypes.size > 0 && (
            <span className="ml-1 text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">
              {selectedDocTypes.size}
            </span>
          )}
        </button>

        {/* Collapsible filters */}
        {showFilters && (
          <div className="p-4 bg-gray-50 rounded-lg space-y-3">
            <div className="grid grid-cols-3 gap-3">
              {/* Act Type — searchable multi-select */}
              <div ref={docTypeRef} className="relative">
                <label className="block text-xs font-semibold text-gray-600 mb-1">Act Type</label>
                <div
                  className="w-full min-h-[38px] rounded-md border border-gray-300 px-2 py-1.5 bg-white cursor-text flex flex-wrap gap-1 items-center"
                  onClick={() => setShowDocTypeDropdown(true)}
                >
                  {selectedDocTypeLabels.map((t) => (
                    <span
                      key={t.value}
                      className="inline-flex items-center gap-1 bg-blue-100 text-blue-800 text-xs px-2 py-0.5 rounded"
                    >
                      {t.label}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleDocType(t.value);
                        }}
                        className="text-blue-500 hover:text-blue-700 font-bold leading-none"
                      >
                        x
                      </button>
                    </span>
                  ))}
                  <input
                    type="text"
                    value={docTypeSearch}
                    onChange={(e) => {
                      setDocTypeSearch(e.target.value);
                      setShowDocTypeDropdown(true);
                    }}
                    onFocus={() => setShowDocTypeDropdown(true)}
                    placeholder={selectedDocTypes.size === 0 ? "All types — search..." : ""}
                    className="flex-1 min-w-[80px] text-sm outline-none bg-transparent py-0.5"
                  />
                </div>

                {showDocTypeDropdown && (
                  <div className="absolute z-50 w-full mt-1 bg-white rounded-md border border-gray-200 shadow-lg max-h-60 overflow-y-auto">
                    {selectedDocTypes.size > 0 && (
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedDocTypes(new Set());
                          setDocTypeSearch("");
                        }}
                        className="w-full text-left px-3 py-1.5 text-xs text-gray-400 hover:bg-gray-50 border-b border-gray-100"
                      >
                        Clear selection
                      </button>
                    )}
                    {filteredActTypes.length === 0 && (
                      <div className="px-3 py-2 text-sm text-gray-400">No matching types</div>
                    )}
                    {filteredActTypes.map((t) => {
                      const isSelected = selectedDocTypes.has(t.value);
                      return (
                        <button
                          key={t.value}
                          type="button"
                          onClick={() => toggleDocType(t.value)}
                          className={`w-full text-left px-3 py-1.5 text-sm border-b border-gray-50 last:border-b-0 flex items-center gap-2 ${
                            isSelected ? "bg-blue-50 text-blue-800" : "hover:bg-gray-50 text-gray-700"
                          }`}
                        >
                          <span className={`w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center text-xs ${
                            isSelected ? "bg-blue-600 border-blue-600 text-white" : "border-gray-300"
                          }`}>
                            {isSelected && "✓"}
                          </span>
                          {t.label}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Law Number */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Law Number</label>
                <input
                  type="text"
                  value={lawNumber}
                  onChange={(e) => setLawNumber(e.target.value.replace(/\D/g, ""))}
                  placeholder="e.g. 31"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>

              {/* Year */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Year</label>
                <input
                  type="text"
                  value={year}
                  onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
                  placeholder="e.g. 1990"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              {/* Emitent */}
              <div ref={emitentRef} className="relative">
                <label className="block text-xs font-semibold text-gray-600 mb-1">Emitent</label>
                <input
                  type="text"
                  value={emitentLabel}
                  onChange={(e) => handleEmitentChange(e.target.value)}
                  onFocus={() => fetchEmitents(emitentLabel)}
                  placeholder="Search issuers..."
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
                {showEmitentDropdown && emitentSuggestions.length > 0 && (
                  <div className="absolute z-50 w-full mt-1 bg-white rounded-md border border-gray-200 shadow-lg max-h-48 overflow-y-auto">
                    {emitentSuggestions.map((e) => (
                      <button
                        key={e.value}
                        type="button"
                        onClick={() => {
                          setEmitent(e.value);
                          setEmitentLabel(e.label);
                          setShowEmitentDropdown(false);
                        }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 border-b border-gray-50 last:border-b-0"
                      >
                        {e.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Date From */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">In Force From</label>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>

              {/* Date To */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Signed Before</label>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="flex items-center justify-between">
              {/* Status filter */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Status</label>
                <select
                  value={includeRepealed}
                  onChange={(e) => setIncludeRepealed(e.target.value)}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>

              {/* Clear filters */}
              <button
                type="button"
                onClick={handleClearFilters}
                className="text-sm text-gray-500 hover:text-gray-700 border border-gray-300 rounded-md px-3 py-1.5"
              >
                Clear Filters
              </button>
            </div>
          </div>
        )}
      </form>

      {/* Search error */}
      {searchError && (
        <div className="mt-4 rounded-md bg-red-50 border border-red-200 p-3">
          <p className="text-sm text-red-700">{searchError}</p>
        </div>
      )}

      {/* Results */}
      {results.length > 0 && (
        <div className="mt-4 border border-gray-200 rounded-lg overflow-visible">
          {/* Results header */}
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
            <span className="text-sm text-gray-600">{total} result{total !== 1 ? "s" : ""} found</span>
          </div>

          {/* Result rows */}
          {results.map((r) => {
            const isImporting = importingIds.has(r.ver_id);
            const justImported = importedIds.has(r.ver_id);
            const isAlreadyImported = r.already_imported || justImported;
            const localId = r.local_law_id || importedIds.get(r.ver_id);
            const error = importErrors.get(r.ver_id);
            const colorClass = DOC_TYPE_COLORS[r.doc_type] || "bg-gray-100 text-gray-600";

            return (
              <div key={r.ver_id} className="px-4 py-3 border-b border-gray-100 last:border-b-0">
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${
                        r.source === "eu"
                          ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                          : "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
                      }`}>
                        {r.source === "eu" ? "EU" : "RO"}
                      </span>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${colorClass}`}>
                        {r.doc_type || "DOC"}
                      </span>
                      <span className="text-sm font-semibold text-gray-900">
                        nr. {r.number} din {r.date}
                      </span>
                    </div>
                    <p className="text-sm text-gray-600 truncate">{r.description || r.title}</p>
                    {r.issuer && (
                      <p className="text-xs text-gray-400 mt-0.5">Emitent: {r.issuer}</p>
                    )}
                    {error && (
                      <p className="text-xs text-red-600 mt-1">{error}</p>
                    )}
                  </div>
                  <div className="ml-4 shrink-0">
                    {isAlreadyImported ? (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-green-600 bg-green-50 px-2 py-1 rounded">
                          Imported
                        </span>
                        {localId && (
                          <a
                            href={`/laws/${localId}`}
                            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
                          >
                            View
                          </a>
                        )}
                      </div>
                    ) : (
                      <div className="relative" data-import-dropdown>
                        <button
                          onClick={() => setPendingImportId(r.ver_id)}
                          disabled={isImporting}
                          className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                        >
                          {isImporting ? "Importing..." : "Import"}
                        </button>
                        {pendingImportId === r.ver_id && !isImporting && (
                          <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg border border-gray-200 shadow-lg p-3 w-56">
                            <p className="text-xs text-gray-500 mb-2">What to import?</p>
                            <button
                              onClick={() => handleImport(r.ver_id, false)}
                              className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                            >
                              Current version only
                            </button>
                            <button
                              onClick={() => handleImport(r.ver_id, true)}
                              className="w-full text-left px-3 py-2 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                            >
                              All historical versions
                            </button>
                            <button
                              onClick={() => setPendingImportId(null)}
                              className="w-full text-left px-3 py-1.5 text-xs rounded-md hover:bg-gray-50 text-gray-400 mt-1"
                            >
                              Cancel
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* No results message — shown after any search attempt with no results */}
      {!searching && results.length === 0 && total === 0 && searchError === null && (keyword || selectedDocTypes.size > 0 || lawNumber || year || emitent || dateFrom || dateTo) && (
        <div className="mt-4 text-center py-6 text-sm text-gray-500">
          No results found. Try different filters or keywords.
        </div>
      )}
    </div>
  );
}
