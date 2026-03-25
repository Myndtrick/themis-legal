"use client";

import { useState } from "react";
import { AnnexData } from "@/lib/api";

/**
 * Format raw annex text into structured segments for display.
 * Inserts line breaks before numbered items, lettered sub-items,
 * and dashed separators that leropa collapses into a single string.
 */
function formatAnnexText(raw: string): { type: "title" | "separator" | "note" | "item" | "text"; content: string }[] {
  // First split off [Modificare: ...] notes
  const chunks = raw.split(/(\[Modificare:[^\]]*\])/g);
  const segments: { type: "title" | "separator" | "note" | "item" | "text"; content: string }[] = [];

  for (const chunk of chunks) {
    if (!chunk.trim()) continue;

    if (chunk.startsWith("[Modificare:")) {
      segments.push({ type: "note", content: chunk });
      continue;
    }

    // Split on the dashed separator lines (-----------)
    const dashParts = chunk.split(/(--{5,})/);
    for (const dashPart of dashParts) {
      if (!dashPart.trim()) continue;

      if (/^--{5,}$/.test(dashPart.trim())) {
        segments.push({ type: "separator", content: "" });
        continue;
      }

      // Check if this looks like a table (box-drawing chars)
      if (/[─│┌┐└┘├┤┬┴┼═║]/.test(dashPart)) {
        segments.push({ type: "text", content: dashPart.trim() });
        continue;
      }

      // For structured text: split before numbered items and lettered sub-items.
      // Match patterns like: "1. ", "2. ", "a) ", "b) ", "Pct. 1", "Lit. a)"
      // But be careful not to split on things like "nr. 123" or "art. 5"
      const lines = dashPart
        .replace(/(?<=[.;]) (\d{1,3})\. (?=[A-ZĂÂÎȘȚ])/g, "\n$1. ")
        .replace(/(?<=[.;…]) ([a-z]\)) /g, "\n$1 ")
        .replace(/(?<=[.;…]) (Pct\. \d)/g, "\n$1")
        .replace(/(?<=[.;…]) (Lit\. [a-z]\))/g, "\n$1")
        .split("\n");

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;

        // First line that's all caps or short = title
        if (i === 0 && segments.length === 0 && /^[A-ZĂÂÎȘȚÜÖ\s]{10,}/.test(line.split(/\d/)[0])) {
          segments.push({ type: "title", content: line });
        } else if (/^\d{1,3}\.\s/.test(line)) {
          segments.push({ type: "item", content: line });
        } else if (/^[a-z]\)\s/.test(line)) {
          segments.push({ type: "item", content: line });
        } else {
          // Append to previous text segment if exists, or create new
          const prev = segments[segments.length - 1];
          if (prev && prev.type === "text") {
            prev.content += " " + line;
          } else if (prev && prev.type === "item") {
            prev.content += " " + line;
          } else {
            segments.push({ type: "text", content: line });
          }
        }
      }
    }
  }

  return segments;
}

export function AnnexCard({ annex }: { annex: AnnexData }) {
  const [expanded, setExpanded] = useState(false);

  // Check if content is primarily a table
  const isTable = /[─│┌┐└┘├┤┬┴┼═║]/.test(annex.full_text);

  const segments = formatAnnexText(annex.full_text);

  return (
    <div className="border border-gray-200 bg-white rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-gray-50 transition-colors text-left"
      >
        <h4 className="font-semibold text-gray-900">{annex.title}</h4>
        <svg
          className={`w-5 h-5 text-gray-400 shrink-0 ml-3 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-100">
          <div className="mt-3 max-h-[600px] overflow-y-auto space-y-2">
            {isTable ? (
              <pre className="text-xs font-mono text-gray-700 whitespace-pre overflow-x-auto">
                {annex.full_text.replace(/\[Modificare:[^\]]*\]/g, "").trim()}
              </pre>
            ) : (
              segments.map((seg, i) => {
                switch (seg.type) {
                  case "title":
                    return (
                      <p key={i} className="font-semibold text-gray-900 text-sm">
                        {seg.content}
                      </p>
                    );
                  case "item":
                    return (
                      <p key={i} className="text-sm text-gray-700 leading-relaxed pl-4">
                        {seg.content}
                      </p>
                    );
                  case "separator":
                    return <hr key={i} className="border-gray-200 my-2" />;
                  case "text":
                    return (
                      <p key={i} className="text-sm text-gray-700 leading-relaxed">
                        {seg.content}
                      </p>
                    );
                  default:
                    return null;
                }
              })
            )}

            {/* Modification notes always rendered at the end */}
            {segments
              .filter((s) => s.type === "note")
              .map((seg, i) => (
                <div
                  key={`note-${i}`}
                  className="mt-3 pt-3 border-t border-dashed border-gray-200 text-xs text-gray-500 italic"
                >
                  {seg.content}
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
