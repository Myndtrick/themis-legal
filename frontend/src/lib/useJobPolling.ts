"use client";

import { useEffect, useRef, useState } from "react";

import { api, JobData, TERMINAL_JOB_STATUSES } from "./api";

/**
 * Poll a backend Job row by id until it reaches a terminal state.
 *
 * The whole point of jobs is that they are *resumable*: a parent component
 * can store a job_id in localStorage / URL params, and on remount this hook
 * will pick up polling the existing job rather than restarting any work.
 *
 * Pass `null` to pause polling (e.g. when no job is active).
 */
export function useJobPolling(
  jobId: string | null,
  options?: { intervalMs?: number }
): {
  job: JobData | null;
  isPolling: boolean;
  error: Error | null;
} {
  const intervalMs = options?.intervalMs ?? 1000;
  const [job, setJob] = useState<JobData | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isPolling, setIsPolling] = useState<boolean>(false);

  // Use a ref so the polling loop always sees the latest jobId without
  // re-tearing the timer on every render.
  const cancelledRef = useRef<boolean>(false);

  useEffect(() => {
    cancelledRef.current = false;

    if (!jobId) {
      setJob(null);
      setError(null);
      setIsPolling(false);
      return;
    }

    setIsPolling(true);
    setError(null);
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (cancelledRef.current) return;
      try {
        const next = await api.jobs.get(jobId);
        if (cancelledRef.current) return;
        setJob(next);
        if (TERMINAL_JOB_STATUSES.has(next.status)) {
          setIsPolling(false);
          return;
        }
      } catch (err) {
        if (cancelledRef.current) return;
        // 404 → job no longer exists. Treat as terminal so the UI can clear.
        const statusCode = (err as { statusCode?: number }).statusCode;
        if (statusCode === 404) {
          setJob(null);
          setError(new Error("Job no longer exists"));
          setIsPolling(false);
          return;
        }
        setError(err instanceof Error ? err : new Error(String(err)));
        // Keep polling on transient errors — the next tick may recover.
      }
      timer = setTimeout(tick, intervalMs);
    };

    tick();

    return () => {
      cancelledRef.current = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return { job, isPolling, error };
}
