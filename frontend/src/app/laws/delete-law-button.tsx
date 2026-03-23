"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function DeleteLawButton({
  lawId,
  lawTitle,
  versionCount,
}: {
  lawId: number;
  lawTitle: string;
  versionCount: number;
}) {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleDeleteAll() {
    setLoading(true);
    try {
      await api.laws.delete(lawId);
      router.refresh();
    } catch {
      alert("Failed to delete law. Please try again.");
    } finally {
      setLoading(false);
      setConfirming(false);
    }
  }

  async function handleDeleteOld() {
    setLoading(true);
    try {
      await api.laws.deleteOldVersions(lawId);
      router.refresh();
    } catch {
      alert("Failed to delete old versions. Please try again.");
    } finally {
      setLoading(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <div
        className="flex items-center gap-2 flex-wrap"
        onClick={(e) => e.preventDefault()}
      >
        <span className="text-xs text-gray-700">Delete:</span>
        <button
          onClick={handleDeleteAll}
          disabled={loading}
          className="px-2 py-1 text-xs font-medium text-white bg-red-600 rounded hover:bg-red-700 disabled:bg-gray-300"
        >
          {loading ? "..." : "Everything"}
        </button>
        {versionCount > 1 && (
          <button
            onClick={handleDeleteOld}
            disabled={loading}
            className="px-2 py-1 text-xs font-medium text-red-700 bg-red-50 border border-red-200 rounded hover:bg-red-100 disabled:bg-gray-300"
          >
            {loading ? "..." : "Old versions only"}
          </button>
        )}
        <button
          onClick={() => setConfirming(false)}
          className="px-2 py-1 text-xs font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.preventDefault();
        setConfirming(true);
      }}
      className="px-2 py-1 text-xs font-medium text-red-600 bg-red-50 rounded hover:bg-red-100 transition-colors"
    >
      Delete
    </button>
  );
}
