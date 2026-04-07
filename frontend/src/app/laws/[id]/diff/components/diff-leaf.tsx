"use client";

import { useState, type ReactNode } from "react";
import type { DiffUnit } from "@/lib/api";

function renderLabel(label: string): ReactNode {
  if (!label) return null;
  // "d^1)" -> d<sup>1</sup>)
  const lit = label.match(/^([a-z])\^(\d+)(\).*)$/);
  if (lit) {
    return (
      <>
        {lit[1]}
        <sup>{lit[2]}</sup>
        {lit[3]}
      </>
    );
  }
  // "(4^1)" -> (4<sup>1</sup>)
  const para = label.match(/^\((\d+)\^(\d+)(\).*)$/);
  if (para) {
    return (
      <>
        ({para[1]}
        <sup>{para[2]}</sup>
        {para[3]}
      </>
    );
  }
  // "42^2." -> 42<sup>2</sup>.
  const num = label.match(/^(\d+)\^(\d+)(\..*)$/);
  if (num) {
    return (
      <>
        {num[1]}
        <sup>{num[2]}</sup>
        {num[3]}
      </>
    );
  }
  return label;
}

function leafBodyStyle(changeType: DiffUnit["change_type"]): string {
  if (changeType === "added") return "text-green-800 bg-green-50/50 rounded px-1";
  if (changeType === "removed")
    return "text-red-800 bg-red-50/50 rounded px-1 line-through";
  return "text-gray-700";
}

function NewBadge() {
  return (
    <span className="inline-block text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded bg-green-100 text-green-800 border border-green-200 ml-2">
      New
    </span>
  );
}

export function DiffUnitRow({ unit }: { unit: DiffUnit }) {
  if (unit.change_type === "unchanged") return null;

  let body: ReactNode;
  if (unit.change_type === "modified" && unit.diff_html) {
    body = (
      <span
        className="diff-content text-[15px] leading-[1.75] text-gray-700"
        dangerouslySetInnerHTML={{ __html: unit.diff_html }}
      />
    );
  } else if (unit.change_type === "added") {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("added")}`}>
        {unit.text_b}
      </span>
    );
  } else {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("removed")}`}>
        {unit.text_a}
      </span>
    );
  }

  return (
    <div className="flex gap-2 pl-6 mt-1">
      {unit.label && (
        <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
          {renderLabel(unit.label)}
          {unit.change_type === "added" && <NewBadge />}
        </span>
      )}
      {body}
    </div>
  );
}

export function CollapsedRun({
  units,
  forceShowAll,
}: {
  units: DiffUnit[];
  forceShowAll: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const open = expanded || forceShowAll;

  if (units.length === 0) return null;

  if (open) {
    return (
      <div className="space-y-1">
        {units.map((u, i) => (
          <div key={i} className="flex gap-2 pl-6 mt-1">
            {u.label && (
              <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-400">
                {renderLabel(u.label)}
              </span>
            )}
            <span className="text-[15px] leading-[1.75] text-gray-500">
              (unchanged — full text hidden in diff view)
            </span>
          </div>
        ))}
      </div>
    );
  }

  const first = units[0].label;
  const last = units[units.length - 1].label;
  const range = units.length === 1 ? first : `${first}–${last}`;

  return (
    <div className="text-xs text-gray-400 italic pl-6 py-1 border-t border-dashed border-gray-200 mt-2">
      … {range} — unchanged{" "}
      <button
        type="button"
        className="text-blue-600 hover:underline not-italic ml-1"
        onClick={() => setExpanded(true)}
      >
        show
      </button>
    </div>
  );
}
