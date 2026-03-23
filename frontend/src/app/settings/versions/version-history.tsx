"use client";

import { useEffect, useState } from "react";
import { api, type PromptSummary, type PromptVersionSummary, type PromptDetail } from "@/lib/api";
import { VersionDiff } from "./version-diff";

export function VersionHistory() {
  const [prompts, setPrompts] = useState<PromptSummary[]>([]);
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null);
  const [versions, setVersions] = useState<PromptVersionSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [diffVersions, setDiffVersions] = useState<[number, number] | null>(null);
  const [diffTexts, setDiffTexts] = useState<[string, string] | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.settings.prompts.list().then(setPrompts);
  }, []);

  useEffect(() => {
    if (!selectedPrompt) return;
    setLoading(true);
    setDiffVersions(null);
    setDiffTexts(null);
    api.settings.prompts.versions(selectedPrompt).then((data) => {
      setVersions(data);
      setLoading(false);
    });
  }, [selectedPrompt]);

  const handleDiff = async (vA: number, vB: number) => {
    if (!selectedPrompt) return;
    const [a, b] = await Promise.all([
      api.settings.prompts.getVersion(selectedPrompt, vA),
      api.settings.prompts.getVersion(selectedPrompt, vB),
    ]);
    setDiffVersions([vA, vB]);
    setDiffTexts([a.prompt_text, b.prompt_text]);
  };

  const handleRestore = async (version: number) => {
    if (!selectedPrompt) return;
    setMessage(null);
    try {
      const diff = await api.settings.prompts.restore(selectedPrompt, version);
      await api.settings.prompts.approve(selectedPrompt, diff.proposed_version);
      setMessage(`Restored v${version} as new active version.`);
      // Reload versions
      const data = await api.settings.prompts.versions(selectedPrompt);
      setVersions(data);
    } catch (e) {
      setMessage(`Error: ${(e as Error).message}`);
    }
  };

  if (diffVersions && diffTexts && selectedPrompt) {
    return (
      <div>
        <button
          onClick={() => {
            setDiffVersions(null);
            setDiffTexts(null);
          }}
          className="text-sm text-gray-500 hover:text-gray-700 mb-3"
        >
          &larr; Back to versions
        </button>
        <VersionDiff
          promptId={selectedPrompt}
          versionA={diffVersions[0]}
          versionB={diffVersions[1]}
          textA={diffTexts[0]}
          textB={diffTexts[1]}
        />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4">
        <select
          value={selectedPrompt || ""}
          onChange={(e) => setSelectedPrompt(e.target.value || null)}
          className="text-sm border border-gray-300 rounded-md px-3 py-2"
        >
          <option value="">Select a prompt to view history...</option>
          {prompts.map((p) => (
            <option key={p.prompt_id} value={p.prompt_id}>
              {p.prompt_id} — {p.description}
            </option>
          ))}
        </select>
      </div>

      {message && (
        <div
          className={`mb-3 text-sm px-3 py-2 rounded ${
            message.startsWith("Error")
              ? "bg-red-50 text-red-700"
              : "bg-green-50 text-green-700"
          }`}
        >
          {message}
        </div>
      )}

      {loading && (
        <div className="text-sm text-gray-400 py-4">Loading versions...</div>
      )}

      {selectedPrompt && !loading && versions.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-center px-4 py-2 font-medium text-gray-600">
                  Version
                </th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">
                  Date
                </th>
                <th className="text-center px-4 py-2 font-medium text-gray-600">
                  Status
                </th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">
                  Created By
                </th>
                <th className="text-left px-4 py-2 font-medium text-gray-600">
                  Note
                </th>
                <th className="text-right px-4 py-2 font-medium text-gray-600">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {versions.map((v) => (
                <tr key={v.version_number} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-center font-mono text-xs">
                    v{v.version_number}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {new Date(v.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-2 text-center">
                    <span
                      className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                        v.status === "ACTIVE"
                          ? "bg-green-100 text-green-700"
                          : v.status === "PENDING"
                          ? "bg-yellow-100 text-yellow-700"
                          : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {v.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {v.created_by}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500 max-w-xs truncate">
                    {v.modification_note || "—"}
                  </td>
                  <td className="px-4 py-2 text-right space-x-2">
                    {versions.length > 1 && (
                      <button
                        onClick={() => {
                          const activeV = versions.find(
                            (x) => x.status === "ACTIVE"
                          );
                          if (activeV && activeV.version_number !== v.version_number) {
                            handleDiff(v.version_number, activeV.version_number);
                          }
                        }}
                        className="text-xs text-indigo-600 hover:text-indigo-800"
                      >
                        Diff
                      </button>
                    )}
                    {v.status !== "ACTIVE" && (
                      <button
                        onClick={() => handleRestore(v.version_number)}
                        className="text-xs text-amber-600 hover:text-amber-800"
                      >
                        Restore
                      </button>
                    )}
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
