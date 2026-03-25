"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
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
      if (parsed.answer) return parsed.answer;
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

export function MessageBubble({
  message,
  onRetry,
}: {
  message: ChatMessage;
  onRetry?: (runId: string, mode: "full" | "resume") => void;
}) {
  const [showRetryOptions, setShowRetryOptions] = useState(false);

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
        {/* Legal analysis answer with markdown */}
        <div className="text-sm text-gray-800 leading-relaxed prose prose-sm max-w-none prose-headings:text-gray-900 prose-h2:text-base prose-h2:mt-4 prose-h2:mb-2 prose-h3:text-sm prose-h3:mt-3 prose-h3:mb-1 prose-strong:text-gray-900 prose-hr:my-3 prose-hr:border-gray-200 prose-ul:my-1 prose-li:my-0.5 prose-blockquote:text-gray-600 prose-blockquote:border-indigo-300 prose-p:my-1.5">
          <ReactMarkdown>{displayContent}</ReactMarkdown>
        </div>

        {/* Badges */}
        <div className="mt-2 flex items-center gap-2">
          <ModeBadge mode={message.mode} />
          <ConfidenceBadge level={confidence} />
        </div>

        {/* Retry button for error messages */}
        {onRetry && message.run_id && (
          <div className="mt-3">
            {!showRetryOptions ? (
              <button
                onClick={() => setShowRetryOptions(true)}
                className="px-3 py-1.5 text-sm font-medium text-indigo-600 bg-indigo-50 border border-indigo-200 rounded-md hover:bg-indigo-100 transition-colors"
              >
                Retry analysis
              </button>
            ) : (
              <div className="flex flex-col gap-2 p-3 bg-slate-50 border border-slate-200 rounded-lg">
                <p className="text-xs text-slate-600 font-medium">How would you like to retry?</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      setShowRetryOptions(false);
                      onRetry(message.run_id!, "resume");
                    }}
                    className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors"
                  >
                    Resume from where it stopped
                  </button>
                  <button
                    onClick={() => {
                      setShowRetryOptions(false);
                      onRetry(message.run_id!, "full");
                    }}
                    className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                  >
                    Restart full analysis
                  </button>
                </div>
                <p className="text-[10px] text-slate-400">
                  Resume reuses the classification step (saves tokens). Full restart re-analyzes from scratch.
                </p>
              </div>
            )}
          </div>
        )}

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
