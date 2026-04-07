"use client";

import { useState } from "react";
import type { DiffArticle } from "@/lib/api";
import { DiffParagraphLeaf } from "./diff-leaf";

function badgeStyle(changeType: string): string {
  switch (changeType) {
    case "modified":
      return "bg-yellow-50 text-yellow-800 border-yellow-200";
    case "added":
      return "bg-green-50 text-green-800 border-green-200";
    case "removed":
      return "bg-red-50 text-red-800 border-red-200";
    default:
      return "bg-gray-50 text-gray-600 border-gray-200";
  }
}

function badgeLabel(changeType: string): string {
  if (changeType === "modified") return "Modified";
  if (changeType === "added") return "Added";
  if (changeType === "removed") return "Removed";
  return "Unchanged";
}

export function StructuredDiffArticle({ article }: { article: DiffArticle }) {
  const [showAll, setShowAll] = useState(false);
  const isModified = article.change_type === "modified";

  const headerLabel = article.renumbered_from
    ? `Art. ${article.article_number} (was Art. ${article.renumbered_from})`
    : `Art. ${article.article_number}`;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <button
        type="button"
        disabled={!isModified}
        onClick={() => setShowAll((v) => !v)}
        className={`w-full flex items-center justify-between gap-3 px-4 py-2 text-sm font-medium border-b text-left ${badgeStyle(
          article.change_type,
        )} ${isModified ? "hover:brightness-95 cursor-pointer" : "cursor-default"}`}
      >
        <span>
          {headerLabel}
          {article.title && (
            <span className="font-bold"> — {article.title}</span>
          )}
        </span>
        <span className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide opacity-80">
            {badgeLabel(article.change_type)}
          </span>
          {isModified && (
            <span className="text-xs underline">
              {showAll ? "hide unchanged" : "show full article"}
            </span>
          )}
        </span>
      </button>

      <div className="p-4">
        {article.change_type === "modified" && (
          <div className="space-y-1">
            {article.paragraphs.map((p, i) => {
              if (p.change_type === "unchanged" && !showAll) {
                return (
                  <div
                    key={i}
                    className="text-xs text-gray-400 italic py-1 border-t border-dashed border-gray-200"
                  >
                    … {p.label ?? "(intro)"} — unchanged
                  </div>
                );
              }
              return <DiffParagraphLeaf key={i} para={p} forceShowAll={showAll} />;
            })}
          </div>
        )}
        {article.change_type === "added" && (
          <div className="text-sm text-green-800 bg-green-50/50 rounded p-2 whitespace-pre-wrap">
            {article.text_b}
          </div>
        )}
        {article.change_type === "removed" && (
          <div className="text-sm text-red-800 bg-red-50/50 rounded p-2 line-through whitespace-pre-wrap">
            {article.text_a}
          </div>
        )}
      </div>
    </div>
  );
}
