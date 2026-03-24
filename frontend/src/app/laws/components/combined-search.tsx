"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { LocalSearchResult } from "@/lib/api";
import Link from "next/link";

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

interface FilterOption {
  value: string;
  label: string;
}

const DEFAULT_ACT_TYPES: FilterOption[] = [
  { label: "LEGE", value: "1" },
  { label: "ORDONANȚĂ DE URGENȚĂ", value: "18" },
  { label: "ORDONANȚĂ", value: "13" },
  { label: "HOTĂRÂRE", value: "2" },
  { label: "ORDIN", value: "5" },
];

const DOC_TYPE_COLORS: Record<string, string> = {
  LEGE: "bg-blue-100 text-blue-800",
  "ORDONANȚĂ DE URGENȚĂ": "bg-amber-100 text-amber-800",
  OUG: "bg-amber-100 text-amber-800",
  "ORDONANȚĂ": "bg-orange-100 text-orange-800",
  OG: "bg-orange-100 text-orange-800",
  "HOTĂRÂRE": "bg-indigo-100 text-indigo-800",
  HG: "bg-indigo-100 text-indigo-800",
  ORDIN: "bg-purple-100 text-purple-800",
  DECIZIE: "bg-teal-100 text-teal-800",
  DECRET: "bg-rose-100 text-rose-800",
  "CONSTITUȚIE": "bg-red-100 text-red-800",
  COD: "bg-emerald-100 text-emerald-800",
};

const STATE_COLORS: Record<string, string> = {
  actual: "bg-green-100 text-green-800",
  republished: "bg-blue-100 text-blue-800",
  amended: "bg-yellow-100 text-yellow-800",
  deprecated: "bg-red-100 text-red-800",
};

interface CombinedSearchProps {
  onImportComplete: () => void;
}

