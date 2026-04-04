"use client";

import { useState, useRef, useEffect } from "react";
import { CategoryData, LibraryLaw, SuggestedLaw } from "@/lib/api";
import LawCard from "./law-card";

interface PendingImportEntry {
  suggestion: SuggestedLaw;
  error?: string;
  errorCode?: string;
  progress?: {
    phase: string;
    current?: number;
    total?: number;
    message: string;
  };
}

const WARNING_ERROR_CODES = ["db_locked", "search_failed"];

function isWarningError(code?: string): boolean {
  return code !== undefined && WARNING_ERROR_CODES.includes(code);
}

interface CategoryGroupSectionProps {
  groupSlug: string;
  groupName: string;
  colorHex: string;
  categories?: CategoryData[];
  laws: LibraryLaw[];
  suggestedLaws: SuggestedLaw[];
  pendingImports?: PendingImportEntry[];
  defaultExpanded?: boolean;
  onAssign?: (lawId: number) => void;
  onDelete?: () => void;
  onImportSuggestion?: (mappingId: number, importHistory: boolean) => void;
  onDismissPendingError?: (mappingId: number) => void;
  favoriteIds?: Set<number>;
  onToggleFavorite?: (lawId: number) => void;
}

const PREVIEW_COUNT = 3;

export default function CategoryGroupSection({
  groupSlug,
  groupName,
  colorHex,
  categories,
  laws,
  suggestedLaws,
  pendingImports = [],
  defaultExpanded = false,
  onAssign,
  onDelete,
  onImportSuggestion,
  onDismissPendingError,
  favoriteIds = new Set<number>(),
  onToggleFavorite,
}: CategoryGroupSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [pickingId, setPickingId] = useState<number | null>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  // Close version picker on outside click
  useEffect(() => {
    if (pickingId === null) return;
    function handleClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setPickingId(null);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [pickingId]);

  function handleSuggestionImport(id: number, importHistory: boolean) {
    setPickingId(null);
    onImportSuggestion?.(id, importHistory);
  }
  const totalCount = laws.length + pendingImports.length;

  // Sort: favorited laws first (stable sort preserves original order within groups)
  const sortedLaws = favoriteIds.size > 0
    ? [...laws].sort((a, b) => {
        const aFav = favoriteIds.has(a.id) ? 0 : 1;
        const bFav = favoriteIds.has(b.id) ? 0 : 1;
        return aFav - bFav;
      })
    : laws;

  const visibleLaws = expanded ? sortedLaws : sortedLaws.slice(0, PREVIEW_COUNT);
  const hasMore = sortedLaws.length > PREVIEW_COUNT;

  return (
    <div className="mb-5">
      {/* Group header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: colorHex }}
          />
          <span className="font-bold text-sm">{groupName}</span>
          <span className="text-xs text-gray-400">
            {totalCount} law{totalCount !== 1 ? "s" : ""}
          </span>
        </div>
        {hasMore && !expanded && (
          <button
            onClick={() => setExpanded(true)}
            className="text-xs text-amber-700 hover:text-amber-900"
          >
            See all →
          </button>
        )}
      </div>

      {/* Pending import cards (loading) */}
      {pendingImports.length > 0 && (
        <div className="space-y-1.5 mb-1.5">
          {pendingImports.map((p) => (
            <div
              key={`pending-${p.suggestion.id}`}
              className="border border-gray-200 rounded-lg bg-white p-3 flex justify-between items-center"
            >
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-sm text-gray-900 line-clamp-2">
                  {p.suggestion.title}
                </div>
                {p.error ? (
                  <div
                    className={`text-xs mt-1 px-2 py-1 rounded border ${
                      isWarningError(p.errorCode)
                        ? "bg-amber-50 text-amber-800 border-amber-200"
                        : "bg-red-50 text-red-700 border-red-200"
                    }`}
                  >
                    {p.error}
                  </div>
                ) : (
                  <div className="mt-1">
                    <div className="text-xs text-gray-400 flex items-center gap-1.5">
                      <span className="inline-block w-3 h-3 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
                      {p.progress ? (
                        <span>
                          {p.progress.message}
                          {p.progress.phase === "version" && p.progress.current != null && p.progress.total != null && (
                            <span className="ml-1 text-gray-500">
                              {p.progress.current} / {p.progress.total}
                            </span>
                          )}
                        </span>
                      ) : (
                        <span>Importing...</span>
                      )}
                    </div>
                    {p.progress?.phase === "version" && p.progress.current != null && p.progress.total != null && (
                      <div className="mt-1 h-1 bg-gray-100 rounded overflow-hidden">
                        <div
                          className="h-1 bg-blue-500 rounded transition-all"
                          style={{ width: `${(p.progress.current / p.progress.total) * 100}%` }}
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>
              {p.error && (
                <button
                  onClick={() => onDismissPendingError?.(p.suggestion.id)}
                  className="ml-3 text-xs text-gray-400 hover:text-gray-600"
                >
                  Dismiss
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Law cards — grouped by subcategory if categories are provided */}
      {categories && categories.length > 1 ? (
        <div className="space-y-3">
          {categories
            .filter((cat) => visibleLaws.some((l) => l.category_id === cat.id))
            .map((cat) => {
              const catLaws = visibleLaws.filter((l) => l.category_id === cat.id);
              return (
                <div key={cat.id}>
                  <div className="text-xs font-medium text-gray-500 mb-1 pl-1">
                    {cat.name_en}
                    <span className="text-gray-400 ml-1">({catLaws.length})</span>
                  </div>
                  <div className="space-y-1.5">
                    {catLaws.map((law) => (
                      <LawCard
                        key={law.id}
                        law={law}
                        onAssign={onAssign}
                        onDelete={onDelete}
                        isFavorite={favoriteIds.has(law.id)}
                        onToggleFavorite={onToggleFavorite}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          {/* Laws without a matching subcategory */}
          {visibleLaws.filter((l) => !categories.some((c) => c.id === l.category_id)).length > 0 && (
            <div className="space-y-1.5">
              {visibleLaws
                .filter((l) => !categories.some((c) => c.id === l.category_id))
                .map((law) => (
                  <LawCard
                    key={law.id}
                    law={law}
                    onAssign={onAssign}
                    onDelete={onDelete}
                    isFavorite={favoriteIds.has(law.id)}
                    onToggleFavorite={onToggleFavorite}
                  />
                ))}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-1.5">
          {visibleLaws.map((law) => (
            <LawCard
              key={law.id}
              law={law}
              onAssign={onAssign}
              onDelete={onDelete}
              isFavorite={favoriteIds.has(law.id)}
              onToggleFavorite={onToggleFavorite}
            />
          ))}
        </div>
      )}

      {expanded && hasMore && (
        <button
          onClick={() => setExpanded(false)}
          className="text-xs text-gray-400 hover:text-gray-600 mt-2"
        >
          Show less
        </button>
      )}

      {/* Per-category suggestions */}
      {suggestedLaws.length > 0 && expanded && (
        <div className="mt-3 border-t border-dashed border-gray-200 pt-3">
          <div className="text-xs text-gray-400 mb-2 italic">
            Sugestii pentru această categorie
          </div>
          {suggestedLaws.map((s) => (
            <div key={s.id} className="relative border border-dashed border-gray-200 rounded-lg p-3 mb-1.5" style={{ zIndex: pickingId === s.id ? 50 : 0 }}>
              <div className="flex justify-between items-center">
                <div className="text-sm text-gray-400">{s.title}</div>
                <div ref={pickingId === s.id ? pickerRef : undefined} className="relative flex-shrink-0 ml-3">
                  <button
                    onClick={() => setPickingId(pickingId === s.id ? null : s.id)}
                    className="text-xs border border-blue-500 text-blue-600 px-2.5 py-1 rounded hover:bg-blue-50"
                  >
                    + Importa
                  </button>
                  {pickingId === s.id && (
                    <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-lg border border-gray-200 shadow-lg p-3 w-52">
                      <p className="text-xs text-gray-500 mb-2">What to import?</p>
                      <button
                        onClick={() => handleSuggestionImport(s.id, false)}
                        className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                      >
                        Current version only
                      </button>
                      <button
                        onClick={() => handleSuggestionImport(s.id, true)}
                        className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-blue-50 text-gray-700"
                      >
                        All historical versions
                      </button>
                      <button
                        onClick={() => setPickingId(null)}
                        className="w-full text-left px-3 py-1 text-xs rounded-md hover:bg-gray-50 text-gray-400 mt-1"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
