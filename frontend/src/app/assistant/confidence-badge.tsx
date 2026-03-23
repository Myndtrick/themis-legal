"use client";

export function ConfidenceBadge({ level }: { level: string | null }) {
  if (!level) return null;

  const colors: Record<string, string> = {
    HIGH: "bg-green-100 text-green-700",
    MEDIUM: "bg-yellow-100 text-yellow-700",
    LOW: "bg-red-100 text-red-700",
  };

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        colors[level] || "bg-gray-100 text-gray-700"
      }`}
    >
      Confidence: {level}
    </span>
  );
}
