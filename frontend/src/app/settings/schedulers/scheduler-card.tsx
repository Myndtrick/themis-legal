"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type SchedulerSettingData } from "@/lib/api";
import { DiscoveryProgressPanel } from "./discovery-progress";

const FREQUENCY_OPTIONS = [
  { value: "daily", label: "Every day" },
  { value: "every_3_days", label: "Every 3 days" },
  { value: "weekly", label: "Once a week" },
  { value: "monthly", label: "Once a month" },
];

interface Props {
  setting: SchedulerSettingData;
  label: string;
  emoji: string;
  source: string;
  onChange: (field: string, value: boolean | string | number) => void;
  onRefresh: () => void;
}

export function SchedulerCard({ setting, label, emoji, source, onChange, onRefresh }: Props) {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const jobType = setting.id as "ro" | "eu";

  // On mount: check if a discovery is already running for this kind. This is
  // what makes the "Running..." state survive a page refresh.
  useEffect(() => {
    let cancelled = false;
    api.jobs
      .list({ kind: `discover_${jobType}`, active: true, limit: 1 })
      .then((res) => {
        if (cancelled) return;
        if (res.jobs.length > 0) {
          setActiveJobId(res.jobs[0].id);
          setRunning(true);
        }
      })
      .catch(() => {
        /* ignore */
      });
    return () => {
      cancelled = true;
    };
  }, [jobType]);

  const handleRunNow = async () => {
    setRunError(null);
    try {
      const res = await api.settings.schedulers.triggerDiscovery(jobType);
      setActiveJobId(res.job_id);
      setRunning(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to start";
      setRunError(msg);
      setTimeout(() => setRunError(null), 3000);
    }
  };

  const handleComplete = useCallback(() => {
    setRunning(false);
    setActiveJobId(null);
    onRefresh();
  }, [onRefresh]);

  const formatTime = (hour: number, minute: number) =>
    `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;

  return (
    <div className="flex-1 border border-gray-200 rounded-xl bg-white overflow-hidden">
      <div className="p-4">
        {/* Header with toggle */}
        <div className="flex justify-between items-center mb-4">
          <div>
            <div className="font-semibold text-gray-900">
              {emoji} {label}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">Source: {source}</div>
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`text-xs font-medium ${setting.enabled ? "text-green-600" : "text-gray-400"}`}>
              {setting.enabled ? "Enabled" : "Disabled"}
            </span>
            <button
              onClick={() => onChange("enabled", !setting.enabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                setting.enabled ? "bg-indigo-600" : "bg-gray-200"
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                  setting.enabled ? "translate-x-6" : "translate-x-1"
                }`}
              />
            </button>
          </div>
        </div>

        {/* Controls — dimmed when disabled */}
        <div className={setting.enabled ? "" : "opacity-40 pointer-events-none"}>
          {/* Frequency */}
          <div className="mb-3">
            <label className="block text-xs font-medium text-gray-700 mb-1">Frequency</label>
            <select
              value={setting.frequency}
              onChange={(e) => onChange("frequency", e.target.value)}
              className="w-full border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-white text-gray-900"
            >
              {FREQUENCY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Time */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-700 mb-1">Time of day</label>
            <div className="flex items-center gap-2">
              <input
                type="time"
                value={formatTime(setting.time_hour, setting.time_minute)}
                onChange={(e) => {
                  const [h, m] = e.target.value.split(":").map(Number);
                  onChange("time_hour", h);
                  onChange("time_minute", m);
                }}
                className="border border-gray-300 rounded-md px-2.5 py-1.5 text-sm bg-white text-gray-900"
              />
              <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">UTC</span>
            </div>
          </div>
        </div>

        {/* Last / Next run */}
        <div className="bg-gray-50 rounded-lg px-3 py-2.5 mb-3">
          <div className="flex justify-between mb-1">
            <span className="text-xs text-gray-500">Last run</span>
            <span className="text-xs text-gray-900 font-medium">
              {setting.last_run_at
                ? new Date(setting.last_run_at).toLocaleString("en-GB", { timeZone: "UTC", dateStyle: "short", timeStyle: "short" }) + " UTC"
                : "Never"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-xs text-gray-500">Next run</span>
            <span className="text-xs text-indigo-600 font-medium">
              {!setting.enabled
                ? "\u2014"
                : setting.next_run_utc
                  ? new Date(setting.next_run_utc).toLocaleString("en-GB", { timeZone: "UTC", dateStyle: "short", timeStyle: "short" }) + " UTC"
                  : "\u2014"}
            </span>
          </div>
        </div>

        {/* Run Now */}
        <button
          onClick={handleRunNow}
          disabled={running}
          className={`w-full rounded-md py-2 text-sm font-medium text-white transition-colors ${
            running
              ? "bg-gray-400 cursor-not-allowed"
              : "bg-indigo-600 hover:bg-indigo-700"
          }`}
        >
          {running ? "Running..." : "\u25B6 Run Now"}
        </button>
        {runError && (
          <div className="text-xs text-red-600 mt-1.5">{runError}</div>
        )}
      </div>

      {/* Progress panel */}
      {running && (
        <DiscoveryProgressPanel
          jobType={jobType}
          jobId={activeJobId}
          onComplete={handleComplete}
        />
      )}
    </div>
  );
}
