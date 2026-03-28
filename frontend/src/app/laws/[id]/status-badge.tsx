"use client";

import { useState } from "react";
import { apiFetch } from "@/lib/api";

const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  in_force: { label: "In Force", className: "bg-green-100 text-green-700" },
  repealed: { label: "Repealed", className: "bg-red-100 text-red-700" },
  partially_repealed: { label: "Partially Repealed", className: "bg-yellow-100 text-yellow-700" },
  superseded: { label: "Superseded", className: "bg-orange-100 text-orange-700" },
  unknown: { label: "Unknown", className: "bg-gray-100 text-gray-500" },
};

const STATUS_OPTIONS = ["in_force", "repealed", "partially_repealed", "superseded", "unknown"];

interface StatusBadgeProps {
  lawId: number;
  initialStatus: string;
  initialOverride: boolean;
}

export default function StatusBadge({ lawId, initialStatus, initialOverride }: StatusBadgeProps) {
  const [status, setStatus] = useState(initialStatus);
  const [override, setOverride] = useState(initialOverride);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  const config = STATUS_CONFIG[status] || STATUS_CONFIG.unknown;

  async function handleStatusChange(newStatus: string) {
    setSaving(true);
    try {
      const data = await apiFetch<{ status: string; status_override: boolean }>(
        `/api/laws/${lawId}/status`,
        {
          method: "PATCH",
          body: JSON.stringify({ status: newStatus, override: true }),
        }
      );
      setStatus(data.status);
      setOverride(data.status_override);
    } catch {
      // Silently fail
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  async function handleResetToAuto() {
    setSaving(true);
    try {
      const data = await apiFetch<{ status: string; status_override: boolean }>(
        `/api/laws/${lawId}/status`,
        {
          method: "PATCH",
          body: JSON.stringify({ status, override: false }),
        }
      );
      setStatus(data.status);
      setOverride(data.status_override);
    } catch {
      // Silently fail
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${config.className}`}>
        {config.label}
      </span>

      {override && (
        <span className="text-xs text-gray-400 italic">Manually set</span>
      )}

      {!editing ? (
        <button
          onClick={() => setEditing(true)}
          className="text-xs text-blue-600 hover:text-blue-800"
        >
          Edit
        </button>
      ) : (
        <div className="flex items-center gap-2">
          <select
            value={status}
            onChange={(e) => handleStatusChange(e.target.value)}
            disabled={saving}
            className="text-xs rounded border border-gray-300 px-2 py-1"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{STATUS_CONFIG[s]?.label || s}</option>
            ))}
          </select>
          {override && (
            <button
              onClick={handleResetToAuto}
              disabled={saving}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              Reset to auto
            </button>
          )}
          <button
            onClick={() => setEditing(false)}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
