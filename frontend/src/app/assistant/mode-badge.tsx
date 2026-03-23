"use client";

const MODE_LABELS: Record<string, string> = {
  qa: "Q&A",
  memo: "Legal Memo",
  comparison: "Version Comparison",
  compliance: "Compliance Check",
  checklist: "Checklist",
};

export function ModeBadge({ mode }: { mode: string | null }) {
  if (!mode) return null;

  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-700">
      {MODE_LABELS[mode] || mode}
    </span>
  );
}