export default function CombinedSearch({ onImportComplete }: CombinedSearchProps) {
  const router = useRouter();
  const [keyword, setKeyword] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Local search
  const [localResults, setLocalResults] = useState<LocalSearchResult[]>([]);
  const localTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // External search
  const [externalResults, setExternalResults] = useState<SearchResult[]>([]);
  const [externalTotal, setExternalTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Filters
  const [selectedDocType, setSelectedDocType] = useState("");
  const [lawNumber, setLawNumber] = useState("");
  const [year, setYear] = useState("");

  // Import state
  const [pendingImportId, setPendingImportId] = useState<string | null>(null);
  const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
  const [importedIds, setImportedIds] = useState<Set<string>>(new Set());

  // URL detection
  const detectedUrl = keyword.match(
    /legislatie\.just\.ro\/Public\/DetaliiDocument(?:Afis)?\/(\d+)/
  );

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowResults(false);
        setPendingImportId(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Local search as you type
  const doLocalSearch = useCallback(async (q: string) => {
    if (q.length < 3) {
      setLocalResults([]);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/laws/local-search?q=${encodeURIComponent(q)}`);
      if (res.ok) {
        const data = await res.json();
        setLocalResults(data.results);
      }
    } catch { /* silent */ }
  }, []);

  function handleInputChange(value: string) {
    setKeyword(value);
    setShowResults(true);
    if (localTimeout.current) clearTimeout(localTimeout.current);
    localTimeout.current = setTimeout(() => doLocalSearch(value), 300);
  }

  // External search
  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!keyword.trim() && !lawNumber && !year) return;
    setSearching(true);
    setSearchError(null);
    setShowResults(true);

    const params = new URLSearchParams();
    if (keyword) params.set("keyword", keyword);
    if (selectedDocType) params.set("doc_type", selectedDocType);
    if (lawNumber) params.set("number", lawNumber);
    if (year) params.set("year", year);
    params.set("include_repealed", "only_in_force");

    try {
      const res = await fetch(`${API_BASE}/api/laws/advanced-search?${params}`);
      if (!res.ok) throw new Error(`Search failed (${res.status})`);
      const data = await res.json();
      setExternalResults(data.results);
      setExternalTotal(data.total);
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : "Search failed");
      setExternalResults([]);
      setExternalTotal(0);
    } finally {
      setSearching(false);
    }
  }

  async function handleImport(verId: string, importHistory: boolean) {
    setPendingImportId(null);
    setImportingIds((prev) => new Set(prev).add(verId));
    try {
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
      });
      if (!res.ok) throw new Error("Import failed");
      setImportedIds((prev) => new Set(prev).add(verId));
      onImportComplete();
    } catch { /* silent */ } finally {
      setImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(verId);
        return next;
      });
    }
  }

  // URL import state
  const [urlImporting, setUrlImporting] = useState(false);

  async function handleUrlImport(importHistory: boolean) {
    if (!detectedUrl) return;
    const verId = detectedUrl[1];
    setUrlImporting(true);
    try {
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
      });
      if (!res.ok) throw new Error("Import failed");
      setImportedIds((prev) => new Set(prev).add(verId));
      onImportComplete();
    } catch { /* silent */ } finally {
      setUrlImporting(false);
    }
  }

  const hasResults = localResults.length > 0 || externalResults.length > 0;

  return (
    <div ref={dropdownRef} className="relative mb-5">
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={keyword}
          onChange={(e) => handleInputChange(e.target.value)}
          onFocus={() => { if (keyword.length >= 3 || externalResults.length > 0) setShowResults(true); }}
          placeholder="Search by keyword, name, or paste a legislatie.just.ro link..."
          className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
        />
        {detectedUrl ? (
          <div className="relative" data-import-dropdown>
            <button
              type="button"
              onClick={() => setPendingImportId(detectedUrl[1])}
              disabled={urlImporting}
              className="rounded-md bg-green-600 px-5 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:bg-gray-300 whitespace-nowrap"
            >
              {urlImporting ? "Importing..." : "Import from link"}
            </button>
            {pendingImportId === detectedUrl[1] && !urlImporting && (
              <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg border border-gray-200 shadow-lg p-3 w-52">
                <p className="text-xs text-gray-500 mb-2">What to import?</p>
                <button onClick={() => handleUrlImport(false)} className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700">Current version only</button>
                <button onClick={() => handleUrlImport(true)} className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700">All historical versions</button>
                <button onClick={() => setPendingImportId(null)} className="w-full text-left px-3 py-1 text-xs rounded-md hover:bg-gray-50 text-gray-400 mt-1">Cancel</button>
              </div>
            )}
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={() => setShowFilters(!showFilters)}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm bg-white hover:bg-gray-50"
            >
              Filters {showFilters ? "▴" : "▾"}
            </button>
            <button
              type="submit"
              disabled={searching}
              className="rounded-md bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
            >
              {searching ? "Searching..." : "Search"}
            </button>
          </>
        )}
      </form>

      {/* Filters */}
      {showFilters && (
        <div className="mt-2 p-3 bg-gray-50 rounded-lg border border-gray-200 grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Act Type</label>
            <select
              value={selectedDocType}
              onChange={(e) => setSelectedDocType(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            >
              <option value="">All types</option>
              {DEFAULT_ACT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Number</label>
            <input
              type="text"
              value={lawNumber}
              onChange={(e) => setLawNumber(e.target.value.replace(/\D/g, ""))}
              placeholder="e.g. 31"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1">Year</label>
            <input
              type="text"
              value={year}
              onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
              placeholder="e.g. 2015"
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
        </div>
      )}

      {/* Results dropdown */}
      {showResults && hasResults && (
        <div className="absolute z-40 left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-[60vh] overflow-y-auto">
          {/* Local results */}
          {localResults.length > 0 && (
            <>
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
                <span className="text-[11px] font-bold text-gray-500 tracking-wider">IN YOUR LIBRARY</span>
                <span className="text-[11px] text-gray-400 ml-2">{localResults.length} match{localResults.length !== 1 ? "es" : ""}</span>
              </div>
              {localResults.map((r) => {
                const stateClass = r.current_version?.state ? STATE_COLORS[r.current_version.state] || "" : "";
                return (
                  <Link
                    key={r.id}
                    href={`/laws/${r.id}`}
                    className="block px-4 py-2.5 border-b border-gray-100 hover:bg-gray-50"
                    onClick={() => setShowResults(false)}
                  >
                    <div className="font-semibold text-sm">{r.title}</div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      Legea {r.law_number}/{r.law_year}
                      {r.current_version?.state && (
                        <span className={`ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${stateClass}`}>
                          {r.current_version.state}
                        </span>
                      )}
                      {r.category_name && (
                        <span className="ml-2 text-gray-400">{r.category_name}</span>
                      )}
                    </div>
                  </Link>
                );
              })}
            </>
          )}

          {/* External results */}
          {externalResults.length > 0 && (
            <>
              <div className="px-4 py-2 bg-amber-50 border-b border-gray-200">
                <span className="text-[11px] font-bold text-amber-700 tracking-wider">FROM LEGISLATIE.JUST.RO</span>
                <span className="text-[11px] text-amber-600 ml-2">{externalTotal} result{externalTotal !== 1 ? "s" : ""}</span>
              </div>
              {externalResults.map((r) => {
                const colorClass = DOC_TYPE_COLORS[r.doc_type] || "bg-gray-100 text-gray-600";
                const isImporting = importingIds.has(r.ver_id);
                const isImported = importedIds.has(r.ver_id) || r.already_imported;

                return (
                  <div key={r.ver_id} className="px-4 py-2.5 border-b border-gray-100 flex justify-between items-center">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-semibold ${colorClass}`}>
                          {r.doc_type || "DOC"}
                        </span>
                        <span className="text-sm font-semibold">nr. {r.number} din {r.date}</span>
                      </div>
                      <p className="text-xs text-gray-500 truncate">{r.description || r.title}</p>
                    </div>
                    <div className="ml-3 flex-shrink-0">
                      {isImported ? (
                        <span className="text-xs text-green-600 bg-green-50 border border-green-200 px-2.5 py-1 rounded">
                          Imported
                        </span>
                      ) : (
                        <div className="relative" data-import-dropdown>
                          <button
                            onClick={() => setPendingImportId(r.ver_id)}
                            disabled={isImporting}
                            className="rounded-md bg-blue-600 px-3.5 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
                          >
                            {isImporting ? "..." : "Import"}
                          </button>
                          {pendingImportId === r.ver_id && !isImporting && (
                            <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg border border-gray-200 shadow-lg p-3 w-52">
                              <p className="text-xs text-gray-500 mb-2">What to import?</p>
                              <button
                                onClick={() => handleImport(r.ver_id, false)}
                                className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                              >
                                Current version only
                              </button>
                              <button
                                onClick={() => handleImport(r.ver_id, true)}
                                className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                              >
                                All historical versions
                              </button>
                              <button
                                onClick={() => setPendingImportId(null)}
                                className="w-full text-left px-3 py-1 text-xs rounded-md hover:bg-gray-50 text-gray-400 mt-1"
                              >
                                Cancel
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </>
          )}

          {/* Loading indicator */}
          {searching && (
            <div className="px-4 py-3 text-center text-xs text-gray-400">
              Searching legislatie.just.ro...
            </div>
          )}
        </div>
      )}

      {searchError && (
        <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded-md">
          <p className="text-sm text-red-700">{searchError}</p>
        </div>
      )}
    </div>
  );
}
