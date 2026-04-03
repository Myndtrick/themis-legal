"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function DeleteVersionsButton({
  lawId,
  oldVersionCount,
}: {
  lawId: number;
  oldVersionCount: number;
}) {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const router = useRouter();

  if (oldVersionCount === 0) return null;

  async function handleDelete() {
    setLoading(true);
    try {
      const res = await api.laws.deleteOldVersions(lawId);
      setResult(res.message);
      setConfirming(false);
      // Small delay to let the background deletion finish before refreshing
      setTimeout(() => router.refresh(), 500);
    } catch {
      alert("Failed to delete old versions. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mb-4">
      {!confirming && !result && (
        <button
          onClick={() => setConfirming(true)}
          className="px-3 py-1.5 text-sm font-medium text-red-600 bg-red-50 rounded hover:bg-red-100 transition-colors"
        >
          Delete {oldVersionCount} old version{oldVersionCount !== 1 ? "s" : ""} (keep current)
        </button>
      )}

      {confirming && (
        <div className="flex items-center gap-3 rounded-md bg-red-50 border border-red-200 p-3">
          <span className="text-sm text-red-700">
            Delete {oldVersionCount} old version{oldVersionCount !== 1 ? "s" : ""}? Only the current version will be kept.
          </span>
          <button
            onClick={handleDelete}
            disabled={loading}
            className="px-3 py-1 text-sm font-medium text-white bg-red-600 rounded hover:bg-red-700 disabled:bg-gray-300"
          >
            {loading ? "Deleting..." : "Confirm"}
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="px-3 py-1 text-sm font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200"
          >
            Cancel
          </button>
        </div>
      )}

      {result && (
        <div className="rounded-md bg-green-50 border border-green-200 p-3">
          <p className="text-sm text-green-700">{result}</p>
        </div>
      )}
    </div>
  );
}
