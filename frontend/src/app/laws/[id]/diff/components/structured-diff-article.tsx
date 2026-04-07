"use client";

import { useState } from "react";
import type { DiffArticle, DiffUnit } from "@/lib/api";
import { DiffUnitRow } from "./diff-leaf";

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

/** Group units by their effective alineat key, preserving first-seen order. */
function groupByAlineat(units: DiffUnit[]): Array<{ key: string | null; units: DiffUnit[] }> {
  const order: Array<string | null> = [];
  const buckets = new Map<string | null, DiffUnit[]>();
  for (const u of units) {
    // alineat marker units sit in their OWN bucket (the alineat they introduce)
    const key = u.marker_kind === "alineat" ? u.label : u.alineat_label;
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(u);
  }
  return order.map((k) => ({ key: k, units: buckets.get(k)! }));
}

function renderUnitsWithCollapse(units: DiffUnit[], forceShowAll: boolean) {
  const out: React.ReactNode[] = [];
  let run: DiffUnit[] = [];

  const flush = (key: string) => {
    if (run.length === 0) return;
    if (forceShowAll) {
      // Render every unchanged unit with its actual text, dimmed.
      run.forEach((u, i) =>
        out.push(<DiffUnitRow key={`${key}-${i}`} unit={u} />),
      );
    }
    // When not showing all, unchanged runs are dropped entirely.
    run = [];
  };

  units.forEach((u, i) => {
    if (u.change_type === "unchanged") {
      run.push(u);
      return;
    }
    flush(`run-${i}`);
    out.push(<DiffUnitRow key={`u-${i}`} unit={u} />);
  });
  flush("run-end");
  return out;
}

export function StructuredDiffArticle({ article }: { article: DiffArticle }) {
  const [showAll, setShowAll] = useState(false);
  const isModified = article.change_type === "modified";

  const headerLabel = article.renumbered_from
    ? `Art. ${article.article_number} (was Art. ${article.renumbered_from})`
    : `Art. ${article.article_number}`;

  // Fallback shape: a modified article with no units but a top-level diff_html.
  const isFallback = isModified && article.units.length === 0 && !!article.diff_html;

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <button
        type="button"
        disabled={!isModified || isFallback}
        onClick={() => setShowAll((v) => !v)}
        className={`w-full flex items-center justify-between gap-3 px-4 py-2 text-sm font-medium border-b text-left ${badgeStyle(
          article.change_type,
        )} ${isModified && !isFallback ? "hover:brightness-95 cursor-pointer" : "cursor-default"}`}
      >
        <span>
          {headerLabel}
          {article.title && <span className="font-bold"> — {article.title}</span>}
        </span>
        <span className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide opacity-80">
            {badgeLabel(article.change_type)}
          </span>
          {isModified && !isFallback && (
            <span className="text-xs underline">
              {showAll ? "hide unchanged" : "show full article"}
            </span>
          )}
        </span>
      </button>

      <div className="p-4">
        {isModified && !isFallback && (
          <div className="space-y-1">
            {groupByAlineat(article.units)
              .filter(
                ({ units }) =>
                  showAll || units.some((u) => u.change_type !== "unchanged"),
              )
              .map(({ key, units }, i) => (
                <div key={`${key ?? "intro"}-${i}`} className="mt-2">
                  {key && (
                    <div className="font-mono text-xs text-gray-500 mb-1">{key}</div>
                  )}
                  {renderUnitsWithCollapse(units, showAll)}
                </div>
              ))}
          </div>
        )}
        {isFallback && (
          <div>
            <div
              className="diff-content text-sm text-gray-700 whitespace-pre-wrap"
              dangerouslySetInnerHTML={{ __html: article.diff_html! }}
            />
            <div className="mt-3 text-xs text-gray-400 italic">
              structural diff unavailable for this article
            </div>
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
