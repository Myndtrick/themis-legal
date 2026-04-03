"use client";

import { useEffect, useRef, useState } from "react";
import { api, type DiscoveryProgress } from "@/lib/api";

interface Props {
  jobType: "ro" | "eu";
  onComplete: () => void;
}

export function DiscoveryProgressPanel({ jobType, onComplete }: Props) {
  const [progress, setProgress] = useState<DiscoveryProgress | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const completedRef = useRef(false);

  useEffect(() => {
    intervalRef.current = setInterval(async () => {
      try {
        const p = await api.settings.schedulers.progress(jobType);
        setProgress(p);

        if (!p.running && !completedRef.current) {
          completedRef.current = true;
          if (intervalRef.current) clearInterval(intervalRef.current);
          // Wait a moment so user can see the completed state before refreshing
          setTimeout(onComplete, 2000);
        }
      } catch {
        // Ignore polling errors
      }
    }, 2000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [jobType, onComplete]);

  if (!progress) {
    return (
      <div className="border-t border-gray-200 bg-gray-50 px-4 py-3">
        <div className="text-xs text-gray-500">Starting discovery...</div>
      </div>
    );
  }

  if (progress.running) {
    const pct = progress.total > 0 ? (progress.current / progress.total) * 100 : 0;
    return (
      <div className="border-t border-gray-200 bg-green-50 px-4 py-3">
        <div className="flex justify-between items-center mb-1.5">
          <div className="text-xs font-medium text-green-800">Running discovery...</div>
          <div className="text-xs text-gray-500">
            {progress.current} / {progress.total} laws
          </div>
        </div>
        <div className="bg-green-200 rounded h-1.5 overflow-hidden">
          <div
            className="bg-green-600 h-full rounded transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        {progress.current_law && (
          <div className="text-[10px] text-gray-500 mt-1.5 truncate">
            Checking: {progress.current_law}
          </div>
        )}
      </div>
    );
  }

  // Completed
  const r = progress.results;
  return (
    <div className="border-t border-gray-200 bg-green-50 px-4 py-3">
      <div className="flex justify-between items-center">
        <div className="text-xs font-medium text-green-800">✓ Discovery complete</div>
        <div className="text-xs text-gray-500">{r?.checked ?? 0} checked</div>
      </div>
      {r && (
        <div className="text-xs text-green-700 mt-1">
          {r.discovered} new version{r.discovered !== 1 ? "s" : ""} found · {r.errors} error{r.errors !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}
