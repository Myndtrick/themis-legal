"use client";

import { useState, type ReactNode } from "react";
import type { DiffParagraph, DiffSubparagraph } from "@/lib/api";

function renderLabel(label: string | null): ReactNode {
  if (!label) return null;
  // Handle "d^1)" -> d<sup>1</sup>)
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
  // Handle "(4^1)" -> (4<sup>1</sup>)
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
  return label;
}

function renumberedSuffix(renumberedFrom: string | null | undefined): ReactNode {
  if (!renumberedFrom) return null;
  return (
    <span className="text-xs text-gray-400 ml-1">(was {renumberedFrom})</span>
  );
}

function leafBodyStyle(changeType: string): string {
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

export function DiffSubparagraphLeaf({ leaf }: { leaf: DiffSubparagraph }) {
  const showText =
    leaf.change_type === "modified" ||
    leaf.change_type === "added" ||
    leaf.change_type === "removed";

  if (!showText) return null; // unchanged leaves are rendered by CollapsedRun

  let body: ReactNode;
  if (leaf.change_type === "modified" && leaf.diff_html) {
    body = (
      <span
        className="diff-content text-[15px] leading-[1.75] text-gray-700"
        dangerouslySetInnerHTML={{ __html: leaf.diff_html }}
      />
    );
  } else if (leaf.change_type === "added") {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("added")}`}>
        {leaf.text_b}
      </span>
    );
  } else {
    body = (
      <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("removed")}`}>
        {leaf.text_a}
      </span>
    );
  }

  return (
    <div className="flex gap-2 pl-6 mt-1">
      {leaf.label && (
        <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
          {renderLabel(leaf.label)}
          {renumberedSuffix(leaf.renumbered_from)}
          {leaf.change_type === "added" && <NewBadge />}
        </span>
      )}
      {body}
    </div>
  );
}

export function DiffParagraphLeaf({
  para,
  forceShowAll,
}: {
  para: DiffParagraph;
  forceShowAll: boolean;
}) {
  // Render the paragraph's intro line if it's modified/added/removed.
  let intro: ReactNode = null;
  if (para.change_type === "modified" && para.diff_html) {
    intro = (
      <div className="flex gap-2">
        {para.label && (
          <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
            {renderLabel(para.label)}
          </span>
        )}
        <span
          className="diff-content text-[15px] leading-[1.75] text-gray-700"
          dangerouslySetInnerHTML={{ __html: para.diff_html }}
        />
      </div>
    );
  } else if (para.change_type === "added") {
    intro = (
      <div className="flex gap-2">
        {para.label && (
          <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
            {renderLabel(para.label)}
            <NewBadge />
          </span>
        )}
        <span className={`text-[15px] leading-[1.75] ${leafBodyStyle("added")}`}>
          {para.text_b}
        </span>
      </div>
    );
  } else if (para.change_type === "removed") {
    intro = (
      <div className="flex gap-2">
        {para.label && (
          <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-500">
            {renderLabel(para.label)}
          </span>
        )}
        <span
          className={`text-[15px] leading-[1.75] ${leafBodyStyle("removed")}`}
        >
          {para.text_a}
        </span>
      </div>
    );
  } else if (forceShowAll && para.label) {
    // Unchanged paragraph being shown because the user clicked "show full article".
    intro = (
      <div className="flex gap-2">
        <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-400">
          {renderLabel(para.label)}
        </span>
        <span className="text-[15px] leading-[1.75] text-gray-500">
          (unchanged)
        </span>
      </div>
    );
  }

  // Children: collapse runs of consecutive unchanged subparagraphs into one CollapsedRun.
  const children: ReactNode[] = [];
  let unchangedRun: DiffSubparagraph[] = [];
  const flushRun = (key: string) => {
    if (unchangedRun.length === 0) return;
    children.push(
      <CollapsedRun
        key={`run-${key}`}
        leaves={unchangedRun}
        forceShowAll={forceShowAll}
      />,
    );
    unchangedRun = [];
  };

  para.subparagraphs.forEach((s, i) => {
    if (s.change_type === "unchanged") {
      unchangedRun.push(s);
      return;
    }
    flushRun(`before-${i}`);
    children.push(<DiffSubparagraphLeaf key={i} leaf={s} />);
  });
  flushRun("end");

  return (
    <div className="mt-2 space-y-1">
      {intro}
      {children}
    </div>
  );
}

export function CollapsedRun({
  leaves,
  forceShowAll,
}: {
  leaves: DiffSubparagraph[];
  forceShowAll: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const open = expanded || forceShowAll;

  if (leaves.length === 0) return null;

  if (open) {
    return (
      <div className="space-y-1">
        {leaves.map((s, i) => (
          <div key={i} className="flex gap-2 pl-6 mt-1">
            {s.label && (
              <span className="font-mono text-xs leading-[1.75] shrink-0 text-gray-400">
                {renderLabel(s.label)}
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

  const first = leaves[0].label;
  const last = leaves[leaves.length - 1].label;
  const range = leaves.length === 1 ? first : `${first}–${last}`;

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
