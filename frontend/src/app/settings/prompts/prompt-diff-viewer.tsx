"use client";

export function PromptDiffViewer({
  promptId,
  currentText,
  proposedText,
  note,
  onApprove,
  onDiscard,
}: {
  promptId: string;
  currentText: string;
  proposedText: string;
  note: string;
  onApprove: () => void;
  onDiscard: () => void;
}) {
  // Simple line-by-line diff
  const currentLines = currentText.split("\n");
  const proposedLines = proposedText.split("\n");
  const maxLines = Math.max(currentLines.length, proposedLines.length);

  const diffLines: Array<{
    type: "same" | "removed" | "added" | "changed";
    current?: string;
    proposed?: string;
  }> = [];

  for (let i = 0; i < maxLines; i++) {
    const c = currentLines[i];
    const p = proposedLines[i];
    if (c === p) {
      diffLines.push({ type: "same", current: c });
    } else if (c === undefined) {
      diffLines.push({ type: "added", proposed: p });
    } else if (p === undefined) {
      diffLines.push({ type: "removed", current: c });
    } else {
      diffLines.push({ type: "changed", current: c, proposed: p });
    }
  }

  const addedCount = diffLines.filter(
    (d) => d.type === "added" || d.type === "changed"
  ).length;
  const removedCount = diffLines.filter(
    (d) => d.type === "removed" || d.type === "changed"
  ).length;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">
            Review Changes — {promptId}
          </h3>
          <p className="text-sm text-gray-500 mt-1">
            {note} | +{addedCount} / -{removedCount} lines
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={onApprove}
            className="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-md hover:bg-green-700 transition-colors"
          >
            Approve &amp; Save
          </button>
          <button
            onClick={onDiscard}
            className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
          >
            Discard
          </button>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden max-h-[60vh] overflow-y-auto">
        <pre className="text-xs font-mono p-0">
          {diffLines.map((line, i) => {
            if (line.type === "same") {
              return (
                <div key={i} className="px-4 py-0.5 text-gray-600">
                  {" "}
                  {line.current}
                </div>
              );
            }
            if (line.type === "removed") {
              return (
                <div
                  key={i}
                  className="px-4 py-0.5 bg-red-50 text-red-800"
                >
                  -{line.current}
                </div>
              );
            }
            if (line.type === "added") {
              return (
                <div
                  key={i}
                  className="px-4 py-0.5 bg-green-50 text-green-800"
                >
                  +{line.proposed}
                </div>
              );
            }
            // changed
            return (
              <div key={i}>
                <div className="px-4 py-0.5 bg-red-50 text-red-800">
                  -{line.current}
                </div>
                <div className="px-4 py-0.5 bg-green-50 text-green-800">
                  +{line.proposed}
                </div>
              </div>
            );
          })}
        </pre>
      </div>
    </div>
  );
}
