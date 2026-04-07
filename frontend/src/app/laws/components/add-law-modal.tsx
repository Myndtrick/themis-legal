"use client";

import { useState, useMemo } from "react";
import { api, CategoryGroupData } from "@/lib/api";

interface AddLawModalProps {
  groups: CategoryGroupData[];
  onCreated: () => void;
  onCancel: () => void;
}

export default function AddLawModal({
  groups,
  onCreated,
  onCancel,
}: AddLawModalProps) {
  const [url, setUrl] = useState("");
  const [titleOverride, setTitleOverride] = useState("");
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detect URL kind for the inline hint
  const urlKind = useMemo<"ro" | "eu" | "unknown">(() => {
    if (!url) return "unknown";
    try {
      const host = new URL(url).hostname.toLowerCase();
      if (host.endsWith("legislatie.just.ro")) return "ro";
      if (host.endsWith("eur-lex.europa.eu")) return "eu";
    } catch {
      // not a parseable URL yet
    }
    return "unknown";
  }, [url]);

  const filteredGroups = useMemo(() => {
    if (!search) return groups;
    const q = search.toLowerCase();
    return groups
      .map((g) => ({
        ...g,
        categories: g.categories.filter(
          (c) =>
            c.name_en.toLowerCase().includes(q) ||
            c.name_ro.toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.categories.length > 0);
  }, [groups, search]);

  function toggleGroup(slug: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  async function handleSubmit() {
    if (!url.trim() || !categoryId) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.lawMappings.create(
        url.trim(),
        categoryId,
        titleOverride.trim() || undefined,
      );
      onCreated();
    } catch (e: unknown) {
      const message =
        e instanceof Error ? e.message : "Failed to add law";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit = url.trim().length > 0 && categoryId !== null && !submitting;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-200">
          <h3 className="font-bold text-lg">Add Law to Suggestions</h3>
          <p className="text-sm text-gray-500 mt-1">
            Paste a legislatie.just.ro or eur-lex.europa.eu URL. The title is
            fetched automatically.
          </p>
        </div>

        {/* URL */}
        <div className="px-4 pt-3 space-y-2">
          <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
            Source URL
          </label>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://legislatie.just.ro/Public/DetaliiDocument/..."
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
          {url && urlKind === "unknown" && (
            <p className="text-xs text-amber-700">
              Host not recognized — must be legislatie.just.ro or eur-lex.europa.eu
            </p>
          )}
          {url && urlKind === "ro" && (
            <p className="text-xs text-gray-500">
              Detected: Romanian law (legislatie.just.ro)
            </p>
          )}
          {url && urlKind === "eu" && (
            <p className="text-xs text-gray-500">
              Detected: EU law (EUR-Lex)
            </p>
          )}
        </div>

        {/* Optional title override */}
        <div className="px-4 pt-3 space-y-2">
          <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
            Title <span className="lowercase text-gray-400">(optional, otherwise fetched)</span>
          </label>
          <input
            type="text"
            value={titleOverride}
            onChange={(e) => setTitleOverride(e.target.value)}
            placeholder="Leave blank to auto-fetch from the URL"
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
        </div>

        {/* Category */}
        <div className="px-4 pt-3 pb-2">
          <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
            Category
          </label>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search categories..."
            className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
        </div>

        <div className="flex-1 overflow-y-auto px-4 pb-3 space-y-1">
          {filteredGroups.map((g) => {
            const isExpanded = expandedGroups.has(g.slug) || !!search;
            return (
              <div key={g.slug}>
                <button
                  onClick={() => toggleGroup(g.slug)}
                  className="w-full text-left px-2 py-1.5 rounded flex items-center gap-2 hover:bg-gray-50 font-medium text-sm"
                >
                  <div
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: g.color_hex }}
                  />
                  <span className="text-xs text-gray-400">{isExpanded ? "▾" : "▸"}</span>
                  <span>{g.name_en}</span>
                </button>
                {isExpanded && (
                  <div className="pl-7 space-y-0.5">
                    {g.categories.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => setCategoryId(c.id)}
                        className={`w-full text-left px-3 py-2 rounded text-sm flex items-center gap-2 ${
                          categoryId === c.id
                            ? "bg-blue-50 border border-blue-200 text-blue-900"
                            : "hover:bg-gray-50 text-gray-700"
                        }`}
                      >
                        <div
                          className={`w-3.5 h-3.5 rounded-full border flex-shrink-0 flex items-center justify-center text-[9px] ${
                            categoryId === c.id
                              ? "bg-blue-600 border-blue-600 text-white"
                              : "border-gray-300"
                          }`}
                        >
                          {categoryId === c.id && "✓"}
                        </div>
                        <div>{c.name_en}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Error */}
        {error && (
          <div className="mx-4 mb-3 p-2.5 rounded-md bg-rose-50 border border-rose-200 text-xs text-rose-700">
            {error}
          </div>
        )}

        {/* Footer */}
        <div className="p-4 border-t border-gray-200 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={submitting}
            className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-md disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed rounded-md"
          >
            {submitting ? "Adding..." : "Add to suggestions"}
          </button>
        </div>
      </div>
    </div>
  );
}
