"use client";

import type { ChatMessage } from "@/lib/api";
import { ConfidenceBadge } from "./confidence-badge";
import { ModeBadge } from "./mode-badge";
import { ReasoningPanel } from "./reasoning-panel";
import type { StepProgress } from "./use-chat";

export function MessageBubble({
  message,
  steps,
  isStreaming,
}: {
  message: ChatMessage;
  steps?: StepProgress[];
  isStreaming?: boolean;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-[70%] bg-indigo-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
          {message.content}
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
        {message.mode && (
          <div className="mb-2 flex items-center gap-2">
            <ModeBadge mode={message.mode} />
          </div>
        )}

        <div className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
          {message.content}
        </div>

        {/* Confidence + reasoning for completed assistant messages */}
        {message.reasoning_data && (
          <>
            <div className="mt-3">
              <ConfidenceBadge
                level={
                  (() => {
                    try {
                      const r = JSON.parse(message.reasoning_data!);
                      return r.step7_answer?.confidence || null;
                    } catch {
                      return null;
                    }
                  })()
                }
              />
            </div>
            <ReasoningPanel
              steps={steps || []}
              reasoningData={message.reasoning_data}
              isStreaming={isStreaming || false}
            />
          </>
        )}
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
        {/* Pipeline progress */}
        {steps.length > 0 && !text && (
          <div className="space-y-1 mb-2">
            {steps.map((s) => (
              <div key={s.step} className="flex items-center gap-2 text-xs text-gray-500">
                {s.status === "running" ? (
                  <span className="animate-spin inline-block w-3 h-3 border-2 border-indigo-500 border-t-transparent rounded-full" />
                ) : (
                  <span className="text-green-500">&#10003;</span>
                )}
                <span>
                  Step {s.step}:{" "}
                  {s.name.replace(/_/g, " ")}
                </span>
                {s.duration != null && (
                  <span className="text-gray-400">{s.duration.toFixed(1)}s</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Streaming text */}
        {text && (
          <div className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
            {text}
            <span className="inline-block w-1.5 h-4 bg-indigo-500 animate-pulse ml-0.5 align-text-bottom" />
          </div>
        )}

        {/* Loading state when no text yet and steps are done */}
        {!text && steps.length > 0 && steps.every((s) => s.status === "done") && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <span className="animate-spin inline-block w-3 h-3 border-2 border-indigo-500 border-t-transparent rounded-full" />
            <span>Generating answer...</span>
          </div>
        )}
      </div>
    </div>
  );
}
