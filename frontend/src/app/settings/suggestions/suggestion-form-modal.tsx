"use client";

import { useState, useEffect, useMemo } from "react";
import { api, apiFetch, LawMappingRow, ProbeUrlResult } from "@/lib/api";

interface CategoryRow {
  id: number;
  slug: string;
  name_ro: string;
  name_en: string;
  description: string | null;
  group_name: string;
  group_slug: string;
  group_color: string;
  law_count: number;
}

interface Props {
  mode: "create" | "edit";
  row: LawMappingRow | null;
  onClose: () => void;
  onSaved: () => void;
}

const DOC_TYPES = [
  { value: "law", label: "LEGE" },
  { value: "emergency_ordinance", label: "ORDONANȚĂ DE URGENȚĂ" },
  { value: "government_ordinance", label: "ORDONANȚĂ" },
  { value: "government_resolution", label: "HOTĂRÂRE" },
  { value: "decree", label: "DECRET" },
  { value: "constitution", label: "CONSTITUȚIE" },
  { value: "code", label: "COD" },
  { value: "regulation", label: "REGULAMENT (UE)" },
  { value: "directive", label: "DIRECTIVĂ (UE)" },
];

export function SuggestionFormModal({ mode, row, onClose, onSaved }: Props) {
  // Common state
  const [categories, setCategories] = useState<CategoryRow[]>([]);
  const [search, setSearch] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Create-mode state
  const [url, setUrl] = useState("");
  const [titleOverride, setTitleOverride] = useState("");
  const [probe, setProbe] = useState<ProbeUrlResult | null>(null);
  const [probing, setProbing] = useState(false);

  // Edit-mode state
  const [title, setTitle] = useState(row?.title || "");
  const [lawNumber, setLawNumber] = useState(row?.law_number || "");
  const [lawYear, setLawYear] = useState<string>(
    row?.law_year != null ? String(row.law_year) : "",
  );
  const [docType, setDocType] = useState(row?.document_type || "");

  const [categoryId, setCategoryId] = useState<number | null>(row?.category_id ?? null);

  // Fetch categories on mount
  useEffect(() => {
    let active = true;
    apiFetch<CategoryRow[]>("/api/settings/categories")
      .then((data) => {
        if (active) setCategories(data);
      })
      .catch(() => { /* silent */ });
    return () => {
      active = false;
    };
  }, []);

  // Debounced URL probe (create mode only)
  useEffect(() => {
    if (mode !== "create") return;
    if (!url.trim()) {
      setProbe(null);
      return;
    }
    setProbing(true);
    const t = setTimeout(async () => {
      try {
        const result = await api.lawMappings.probeUrl(url.trim());
        setProbe(result);
      } catch {
        setProbe(null);
      } finally {
        setProbing(false);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [url, mode]);

  // Group categories by group_slug
  const grouped = useMemo(() => {
    const map = new Map<
      string,
      { slug: string; name: string; color: string; categories: CategoryRow[] }
    >();
    for (const c of categories) {
      let entry = map.get(c.group_slug);
      if (!entry) {
        entry = {
          slug: c.group_slug,
          name: c.group_name,
          color: c.group_color,
          categories: [],
        };
        map.set(c.group_slug, entry);
      }
      entry.categories.push(c);
    }
    return Array.from(map.values());
  }, [categories]);

  const filteredGroups = useMemo(() => {
    if (!search) return grouped;
    const q = search.toLowerCase();
    return grouped
      .map((g) => ({
        ...g,
        categories: g.categories.filter(
          (c) =>
            c.name_en.toLowerCase().includes(q) ||
            c.name_ro.toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.categories.length > 0);
  }, [grouped, search]);

  function toggleGroup(slug: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  }

  // Auto-expand the group containing the currently-selected category in edit mode
  useEffect(() => {
    if (categoryId == null) return;
    const cat = categories.find((c) => c.id === categoryId);
    if (cat) {
      setExpandedGroups((prev) => {
        if (prev.has(cat.group_slug)) return prev;
        const next = new Set(prev);
        next.add(cat.group_slug);
        return next;
      });
    }
  }, [categoryId, categories]);

  async function handleSubmit() {
    setError(null);
    if (mode === "create") {
      if (!url.trim() || categoryId == null) return;
      setSubmitting(true);
      try {
        await api.lawMappings.create(
          url.trim(),
          categoryId,
          titleOverride.trim() || undefined,
        );
        onSaved();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to create suggestion");
      } finally {
        setSubmitting(false);
      }
    } else {
      if (!row || categoryId == null || !title.trim()) return;
      setSubmitting(true);
      try {
        const fields: Partial<{
          title: string;
          category_id: number;
          law_number: string;
          law_year: number;
          document_type: string;
        }> = {
          title: title.trim(),
          category_id: categoryId,
        };
        if (lawNumber.trim()) fields.law_number = lawNumber.trim();
        if (lawYear.trim()) {
          const parsed = parseInt(lawYear.trim(), 10);
          if (!isNaN(parsed)) fields.law_year = parsed;
        }
        if (docType) fields.document_type = docType;
        await api.lawMappings.update(row.id, fields);
        onSaved();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to update suggestion");
      } finally {
        setSubmitting(false);
      }
    }
  }

  const canSubmit =
    !submitting &&
    categoryId != null &&
    (mode === "create" ? url.trim().length > 0 : title.trim().length > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-200">
          <h3 className="font-bold text-lg">
            {mode === "create" ? "Add Suggestion" : "Edit Suggestion"}
          </h3>
          {mode === "create" && (
            <p className="text-sm text-gray-500 mt-1">
              Paste a legislatie.just.ro or eur-lex.europa.eu URL. Title is fetched
              automatically unless overridden.
            </p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* Edit-mode read-only header */}
          {mode === "edit" && row && (
            <div className="px-4 pt-3 pb-2 flex items-center gap-2 text-xs">
              <span
                className={`px-2 py-0.5 rounded font-semibold ${
                  row.source === "system"
                    ? "bg-gray-100 text-gray-700"
                    : "bg-blue-100 text-blue-700"
                }`}
              >
                {row.source}
              </span>
              {row.source_ver_id && (
                <span className="text-emerald-700">ver {row.source_ver_id}</span>
              )}
              {row.celex_number && (
                <span className="text-emerald-700">CELEX {row.celex_number}</span>
              )}
              {!row.source_ver_id && !row.celex_number && (
                <span className="text-amber-600">⚠ no pinned identifier</span>
              )}
            </div>
          )}

          {/* Create: URL */}
          {mode === "create" && (
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
              {probing && (
                <p className="text-xs text-gray-400">Probing URL...</p>
              )}
              {!probing && probe && probe.kind === "ro" && probe.identifier && (
                <p className="text-xs text-emerald-700">
                  ✓ Detected ver_id {probe.identifier}
                </p>
              )}
              {!probing && probe && probe.kind === "eu" && probe.identifier && (
                <p className="text-xs text-emerald-700">
                  ✓ Detected CELEX {probe.identifier}
                </p>
              )}
              {!probing && probe && probe.error && (
                <p className="text-xs text-amber-700">⚠ {probe.error}</p>
              )}
            </div>
          )}

          {/* Create: title override */}
          {mode === "create" && (
            <div className="px-4 pt-3 space-y-2">
              <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
                Title{" "}
                <span className="lowercase text-gray-400">
                  (optional, otherwise fetched)
                </span>
              </label>
              <input
                type="text"
                value={titleOverride}
                onChange={(e) => setTitleOverride(e.target.value)}
                placeholder="Leave blank to auto-fetch from the URL"
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
              />
            </div>
          )}

          {/* Edit: detail fields */}
          {mode === "edit" && (
            <div className="px-4 pt-3 space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
                  Title
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
                    Law Number
                  </label>
                  <input
                    type="text"
                    value={lawNumber}
                    onChange={(e) => setLawNumber(e.target.value)}
                    className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
                    Year
                  </label>
                  <input
                    type="number"
                    value={lawYear}
                    onChange={(e) => setLawYear(e.target.value)}
                    className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
                  Document Type
                </label>
                <select
                  value={docType}
                  onChange={(e) => setDocType(e.target.value)}
                  className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                >
                  <option value="">—</option>
                  {DOC_TYPES.map((d) => (
                    <option key={d.value} value={d.value}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}

          {/* Category picker */}
          <div className="px-4 pt-3 pb-2">
            <label className="text-xs font-medium text-gray-600 uppercase tracking-wide">
              Category
            </label>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search categories..."
              className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div className="px-4 pb-3 space-y-1">
            {filteredGroups.map((g) => {
              const isExpanded = expandedGroups.has(g.slug) || !!search;
              return (
                <div key={g.slug}>
                  <button
                    onClick={() => toggleGroup(g.slug)}
                    type="button"
                    className="w-full text-left px-2 py-1.5 rounded flex items-center gap-2 hover:bg-gray-50 font-medium text-sm"
                  >
                    <div
                      className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                      style={{ backgroundColor: g.color }}
                    />
                    <span className="text-xs text-gray-400">
                      {isExpanded ? "▾" : "▸"}
                    </span>
                    <span>{g.name}</span>
                  </button>
                  {isExpanded && (
                    <div className="pl-7 space-y-0.5">
                      {g.categories.map((c) => (
                        <button
                          key={c.id}
                          type="button"
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
        </div>

        {error && (
          <div className="mx-4 mb-3 p-2.5 rounded-md bg-rose-50 border border-rose-200 text-xs text-rose-700">
            {error}
          </div>
        )}

        <div className="p-4 border-t border-gray-200 flex justify-end gap-2">
          <button
            onClick={onClose}
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
            {submitting
              ? mode === "create"
                ? "Adding..."
                : "Saving..."
              : mode === "create"
                ? "Add suggestion"
                : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}
