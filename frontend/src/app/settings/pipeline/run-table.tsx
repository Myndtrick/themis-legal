"use client";

import { useEffect, useState } from "react";
import { api, type PipelineRunSummary } from "@/lib/api";
import { RunDetail } from "./run-detail";

const STATUS_COLORS: Record<string, string> = {
  ok: "bg-green-100 text-green-700",
  warning: "bg-yellow-100 text-yellow-700",
  error: "bg-red-100 text-red-700",
  partial: "bg-orange-100 text-orange-700",
  running: "bg-blue-100 text-blue-700",
  paused: "bg-gray-100 text-gray-600",
};

export function RunTable() {
  const [runs, setRuns] = useState<PipelineRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [confidenceFilter, setConfidenceFilter] = useState("");

  useEffect(() => {
    const params: Record<string, string> = {};
    if (statusFilter) params.status = statusFilter;
    if (confidenceFilter) params.confidence = confidenceFilter;

    api.settings.pipeline.runs(params).then((data) => {
      setRuns(data);
      setLoading(false);
    });
  }, [statusFilter, confidenceFilter]);

  if (selectedRunId) {
    return (
      <RunDetail
        runId={selectedRunId}
        onBack={() => setSelectedRunId(null)}
      />
    );
  }

  return (
    <div>
      {/* Filters */}
      <div className="flex gap-3 mb-3">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-sm border border-gray-300 rounded-md px-2 py-1"
        >
          <option value="">All statuses</option>
          <option value="ok">OK</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="partial">Partial</option>
        </select>
        <select
          value={confidenceFilter}
          onChange={(e) => setConfidenceFilter(e.target.value)}
          className="text-sm border border-gray-300 rounded-md px-2 py-1"
        >
          <option value="">All confidence</option>
          <option value="HIGH">HIGH</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="LOW">LOW</option>
        </select>
      </div>

      {loading ? (
        <div className="text-sm text-gray-400 py-4">Loading runs...</div>
      ) : runs.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-sm text-gray-400">
          No pipeline runs found.
        </div>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-2 font-medium text-gray-600">
                  Run ID
                </th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">
                  Question
                </th>
                <th className="text-center px-4 py-2 font-medium text-gray-600">
                  Mode
                </th>
                <th className="text-center px-4 py-2 font-medium text-gray-600">
                  Status
                </th>
                <th className="text-center px-4 py-2 font-medium text-gray-600">
                  Confidence
                </th>
                <th className="text-right px-4 py-2 font-medium text-gray-600">
                  Duration
                </th>
                <th className="text-right px-4 py-2 font-medium text-gray-600">
                  Cost
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {runs.map((run) => (
                <tr
                  key={run.run_id}
                  onClick={() => setSelectedRunId(run.run_id)}
                  className="hover:bg-gray-50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-xs text-gray-500">
                    {run.run_id}
                  </td>
                  <td className="px-4 py-2 text-gray-700 max-w-xs truncate">
                    {run.question_summary || "—"}
                  </td>
                  <td className="px-4 py-2 text-center text-xs text-gray-500">
                    {run.mode || "—"}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <span
                      className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                        STATUS_COLORS[run.overall_status] ||
                        "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {run.overall_status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-center text-xs">
                    {run.overall_confidence || "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-gray-500">
                    {run.total_duration_seconds
                      ? `${run.total_duration_seconds.toFixed(1)}s`
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-gray-500">
                    {run.estimated_cost
                      ? `$${run.estimated_cost.toFixed(4)}`
                      : "—"}
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
