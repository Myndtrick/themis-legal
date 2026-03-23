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
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/assistant/sessions/${sessionId}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: message }),
        signal,
      }
    );
  } catch {
    handlers.onError?.("Cannot reach the backend. Is the server running?");
    return;
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
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
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/api/assistant/sessions/${sessionId}/resume`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, decisions }),
        signal,
      }
    );
  } catch {
    handlers.onError?.("Cannot reach the backend. Is the server running?");
    return;
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
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

      // Process complete events (separated by double newline)
      while (buffer.includes("\n\n")) {
        const eventEnd = buffer.indexOf("\n\n");
        const eventStr = buffer.slice(0, eventEnd);
        buffer = buffer.slice(eventEnd + 2);

        if (!eventStr.trim()) continue;

        // Skip SSE comments (lines starting with :)
        const lines = eventStr.split("\n").filter(
          (l) => !l.startsWith(":")
        );
        if (lines.length === 0) continue;

        let eventType = "message";
        const dataLines: string[] = [];

        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            // Concatenate multiple data: lines (SSE spec)
            dataLines.push(line.slice(5).trim());
          }
        }

        const eventData = dataLines.join("\n");
        if (!eventData) continue;

        try {
          const parsed = JSON.parse(eventData);
          dispatchEvent(eventType, parsed, handlers);
        } catch {
          // JSON parse failed — could be split across chunks
          // For the done event, this is critical. Log it.
          if (eventType === "done") {
            console.warn("Failed to parse SSE done event:", eventData.slice(0, 200));
          }
        }
      }
    }

    // Process any remaining buffer after stream ends
    if (buffer.trim()) {
      const lines = buffer.split("\n").filter((l) => !l.startsWith(":"));
      let eventType = "message";
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trim());
        }
      }
      const eventData = dataLines.join("\n");
      if (eventData) {
        try {
          const parsed = JSON.parse(eventData);
          dispatchEvent(eventType, parsed, handlers);
        } catch {
          if (eventType === "done") {
            console.warn("Failed to parse final SSE event:", eventData.slice(0, 200));
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function dispatchEvent(
  eventType: string,
  parsed: Record<string, unknown>,
  handlers: SSEHandlers
) {
  switch (eventType) {
    case "step":
      handlers.onStep?.(parsed as Parameters<NonNullable<SSEHandlers["onStep"]>>[0]);
      break;
    case "token":
      handlers.onToken?.((parsed as { text: string }).text);
      break;
    case "pause":
      handlers.onPause?.(parsed as Parameters<NonNullable<SSEHandlers["onPause"]>>[0]);
      break;
    case "done":
      handlers.onDone?.(parsed as Parameters<NonNullable<SSEHandlers["onDone"]>>[0]);
      break;
    case "error":
      handlers.onError?.((parsed as { error?: string }).error || "Unknown error");
      break;
  }
}
