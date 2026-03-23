"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/api";
import { MessageBubble, StreamingBubble } from "./message-bubble";
import { ImportPrompt } from "./import-prompt";
import type { PauseData, StepProgress } from "./use-chat";

export function MessageList({
  messages,
  streamingText,
  isStreaming,
  steps,
  pendingPause,
  error,
  onImportDecision,
}: {
  messages: ChatMessage[];
  streamingText: string;
  isStreaming: boolean;
  steps: StepProgress[];
  pendingPause: PauseData | null;
  error: string | null;
  onImportDecision: (decisions: Record<string, string>) => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText, steps, pendingPause]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4">
      <div className="max-w-3xl mx-auto">
        {messages.length === 0 && !isStreaming && (
          <div className="text-center py-16">
            <h3 className="text-lg font-medium text-gray-400 mb-2">
              Legal Assistant
            </h3>
            <p className="text-sm text-gray-400 max-w-md mx-auto">
              Ask a legal question about Romanian law. Your answers will be
              grounded in the laws stored in the Legal Library, with full source
              citations.
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Streaming state */}
        {isStreaming && (
          <StreamingBubble text={streamingText} steps={steps} />
        )}

        {/* Import pause */}
        {pendingPause && (
          <ImportPrompt
            pauseData={pendingPause}
            onDecision={onImportDecision}
          />
        )}

        {/* Error */}
        {error && (
          <div className="my-3 mx-auto max-w-xl bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
