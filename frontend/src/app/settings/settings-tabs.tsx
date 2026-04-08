"use client";

import { useSearchParams, useRouter } from "next/navigation";

const TABS = [
  { id: "prompts", label: "Prompt Management" },
  { id: "pipeline", label: "Pipeline Tracking" },
  { id: "versions", label: "Version History" },
  { id: "categories", label: "Categories" },
  { id: "suggestions", label: "Suggestions" },
  { id: "models", label: "Models" },
  { id: "users", label: "Users" },
  { id: "schedulers", label: "Schedulers" },
  { id: "maintenance", label: "Maintenance" },
] as const;

export type TabId = (typeof TABS)[number]["id"];

export function SettingsTabs({
  children,
}: {
  children: (activeTab: TabId) => React.ReactNode;
}) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const activeTab = (searchParams.get("tab") as TabId) || "prompts";

  return (
    <div>
      <div className="border-b border-gray-200 mb-6">
        <nav className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => router.push(`/settings?tab=${tab.id}`)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
      {children(activeTab)}
    </div>
  );
}
