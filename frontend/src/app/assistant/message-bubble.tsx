"use client";

import type { ChatMessage } from "@/lib/api";
import { AnswerDetail } from "./answer-detail";
import { ConfidenceBadge } from "./confidence-badge";
import { ModeBadge } from "./mode-badge";
import { StepIndicator } from "./step-indicator";
import type { StepProgress } from "./use-chat";

export function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[70%] bg-indigo-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
          {message.content}
        </div>
      </div>
    );
  }

  // Parse the combined data for confidence
  let confidence: string | null = null;
  try {
    if (message.reasoning_data) {
      const data = JSON.parse(message.reasoning_data);
      confidence = data.confidence || data.structured?.confidence || null;
    }
  } catch {
    // ignore
  }

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
        {/* Clean conversational answer */}
        <div className="text-sm text-gray-800 leading-relaxed">
          {message.content}
        </div>

        {/* Badges */}
        <div className="mt-2 flex items-center gap-2">
          <ModeBadge mode={message.mode} />
          <ConfidenceBadge level={confidence} />
        </div>

        {/* Collapsible details (legal basis, sources, etc.) */}
        <AnswerDetail reasoningData={message.reasoning_data} />

        {/* Disclaimer */}
        <div className="mt-2 text-[10px] text-gray-400 leading-tight">
          Analiza juridica preliminara asistata de AI — necesita revizuire umana.
        </div>
      </div>
    </div>
  );
}

export function StreamingBubble({
  text,
  steps,
}: {
  text: string;
  steps: StepProgress[];
}) {
  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
        {/* Subtle step progress */}
        {!text && <StepIndicator steps={steps} />}

        {/* Streaming text */}
        {text && (
          <div className="text-sm text-gray-800 leading-relaxed">
            {text}
            <span className="inline-block w-1.5 h-4 bg-indigo-500 animate-pulse ml-0.5 align-text-bottom" />
          </div>
        )}

        {/* Loading state when steps are done but no text yet */}
        {!text && steps.length > 0 && steps.every((s) => s.status === "done") && (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span className="animate-spin inline-block w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full" />
            <span>Generating answer...</span>
          </div>
        )}
      </div>
    </div>
  );
}
