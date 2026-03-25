"use client";

import { useState } from "react";
import { AnnexData } from "@/lib/api";

export function AnnexCard({ annex }: { annex: AnnexData }) {
  const [expanded, setExpanded] = useState(false);

  // Split text from modification notes
  const parts = annex.full_text.split(/(\[Modificare:.*?\])/s);

  // Check if content looks like it has table/box-drawing characters
  const hasBoxChars = /[─│┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬═║┌─┐├─┤└─┘]/.test(annex.full_text)
    || /[|].*[|].*[|]/.test(annex.full_text);

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
          <div
            className={`mt-3 text-sm text-gray-700 whitespace-pre-wrap leading-relaxed max-h-[600px] overflow-y-auto ${
              hasBoxChars ? "font-mono text-xs" : ""
            }`}
          >
            {parts.map((part, i) =>
              part.startsWith("[Modificare:") ? (
                <div
                  key={i}
                  className="mt-3 pt-3 border-t border-dashed border-gray-200 text-xs text-gray-500 italic font-sans"
                >
                  {part}
                </div>
              ) : (
                <span key={i}>{part}</span>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}
