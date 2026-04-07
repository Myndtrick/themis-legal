"use client";

import { type ReactNode } from "react";
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
  } else if (unit.change_type === "removed") {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("removed")}`}>
        {unit.text_a}
      </span>
    );
  } else {
    // unchanged — render the actual text, dimmed.
    body = (
      <span className="text-[15px] leading-[1.75] text-gray-400">
        {unit.text_b ?? unit.text_a}
      </span>
    );
  }

  const labelColor =
    unit.change_type === "unchanged" ? "text-gray-400" : "text-gray-500";

  return (
    <div className="flex gap-2 pl-6 mt-1">
      {unit.label && (
        <span className={`font-mono text-xs leading-[1.75] shrink-0 ${labelColor}`}>
          {renderLabel(unit.label)}
          {unit.change_type === "added" && <NewBadge />}
        </span>
      )}
      {body}
    </div>
  );
}

