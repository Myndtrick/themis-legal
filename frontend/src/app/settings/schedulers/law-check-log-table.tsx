"use client";

import { useEffect, useState } from "react";
import { api, type LawCheckLogData } from "@/lib/api";

export function LawCheckLogTable() {
  const [rows, setRows] = useState<LawCheckLogData[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.settings.schedulers
      .listLawCheckLogs(20)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load per-law check log.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    });

  const userShortName = (email: string | null) =>
    email ? email.split("@")[0] : "—";

  const hasErrors = (rows ?? []).some((r) => r.status === "error");

  return (
    <div className="mt-6 border border-gray-200 rounded-xl bg-white p-4">
      <div className="text-sm font-semibold text-gray-900 mb-2">
        Per-law update checks
      </div>
      <div className="text-xs text-gray-500 mb-3">
        Last 20 manual update checks across all laws
      </div>

      {error && <div className="text-xs text-red-600">{error}</div>}
      {!error && rows === null && (
        <div className="text-xs text-gray-400">Loading…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="text-xs text-gray-400">No per-law checks recorded yet.</div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500 sticky top-0 bg-white">
              <tr>
                <th className="text-left font-medium py-1 pr-2">Time</th>
                <th className="text-left font-medium py-1 pr-2">Source</th>
                <th className="text-left font-medium py-1 pr-2">Law</th>
                <th className="text-right font-medium py-1 pr-2">New</th>
                {hasErrors && (
                  <th className="text-right font-medium py-1 pr-2">Errors</th>
                )}
                <th className="text-left font-medium py-1">By</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="py-1 pr-2 text-gray-900 whitespace-nowrap">
                    {formatTime(r.checked_at)}
                  </td>
                  <td className="py-1 pr-2">
                    <span
                      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase ${
                        r.source === "ro"
                          ? "bg-blue-100 text-blue-700"
                          : "bg-purple-100 text-purple-700"
                      }`}
                    >
                      {r.source}
                    </span>
                  </td>
                  <td className="py-1 pr-2 text-gray-900 truncate max-w-xs" title={r.law_label}>
                    {r.law_label}
                  </td>
                  <td
                    className={`py-1 pr-2 text-right ${
                      r.new_versions > 0 ? "text-gray-900 font-medium" : "text-gray-400"
                    }`}
                  >
                    {r.new_versions}
                  </td>
                  {hasErrors && (
                    <td
                      className={`py-1 pr-2 text-right font-medium ${
                        r.status === "error" ? "text-red-600" : "text-gray-300"
                      }`}
                      title={r.error_message ?? undefined}
                    >
                      {r.status === "error" ? "1" : "0"}
                    </td>
                  )}
                  <td className="py-1 text-gray-600 truncate max-w-[8rem]" title={r.user_email ?? undefined}>
                    {userShortName(r.user_email)}
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
