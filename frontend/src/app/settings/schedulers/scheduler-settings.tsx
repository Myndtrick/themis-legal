"use client";

import { useEffect, useState, useCallback } from "react";
import { api, type SchedulerSettingData } from "@/lib/api";
import { SchedulerCard } from "./scheduler-card";

const LABELS: Record<string, { label: string; emoji: string; source: string }> = {
  ro: { label: "Romanian Laws", emoji: "\uD83C\uDDF7\uD83C\uDDF4", source: "legislatie.just.ro" },
  eu: { label: "EU Laws", emoji: "\uD83C\uDDEA\uD83C\uDDFA", source: "EU Cellar API" },
};

export function SchedulerSettings() {
  const [settings, setSettings] = useState<SchedulerSettingData[]>([]);
  const [original, setOriginal] = useState<SchedulerSettingData[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  const fetchSettings = useCallback(async () => {
    try {
      const data = await api.settings.schedulers.list();
      setSettings(data);
      setOriginal(data);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load scheduler settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const isDirty = JSON.stringify(settings) !== JSON.stringify(original);

  const handleChange = (id: string, field: string, value: boolean | string | number) => {
    setSettings((prev) =>
      prev.map((s) => (s.id === id ? { ...s, [field]: value } : s))
    );
    setSaveSuccess(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const ro = settings.find((s) => s.id === "ro")!;
      const eu = settings.find((s) => s.id === "eu")!;
      await api.settings.schedulers.save({
        ro: { enabled: ro.enabled, frequency: ro.frequency, time_hour: ro.time_hour, time_minute: ro.time_minute },
        eu: { enabled: eu.enabled, frequency: eu.frequency, time_hour: eu.time_hour, time_minute: eu.time_minute },
      });
      // Refresh to get updated next_run_utc
      await fetchSettings();
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (e: any) {
      setError(e.message || "Failed to save scheduler settings");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="py-8 text-sm text-gray-400">Loading scheduler settings...</div>;
  }

  return (
    <div>
      {/* Header with Save */}
      <div className="flex justify-between items-center mb-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Version Check Schedulers</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Configure automatic checks for new law versions
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isDirty && (
            <span className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
              ● Unsaved changes
            </span>
          )}
          {saveSuccess && (
            <span className="text-xs text-green-600 bg-green-50 border border-green-200 px-2 py-0.5 rounded">
              ✓ Saved
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={!isDirty || saving}
            className={`px-4 py-1.5 text-sm font-medium rounded-md text-white transition-colors ${
              isDirty && !saving
                ? "bg-indigo-600 hover:bg-indigo-700"
                : "bg-gray-300 cursor-not-allowed"
            }`}
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg border border-red-200 mb-4 text-sm">
          {error}
        </div>
      )}

      {/* Two cards side-by-side */}
      <div className="flex gap-5">
        {settings.map((s) => {
          const meta = LABELS[s.id] || { label: s.id, emoji: "", source: "" };
          return (
            <SchedulerCard
              key={s.id}
              setting={s}
              label={meta.label}
              emoji={meta.emoji}
              source={meta.source}
              onChange={(field, value) => handleChange(s.id, field, value)}
              onRefresh={fetchSettings}
            />
          );
        })}
      </div>
    </div>
  );
}
