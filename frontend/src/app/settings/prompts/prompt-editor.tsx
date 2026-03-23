"use client";

import { useEffect, useState } from "react";
import { api, type PromptDetail } from "@/lib/api";
import { PromptDiffViewer } from "./prompt-diff-viewer";

export function PromptEditor({
  promptId,
  onBack,
}: {
  promptId: string;
  onBack: () => void;
}) {
  const [prompt, setPrompt] = useState<PromptDetail | null>(null);
  const [editText, setEditText] = useState("");
  const [note, setNote] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const [pendingVersion, setPendingVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.settings.prompts.get(promptId).then((data) => {
      setPrompt(data);
      setEditText(data.prompt_text);
      setLoading(false);
    });
  }, [promptId]);

  const handlePropose = async () => {
    if (!prompt || !note.trim()) return;
    setMessage(null);
    try {
      const diff = await api.settings.prompts.propose(
        promptId,
        editText,
        note
      );
      setPendingVersion(diff.proposed_version);
      setShowDiff(true);
    } catch (e) {
      setMessage(`Error: ${(e as Error).message}`);
    }
  };

  const handleApprove = async () => {
    if (pendingVersion == null) return;
    try {
      await api.settings.prompts.approve(promptId, pendingVersion);
      setMessage("Change approved and saved.");
      setShowDiff(false);
      setIsEditing(false);
      setPendingVersion(null);
      setNote("");
      // Reload
      const data = await api.settings.prompts.get(promptId);
      setPrompt(data);
      setEditText(data.prompt_text);
    } catch (e) {
      setMessage(`Error: ${(e as Error).message}`);
    }
  };

  const handleDiscard = async () => {
    if (pendingVersion == null) return;
    try {
      await api.settings.prompts.discard(promptId, pendingVersion);
      setShowDiff(false);
      setPendingVersion(null);
      setEditText(prompt?.prompt_text || "");
      setNote("");
      setMessage("Change discarded.");
    } catch (e) {
      setMessage(`Error: ${(e as Error).message}`);
    }
  };

  if (loading) {
    return <div className="text-sm text-gray-400 py-4">Loading prompt...</div>;
  }

  if (!prompt) {
    return <div className="text-sm text-red-500 py-4">Prompt not found.</div>;
  }

  if (showDiff && prompt) {
    return (
      <PromptDiffViewer
        promptId={promptId}
        currentText={prompt.prompt_text}
        proposedText={editText}
        note={note}
        onApprove={handleApprove}
        onDiscard={handleDiscard}
      />
    );
  }

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
          {promptId} — {prompt.description}
        </h3>
        <span className="text-xs text-gray-400">
          v{prompt.version_number} | {prompt.created_by}
        </span>
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

      {isEditing ? (
        <div>
          <textarea
            value={editText}
            onChange={(e) => setEditText(e.target.value)}
            rows={20}
            className="w-full font-mono text-xs border border-gray-300 rounded-lg p-3 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
          />
          <div className="mt-3 flex items-center gap-3">
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What did you change and why?"
              className="flex-1 text-sm border border-gray-300 rounded-md px-3 py-1.5 focus:border-indigo-500 outline-none"
            />
            <button
              onClick={handlePropose}
              disabled={!note.trim() || editText === prompt.prompt_text}
              className="px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              Propose change
            </button>
            <button
              onClick={() => {
                setIsEditing(false);
                setEditText(prompt.prompt_text);
                setNote("");
              }}
              className="px-4 py-1.5 text-sm font-medium text-gray-600 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div>
          <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-[60vh]">
            {prompt.prompt_text}
          </pre>
          <div className="mt-3">
            <button
              onClick={() => setIsEditing(true)}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors"
            >
              Edit Prompt
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
