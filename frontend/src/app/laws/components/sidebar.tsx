"use client";

import { useState } from "react";
import { CategoryGroupData, LibraryLaw } from "@/lib/api";

interface SidebarProps {
  groups: CategoryGroupData[];
  laws: LibraryLaw[];
  selectedGroup: string | null;
  selectedCategory: string | null;
  selectedStatus: string | null;
  onSelectGroup: (slug: string | null) => void;
  onSelectCategory: (slug: string | null) => void;
  onSelectStatus: (status: string | null) => void;
  favoriteCounts: Map<string, number>;
  selectedView: "all" | "favorites";
  favoriteCategoryFilter: string | null;
  onSelectFavorites: (groupSlug: string | null) => void;
}

const STATUS_LABELS: Record<string, string> = {
  actual: "Actual",
  republished: "Republished",
  amended: "Amended",
  deprecated: "Deprecated",
};

export default function Sidebar({
  groups,
  laws,
  selectedGroup,
  selectedCategory,
  selectedStatus,
  onSelectGroup,
  onSelectCategory,
  onSelectStatus,
  favoriteCounts,
  selectedView,
  favoriteCategoryFilter,
  onSelectFavorites,
}: SidebarProps) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [showSuggested, setShowSuggested] = useState(false);

  const totalLaws = laws.length;

  // Groups that have at least one imported law
  const activeGroups = groups.filter((g) =>
    g.categories.some((c) => c.law_count > 0)
  );
  const suggestedGroups = groups.filter((g) =>
    g.categories.every((c) => c.law_count === 0)
  );

  // Status counts based on current_version.state
  const statusCounts: Record<string, number> = {};
  for (const law of laws) {
    const state = law.current_version?.state;
    if (state) {
      statusCounts[state] = (statusCounts[state] || 0) + 1;
    }
  }

  function toggleGroup(slug: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  }

  const isAllSelected = !selectedGroup && !selectedCategory;

  return (
    <div className="w-56 border-r border-gray-200 p-4 text-sm flex-shrink-0">
      {/* CATEGORIES */}
      <div className="text-[10px] font-bold text-gray-500 tracking-wider mb-2">
        CATEGORIES
      </div>

      {/* All laws */}
      <button
        onClick={() => { onSelectGroup(null); onSelectCategory(null); }}
        className={`w-full text-left px-2 py-1.5 rounded flex justify-between items-center mb-1 ${
          isAllSelected ? "bg-amber-50 font-semibold text-amber-900" : "hover:bg-gray-50"
        }`}
      >
        <span>All laws</span>
        <span className={`text-xs px-1.5 rounded-full ${
          isAllSelected ? "bg-amber-900 text-white" : "text-gray-400"
        }`}>
          {totalLaws}
        </span>
      </button>

      {/* Active groups */}
      {activeGroups.map((g) => {
        const groupLawCount = g.categories.reduce((sum, c) => sum + c.law_count, 0);
        const isExpanded = expandedGroups.has(g.slug);
        const isSelected = selectedGroup === g.slug && !selectedCategory;

        return (
          <div key={g.slug} className="mb-0.5">
            <div className="flex items-center">
              <button
                onClick={() => toggleGroup(g.slug)}
                className="text-xs text-gray-400 w-4 flex-shrink-0"
              >
                {isExpanded ? "▾" : "▸"}
              </button>
              <button
                onClick={() => { onSelectGroup(g.slug); onSelectCategory(null); }}
                className={`flex-1 text-left px-1 py-1.5 rounded flex justify-between items-center ${
                  isSelected ? "font-semibold text-gray-900" : "hover:bg-gray-50 text-gray-700"
                }`}
              >
                <span className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: g.color_hex }} />
                  {g.name_en}
                </span>
                <span className="text-xs text-gray-400">{groupLawCount}</span>
              </button>
            </div>

            {/* Subcategories */}
            {isExpanded && (
              <div className="pl-5">
                {g.categories.map((c) => {
                  const isCatSelected = selectedCategory === c.slug;
                  return (
                    <button
                      key={c.slug}
                      onClick={() => { onSelectGroup(g.slug); onSelectCategory(c.slug); }}
                      className={`w-full text-left px-2 py-1 rounded flex justify-between items-center text-xs ${
                        isCatSelected
                          ? "font-semibold text-gray-900 bg-gray-100"
                          : "text-gray-500 hover:bg-gray-50"
                      }`}
                    >
                      <span>{c.name_en}</span>
                      <span className="text-gray-400">{c.law_count}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {/* STATUS */}
      <div className="border-t border-gray-200 mt-3 pt-3">
        <div className="text-[10px] font-bold text-gray-500 tracking-wider mb-2">
          STATUS
        </div>
        {Object.entries(STATUS_LABELS).map(([value, label]) => {
          const count = statusCounts[value] || 0;
          if (count === 0) return null;
          const isSelected = selectedStatus === value;
          return (
            <button
              key={value}
              onClick={() => onSelectStatus(isSelected ? null : value)}
              className={`w-full text-left px-2 py-1.5 rounded flex justify-between items-center ${
                isSelected ? "font-semibold text-gray-900 bg-gray-100" : "hover:bg-gray-50 text-gray-700"
              }`}
            >
              <span>{label}</span>
              <span className="text-xs text-gray-400">{count}</span>
            </button>
          );
        })}
      </div>

      {/* SUGGESTED CATEGORIES */}
      {suggestedGroups.length > 0 && (
        <div className="border-t border-gray-200 mt-3 pt-3">
          <button
            onClick={() => setShowSuggested(!showSuggested)}
            className="w-full text-left px-2 py-1.5 text-xs text-gray-400 italic hover:text-gray-600"
          >
            {showSuggested ? "▾" : "▸"} Sugestii neimportate ({suggestedGroups.length})
          </button>
          {showSuggested && (
            <div className="pl-4">
              {suggestedGroups.map((g) => {
                const isSelected = selectedGroup === g.slug;
                return (
                  <button
                    key={g.slug}
                    onClick={() => { onSelectGroup(g.slug); onSelectCategory(null); }}
                    className={`w-full text-left px-2 py-1 text-xs italic rounded ${
                      isSelected
                        ? "font-semibold text-gray-700 bg-gray-100"
                        : "text-gray-400 hover:text-gray-600 hover:bg-gray-50"
                    }`}
                  >
                    {g.name_en}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* FAVORITES */}
      {favoriteCounts.size > 0 && (
        <div className="border-t border-gray-200 mt-3 pt-3">
          <div className="text-[10px] font-bold text-gray-500 tracking-wider mb-2">
            FAVORITES
          </div>
          {Array.from(favoriteCounts.entries()).map(([groupSlug, count]) => {
            const group = groups.find((g) => g.slug === groupSlug);
            if (!group) return null;
            const isSelected = selectedView === "favorites" && favoriteCategoryFilter === groupSlug;
            return (
              <button
                key={groupSlug}
                onClick={() => onSelectFavorites(groupSlug)}
                className={`w-full text-left px-2 py-1.5 rounded flex justify-between items-center ${
                  isSelected ? "font-semibold text-gray-900 bg-pink-50" : "hover:bg-gray-50 text-gray-700"
                }`}
              >
                <span>{group.name_en}</span>
                <span className="text-xs text-gray-400">{count}</span>
              </button>
            );
          })}
          <button
            onClick={() => onSelectFavorites(null)}
            className={`w-full text-left px-2 py-1.5 text-xs rounded ${
              selectedView === "favorites" && !favoriteCategoryFilter
                ? "font-semibold text-pink-700 bg-pink-50"
                : "text-pink-600 hover:text-pink-700 hover:bg-pink-50"
            }`}
          >
            Show all favorites
          </button>
        </div>
      )}
    </div>
  );
}
