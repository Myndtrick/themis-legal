"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  TERMINAL_JOB_STATUSES,
  type BackfillNotesReport,
  type JobData,
} from "@/lib/api";

const BACKFILL_KIND = "backfill_notes";
const POLL_INTERVAL_MS = 1500;

export function MaintenancePanel() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">Maintenance</h2>
        <p className="mt-1 text-sm text-gray-600">
          One-off backfill and data-migration operations. Read each card before clicking.
        </p>
      </div>

      <ParagraphNotesBackfillCard />
    </div>
  );
}

function ParagraphNotesBackfillCard() {
  const [job, setJob] = useState<JobData | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const pollOnce = useCallback(async (jobId: string) => {
    try {
      const fresh = await api.jobs.get(jobId);
      setJob(fresh);
      if (TERMINAL_JOB_STATUSES.has(fresh.status)) {
        stopPolling();
      }
    } catch (e) {
      // Transient network error — keep polling, the next tick may recover.
      // Only surface if it persists; for now, swallow and let the next poll try.
    }
  }, [stopPolling]);

  const startPolling = useCallback((jobId: string) => {
    stopPolling();
    pollOnce(jobId); // immediate first read so the UI updates without waiting
    pollRef.current = setInterval(() => pollOnce(jobId), POLL_INTERVAL_MS);
  }, [pollOnce, stopPolling]);

  // On mount: check if there's already an active backfill job and resume polling.
  // This is what makes the progress survive a page refresh.
  useEffect(() => {
    let cancelled = false;
    api.jobs
      .list({ kind: BACKFILL_KIND, active: true, limit: 1 })
      .then((res) => {
        if (cancelled) return;
        if (res.jobs.length > 0) {
          const active = res.jobs[0];
          setJob(active);
          startPolling(active.id);
        }
      })
      .catch(() => {
        /* ignore — the user can always click a button */
      });
    return () => {
      cancelled = true;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async (dryRun: boolean) => {
    if (!dryRun) {
      const ok = window.confirm(
        "Live run: this will write paragraph-level amendment notes and text_clean to the production database. " +
          "It is additive (no existing data is modified or deleted) and a runtime guardrail blocks any forbidden mutation, " +
          "but please confirm you have a recent SQLite snapshot before continuing.\n\n" +
          "Proceed with the live run?"
      );
      if (!ok) return;
    }
    setStartError(null);
    setStarting(true);
    setJob(null);
    try {
      const res = await api.settings.maintenance.startBackfillNotes(dryRun);
      // Fetch the freshly-created job row so we have its full state to render
      const fresh = await api.jobs.get(res.job_id);
      setJob(fresh);
      startPolling(res.job_id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to start backfill";
      setStartError(msg);
    } finally {
      setStarting(false);
    }
  };

  const isActive = job !== null && !TERMINAL_JOB_STATUSES.has(job.status);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <h3 className="text-base font-semibold text-gray-900">
            Paragraph-Notes Backfill
          </h3>
          <p className="mt-1 text-sm text-gray-600">
            Re-fetches every imported Romanian law version through the leropa parser and inserts
            any paragraph-level amendment notes that were previously dropped. Also populates the
            new <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">text_clean</code> column
            on articles and paragraphs by stripping inline{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">(la &lt;date&gt;, …)</code>{" "}
            annotations. EU laws are skipped.
          </p>
          <p className="mt-2 text-sm text-gray-600">
            <strong className="text-gray-800">Read-only on existing content:</strong> never
            modifies or deletes laws, versions, articles, paragraphs, or subparagraphs. A runtime
            guardrail aborts the job immediately if anything tries to. Idempotent — safe to
            re-run. The backfill runs in the background; you can navigate away and come back.
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => run(true)}
          disabled={starting || isActive}
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Dry run
        </button>
        <button
          type="button"
          onClick={() => run(false)}
          disabled={starting || isActive}
          className="rounded-md border border-transparent bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Live run
        </button>
        {isActive && (
          <span className="ml-2 self-center text-xs text-gray-500">
            Job running — leave this page open or come back later
          </span>
        )}
      </div>

      {startError && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <strong className="font-semibold">Error:</strong> {startError}
        </div>
      )}

      {job && <JobPanel job={job} />}
    </div>
  );
}

function JobPanel({ job }: { job: JobData }) {
  const status = job.status;
  const isTerminal = TERMINAL_JOB_STATUSES.has(status);
  const params = (job.params ?? {}) as { dry_run?: boolean };
  const dryRun = params.dry_run ?? true;

  if (status === "pending" || status === "running") {
    return (
      <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4">
        <ProgressHeader title={dryRun ? "Dry run in progress" : "Live run in progress"} status="running" />
        <ProgressBar current={job.current ?? 0} total={job.total ?? 0} />
        <div className="mt-2 text-xs text-gray-600">
          {job.phase ?? "Starting…"}
        </div>
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-4">
        <ProgressHeader title={dryRun ? "Dry run failed" : "Live run failed"} status="failed" />
        <div className="mt-2 text-sm text-red-800">
          {job.error?.message ?? "The backfill job failed without a message."}
        </div>
      </div>
    );
  }

  // succeeded
  const report = (job.result ?? null) as BackfillNotesReport | null;
  if (!report) {
    return (
      <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4">
        <ProgressHeader title="Backfill completed" status="succeeded" />
        <div className="mt-2 text-xs text-gray-500">No report data was returned.</div>
      </div>
    );
  }
  return <ReportPanel report={report} />;
}

function ProgressHeader({
  title,
  status,
}: {
  title: string;
  status: "running" | "failed" | "succeeded";
}) {
  const styles = {
    running: "bg-blue-100 text-blue-800",
    failed: "bg-red-100 text-red-800",
    succeeded: "bg-green-100 text-green-800",
  } as const;
  const labels = {
    running: "Running",
    failed: "Failed",
    succeeded: "Done",
  } as const;
  return (
    <div className="flex items-center justify-between">
      <div className="text-sm font-semibold text-gray-900">{title}</div>
      <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status]}`}>
        {labels[status]}
      </span>
    </div>
  );
}

function ProgressBar({ current, total }: { current: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between text-xs text-gray-700">
        <span>
          {total > 0 ? `${current} / ${total} versions` : "Preparing…"}
        </span>
        <span>{total > 0 ? `${pct}%` : ""}</span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full bg-indigo-600 transition-all duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function ReportPanel({ report }: { report: BackfillNotesReport }) {
  const ok = report.versions_failed === 0 && report.errors.length === 0;
  return (
    <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-900">
          {report.dry_run ? "Dry run report" : "Live run report"}
        </div>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
            ok ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800"
          }`}
        >
          {ok ? "OK" : "Check warnings"}
        </span>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
        <Row label="Versions processed" value={report.versions_processed} />
        <Row
          label="Versions failed"
          value={report.versions_failed}
          warn={report.versions_failed > 0}
        />
        <Row label="Paragraph notes to insert" value={report.paragraph_notes_to_insert} />
        <Row label="Article notes to insert" value={report.article_notes_to_insert} />
        <Row label="text_clean writes" value={report.text_clean_writes} />
      </dl>

      {report.unknown_paragraph_labels.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-gray-600">
            Unknown paragraph labels ({report.unknown_paragraph_labels.length})
          </div>
          <ul className="mt-1 max-h-40 list-disc overflow-auto pl-5 text-xs text-gray-700">
            {report.unknown_paragraph_labels.map((s, i) => (
              <li key={i} className="font-mono">
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.errors.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-red-700">
            Errors ({report.errors.length})
          </div>
          <ul className="mt-1 max-h-40 list-disc overflow-auto pl-5 text-xs text-red-800">
            {report.errors.map((s, i) => (
              <li key={i} className="font-mono">
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.dry_run && ok && (
        <p className="mt-4 text-xs text-gray-600">
          Nothing was persisted. If the numbers look right, click <strong>Live run</strong> to
          actually write the data.
        </p>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  warn = false,
}: {
  label: string;
  value: number;
  warn?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className={`text-base font-semibold ${warn ? "text-amber-700" : "text-gray-900"}`}>
        {value}
      </dd>
    </div>
  );
}
