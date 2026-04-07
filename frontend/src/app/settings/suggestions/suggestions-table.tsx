"use client";

import { useState, useEffect, useCallback } from "react";
import { api, LawMappingRow } from "@/lib/api";
import { SuggestionFormModal } from "./suggestion-form-modal";

const DOC_TYPE_LABELS: Record<string, string> = {
  law: "LEGE",
  emergency_ordinance: "OUG",
  government_ordinance: "OG",
  government_resolution: "HG",
  decree: "DECRET",
  constitution: "CONSTITUȚIE",
  code: "COD",
  regulation: "REG",
  directive: "DIR",
};

export function SuggestionsTable() {
  const [rows, setRows] = useState<LawMappingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [groupSlug, setGroupSlug] = useState<string>("");
  const [source, setSource] = useState<"all" | "system" | "user">("all");
  const [pinned, setPinned] = useState<"all" | "true" | "false">("all");
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");

  // Modal state
  const [modalMode, setModalMode] = useState<"create" | "edit" | null>(null);
  const [modalRow, setModalRow] = useState<LawMappingRow | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.lawMappings.list({
        group_slug: groupSlug || undefined,
        source: source === "all" ? undefined : source,
        pinned: pinned === "all" ? undefined : pinned,
        q: debouncedQ || undefined,
      });
      setRows(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load suggestions");
    } finally {
      setLoading(false);
    }
  }, [groupSlug, source, pinned, debouncedQ]);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  // Build group dropdown options from current rows
  const groupOptions = Array.from(
    new Map(
      rows
        .filter((r) => r.group_slug)
        .map((r) => [r.group_slug, { slug: r.group_slug!, name: r.group_name || r.group_slug! }]),
    ).values(),
  );

  async function handleDelete(row: LawMappingRow) {
    if (row.source === "system") return;
    if (!confirm("Delete this suggestion?")) return;
    try {
      await api.lawMappings.remove(row.id);
      fetchRows();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  function openCreate() {
    setModalRow(null);
    setModalMode("create");
  }

  function openEdit(row: LawMappingRow) {
    setModalRow(row);
    setModalMode("edit");
  }

  function closeModal() {
    setModalMode(null);
    setModalRow(null);
  }

  function onSaved() {
    closeModal();
    fetchRows();
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Suggested Laws</h2>
        <button
          onClick={openCreate}
          className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
        >
          + Add suggestion
        </button>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap gap-2 items-end">
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">Group</label>
          <select
            value={groupSlug}
            onChange={(e) => setGroupSlug(e.target.value)}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm bg-white"
          >
            <option value="">All groups</option>
            {groupOptions.map((g) => (
              <option key={g.slug} value={g.slug}>
                {g.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">Source</label>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value as "all" | "system" | "user")}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm bg-white"
          >
            <option value="all">All</option>
            <option value="system">System</option>
            <option value="user">User</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-1">Pinned</label>
          <select
            value={pinned}
            onChange={(e) => setPinned(e.target.value as "all" | "true" | "false")}
            className="rounded-md border border-gray-300 px-2 py-1.5 text-sm bg-white"
          >
            <option value="all">All</option>
            <option value="true">Pinned</option>
            <option value="false">Unpinned</option>
          </select>
        </div>
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs font-semibold text-gray-600 mb-1">Search title</label>
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by title..."
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </div>
      </div>

      {error && (
        <div className="mb-3 p-2.5 rounded-md bg-rose-50 border border-rose-200 text-xs text-rose-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-gray-400 py-4">Loading suggestions...</div>
      ) : (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Source</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Group</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Type</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">No.</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Year</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Title</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600">Pinned</th>
                <th className="px-3 py-2.5 font-semibold text-gray-600 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-gray-400">
                    No suggestions match the current filters.
                  </td>
                </tr>
              )}
              {rows.map((row) => {
                const docLabel = row.document_type
                  ? DOC_TYPE_LABELS[row.document_type] || row.document_type
                  : "—";
                const pinnedCell = row.source_ver_id ? (
                  <span className="text-xs text-emerald-700">ver {row.source_ver_id}</span>
                ) : row.celex_number ? (
                  <span className="text-xs text-emerald-700">CELEX {row.celex_number}</span>
                ) : (
                  <span className="text-xs text-amber-600">⚠ none</span>
                );
                return (
                  <tr key={row.id}>
                    <td className="px-3 py-2.5">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                          row.source === "system"
                            ? "bg-gray-100 text-gray-700"
                            : "bg-blue-100 text-blue-700"
                        }`}
                      >
                        {row.source}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      {row.group_name ? (
                        <span className="flex items-center gap-1.5">
                          <span
                            className="w-2 h-2 rounded-full"
                            style={{ backgroundColor: row.group_color || "#9ca3af" }}
                          />
                          <span className="text-xs">{row.group_name}</span>
                        </span>
                      ) : (
                        <span className="text-gray-400 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-gray-700">{docLabel}</td>
                    <td className="px-3 py-2.5 text-xs">{row.law_number || "—"}</td>
                    <td className="px-3 py-2.5 text-xs">{row.law_year || "—"}</td>
                    <td className="px-3 py-2.5 max-w-md">
                      <div className="truncate" title={row.title}>
                        {row.title}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">{pinnedCell}</td>
                    <td className="px-3 py-2.5 text-right">
                      <div className="flex justify-end gap-1">
                        <button
                          onClick={() => openEdit(row)}
                          className="text-xs text-blue-600 hover:text-blue-800 px-2 py-1"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => handleDelete(row)}
                          disabled={row.source === "system"}
                          title={
                            row.source === "system"
                              ? "System suggestions cannot be deleted"
                              : "Delete"
                          }
                          className="text-xs text-rose-600 hover:text-rose-800 px-2 py-1 disabled:text-gray-300 disabled:cursor-not-allowed"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {modalMode && (
        <SuggestionFormModal
          mode={modalMode}
          row={modalRow}
          onClose={closeModal}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}
