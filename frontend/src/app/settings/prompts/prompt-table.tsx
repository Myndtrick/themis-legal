"use client";

import { useEffect, useState } from "react";
import { api, type PromptSummary } from "@/lib/api";

export function PromptTable({
  onSelect,
}: {
  onSelect: (promptId: string) => void;
}) {
  const [prompts, setPrompts] = useState<PromptSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.settings.prompts.list().then((data) => {
      setPrompts(data);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return <div className="text-sm text-gray-400 py-4">Loading prompts...</div>;
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            <th className="text-left px-4 py-2.5 font-medium text-gray-600">
              Prompt ID
            </th>
            <th className="text-left px-4 py-2.5 font-medium text-gray-600">
              Description
            </th>
            <th className="text-center px-4 py-2.5 font-medium text-gray-600">
              Version
            </th>
            <th className="text-center px-4 py-2.5 font-medium text-gray-600">
              Status
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {prompts.map((p) => (
            <tr
              key={p.prompt_id}
              onClick={() => onSelect(p.prompt_id)}
              className="hover:bg-gray-50 cursor-pointer transition-colors"
            >
              <td className="px-4 py-2.5 font-mono text-xs text-indigo-600">
                {p.prompt_id}
              </td>
              <td className="px-4 py-2.5 text-gray-700">{p.description}</td>
              <td className="px-4 py-2.5 text-center text-gray-500">
                v{p.version_number}
              </td>
              <td className="px-4 py-2.5 text-center">
                <span
                  className={`inline-flex px-2 py-0.5 rounded text-xs font-medium ${
                    p.status === "ACTIVE"
                      ? "bg-green-100 text-green-700"
                      : p.status === "PENDING"
                      ? "bg-yellow-100 text-yellow-700"
                      : "bg-gray-100 text-gray-500"
                  }`}
                >
                  {p.status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
