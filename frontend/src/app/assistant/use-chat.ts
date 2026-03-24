"use client";

import { useCallback, useRef, useState } from "react";
import {
  api,
  type ChatMessage,
  type ChatSession,
  type LawPreview,
  type StructuredAnswer,
} from "@/lib/api";
import { streamChat, streamResume, type SSEHandlers } from "@/lib/use-event-source";

export interface StepProgress {
  step: number;
  name: string;
  status: string;
  data?: Record<string, unknown>;
  duration?: number;
}

export interface PauseData {
  run_id: string;
  message: string;
  laws: LawPreview[];
}

export function useChat() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [steps, setSteps] = useState<StepProgress[]>([]);
  const [pendingPause, setPendingPause] = useState<PauseData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const data = await api.assistant.listSessions();
      setSessions(data);
    } catch (e) {
      console.error("Failed to load sessions:", e);
    }
  }, []);

  const loadSession = useCallback(async (sessionId: string) => {
    try {
      const data = await api.assistant.getSession(sessionId);
      setActiveSessionId(sessionId);
      setMessages(data.messages);
      setSteps([]);
      setPendingPause(null);
      setStreamingText("");
      setError(null);
    } catch (e) {
      console.error("Failed to load session:", e);
    }
  }, []);

  const createSession = useCallback(async () => {
    try {
      const session = await api.assistant.createSession();
      setSessions((prev) => [session, ...prev]);
      setActiveSessionId(session.id);
      setMessages([]);
      setSteps([]);
      setPendingPause(null);
      setStreamingText("");
      setError(null);
      return session;
    } catch (e) {
      console.error("Failed to create session:", e);
      return null;
    }
  }, []);

  const deleteSession = useCallback(
    async (sessionId: string) => {
      // Remove from UI immediately, then try backend
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
        setStreamingText("");
        setIsStreaming(false);
      }
      try {
        await api.assistant.deleteSession(sessionId);
      } catch {
        // Silently ignore — session already removed from UI
      }
    },
    [activeSessionId]
  );

  const sendMessage = useCallback(
    async (content: string) => {
      if (!activeSessionId || isStreaming) return;

      setError(null);
      setIsStreaming(true);
      setStreamingText("");
      setSteps([]);
      setPendingPause(null);

      // Add user message optimistically
      const userMsg: ChatMessage = {
        id: Date.now(),
        role: "user",
        content,
        mode: null,
        run_id: null,
        reasoning_data: null,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);

      // Update session title if first message
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSessionId && !s.title
            ? { ...s, title: content.slice(0, 100), message_count: s.message_count + 1 }
            : s.id === activeSessionId
            ? { ...s, message_count: s.message_count + 1 }
            : s
        )
      );

      const abort = new AbortController();
      abortRef.current = abort;

      const handlers: SSEHandlers = {
        onStep: (data) => {
          setSteps((prev) => {
            const existing = prev.findIndex((s) => s.step === data.step);
            if (existing >= 0) {
              const updated = [...prev];
              updated[existing] = data;
              return updated;
            }
            return [...prev, data];
          });
        },
        onToken: (text) => {
          setStreamingText((prev) => prev + text);
        },
        onPause: (data) => {
          setPendingPause(data);
          setIsStreaming(false);
        },
        onDone: (data) => {
          const outputMode = data.output_mode || data.mode;

          // Store structured data (answer sections + reasoning) together
          const combinedData = {
            structured: data.structured,
            reasoning: data.reasoning,
            confidence: data.confidence,
            flags: data.flags,
          };
          const assistantMsg: ChatMessage = {
            id: Date.now() + 1,
            role: "assistant",
            // Use short_answer from structured if available, else raw content
            content: data.structured?.short_answer || data.content,
            mode: outputMode === "clarification" || outputMode === "needs_import"
              ? outputMode
              : data.mode,
            run_id: data.run_id,
            reasoning_data: JSON.stringify(combinedData),
            created_at: new Date().toISOString(),
            clarification_type: data.clarification_type,
            missing_laws: data.missing_laws,
          };
          setMessages((prev) => [...prev, assistantMsg]);
          setStreamingText("");
          setIsStreaming(false);
        },
        onError: (err) => {
          setError(err);
          setIsStreaming(false);
          setStreamingText("");
        },
      };

      try {
        await streamChat(activeSessionId, content, handlers, abort.signal);
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setError((e as Error).message);
        }
        setIsStreaming(false);
        setStreamingText("");
      }
    },
    [activeSessionId, isStreaming]
  );

  const handleImportDecision = useCallback(
    async (decisions: Record<string, string>) => {
      if (!activeSessionId || !pendingPause) return;

      setIsStreaming(true);
      setPendingPause(null);
      setStreamingText("");

      const abort = new AbortController();
      abortRef.current = abort;

      const handlers: SSEHandlers = {
        onStep: (data) => {
          setSteps((prev) => {
            const existing = prev.findIndex((s) => s.step === data.step);
            if (existing >= 0) {
              const updated = [...prev];
              updated[existing] = data;
              return updated;
            }
            return [...prev, data];
          });
        },
        onToken: (text) => {
          setStreamingText((prev) => prev + text);
        },
        onDone: (data) => {
          const outputMode = data.output_mode || data.mode;

          // Store structured data (answer sections + reasoning) together
          const combinedData = {
            structured: data.structured,
            reasoning: data.reasoning,
            confidence: data.confidence,
            flags: data.flags,
          };
          const assistantMsg: ChatMessage = {
            id: Date.now() + 1,
            role: "assistant",
            // Use short_answer from structured if available, else raw content
            content: data.structured?.short_answer || data.content,
            mode: outputMode === "clarification" || outputMode === "needs_import"
              ? outputMode
              : data.mode,
            run_id: data.run_id,
            reasoning_data: JSON.stringify(combinedData),
            created_at: new Date().toISOString(),
            clarification_type: data.clarification_type,
            missing_laws: data.missing_laws,
          };
          setMessages((prev) => [...prev, assistantMsg]);
          setStreamingText("");
          setIsStreaming(false);
        },
        onError: (err) => {
          setError(err);
          setIsStreaming(false);
          setStreamingText("");
        },
      };

      try {
        await streamResume(
          activeSessionId,
          pendingPause.run_id,
          decisions,
          handlers,
          abort.signal
        );
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setError((e as Error).message);
        }
        setIsStreaming(false);
      }
    },
    [activeSessionId, pendingPause]
  );

  const cancelStream = useCallback(() => {
    abortRef.current?.abort();
    setIsStreaming(false);
    setStreamingText("");
  }, []);

  return {
    sessions,
    activeSessionId,
    messages,
    streamingText,
    isStreaming,
    steps,
    pendingPause,
    error,
    loadSessions,
    loadSession,
    createSession,
    deleteSession,
    sendMessage,
    handleImportDecision,
    cancelStream,
  };
}
