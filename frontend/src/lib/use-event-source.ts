/**
 * SSE stream parser for POST-based Server-Sent Events.
 *
 * Uses fetch + ReadableStream (not EventSource, which only supports GET).
 * Parses the SSE protocol: "event: <type>\ndata: <json>\n\n"
 */

import type { StructuredAnswer } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface SSEHandlers {
  onStep?: (data: {
    step: number;
    name: string;
    status: string;
    data?: Record<string, unknown>;
    duration?: number;
  }) => void;
  onToken?: (text: string) => void;
  onPause?: (data: {
    run_id: string;
    message: string;
    missing_laws: Array<{
      law_number: string;
      law_year: number;
      title: string;
      reason: string;
    }>;
  }) => void;
  onDone?: (data: {
    content: string;
    structured: StructuredAnswer | null;
    mode: string;
    run_id: string;
    confidence: string;
    flags: string[];
    reasoning: Record<string, unknown>;
  }) => void;
  onError?: (error: string) => void;
}

export async function streamChat(
  sessionId: string,
  message: string,
  handlers: SSEHandlers,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/api/assistant/sessions/${sessionId}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: message }),
      signal,
    }
  );

  if (!response.ok) {
    const text = await response.text();
    handlers.onError?.(text || `HTTP ${response.status}`);
    return;
  }

  await consumeSSEStream(response, handlers);
}

export async function streamResume(
  sessionId: string,
  runId: string,
  decisions: Record<string, string>,
  handlers: SSEHandlers,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/api/assistant/sessions/${sessionId}/resume`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, decisions }),
      signal,
    }
  );

  if (!response.ok) {
    const text = await response.text();
    handlers.onError?.(text || `HTTP ${response.status}`);
    return;
  }

  await consumeSSEStream(response, handlers);
}

async function consumeSSEStream(
  response: Response,
  handlers: SSEHandlers
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    handlers.onError?.("No response body");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on double newline (SSE event boundary)
      const events = buffer.split("\n\n");
      // Keep the last incomplete chunk in the buffer
      buffer = events.pop() || "";

      for (const eventStr of events) {
        if (!eventStr.trim()) continue;

        let eventType = "message";
        let eventData = "";

        for (const line of eventStr.split("\n")) {
          if (line.startsWith("event:")) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            eventData = line.slice(5).trim();
          }
        }

        if (!eventData) continue;

        try {
          const parsed = JSON.parse(eventData);

          switch (eventType) {
            case "step":
              handlers.onStep?.(parsed);
              break;
            case "token":
              handlers.onToken?.(parsed.text);
              break;
            case "pause":
              handlers.onPause?.(parsed);
              break;
            case "done":
              handlers.onDone?.(parsed);
              break;
            case "error":
              handlers.onError?.(parsed.error || "Unknown error");
              break;
          }
        } catch {
          // Skip malformed JSON
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
