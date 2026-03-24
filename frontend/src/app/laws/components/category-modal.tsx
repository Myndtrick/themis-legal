"use client";

import { useState, useMemo } from "react";
import { CategoryGroupData } from "@/lib/api";

interface CategoryModalProps {
  lawTitle: string;
  groups: CategoryGroupData[];
  prefillCategoryId?: number | null;
  onConfirm: (categoryId: number) => void;
  onSkip: () => void;
  onCancel: () => void;
}

export default function CategoryModal({
  lawTitle,
  groups,
  prefillCategoryId,
  onConfirm,
  onSkip,
  onCancel,
}: CategoryModalProps) {
  const [selectedId, setSelectedId] = useState<number | null>(prefillCategoryId ?? null);
  const [search, setSearch] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => {
    // Auto-expand the group containing the pre-filled category
    if (prefillCategoryId) {
      for (const g of groups) {
        if (g.categories.some((c) => c.id === prefillCategoryId)) {
          return new Set([g.slug]);
        }
      }
    }
    return new Set();
  });

  const filteredGroups = useMemo(() => {
    if (!search) return groups;
    const q = search.toLowerCase();
    return groups
      .map((g) => ({
        ...g,
        categories: g.categories.filter(
          (c) =>
            c.name_en.toLowerCase().includes(q) ||
            c.name_ro.toLowerCase().includes(q) ||
            (c.description || "").toLowerCase().includes(q)
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-200">
          <h3 className="font-bold text-lg">Assign Category</h3>
          <p className="text-sm text-gray-500 mt-1 truncate">{lawTitle}</p>
        </div>

        {/* Search */}
        <div className="px-4 pt-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search categories..."
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
          />
        </div>

        {/* Category list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-1">
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
                        onClick={() => setSelectedId(c.id)}
                        className={`w-full text-left px-3 py-2 rounded text-sm flex items-center gap-2 ${
                          selectedId === c.id
                            ? "bg-blue-50 border border-blue-200 text-blue-900"
                            : "hover:bg-gray-50 text-gray-700"
                        }`}
                      >
                        <div className={`w-3.5 h-3.5 rounded-full border flex-shrink-0 flex items-center justify-center text-[9px] ${
                          selectedId === c.id
                            ? "bg-blue-600 border-blue-600 text-white"
                            : "border-gray-300"
                        }`}>
                          {selectedId === c.id && "✓"}
                        </div>
                        <div>
                          <div>{c.name_en}</div>
                          {c.description && (
                            <div className="text-xs text-gray-400 mt-0.5">{c.description}</div>
                          )}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-200 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-md"
          >
            Cancel
          </button>
          <button
            onClick={onSkip}
            className="px-4 py-2 text-sm text-amber-700 border border-amber-300 hover:bg-amber-50 rounded-md"
          >
            Skip
          </button>
          <button
            onClick={() => selectedId && onConfirm(selectedId)}
            disabled={!selectedId}
            className="px-4 py-2 text-sm text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed rounded-md"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
