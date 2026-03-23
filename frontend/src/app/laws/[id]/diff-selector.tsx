"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LawVersionSummary } from "@/lib/api";

export default function DiffSelector({
  lawId,
  versions,
}: {
  lawId: number;
  versions: LawVersionSummary[];
}) {
  const [versionA, setVersionA] = useState("");
  const [versionB, setVersionB] = useState("");
  const router = useRouter();

  if (versions.length < 2) return null;

  function handleCompare() {
    if (versionA && versionB && versionA !== versionB) {
      router.push(`/laws/${lawId}/diff?a=${versionA}&b=${versionB}`);
    }
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 mb-6">
      <h3 className="text-sm font-semibold text-gray-900 mb-3">
        Compare Versions
      </h3>
      <div className="flex items-end gap-3">
        <div className="flex-1">
          <label className="block text-xs text-gray-500 mb-1">From</label>
          <select
            value={versionA}
            onChange={(e) => setVersionA(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          >
            <option value="">Select version...</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.date_in_force || v.ver_id}
                {v.is_current ? " (current)" : ""}
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs text-gray-500 mb-1">To</label>
          <select
            value={versionB}
            onChange={(e) => setVersionB(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          >
            <option value="">Select version...</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.date_in_force || v.ver_id}
                {v.is_current ? " (current)" : ""}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={handleCompare}
          disabled={!versionA || !versionB || versionA === versionB}
          className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        >
          Compare
        </button>
      </div>
    </div>
  );
}
