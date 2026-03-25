"use client";

import { useState, useRef, useEffect } from "react";
import { LibraryLaw, SuggestedLaw } from "@/lib/api";
import LawCard from "./law-card";

interface CategoryGroupSectionProps {
  groupSlug: string;
  groupName: string;
  colorHex: string;
  laws: LibraryLaw[];
  suggestedLaws: SuggestedLaw[];
  defaultExpanded?: boolean;
  onAssign?: (lawId: number) => void;
  onDelete?: () => void;
  onImportSuggestion?: (mappingId: number, importHistory: boolean) => Promise<void>;
}

const PREVIEW_COUNT = 3;

export default function CategoryGroupSection({
  groupSlug,
  groupName,
  colorHex,
  laws,
  suggestedLaws,
  defaultExpanded = false,
  onAssign,
  onDelete,
  onImportSuggestion,
}: CategoryGroupSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [pickingId, setPickingId] = useState<number | null>(null);
  const [importingIds, setImportingIds] = useState<Set<number>>(new Set());
  const [errorMap, setErrorMap] = useState<Record<number, string>>({});
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

  async function handleSuggestionImport(id: number, importHistory: boolean) {
    setPickingId(null);
    setImportingIds((prev) => new Set(prev).add(id));
    setErrorMap((prev) => { const next = { ...prev }; delete next[id]; return next; });
    try {
      await onImportSuggestion?.(id, importHistory);
    } catch (err) {
      setErrorMap((prev) => ({
        ...prev,
        [id]: err instanceof Error ? err.message : "Import failed",
      }));
    } finally {
      setImportingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }
  const visibleLaws = expanded ? laws : laws.slice(0, PREVIEW_COUNT);
  const hasMore = laws.length > PREVIEW_COUNT;

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
            {laws.length} law{laws.length !== 1 ? "s" : ""}
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

      {/* Law cards */}
      <div className="space-y-1.5">
        {visibleLaws.map((law) => (
          <LawCard key={law.id} law={law} onAssign={onAssign} onDelete={onDelete} />
        ))}
      </div>

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
          {suggestedLaws.map((s) => {
            const isImporting = importingIds.has(s.id);
            return (
              <div key={s.id} className="border border-dashed border-gray-200 rounded-lg p-3 mb-1.5 opacity-60">
                <div className="flex justify-between items-center">
                  <div className="text-sm text-gray-600">{s.title}</div>
                  <div ref={pickingId === s.id ? pickerRef : undefined} className="relative flex-shrink-0 ml-3">
                    {isImporting ? (
                      <span className="text-xs text-gray-400 px-2.5 py-1">
                        Importing...
                      </span>
                    ) : (
                      <button
                        onClick={() => setPickingId(pickingId === s.id ? null : s.id)}
                        className="text-xs border border-blue-500 text-blue-600 px-2.5 py-1 rounded hover:bg-blue-50"
                      >
                        + Importa
                      </button>
                    )}
                    {pickingId === s.id && !isImporting && (
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
                {errorMap[s.id] && (
                  <p className="text-xs text-red-600 mt-1">{errorMap[s.id]}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
