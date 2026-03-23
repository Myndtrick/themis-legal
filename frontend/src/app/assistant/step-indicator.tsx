"use client";

import type { StepProgress } from "./use-chat";

const STEP_LABELS: Record<string, string> = {
  issue_classification: "Classifying question",
  date_extraction: "Identifying dates",
  law_identification: "Finding applicable laws",
  coverage_check: "Checking library",
  import_permission: "Checking coverage",
  version_selection: "Selecting versions",
  answer_generation: "Generating answer",
};

export function StepIndicator({ steps }: { steps: StepProgress[] }) {
  if (steps.length === 0) return null;

  const currentStep = steps.find((s) => s.status === "running");
  const doneCount = steps.filter((s) => s.status === "done").length;

  return (
    <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
      {currentStep ? (
        <>
          <span className="animate-spin inline-block w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full" />
          <span>{STEP_LABELS[currentStep.name] || currentStep.name}...</span>
        </>
      ) : (
        <>
          <span className="text-green-500">&#10003;</span>
          <span>{doneCount} steps complete</span>
        </>
      )}
    </div>
  );
}
