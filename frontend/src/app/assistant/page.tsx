"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { Suspense } from "react";
import { ChatShell } from "./chat-shell";
import { CompareTab } from "./compare-tab";

function AssistantContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const tab = searchParams.get("tab") || "chat";

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-gray-200 px-4">
        <nav className="flex gap-1">
          {[
            { id: "chat", label: "Chat" },
            { id: "compare", label: "Compare" },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => router.push(`/assistant?tab=${t.id}`)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="flex-1 overflow-hidden">
        {tab === "compare" ? <CompareTab /> : <ChatShell />}
      </div>
    </div>
  );
}

export const dynamic = "force-dynamic";

export default function AssistantPage() {
  return (
    <Suspense fallback={<div className="text-gray-400 py-8">Loading...</div>}>
      <AssistantContent />
    </Suspense>
  );
}
