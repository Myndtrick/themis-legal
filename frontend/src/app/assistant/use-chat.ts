"use client";

import { useCallback, useRef, useState } from "react";
import {
  api,
  type ChatMessage,
  type ChatSession,
  type MissingLaw,
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
  missing_laws: MissingLaw[];
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
      try {
        await api.assistant.deleteSession(sessionId);
        setSessions((prev) => prev.filter((s) => s.id !== sessionId));
        if (activeSessionId === sessionId) {
          setActiveSessionId(null);
          setMessages([]);
        }
      } catch (e) {
        console.error("Failed to delete session:", e);
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
          const assistantMsg: ChatMessage = {
            id: Date.now() + 1,
            role: "assistant",
            content: data.content,
            mode: data.mode,
            run_id: data.run_id,
            reasoning_data: JSON.stringify(data.reasoning),
            created_at: new Date().toISOString(),
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
          const assistantMsg: ChatMessage = {
            id: Date.now() + 1,
            role: "assistant",
            content: data.content,
            mode: data.mode,
            run_id: data.run_id,
            reasoning_data: JSON.stringify(data.reasoning),
            created_at: new Date().toISOString(),
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
