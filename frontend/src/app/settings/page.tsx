"use client";

import { Suspense, useState } from "react";
import { SettingsTabs, type TabId } from "./settings-tabs";
import { PromptTable } from "./prompts/prompt-table";
import { PromptEditor } from "./prompts/prompt-editor";
import { HealthDashboard } from "./pipeline/health-dashboard";
import { RunTable } from "./pipeline/run-table";
import { VersionHistory } from "./versions/version-history";
import { CategoriesTable } from "./categories/categories-table";
import { SuggestionsTable } from "./suggestions/suggestions-table";
import { ModelsTable } from "./models/models-table";
import { UsersTable } from "./users/users-table";
import { SchedulerSettings } from "./schedulers/scheduler-settings";
import { MaintenancePanel } from "./maintenance/maintenance-panel";

function SettingsContent() {
  const [selectedPrompt, setSelectedPrompt] = useState<string | null>(null);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-blue-600">Settings</h1>
        <p className="mt-1 text-gray-600">
          Manage prompts, inspect pipeline runs, and review version history
        </p>
      </div>

      <SettingsTabs>
        {(activeTab: TabId) => {
          if (activeTab === "prompts") {
            if (selectedPrompt) {
              return (
                <PromptEditor
                  promptId={selectedPrompt}
                  onBack={() => setSelectedPrompt(null)}
                />
              );
            }
            return <PromptTable onSelect={setSelectedPrompt} />;
          }

          if (activeTab === "pipeline") {
            return (
              <div>
                <HealthDashboard />
                <RunTable />
              </div>
            );
          }

          if (activeTab === "versions") {
            return <VersionHistory />;
          }

          if (activeTab === "categories") {
            return <CategoriesTable />;
          }

          if (activeTab === "suggestions") {
            return <SuggestionsTable />;
          }

          if (activeTab === "models") {
            return <ModelsTable />;
          }

          if (activeTab === "users") {
            return <UsersTable />;
          }

          if (activeTab === "schedulers") {
            return <SchedulerSettings />;
          }

          if (activeTab === "maintenance") {
            return <MaintenancePanel />;
          }

          return null;
        }}
      </SettingsTabs>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="text-gray-400 py-8">Loading settings...</div>}>
      <SettingsContent />
    </Suspense>
  );
}
