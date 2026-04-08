"use client";

import { useEffect, useState } from "react";
import { api, type SchedulerRunLogData } from "@/lib/api";

interface Props {
  schedulerId: "ro" | "eu";
  /** Bumped by the parent after a manual run completes; triggers a refetch. */
  refreshKey: number;
}

export function SchedulerActivityTable({ schedulerId, refreshKey }: Props) {
  const [rows, setRows] = useState<SchedulerRunLogData[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.settings.schedulers
      .listLogs(schedulerId, 20)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load activity");
      });
    return () => {
      cancelled = true;
    };
  }, [schedulerId, refreshKey]);

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    });

  return (
    <div className="border-t border-gray-100 px-4 py-3">
      <div className="text-xs font-semibold text-gray-700 mb-2">Recent activity</div>
      {error && <div className="text-xs text-red-600">{error}</div>}
      {!error && rows === null && (
        <div className="text-xs text-gray-400">Loading…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="text-xs text-gray-400">No runs recorded yet.</div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="max-h-60 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500 sticky top-0 bg-white">
              <tr>
                <th className="text-left font-medium py-1 pr-2">Time</th>
                <th className="text-left font-medium py-1 pr-2">Trigger</th>
                <th className="text-right font-medium py-1 pr-2">Checked</th>
                <th className="text-right font-medium py-1 pr-2">New</th>
                <th className="text-right font-medium py-1">Errors</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="py-1 pr-2 text-gray-900">{formatTime(r.ran_at)}</td>
                  <td className="py-1 pr-2">
                    <span
                      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${
                        r.trigger === "manual"
                          ? "bg-amber-100 text-amber-700"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {r.trigger === "manual" ? "manual" : "auto"}
                    </span>
                  </td>
                  <td className="py-1 pr-2 text-right text-gray-900">{r.laws_checked}</td>
                  <td className="py-1 pr-2 text-right text-gray-900">{r.new_versions}</td>
                  <td
                    className={`py-1 text-right font-medium ${
                      r.errors > 0 ? "text-red-600" : "text-gray-400"
                    }`}
                  >
                    {r.errors}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
