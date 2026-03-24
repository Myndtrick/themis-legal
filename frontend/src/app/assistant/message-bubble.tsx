"use client";

import type { ChatMessage, StructuredAnswer } from "@/lib/api";
import { AnswerDetail } from "./answer-detail";
import { ConfidenceBadge } from "./confidence-badge";
import { ModeBadge } from "./mode-badge";
import { StepIndicator } from "./step-indicator";
import type { StepProgress } from "./use-chat";

/**
 * Try to extract a clean display text from the message content.
 * If the content is a JSON string (from raw streaming), parse out short_answer.
 */
function getDisplayContent(message: ChatMessage): string {
  const content = message.content;

  // If content looks like JSON, try to extract short_answer
  const trimmed = content.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("```")) {
    try {
      let jsonStr = trimmed;
      // Strip markdown code block if present
      if (jsonStr.startsWith("```")) {
        const lines = jsonStr.split("\n");
        if (lines[0].startsWith("```")) lines.shift();
        if (lines[lines.length - 1]?.trim() === "```") lines.pop();
        jsonStr = lines.join("\n");
      }
      const parsed = JSON.parse(jsonStr);
      if (parsed.short_answer) return parsed.short_answer;
    } catch {
      // Not valid JSON — use as-is
    }
  }

  return content;
}

function parseReasoningData(
  reasoningData: string | null
): { confidence: string | null; structured: StructuredAnswer | null } {
  if (!reasoningData) return { confidence: null, structured: null };
  try {
    const data = JSON.parse(reasoningData);
    return {
      confidence:
        data.confidence || data.structured?.confidence || null,
      structured: data.structured || null,
    };
  } catch {
    return { confidence: null, structured: null };
  }
}

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

  const displayContent = getDisplayContent(message);
  const { confidence } = parseReasoningData(message.reasoning_data);

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
        {/* Clean conversational answer */}
        <div className="text-sm text-gray-800 leading-relaxed whitespace-pre-line">
          {displayContent}
        </div>

        {/* Badges */}
        <div className="mt-2 flex items-center gap-2">
          <ModeBadge mode={message.mode} />
          <ConfidenceBadge level={confidence} />
        </div>

        {/* Collapsible details (legal basis, sources, etc.) */}
        <AnswerDetail reasoningData={message.reasoning_data} />

        {/* Disclaimer */}
        <div className="mt-3 px-2 py-1.5 bg-gray-50 border border-gray-200 rounded text-xs text-gray-600 leading-snug">
          Analiza juridica preliminara asistata de AI — necesita revizuire umana. Aceasta nu constituie consultanta juridica.
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
  // During streaming, DON'T show the raw JSON tokens.
  // Just show step progress, then "Generating answer..." until done.
  const hasText = text.length > 0;
  const isJsonStream =
    hasText && (text.trimStart().startsWith("{") || text.trimStart().startsWith("```"));

  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
        {/* Step progress */}
        <StepIndicator steps={steps} />

        {/* If streaming plain text (not JSON), show it */}
        {hasText && !isJsonStream && (
          <div className="text-sm text-gray-800 leading-relaxed">
            {text}
            <span className="inline-block w-1.5 h-4 bg-indigo-500 animate-pulse ml-0.5 align-text-bottom" />
          </div>
        )}

        {/* If streaming JSON (structured output), show a clean waiting state */}
        {isJsonStream && (
          <div className="flex items-center gap-2 text-xs text-gray-400 mt-1">
            <span className="animate-spin inline-block w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full" />
            <span>Composing answer...</span>
          </div>
        )}

        {/* Loading state when steps are done but no text yet */}
        {!hasText &&
          steps.length > 0 &&
          steps.every((s) => s.status === "done") && (
            <div className="flex items-center gap-2 text-xs text-gray-400 mt-1">
              <span className="animate-spin inline-block w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full" />
              <span>Generating answer...</span>
            </div>
          )}
      </div>
    </div>
  );
}
