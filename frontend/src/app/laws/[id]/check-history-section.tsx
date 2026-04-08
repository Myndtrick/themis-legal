"use client";

import { useEffect, useState } from "react";
import { api, type LawCheckLogRowData } from "@/lib/api";

interface Props {
  lawId: number;
  /** Bumped by the parent after a check completes; triggers a refetch. */
  refreshKey: number;
}

export default function CheckHistorySection({ lawId, refreshKey }: Props) {
  const [rows, setRows] = useState<LawCheckLogRowData[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api.laws
      .listCheckLogs(lawId, 20)
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load check history.");
      });
    return () => {
      cancelled = true;
    };
  }, [lawId, refreshKey]);

  const formatTime = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      dateStyle: "short",
      timeStyle: "short",
    });

  const userShortName = (email: string | null) =>
    email ? email.split("@")[0] : "—";

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="text-sm font-semibold text-gray-900 mb-3">
        Recent update checks
      </div>

      {error && <div className="text-xs text-red-600">{error}</div>}
      {!error && rows === null && (
        <div className="text-xs text-gray-400">Loading…</div>
      )}
      {!error && rows !== null && rows.length === 0 && (
        <div className="text-xs text-gray-400">No update checks recorded yet.</div>
      )}
      {!error && rows !== null && rows.length > 0 && (
        <div className="max-h-60 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500 sticky top-0 bg-white">
              <tr>
                <th className="text-left font-medium py-1 pr-2">Time</th>
                <th className="text-right font-medium py-1 pr-2">New</th>
                <th className="text-left font-medium py-1 pr-2">Result</th>
                <th className="text-left font-medium py-1">By</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="py-1 pr-2 text-gray-900 whitespace-nowrap">
                    {formatTime(r.checked_at)}
                  </td>
                  <td
                    className={`py-1 pr-2 text-right ${
                      r.new_versions > 0 ? "text-gray-900 font-medium" : "text-gray-400"
                    }`}
                  >
                    {r.new_versions}
                  </td>
                  <td className="py-1 pr-2">
                    {r.status === "ok" ? (
                      <span className="text-green-700">OK</span>
                    ) : (
                      <span
                        className="text-red-600"
                        title={r.error_message ?? "Error"}
                      >
                        Error
                      </span>
                    )}
                  </td>
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
