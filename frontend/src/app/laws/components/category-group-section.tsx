"use client";

import { useState } from "react";
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
}: CategoryGroupSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
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
          <LawCard key={law.id} law={law} onAssign={onAssign} />
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
          {suggestedLaws.map((s) => (
            <div
              key={s.id}
              className="border border-dashed border-gray-200 rounded-lg p-3 mb-1.5 opacity-60 flex justify-between items-center"
            >
              <div className="text-sm text-gray-600">{s.title}</div>
              <button className="text-xs border border-blue-500 text-blue-600 px-2.5 py-1 rounded hover:bg-blue-50">
                + Importă
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
