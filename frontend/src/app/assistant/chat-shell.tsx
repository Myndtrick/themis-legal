"use client";

import { useEffect } from "react";
import { ChatInput } from "./chat-input";
import { MessageList } from "./message-list";
import { SessionSidebar } from "./session-sidebar";
import { useChat } from "./use-chat";

export function ChatShell() {
  const {
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
    retryRun,
    cancelStream,
  } = useChat();

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  return (
    <div className="flex h-full bg-gray-50 rounded-lg overflow-hidden border border-gray-200">
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={loadSession}
        onNewSession={createSession}
        onDeleteSession={deleteSession}
      />

      <div className="flex-1 flex flex-col min-w-0">
        {activeSessionId ? (
          <>
            <MessageList
              messages={messages}
              streamingText={streamingText}
              isStreaming={isStreaming}
              steps={steps}
              pendingPause={pendingPause}
              error={error}
              onImportDecision={handleImportDecision}
              onRetry={retryRun}
            />
            <ChatInput
              onSend={sendMessage}
              disabled={isStreaming || !!pendingPause}
              onCancel={cancelStream}
              isStreaming={isStreaming}
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <h3 className="text-lg font-medium text-gray-400 mb-2">
                Legal Assistant
              </h3>
              <p className="text-sm text-gray-400 mb-4">
                Select a conversation or start a new one
              </p>
              <button
                onClick={createSession}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
              >
                Start New Chat
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
