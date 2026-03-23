"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function CheckUpdatesButton({ lawId }: { lawId: number }) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    has_update: boolean;
    message: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function handleCheck() {
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const res = await api.laws.checkUpdates(lawId);
      setResult(res);
      if (res.has_update) {
        router.refresh();
      }
    } catch {
      setError("Failed to check for updates. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleCheck}
        disabled={loading}
        className="px-3 py-1.5 text-sm font-medium text-blue-600 bg-blue-50 rounded hover:bg-blue-100 disabled:bg-gray-100 disabled:text-gray-400 transition-colors"
      >
        {loading ? "Checking..." : "Check for updates"}
      </button>
      {result && (
        <span
          className={`text-sm ${
            result.has_update ? "text-green-600" : "text-gray-500"
          }`}
        >
          {result.message}
        </span>
      )}
      {error && <span className="text-sm text-red-600">{error}</span>}
    </div>
  );
}
