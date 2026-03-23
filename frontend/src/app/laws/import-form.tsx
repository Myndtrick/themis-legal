"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface SearchResult {
  ver_id: string;
  title: string;
  description: string;
  doc_type: string;
  number: string;
  date: string;
  issuer: string;
}

export default function ImportForm() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<SearchResult[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [searching, setSearching] = useState(false);
  const [selectedVerId, setSelectedVerId] = useState<string | null>(null);
  const [selectedTitle, setSelectedTitle] = useState("");
  const [importHistory, setImportHistory] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    title: string;
    law_number: string;
    law_year: number;
    versions_imported: number;
  } | null>(null);
  const router = useRouter();
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close suggestions when clicking outside
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) {
      setSuggestions([]);
      return;
    }
    setSearching(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/laws/search?q=${encodeURIComponent(q)}`
      );
      if (res.ok) {
        const data: SearchResult[] = await res.json();
        setSuggestions(data);
        setShowSuggestions(true);
      }
    } catch {
      // Silently fail search suggestions
    } finally {
      setSearching(false);
    }
  }, []);

  function handleInputChange(value: string) {
    setQuery(value);
    setSelectedVerId(null);
    setSelectedTitle("");
    setError(null);
    setResult(null);

    // Debounce search by 500ms
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => doSearch(value), 500);
  }

  function handleSelectResult(result: SearchResult) {
    setSelectedVerId(result.ver_id);
    setSelectedTitle(result.description || result.title);
    setQuery(result.description || result.title);
    setShowSuggestions(false);
    setSuggestions([]);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    // Determine what to import: selected result or raw input
    let verIdToImport = selectedVerId || query.trim();

    try {
      const res = await fetch(`${API_BASE}/api/laws/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ver_id: verIdToImport,
          import_history: importHistory,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.detail || "Import failed");
        return;
      }

      setResult(data);
      setQuery("");
      setSelectedVerId(null);
      setSelectedTitle("");
      router.refresh();
    } catch {
      setError("Could not connect to the backend. Is the API server running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6 mb-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Import a Law</h2>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div ref={containerRef} className="relative">
          <label
            htmlFor="search"
            className="block text-sm font-medium text-gray-700 mb-1"
          >
            Search by name, number, or paste a legislatie.just.ro link
          </label>
          <input
            id="search"
            type="text"
            value={query}
            onChange={(e) => handleInputChange(e.target.value)}
            onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
            placeholder='e.g. "legea 31/1990", "codul civil", "spalarea banilor", or a URL'
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
            required
            disabled={loading}
            autoComplete="off"
          />
          {searching && (
            <div className="absolute right-3 top-9 text-xs text-gray-400">
              Searching...
            </div>
          )}

          {/* Suggestions dropdown */}
          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute z-50 w-full mt-1 bg-white rounded-md border border-gray-200 shadow-lg max-h-80 overflow-y-auto">
              {suggestions.map((s) => (
                <button
                  key={s.ver_id}
                  type="button"
                  onClick={() => handleSelectResult(s)}
                  className="w-full text-left px-4 py-3 hover:bg-blue-50 border-b border-gray-100 last:border-b-0 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600 shrink-0">
                      {s.doc_type || "DOC"}
                    </span>
                    <span className="text-sm font-medium text-gray-900 truncate">
                      {s.title}
                    </span>
                    {s.date && (
                      <span className="text-xs text-gray-400 shrink-0">
                        {s.date}
                      </span>
                    )}
                  </div>
                  {s.description && (
                    <p className="text-xs text-gray-500 mt-1 line-clamp-2">
                      {s.description}
                    </p>
                  )}
                  {s.issuer && (
                    <p className="text-xs text-gray-400 mt-0.5">{s.issuer}</p>
                  )}
                </button>
              ))}
            </div>
          )}

          {showSuggestions && !searching && suggestions.length === 0 && query.length >= 2 && !selectedVerId && (
            <div className="absolute z-50 w-full mt-1 bg-white rounded-md border border-gray-200 shadow-lg p-4 text-sm text-gray-500">
              No results found. Try a different search or paste a direct URL.
            </div>
          )}
        </div>

        {selectedVerId && (
          <div className="rounded-md bg-blue-50 border border-blue-200 p-3 text-sm">
            <span className="text-blue-700">
              Selected: <strong>{selectedTitle}</strong>
            </span>
            <span className="text-blue-400 ml-2">(ver_id: {selectedVerId})</span>
          </div>
        )}

        <div className="flex items-center gap-2">
          <input
            id="import_history"
            type="checkbox"
            checked={importHistory}
            onChange={(e) => setImportHistory(e.target.checked)}
            className="rounded border-gray-300"
            disabled={loading}
          />
          <label htmlFor="import_history" className="text-sm text-gray-700">
            Import all historical versions (recommended, may take a few minutes for laws with many versions)
          </label>
        </div>

        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Importing... (this may take a few minutes)" : "Import Law"}
        </button>
      </form>

      {error && (
        <div className="mt-4 rounded-md bg-red-50 border border-red-200 p-3">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {result && (
        <div className="mt-4 rounded-md bg-green-50 border border-green-200 p-3">
          <p className="text-sm text-green-700">
            Successfully imported <strong>{result.title}</strong> (Legea{" "}
            {result.law_number}/{result.law_year}) with{" "}
            {result.versions_imported} version(s).
          </p>
        </div>
      )}
    </div>
  );
}
