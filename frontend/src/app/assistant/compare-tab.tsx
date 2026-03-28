"use client";

import { useState, useEffect } from "react";
import { api, ModelConfig, CompareResponse } from "@/lib/api";

const PROVIDER_COLORS: Record<string, { bg: string; border: string; header: string }> = {
  anthropic: { bg: "bg-purple-50", border: "border-purple-200", header: "bg-purple-100" },
  mistral: { bg: "bg-orange-50", border: "border-orange-200", header: "bg-orange-100" },
  openai: { bg: "bg-green-50", border: "border-green-200", header: "bg-green-100" },
};

export function CompareTab() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<"full" | "pipeline_steps">("full");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.settings.models.list().then((m) => {
      // Filter out OCR-only models
      setModels(m.filter((model) => model.capabilities.includes("chat") && model.enabled));
    });
  }, []);

  const toggleModel = (id: string) => {
    setSelectedModels((prev) =>
      prev.includes(id)
        ? prev.filter((m) => m !== id)
        : prev.length < 5
          ? [...prev, id]
          : prev
    );
  };

  const runComparison = async () => {
    if (selectedModels.length < 2 || !question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.assistant.compare(question, selectedModels, mode);
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const getGridCols = (count: number) => {
    if (count <= 2) return "grid-cols-1 md:grid-cols-2";
    if (count === 3) return "grid-cols-1 md:grid-cols-3";
    return "grid-cols-1 md:grid-cols-2 xl:grid-cols-3";
  };

  const getModelProvider = (modelId: string) =>
    models.find((m) => m.id === modelId)?.provider || "openai";

  return (
    <div className="p-6 space-y-6">
      {/* Question Input */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Legal Question</label>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Ce spune legea despre protecția datelor personale?"
          className="w-full border border-gray-300 rounded-lg px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          rows={3}
        />
      </div>

      {/* Model Selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Select Models (2-5)
          <span className="ml-2 text-gray-400 font-normal">{selectedModels.length} selected</span>
        </label>
        <div className="flex flex-wrap gap-2">
          {models.map((model) => {
            const selected = selectedModels.includes(model.id);
            const colors = PROVIDER_COLORS[model.provider] || PROVIDER_COLORS.openai;
            return (
              <button
                key={model.id}
                onClick={() => toggleModel(model.id)}
                className={`px-3 py-1.5 text-sm rounded-full border transition-all ${
                  selected
                    ? `${colors.bg} ${colors.border} font-medium ring-2 ring-offset-1 ring-indigo-400`
                    : "bg-white border-gray-200 text-gray-600 hover:border-gray-400"
                }`}
              >
                {model.label}
                <span className="ml-1 text-xs opacity-60">{model.cost_tier}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Mode Toggle */}
      <div className="flex items-center gap-4">
        <label className="text-sm font-medium text-gray-700">Mode:</label>
        <div className="flex rounded-lg border border-gray-200 overflow-hidden">
          <button
            onClick={() => setMode("full")}
            className={`px-4 py-1.5 text-sm ${mode === "full" ? "bg-indigo-600 text-white" : "bg-white text-gray-600"}`}
          >
            Full Answer
          </button>
          <button
            onClick={() => setMode("pipeline_steps")}
            className={`px-4 py-1.5 text-sm ${mode === "pipeline_steps" ? "bg-indigo-600 text-white" : "bg-white text-gray-600"}`}
          >
            Pipeline Steps
          </button>
        </div>
      </div>

      {/* Compare Button */}
      <button
        onClick={runComparison}
        disabled={selectedModels.length < 2 || !question.trim() || loading}
        className="px-6 py-2.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? "Comparing..." : "Compare Models"}
      </button>

      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg border border-red-200">{error}</div>
      )}

      {/* Loading Skeletons */}
      {loading && (
        <div className={`grid ${getGridCols(selectedModels.length)} gap-4`}>
          {selectedModels.map((id) => (
            <div key={id} className="border border-gray-200 rounded-lg p-4 animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-1/2 mb-3" />
              <div className="space-y-2">
                <div className="h-3 bg-gray-200 rounded w-full" />
                <div className="h-3 bg-gray-200 rounded w-3/4" />
                <div className="h-3 bg-gray-200 rounded w-5/6" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Results Grid */}
      {result && (
        <div className={`grid ${getGridCols(result.results.length)} gap-4`}>
          {result.results.map((r) => {
            const colors = PROVIDER_COLORS[getModelProvider(r.model_id)] || PROVIDER_COLORS.openai;
            return (
              <div key={r.model_id} className={`rounded-lg border ${r.status === "error" ? "border-red-200" : colors.border} overflow-hidden`}>
                {/* Header */}
                <div className={`px-4 py-3 ${r.status === "error" ? "bg-red-50" : colors.header} flex items-center justify-between`}>
                  <span className="font-medium text-sm">{r.model_label}</span>
                  <span className="text-xs text-gray-500">{(r.duration_ms / 1000).toFixed(1)}s</span>
                </div>

                {/* Body */}
                <div className="p-4">
                  {r.status === "error" ? (
                    <p className="text-red-600 text-sm">{r.error}</p>
                  ) : (
                    <div className="text-sm text-gray-700 whitespace-pre-wrap">{r.answer}</div>
                  )}
                </div>

                {/* Footer */}
                {r.status === "success" && r.usage && (
                  <div className="px-4 py-2 bg-gray-50 border-t border-gray-100 flex items-center justify-between text-xs text-gray-500">
                    <span>{r.usage.input_tokens} in / {r.usage.output_tokens} out</span>
                    <span>${r.cost_usd.toFixed(4)}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
