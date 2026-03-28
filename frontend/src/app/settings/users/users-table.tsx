"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface WhitelistEntry {
  email: string;
  added_by: string;
  created_at: string;
  is_admin: boolean;
}

export function UsersTable() {
  const [entries, setEntries] = useState<WhitelistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [adding, setAdding] = useState(false);

  const load = async () => {
    try {
      setLoading(true);
      const data = await apiFetch<WhitelistEntry[]>("/api/admin/whitelist");
      setEntries(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const addEmail = async () => {
    if (!newEmail.trim()) return;
    setAdding(true);
    try {
      await apiFetch("/api/admin/whitelist", {
        method: "POST",
        body: JSON.stringify({ email: newEmail.trim().toLowerCase() }),
      });
      setNewEmail("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add");
    } finally {
      setAdding(false);
    }
  };

  const removeEmail = async (email: string) => {
    try {
      await apiFetch(`/api/admin/whitelist/${encodeURIComponent(email)}`, {
        method: "DELETE",
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove");
    }
  };

  if (loading) return <p className="text-gray-400 py-4">Loading users...</p>;

  return (
    <div>
      {error && (
        <div className="mb-4 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="flex gap-2 mb-6">
        <input
          type="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addEmail()}
          placeholder="email@example.com"
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
        <button
          onClick={addEmail}
          disabled={adding || !newEmail.trim()}
          className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {adding ? "Adding..." : "Add Email"}
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Email</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Role</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Added By</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Date</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.email} className="border-b border-gray-100 last:border-0">
                <td className="px-4 py-3 text-gray-900">{entry.email}</td>
                <td className="px-4 py-3">
                  {entry.is_admin ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-700">
                      Admin
                    </span>
                  ) : (
                    <span className="text-gray-500">User</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500">{entry.added_by}</td>
                <td className="px-4 py-3 text-gray-500">
                  {new Date(entry.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 text-right">
                  {!entry.is_admin && (
                    <button
                      onClick={() => removeEmail(entry.email)}
                      className="text-red-600 hover:text-red-800 text-xs font-medium"
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
