"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useJobPolling } from "@/lib/useJobPolling";

interface Props {
  jobType: "ro" | "eu";
  /** Job id returned by triggerDiscovery, or null to look one up. */
  jobId: string | null;
  onComplete: () => void;
}

/**
 * Renders progress for a discovery job and reports completion to the parent.
 *
 * Resumability: if `jobId` is null on mount (e.g. after a page refresh), we
 * query the jobs API for an active discover_<jobType> job and adopt it. That
 * way the user can navigate away and return without losing the run.
 */
export function DiscoveryProgressPanel({ jobType, jobId, onComplete }: Props) {
  const [resolvedJobId, setResolvedJobId] = useState<string | null>(jobId);
  const completedRef = useRef(false);

  // Sync prop changes (e.g. parent triggers a new run)
  useEffect(() => {
    completedRef.current = false;
    setResolvedJobId(jobId);
  }, [jobId]);

  // If we don't have a job id, look for an in-flight job to resume.
  useEffect(() => {
    if (resolvedJobId) return;
    let cancelled = false;
    api.jobs
      .list({ kind: `discover_${jobType}`, active: true, limit: 1 })
      .then((res) => {
        if (cancelled) return;
        if (res.jobs.length > 0) setResolvedJobId(res.jobs[0].id);
      })
      .catch(() => {
        /* no in-flight job */
      });
    return () => {
      cancelled = true;
    };
  }, [jobType, resolvedJobId]);

  const { job } = useJobPolling(resolvedJobId);

  // When the job reaches a terminal state, briefly show the completion strip
  // and then notify the parent (refreshes the scheduler list).
  useEffect(() => {
    if (!job) return;
    if (completedRef.current) return;
    if (job.status === "succeeded" || job.status === "failed") {
      completedRef.current = true;
      const t = setTimeout(onComplete, 2000);
      return () => clearTimeout(t);
    }
  }, [job, onComplete]);

  if (!job) {
    return (
      <div className="border-t border-gray-200 bg-gray-50 px-4 py-3">
        <div className="text-xs text-gray-500">Starting discovery...</div>
      </div>
    );
  }

  if (job.status === "running" || job.status === "pending") {
    const total = job.total ?? 0;
    const current = job.current ?? 0;
    const pct = total > 0 ? (current / total) * 100 : 0;
    return (
      <div className="border-t border-gray-200 bg-green-50 px-4 py-3">
        <div className="flex justify-between items-center mb-1.5">
          <div className="text-xs font-medium text-green-800">Running discovery...</div>
          <div className="text-xs text-gray-500">
            {current} / {total} laws
          </div>
        </div>
        <div className="bg-green-200 rounded h-1.5 overflow-hidden">
          <div
            className="bg-green-600 h-full rounded transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
        {job.phase && (
          <div className="text-[10px] text-gray-500 mt-1.5 truncate">
            {job.phase}
          </div>
        )}
      </div>
    );
  }

  if (job.status === "failed") {
    const msg = job.error?.message || "Discovery failed";
    return (
      <div className="border-t border-gray-200 bg-red-50 px-4 py-3">
        <div className="text-xs font-medium text-red-800">✕ Discovery failed</div>
        <div className="text-xs text-red-700 mt-1">{msg}</div>
      </div>
    );
  }

  // Succeeded
  const r = (job.result ?? null) as
    | { checked?: number; discovered?: number; errors?: number }
    | null;
  return (
    <div className="border-t border-gray-200 bg-green-50 px-4 py-3">
      <div className="flex justify-between items-center">
        <div className="text-xs font-medium text-green-800">✓ Discovery complete</div>
        <div className="text-xs text-gray-500">{r?.checked ?? 0} checked</div>
      </div>
      {r && (
        <div className="text-xs text-green-700 mt-1">
          {r.discovered ?? 0} new version{(r.discovered ?? 0) !== 1 ? "s" : ""} found · {r.errors ?? 0} error{(r.errors ?? 0) !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}
