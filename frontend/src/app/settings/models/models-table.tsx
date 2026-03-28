"use client";

import { useEffect, useState } from "react";
import { api, ModelConfig, ModelAssignment } from "@/lib/api";

const PROVIDER_COLORS: Record<string, string> = {
  anthropic: "bg-purple-100 text-purple-800",
  mistral: "bg-orange-100 text-orange-800",
  openai: "bg-green-100 text-green-800",
};

const COST_BADGES: Record<string, string> = {
  "$": "bg-gray-100 text-gray-600",
  "$$": "bg-blue-100 text-blue-700",
  "$$$": "bg-amber-100 text-amber-700",
};

const TASK_LABELS: Record<string, string> = {
  issue_classification: "Issue Classification",
  law_mapping: "Law Mapping",
  fast_general: "Fast General",
  article_selection: "Article Selection",
  answer_generation: "Answer Generation",
  diff_summary: "Diff Summary",
  ocr: "OCR",
};

const TASK_REQUIRED_CAPABILITY: Record<string, string> = {
  issue_classification: "chat",
  law_mapping: "chat",
  fast_general: "chat",
  article_selection: "chat",
  answer_generation: "chat",
  diff_summary: "chat",
  ocr: "ocr",
};

export function ModelsTable() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [assignments, setAssignments] = useState<ModelAssignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.settings.models.list(), api.settings.assignments.list()])
      .then(([m, a]) => {
        setModels(m);
        setAssignments(a);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const toggleModel = async (id: string, enabled: boolean) => {
    try {
      const updated = await api.settings.models.update(id, { enabled });
      setModels((prev) => prev.map((m) => (m.id === id ? updated : m)));
    } catch (e: any) {
      setError(e.message);
    }
  };

  const updateAssignment = async (task: string, modelId: string) => {
    try {
      const updated = await api.settings.assignments.update(task, modelId);
      setAssignments((prev) =>
        prev.map((a) => (a.task === task ? updated : a))
      );
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  };

  if (loading) return <div className="py-8 text-gray-400">Loading models...</div>;

  return (
    <div className="space-y-8">
      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg border border-red-200">
          {error}
        </div>
      )}

      {/* Models Table */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Available Models</h2>
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Provider</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Model</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cost</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Capabilities</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Enabled</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {models.map((model) => (
                <tr key={model.id} className={!model.enabled ? "opacity-50" : ""}>
                  <td className="px-4 py-3">
                    <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${PROVIDER_COLORS[model.provider] || "bg-gray-100"}`}>
                      {model.provider}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{model.label}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${COST_BADGES[model.cost_tier] || ""}`}>
                      {model.cost_tier}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {model.capabilities.map((cap) => (
                        <span key={cap} className="inline-flex px-2 py-0.5 text-xs bg-indigo-50 text-indigo-700 rounded">
                          {cap}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => toggleModel(model.id, !model.enabled)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                        model.enabled ? "bg-indigo-600" : "bg-gray-200"
                      }`}
                    >
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        model.enabled ? "translate-x-6" : "translate-x-1"
                      }`} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Task Assignments */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Pipeline Task Assignments</h2>
        <div className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
          {Object.entries(TASK_LABELS).map(([task, label]) => {
            const current = assignments.find((a) => a.task === task);
            const requiredCap = TASK_REQUIRED_CAPABILITY[task];
            const eligible = models.filter(
              (m) => m.enabled && m.capabilities.includes(requiredCap)
            );

            return (
              <div key={task} className="flex items-center justify-between">
                <div>
                  <span className="text-sm font-medium text-gray-900">{label}</span>
                  <span className="ml-2 text-xs text-gray-400">requires: {requiredCap}</span>
                </div>
                <select
                  value={current?.model_id || ""}
                  onChange={(e) => updateAssignment(task, e.target.value)}
                  className="text-sm border border-gray-300 rounded-md px-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  {eligible.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label} ({m.cost_tier})
                    </option>
                  ))}
                </select>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
