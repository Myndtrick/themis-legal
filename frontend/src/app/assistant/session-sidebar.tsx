"use client";

import type { ChatSession } from "@/lib/api";

export function SessionSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
}: {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDeleteSession: (id: string) => void;
}) {
  return (
    <div className="w-64 bg-white border-r border-gray-200 flex flex-col shrink-0">
      <div className="p-3 border-b border-gray-200">
        <button
          onClick={onNewSession}
          className="w-full px-3 py-2 text-sm font-medium text-indigo-700 bg-indigo-50 rounded-lg hover:bg-indigo-100 transition-colors"
        >
          + New Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-gray-400">
            No conversations yet
          </div>
        )}

        {sessions.map((session) => (
          <div
            key={session.id}
            className={`group flex items-center gap-1 px-3 py-2.5 cursor-pointer border-b border-gray-50 transition-colors ${
              activeSessionId === session.id
                ? "bg-indigo-50 border-l-2 border-l-indigo-500"
                : "hover:bg-gray-50"
            }`}
            onClick={() => onSelectSession(session.id)}
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-gray-800 truncate">
                {session.title || "New conversation"}
              </div>
              <div className="text-xs text-gray-400">
                {session.message_count} message{session.message_count !== 1 ? "s" : ""}
              </div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDeleteSession(session.id);
              }}
              className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 text-xs p-1 transition-opacity"
              title="Delete session"
            >
              &#10005;
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
