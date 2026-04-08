"use client";

import { useState } from "react";
import { api, type BackfillNotesReport } from "@/lib/api";

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
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<BackfillNotesReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastMode, setLastMode] = useState<"dry" | "live" | null>(null);

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
    setRunning(true);
    setError(null);
    setReport(null);
    setLastMode(dryRun ? "dry" : "live");
    try {
      const r = await api.settings.maintenance.backfillNotes(dryRun);
      setReport(r);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Backfill failed";
      setError(msg);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <h3 className="text-base font-semibold text-gray-900">
            Paragraph-Notes Backfill
          </h3>
          <p className="mt-1 text-sm text-gray-600">
            Re-fetches every imported law version through the leropa parser and inserts any
            paragraph-level amendment notes that were previously dropped. Also populates the new{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">text_clean</code> column on
            articles and paragraphs by stripping inline{" "}
            <code className="rounded bg-gray-100 px-1 py-0.5 text-xs">(la &lt;date&gt;, …)</code>{" "}
            annotations.
          </p>
          <p className="mt-2 text-sm text-gray-600">
            <strong className="text-gray-800">Read-only on existing content:</strong> never
            modifies or deletes laws, versions, articles, paragraphs, or subparagraphs. A runtime
            guardrail aborts the job immediately if anything tries to. Idempotent — safe to
            re-run. Synchronous; for ~100 laws this may take 10–30 minutes.
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => run(true)}
          disabled={running}
          className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running && lastMode === "dry" ? "Running dry-run…" : "Dry run"}
        </button>
        <button
          type="button"
          onClick={() => run(false)}
          disabled={running}
          className="rounded-md border border-transparent bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running && lastMode === "live" ? "Running live…" : "Live run"}
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <strong className="font-semibold">Error:</strong> {error}
        </div>
      )}

      {report && <ReportPanel report={report} />}
    </div>
  );
}

function ReportPanel({ report }: { report: BackfillNotesReport }) {
  const ok =
    report.versions_failed === 0 && report.errors.length === 0;
  return (
    <div className="mt-4 rounded-md border border-gray-200 bg-gray-50 p-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-900">
          {report.dry_run ? "Dry run report" : "Live run report"}
        </div>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
            ok
              ? "bg-green-100 text-green-800"
              : "bg-amber-100 text-amber-800"
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
        <Row
          label="Paragraph notes to insert"
          value={report.paragraph_notes_to_insert}
        />
        <Row
          label="Article notes to insert"
          value={report.article_notes_to_insert}
        />
        <Row label="text_clean writes" value={report.text_clean_writes} />
      </dl>

      {report.unknown_paragraph_labels.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-gray-600">
            Unknown paragraph labels ({report.unknown_paragraph_labels.length}, showing up to 50)
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
            Errors ({report.errors.length}, showing up to 50)
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
      <dd
        className={`text-base font-semibold ${
          warn ? "text-amber-700" : "text-gray-900"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
