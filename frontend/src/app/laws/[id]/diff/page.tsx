"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, DiffResult } from "@/lib/api";

export default function DiffPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const id = params.id as string;
  const lawId = parseInt(id, 10);
  const versionA = parseInt(searchParams.get("a") || "", 10);
  const versionB = parseInt(searchParams.get("b") || "", 10);

  const [diff, setDiff] = useState<DiffResult | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!versionA || !versionB) {
      setLoading(false);
      return;
    }
    api.laws.diff(lawId, versionA, versionB)
      .then(setDiff)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [lawId, versionA, versionB]);

  if (loading) {
    return <div className="text-center py-12 text-gray-400">Loading...</div>;
  }

  if (!versionA || !versionB) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-medium text-gray-900">
          Select two versions to compare
        </h2>
        <p className="text-gray-500 mt-2">
          Use the &quot;Compare versions&quot; feature from the law detail page.
        </p>
        <Link
          href={`/laws/${id}`}
          className="text-blue-600 hover:underline mt-4 inline-block"
        >
          Back to law
        </Link>
      </div>
    );
  }

  if (error || !diff) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-medium text-red-600">
          Failed to generate diff
        </h2>
        <Link
          href={`/laws/${id}`}
          className="text-blue-600 hover:underline mt-4 inline-block"
        >
          Back to law
        </Link>
      </div>
    );
  }

  const changedArticles = diff.changes.filter(
    (c) => c.change_type !== "unchanged"
  );

  return (
    <div>
      <div className="mb-6">
        <Link
          href={`/laws/${id}`}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          &larr; Back to law
        </Link>
      </div>

      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Version Comparison</h1>
        <div className="flex items-center gap-3 mt-2 text-sm text-gray-600">
          <span className="px-2 py-1 bg-red-50 border border-red-200 rounded">
            {diff.version_a.date_in_force || diff.version_a.ver_id}
          </span>
          <span>&rarr;</span>
          <span className="px-2 py-1 bg-green-50 border border-green-200 rounded">
            {diff.version_b.date_in_force || diff.version_b.ver_id}
          </span>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        {[
          {
            label: "Modified",
            count: diff.summary.modified,
            color: "bg-yellow-50 text-yellow-700 border-yellow-200",
          },
          {
            label: "Added",
            count: diff.summary.added,
            color: "bg-green-50 text-green-700 border-green-200",
          },
          {
            label: "Removed",
            count: diff.summary.removed,
            color: "bg-red-50 text-red-700 border-red-200",
          },
          {
            label: "Unchanged",
            count: diff.summary.unchanged,
            color: "bg-gray-50 text-gray-500 border-gray-200",
          },
        ].map((stat) => (
          <div
            key={stat.label}
            className={`rounded-lg border p-4 text-center ${stat.color}`}
          >
            <div className="text-2xl font-bold">{stat.count}</div>
            <div className="text-sm">{stat.label}</div>
          </div>
        ))}
      </div>

      {/* Changes */}
      {changedArticles.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <p className="text-gray-500">
            No differences found between these versions.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Changes ({changedArticles.length} articles)
          </h2>
          {changedArticles.map((change, idx) => (
            <div
              key={idx}
              className="bg-white rounded-lg border border-gray-200 overflow-hidden"
            >
              <div
                className={`px-4 py-2 text-sm font-medium border-b ${
                  change.change_type === "modified"
                    ? "bg-yellow-50 text-yellow-800 border-yellow-200"
                    : change.change_type === "added"
                      ? "bg-green-50 text-green-800 border-green-200"
                      : "bg-red-50 text-red-800 border-red-200"
                }`}
              >
                Art. {change.article_number} —{" "}
                {change.change_type === "modified"
                  ? "Modified"
                  : change.change_type === "added"
                    ? "Added"
                    : "Removed"}
              </div>
              <div className="p-4">
                {change.change_type === "modified" && change.diff_html && (
                  <div
                    className="text-sm text-gray-700 leading-relaxed diff-content"
                    dangerouslySetInnerHTML={{ __html: change.diff_html }}
                  />
                )}
                {change.change_type === "added" && (
                  <div className="text-sm text-green-700 whitespace-pre-wrap">
                    {change.text_b}
                  </div>
                )}
                {change.change_type === "removed" && (
                  <div className="text-sm text-red-700 line-through whitespace-pre-wrap">
                    {change.text_a}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
