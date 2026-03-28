"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api, getAuthToken, LocalSearchResult, CategoryGroupData, SuggestedLaw } from "@/lib/api";
import Link from "next/link";
import CategoryModal from "./category-modal";

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
  { label: "DECIZIE", value: "17" },
  { label: "DECRET", value: "3" },
  { label: "CONSTITUȚIE", value: "22" },
  { label: "COD", value: "170" },
  { label: "NORMĂ", value: "11" },
  { label: "REGULAMENT", value: "12" },
  { label: "DIRECTIVĂ", value: "113" },
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
  groups: CategoryGroupData[];
  suggestedLaws: SuggestedLaw[];
  onImportComplete: () => void;
}

export default function CombinedSearch({ groups, suggestedLaws, onImportComplete }: CombinedSearchProps) {
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

  // Filter options from API
  const [actTypes, setActTypes] = useState<FilterOption[]>(DEFAULT_ACT_TYPES);

  // Filters — doc type multi-select
  const [selectedDocTypes, setSelectedDocTypes] = useState<Set<string>>(new Set());
  const [docTypeSearch, setDocTypeSearch] = useState("");
  const [showDocTypeDropdown, setShowDocTypeDropdown] = useState(false);
  const docTypeRef = useRef<HTMLDivElement>(null);

  const [lawNumber, setLawNumber] = useState("");
  const [year, setYear] = useState("");

  // Emitent autocomplete
  const [emitent, setEmitent] = useState("");
  const [emitentLabel, setEmitentLabel] = useState("");
  const [emitentSuggestions, setEmitentSuggestions] = useState<FilterOption[]>([]);
  const [showEmitentDropdown, setShowEmitentDropdown] = useState(false);
  const emitentTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emitentRef = useRef<HTMLDivElement>(null);

  // Date filters
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  // Import state
  const [pendingImportId, setPendingImportId] = useState<string | null>(null);
  const [importingIds, setImportingIds] = useState<Set<string>>(new Set());
  const [importedIds, setImportedIds] = useState<Set<string>>(new Set());
  const [importErrors, setImportErrors] = useState<Record<string, string>>({});

  // Category confirmation after import
  const [importedLawForCategory, setImportedLawForCategory] = useState<{
    lawId: number;
    title: string;
    prefillCategoryId: number | null;
  } | null>(null);

  // URL detection
  const detectedUrl = keyword.match(
    /legislatie\.just\.ro\/Public\/DetaliiDocument(?:Afis)?\/(\d+)/
  );

  // Fetch filter options on mount
  useEffect(() => {
    (async () => {
      const token = await getAuthToken();
      fetch(`${API_BASE}/api/laws/filter-options`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
        .then((res) => res.ok ? res.json() : null)
        .then((data) => {
          if (data?.doc_types?.length) setActTypes(data.doc_types);
        })
        .catch(() => { /* keep defaults */ });
    })();
  }, []);

  // Close dropdowns on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowResults(false);
        setPendingImportId(null);
      }
      if (emitentRef.current && !emitentRef.current.contains(e.target as Node)) {
        setShowEmitentDropdown(false);
      }
      if (docTypeRef.current && !docTypeRef.current.contains(e.target as Node)) {
        setShowDocTypeDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const fetchEmitents = useCallback(async (q: string) => {
    try {
      const token = await getAuthToken();
      const res = await fetch(`${API_BASE}/api/laws/emitents?q=${encodeURIComponent(q)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setEmitentSuggestions(data.emitents);
        setShowEmitentDropdown(true);
      }
    } catch { /* silent */ }
  }, []);

  function handleEmitentChange(value: string) {
    setEmitentLabel(value);
    if (!value) setEmitent("");
    if (emitentTimeout.current) clearTimeout(emitentTimeout.current);
    emitentTimeout.current = setTimeout(() => fetchEmitents(value), 500);
  }

  function toggleDocType(value: string) {
    setSelectedDocTypes((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  }

  const filteredActTypes = docTypeSearch
    ? actTypes.filter((t) => t.label.toLowerCase().includes(docTypeSearch.toLowerCase()))
    : actTypes;

  const selectedDocTypeLabels = actTypes.filter((t) => selectedDocTypes.has(t.value));

  // Local search as you type
  const doLocalSearch = useCallback(async (q: string) => {
    if (q.length < 3) {
      setLocalResults([]);
      return;
    }
    try {
      const token = await getAuthToken();
      const res = await fetch(`${API_BASE}/api/laws/local-search?q=${encodeURIComponent(q)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
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
    if (selectedDocTypes.size > 0) params.set("doc_type", Array.from(selectedDocTypes).join(","));
    if (lawNumber) params.set("number", lawNumber);
    if (year) params.set("year", year);
    if (emitent) params.set("emitent", emitent);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    params.set("include_repealed", "only_in_force");

    try {
      const token = await getAuthToken();
      const res = await fetch(`${API_BASE}/api/laws/advanced-search?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
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
    setImportErrors((prev) => { const next = { ...prev }; delete next[verId]; return next; });
    try {
      // History imports can take minutes — use a 10-minute timeout
      const controller = new AbortController();
      const timeoutMs = importHistory ? 600_000 : 120_000;
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      const token = await getAuthToken();
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
        signal: controller.signal,
      });
      clearTimeout(timer);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Import failed");
      setImportedIds((prev) => new Set(prev).add(verId));
      // Find the external result to get title/number info
      const r = externalResults.find((x) => x.ver_id === verId);
      if (r) {
        // Use backend-provided category suggestion first, fall back to suggestedLaws match
        let prefillId: number | null = data.suggested_category_id ?? null;
        if (!prefillId) {
          const match = suggestedLaws.find(
            (s) =>
              s.law_number === r.number ||
              s.title.toLowerCase().includes((r.description || "").toLowerCase())
          );
          prefillId = match?.category_id ?? null;
        }
        setImportedLawForCategory({
          lawId: data.law_id,
          title: r.description || r.title,
          prefillCategoryId: prefillId,
        });
      } else {
        onImportComplete();
      }
    } catch (err) {
      const msg = err instanceof DOMException && err.name === "AbortError"
        ? "Import timed out — the law may have too many versions. Try importing current version only."
        : err instanceof Error ? err.message : "Import failed";
      setImportErrors((prev) => ({ ...prev, [verId]: msg }));
    } finally {
      setImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(verId);
        return next;
      });
    }
  }

  // URL import state
  const [urlImporting, setUrlImporting] = useState(false);
  const [urlImportError, setUrlImportError] = useState<string | null>(null);

  async function handleUrlImport(importHistory: boolean) {
    if (!detectedUrl) return;
    const verId = detectedUrl[1];
    setUrlImporting(true);
    setUrlImportError(null);
    try {
      const controller = new AbortController();
      const timeoutMs = importHistory ? 600_000 : 120_000;
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      const token = await getAuthToken();
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ ver_id: verId, import_history: importHistory }),
        signal: controller.signal,
      });
      clearTimeout(timer);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Import failed");
      setImportedIds((prev) => new Set(prev).add(verId));
      setImportedLawForCategory({
        lawId: data.law_id,
        title: `Imported law (ver ${verId})`,
        prefillCategoryId: null,
      });
    } catch (err) {
      const msg = err instanceof DOMException && err.name === "AbortError"
        ? "Import timed out — try importing current version only."
        : err instanceof Error ? err.message : "Import failed";
      setUrlImportError(msg);
    } finally {
      setUrlImporting(false);
    }
  }

  async function handleImportCategoryConfirm(categoryId: number) {
    if (!importedLawForCategory) return;
    await api.laws.assignCategory(importedLawForCategory.lawId, categoryId);
    setImportedLawForCategory(null);
    onImportComplete();
  }

  function handleImportCategorySkip() {
    setImportedLawForCategory(null);
    onImportComplete();
  }

  async function handleImportCategoryCancel() {
    if (!importedLawForCategory) return;
    try {
      await api.laws.delete(importedLawForCategory.lawId);
    } catch {
      // Still close the modal even if delete fails
    }
    setImportedLawForCategory(null);
    onImportComplete();
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
            {urlImportError && (
              <p className="absolute right-0 top-full mt-1 text-xs text-red-600 whitespace-nowrap">{urlImportError}</p>
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
              {selectedDocTypes.size > 0 && (
                <span className="ml-1 text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">{selectedDocTypes.size}</span>
              )}
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
        <div className="mt-2 p-3 bg-gray-50 rounded-lg border border-gray-200 space-y-3">
          <div className="grid grid-cols-3 gap-3">
            {/* Act Type — searchable multi-select */}
            <div ref={docTypeRef} className="relative">
              <label className="block text-xs font-semibold text-gray-600 mb-1">Act Type</label>
              <div
                className="w-full min-h-[38px] rounded-md border border-gray-300 px-2 py-1.5 bg-white cursor-text flex flex-wrap gap-1 items-center"
                onClick={() => setShowDocTypeDropdown(true)}
              >
                {selectedDocTypeLabels.map((t) => (
                  <span key={t.value} className="inline-flex items-center gap-1 bg-blue-100 text-blue-800 text-xs px-2 py-0.5 rounded">
                    {t.label}
                    <button type="button" onClick={(e) => { e.stopPropagation(); toggleDocType(t.value); }} className="text-blue-500 hover:text-blue-700 font-bold leading-none">x</button>
                  </span>
                ))}
                <input
                  type="text"
                  value={docTypeSearch}
                  onChange={(e) => { setDocTypeSearch(e.target.value); setShowDocTypeDropdown(true); }}
                  onFocus={() => setShowDocTypeDropdown(true)}
                  placeholder={selectedDocTypes.size === 0 ? "All types — search..." : ""}
                  className="flex-1 min-w-[80px] text-sm outline-none bg-transparent py-0.5"
                />
              </div>
              {showDocTypeDropdown && (
                <div className="absolute z-50 w-full mt-1 bg-white rounded-md border border-gray-200 shadow-lg max-h-60 overflow-y-auto">
                  {selectedDocTypes.size > 0 && (
                    <button type="button" onClick={() => { setSelectedDocTypes(new Set()); setDocTypeSearch(""); }} className="w-full text-left px-3 py-1.5 text-xs text-gray-400 hover:bg-gray-50 border-b border-gray-100">Clear selection</button>
                  )}
                  {filteredActTypes.length === 0 && <div className="px-3 py-2 text-sm text-gray-400">No matching types</div>}
                  {filteredActTypes.map((t) => {
                    const isSelected = selectedDocTypes.has(t.value);
                    return (
                      <button key={t.value} type="button" onClick={() => toggleDocType(t.value)} className={`w-full text-left px-3 py-1.5 text-sm border-b border-gray-50 last:border-b-0 flex items-center gap-2 ${isSelected ? "bg-blue-50 text-blue-800" : "hover:bg-gray-50 text-gray-700"}`}>
                        <span className={`w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center text-xs ${isSelected ? "bg-blue-600 border-blue-600 text-white" : "border-gray-300"}`}>{isSelected && "✓"}</span>
                        {t.label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Number</label>
              <input type="text" value={lawNumber} onChange={(e) => setLawNumber(e.target.value.replace(/\D/g, ""))} placeholder="e.g. 31" className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Year</label>
              <input type="text" value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} placeholder="e.g. 2015" className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            {/* Emitent */}
            <div ref={emitentRef} className="relative">
              <label className="block text-xs font-semibold text-gray-600 mb-1">Emitent</label>
              <input type="text" value={emitentLabel} onChange={(e) => handleEmitentChange(e.target.value)} onFocus={() => fetchEmitents(emitentLabel)} placeholder="Search issuers..." className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
              {showEmitentDropdown && emitentSuggestions.length > 0 && (
                <div className="absolute z-50 w-full mt-1 bg-white rounded-md border border-gray-200 shadow-lg max-h-48 overflow-y-auto">
                  {emitentSuggestions.map((e) => (
                    <button key={e.value} type="button" onClick={() => { setEmitent(e.value); setEmitentLabel(e.label); setShowEmitentDropdown(false); }} className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 border-b border-gray-50 last:border-b-0">{e.label}</button>
                  ))}
                </div>
              )}
            </div>
            {/* Date From */}
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">In Force From</label>
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            {/* Date To */}
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Signed Before</label>
              <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
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
                    {importErrors[r.ver_id] && (
                      <p className="text-xs text-red-600 mt-1 ml-auto max-w-xs text-right">{importErrors[r.ver_id]}</p>
                    )}
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

      {importedLawForCategory && (
        <CategoryModal
          lawTitle={importedLawForCategory.title}
          groups={groups}
          prefillCategoryId={importedLawForCategory.prefillCategoryId}
          onConfirm={handleImportCategoryConfirm}
          onSkip={handleImportCategorySkip}
          onCancel={handleImportCategoryCancel}
        />
      )}
    </div>
  );
}
