"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

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
}

const ACT_TYPES = [
  { label: "All types", value: "" },
  { label: "Lege", value: "lege" },
  { label: "OUG", value: "oug" },
  { label: "HG", value: "hg" },
  { label: "Ordin", value: "ordin" },
  { label: "Regulament", value: "regulament" },
  { label: "Directivă EU", value: "directiva_eu" },
  { label: "Decizie", value: "decizie" },
];

const STATUS_OPTIONS = [
  { label: "In force only", value: "only_in_force" },
  { label: "All (incl. repealed)", value: "all" },
  { label: "Only repealed", value: "only_repealed" },
];

const DOC_TYPE_COLORS: Record<string, string> = {
  LEGE: "bg-blue-100 text-blue-800",
  OUG: "bg-amber-100 text-amber-800",
  HG: "bg-indigo-100 text-indigo-800",
  ORDIN: "bg-purple-100 text-purple-800",
  DECIZIE: "bg-teal-100 text-teal-800",
};

export default function SearchImportForm() {
  const router = useRouter();

  // Search state
  const [keyword, setKeyword] = useState("");
  const [docType, setDocType] = useState("");
  const [lawNumber, setLawNumber] = useState("");
  const [year, setYear] = useState("");
  const [emitent, setEmitent] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [includeRepealed, setIncludeRepealed] = useState("only_in_force");
  const [showFilters, setShowFilters] = useState(false);

  // Results state
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Import state
  const [importHistory, setImportHistory] = useState(true);
  const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
  const [importedIds, setImportedIds] = useState<Map<string, number>>(new Map());
  const [importErrors, setImportErrors] = useState<Map<string, string>>(new Map());

  // Emitent autocomplete
  const [emitentSuggestions, setEmitentSuggestions] = useState<string[]>([]);
  const [showEmitentDropdown, setShowEmitentDropdown] = useState(false);
  const emitentTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emitentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (emitentRef.current && !emitentRef.current.contains(e.target as Node)) {
        setShowEmitentDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

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
    setEmitent(value);
    if (emitentTimeout.current) clearTimeout(emitentTimeout.current);
    emitentTimeout.current = setTimeout(() => fetchEmitents(value), 500);
  }

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    setSearching(true);
    setSearchError(null);

    const params = new URLSearchParams();
    if (keyword) params.set("keyword", keyword);
    if (docType) params.set("doc_type", docType);
    if (lawNumber) params.set("number", lawNumber);
    if (year) params.set("year", year);
    if (emitent) params.set("emitent", emitent);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    params.set("include_repealed", includeRepealed);

    try {
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

  async function handleImport(verId: string) {
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

  function handleClearFilters() {
    setKeyword("");
    setDocType("");
    setLawNumber("");
    setYear("");
    setEmitent("");
    setDateFrom("");
    setDateTo("");
    setIncludeRepealed("only_in_force");
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Search & Import Laws</h2>

      {/* Keyword bar */}
      <form onSubmit={handleSearch} className="space-y-3">
        <div className="flex gap-3">
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder='Search by keyword, name, or topic...'
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            disabled={searching}
          />
          <button
            type="submit"
            disabled={searching}
            className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
          >
            {searching ? "Searching..." : "Search"}
          </button>
        </div>

        {/* Advanced filters toggle */}
        <button
          type="button"
          onClick={() => setShowFilters(!showFilters)}
          className="text-sm text-blue-600 hover:text-blue-800 flex items-center gap-1"
        >
          <span className="text-xs">{showFilters ? "▲" : "▼"}</span>
          Advanced Filters
        </button>

        {/* Collapsible filters */}
        {showFilters && (
          <div className="p-4 bg-gray-50 rounded-lg space-y-3">
            <div className="grid grid-cols-3 gap-3">
              {/* Act Type */}
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Act Type</label>
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                >
                  {ACT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
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
                  value={emitent}
                  onChange={(e) => handleEmitentChange(e.target.value)}
                  onFocus={() => fetchEmitents(emitent)}
                  placeholder="Search issuers..."
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
                {showEmitentDropdown && emitentSuggestions.length > 0 && (
                  <div className="absolute z-50 w-full mt-1 bg-white rounded-md border border-gray-200 shadow-lg max-h-48 overflow-y-auto">
                    {emitentSuggestions.map((e) => (
                      <button
                        key={e}
                        type="button"
                        onClick={() => {
                          setEmitent(e);
                          setShowEmitentDropdown(false);
                        }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 border-b border-gray-50 last:border-b-0"
                      >
                        {e}
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
        <div className="mt-4 border border-gray-200 rounded-lg overflow-hidden">
          {/* Results header */}
          <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
            <span className="text-sm text-gray-600">{total} result{total !== 1 ? "s" : ""} found</span>
            <label className="text-sm text-gray-700 flex items-center gap-2">
              <input
                type="checkbox"
                checked={importHistory}
                onChange={(e) => setImportHistory(e.target.checked)}
                className="rounded border-gray-300"
              />
              Import all historical versions
            </label>
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
                      <button
                        onClick={() => handleImport(r.ver_id)}
                        disabled={isImporting}
                        className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                      >
                        {isImporting ? "Importing..." : "Import"}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* No results message — shown after any search attempt with no results */}
      {!searching && results.length === 0 && total === 0 && searchError === null && (keyword || docType || lawNumber || year || emitent || dateFrom || dateTo) && (
        <div className="mt-4 text-center py-6 text-sm text-gray-500">
          No results found. Try different filters or keywords.
        </div>
      )}
    </div>
  );
}
