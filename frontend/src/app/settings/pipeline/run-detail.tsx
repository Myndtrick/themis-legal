"use client";

import { useEffect, useState } from "react";
import { api, type PipelineRunDetail as RunDetailType } from "@/lib/api";

export function RunDetail({
  runId,
  onBack,
}: {
  runId: string;
  onBack: () => void;
}) {
  const [run, setRun] = useState<RunDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);

  useEffect(() => {
    api.settings.pipeline.runDetail(runId).then((data) => {
      setRun(data);
      setLoading(false);
    });
  }, [runId]);

  if (loading) {
    return <div className="text-sm text-gray-400 py-4">Loading run...</div>;
  }

  if (!run) {
    return <div className="text-sm text-red-500 py-4">Run not found.</div>;
  }

  const totalTokensIn = run.api_calls.reduce((s, c) => s + c.tokens_in, 0);
  const totalTokensOut = run.api_calls.reduce((s, c) => s + c.tokens_out, 0);

  return (
    <div>
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onBack}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          &larr; Back
        </button>
        <h3 className="text-lg font-semibold text-gray-900">
          Run {run.run_id}
        </h3>
      </div>

      {/* Summary card */}
      <div className="bg-white rounded-lg border border-gray-200 p-4 mb-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <div>
          <div className="text-gray-500 text-xs">Status</div>
          <div className="font-medium">{run.overall_status}</div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">Confidence</div>
          <div className="font-medium">{run.overall_confidence || "—"}</div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">Duration</div>
          <div className="font-medium">
            {run.total_duration_seconds
              ? `${run.total_duration_seconds.toFixed(1)}s`
              : "—"}
          </div>
        </div>
        <div>
          <div className="text-gray-500 text-xs">Cost</div>
          <div className="font-medium">
            {run.estimated_cost ? `$${run.estimated_cost.toFixed(4)}` : "—"}
          </div>
        </div>
      </div>

      {/* Question */}
      {run.question_summary && (
        <div className="bg-gray-50 rounded-lg p-3 mb-4 text-sm text-gray-700">
          <span className="text-xs font-medium text-gray-500">Question: </span>
          {run.question_summary}
        </div>
      )}

      {/* Steps accordion */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden divide-y divide-gray-100">
        {run.steps.map((step) => (
          <div key={step.step_number}>
            <button
              onClick={() =>
                setExpandedStep(
                  expandedStep === step.step_number ? null : step.step_number
                )
              }
              className="w-full flex items-center gap-3 px-4 py-3 text-sm hover:bg-gray-50 transition-colors"
            >
              <span
                className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium text-white ${
                  step.status === "done"
                    ? "bg-green-500"
                    : step.status === "error"
                    ? "bg-red-500"
                    : "bg-gray-400"
                }`}
              >
                {step.step_number}
              </span>
              <span className="font-medium text-gray-700 flex-1 text-left">
                {step.step_name.replace(/_/g, " ")}
              </span>
              {step.prompt_id && (
                <span className="text-xs text-gray-400">
                  {step.prompt_id} v{step.prompt_version}
                </span>
              )}
              {step.duration_seconds != null && (
                <span className="text-xs text-gray-400">
                  {step.duration_seconds.toFixed(1)}s
                </span>
              )}
              {step.confidence && (
                <span
                  className={`text-xs px-1.5 py-0.5 rounded ${
                    step.confidence === "HIGH"
                      ? "bg-green-100 text-green-700"
                      : step.confidence === "MEDIUM"
                      ? "bg-yellow-100 text-yellow-700"
                      : "bg-red-100 text-red-700"
                  }`}
                >
                  {step.confidence}
                </span>
              )}
              <span className="text-gray-400 text-xs">
                {expandedStep === step.step_number ? "▲" : "▼"}
              </span>
            </button>

            {expandedStep === step.step_number && (
              <div className="px-4 pb-3 pt-0 text-xs text-gray-600 space-y-1 bg-gray-50">
                {step.input_summary && (
                  <div>
                    <span className="font-medium">Input: </span>
                    {step.input_summary}
                  </div>
                )}
                {step.output_summary && (
                  <div>
                    <span className="font-medium">Output: </span>
                    {step.output_summary}
                  </div>
                )}
                {step.warnings && (
                  <div className="text-yellow-700">
                    <span className="font-medium">Warnings: </span>
                    {step.warnings}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* API calls summary */}
      {run.api_calls.length > 0 && (
        <div className="mt-4 bg-white rounded-lg border border-gray-200 p-4">
          <h4 className="text-sm font-medium text-gray-700 mb-2">
            Claude API Calls
          </h4>
          <div className="space-y-1 text-xs text-gray-600">
            {run.api_calls.map((call, i) => (
              <div key={i} className="flex gap-4">
                <span className="w-32">{call.step_name.replace(/_/g, " ")}</span>
                <span>
                  {call.tokens_in} in / {call.tokens_out} out
                </span>
                <span className="text-gray-400">
                  {call.duration_seconds.toFixed(1)}s
                </span>
              </div>
            ))}
            <div className="border-t border-gray-200 pt-1 mt-1 font-medium">
              Total: {totalTokensIn} in / {totalTokensOut} out
            </div>
          </div>
        </div>
      )}

      {/* Flags */}
      {run.flags && (
        <div className="mt-4 bg-yellow-50 border border-yellow-200 rounded-lg p-3">
          <div className="text-xs font-medium text-yellow-800 mb-1">
            Flags &amp; Warnings
          </div>
          {JSON.parse(run.flags).map((flag: string, i: number) => (
            <div key={i} className="text-xs text-yellow-700">
              {flag}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
