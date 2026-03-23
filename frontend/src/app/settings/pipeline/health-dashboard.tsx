"use client";

import { useEffect, useState } from "react";
import { api, type HealthStats } from "@/lib/api";

export function HealthDashboard() {
  const [stats, setStats] = useState<HealthStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.settings.pipeline.health().then((data) => {
      setStats(data);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return <div className="text-sm text-gray-400 py-4">Loading health data...</div>;
  }

  if (!stats || stats.total_runs === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-sm text-gray-400">
        No pipeline runs yet. Health data will appear after the first Legal
        Assistant query.
      </div>
    );
  }

  const cards = [
    { label: "Total Runs", value: stats.total_runs, color: "text-gray-900" },
    { label: "OK", value: `${stats.ok_pct}%`, color: "text-green-600" },
    { label: "Warnings", value: `${stats.warning_pct}%`, color: "text-yellow-600" },
    { label: "Errors", value: `${stats.error_pct}%`, color: "text-red-600" },
    { label: "High Confidence", value: `${stats.avg_confidence_high_pct}%`, color: "text-indigo-600" },
    { label: "Avg Duration", value: `${stats.avg_duration_seconds}s`, color: "text-gray-700" },
    { label: "Avg Cost", value: `$${stats.avg_cost.toFixed(4)}`, color: "text-gray-700" },
  ];

  return (
    <div className="mb-6">
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        {cards.map((card) => (
          <div
            key={card.label}
            className="bg-white rounded-lg border border-gray-200 p-3 text-center"
          >
            <div className={`text-lg font-semibold ${card.color}`}>
              {card.value}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">{card.label}</div>
          </div>
        ))}
      </div>

      {stats.most_common_warnings.length > 0 && (
        <div className="mt-3 bg-yellow-50 border border-yellow-200 rounded-lg p-3">
          <div className="text-xs font-medium text-yellow-800 mb-1">
            Most Common Warnings
          </div>
          {stats.most_common_warnings.map((w, i) => (
            <div key={i} className="text-xs text-yellow-700">
              {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
