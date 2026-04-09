"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  api,
  type DiffArticleEntry,
  type DiffParagraphEntry,
  type DiffResult,
  type AmendmentNoteRef,
} from "@/lib/api";
import "./diff.css";

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
    api.laws
      .diff(lawId, versionA, versionB)
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

  const changedArticles = diff.articles.filter(
    (a) => a.change_type !== "unchanged"
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
          { label: "Modified", count: diff.summary.modified, color: "bg-yellow-50 text-yellow-700 border-yellow-200" },
          { label: "Added", count: diff.summary.added, color: "bg-green-50 text-green-700 border-green-200" },
          { label: "Removed", count: diff.summary.removed, color: "bg-red-50 text-red-700 border-red-200" },
          { label: "Unchanged", count: diff.summary.unchanged, color: "bg-gray-50 text-gray-500 border-gray-200" },
        ].map((stat) => (
          <div key={stat.label} className={`rounded-lg border p-4 text-center ${stat.color}`}>
            <div className="text-2xl font-bold">{stat.count}</div>
            <div className="text-sm">{stat.label}</div>
          </div>
        ))}
      </div>

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
          {changedArticles.map((art) => (
            <ArticleCard key={art.article_label} article={art} />
          ))}
        </div>
      )}
    </div>
  );
}

function ArticleCard({ article }: { article: DiffArticleEntry }) {
  const headerColor =
    article.change_type === "modified"
      ? "bg-yellow-50 border-yellow-200"
      : article.change_type === "added"
        ? "bg-green-50 border-green-200"
        : "bg-red-50 border-red-200";

  return (
    <div className={`rounded-lg border ${headerColor}`}>
      <div className="px-4 py-3 border-b border-inherit flex items-baseline justify-between">
        <div className="font-semibold text-gray-900">
          Art. {article.article_label}
          {article.renumbered_from && (
            <span className="ml-2 text-xs text-gray-500">
              (was {article.renumbered_from})
            </span>
          )}
        </div>
        <span className="uppercase text-xs font-semibold text-gray-600">
          {article.change_type}
        </span>
      </div>

      {article.notes.length > 0 && (
        <div className="px-4 py-2 border-b border-inherit bg-white">
          {article.notes.map((n, i) => (
            <NoteLine key={i} note={n} />
          ))}
        </div>
      )}

      <div className="bg-white p-4 space-y-3">
        {article.change_type === "added" || article.change_type === "removed" ? (
          <pre className={`whitespace-pre-wrap font-sans text-sm ${
            article.change_type === "added" ? "text-green-900" : "text-red-900 line-through"
          }`}>
            {article.text_clean}
          </pre>
        ) : (
          article.paragraphs.map((p, i) => (
            <ParagraphRow key={`${p.paragraph_label}-${i}`} paragraph={p} />
          ))
        )}
      </div>
    </div>
  );
}

function ParagraphRow({ paragraph }: { paragraph: DiffParagraphEntry }) {
  const label = paragraph.paragraph_label ?? "";
  const labelEl = label ? (
    <span className="text-gray-500 font-mono text-xs mr-2">{label}</span>
  ) : null;

  if (paragraph.change_type === "unchanged") {
    return (
      <div className="text-sm text-gray-700">
        {labelEl}
        <span>{paragraph.text_clean}</span>
      </div>
    );
  }
  if (paragraph.change_type === "added") {
    return (
      <div className="text-sm bg-green-50 border-l-2 border-green-400 pl-2 py-1">
        {labelEl}
        <span className="text-green-900">{paragraph.text_clean}</span>
      </div>
    );
  }
  if (paragraph.change_type === "removed") {
    return (
      <div className="text-sm bg-red-50 border-l-2 border-red-400 pl-2 py-1">
        {labelEl}
        <span className="text-red-900 line-through">{paragraph.text_clean}</span>
      </div>
    );
  }
  // modified
  return (
    <div className="text-sm bg-yellow-50 border-l-2 border-yellow-400 pl-2 py-1">
      {labelEl}
      {paragraph.renumbered_from && (
        <span className="text-xs text-gray-500 mr-2">(was {paragraph.renumbered_from})</span>
      )}
      <span
        className="diff-html"
        dangerouslySetInnerHTML={{ __html: paragraph.diff_html ?? "" }}
      />
      {paragraph.notes.length > 0 && (
        <div className="mt-1">
          {paragraph.notes.map((n, i) => (
            <NoteLine key={i} note={n} />
          ))}
        </div>
      )}
    </div>
  );
}

function NoteLine({ note }: { note: AmendmentNoteRef }) {
  const parts: string[] = [];
  if (note.date) parts.push(note.date);
  if (note.law_number) parts.push(`Legea/OUG nr. ${note.law_number}`);
  if (note.monitor_number) parts.push(`MO ${note.monitor_number}`);
  if (note.subject) parts.push(note.subject);
  if (parts.length === 0) return null;
  return (
    <div className="text-xs text-gray-500 italic">
      modified by {parts.join(" — ")}
    </div>
  );
}
