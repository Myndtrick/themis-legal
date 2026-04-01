"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, LawVersionDetail } from "@/lib/api";
import { ArticleCard } from "./components/article-card";
import { ArticleList } from "./components/article-list";
import { StructuralSection } from "./components/structural-section";
import { LawToolbar } from "./components/law-toolbar";
import { AnnexCard } from "./components/annex-card";

export default function VersionDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const versionId = params.versionId as string;
  const lawId = parseInt(id, 10);
  const verIdNum = parseInt(versionId, 10);

  const [version, setVersion] = useState<LawVersionDetail | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.laws.getVersion(lawId, verIdNum)
      .then(setVersion)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [lawId, verIdNum]);

  if (loading) {
    return <div className="text-center py-12 text-gray-400">Loading...</div>;
  }

  if (error || !version) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-medium text-gray-900">
          Version not found
        </h2>
        <Link
          href={`/laws/${id}`}
          className="text-blue-600 hover:underline mt-2 inline-block"
        >
          Back to law
        </Link>
      </div>
    );
  }

  const orphanCards = version.articles.map((article) => (
    <ArticleCard key={article.id} article={article} />
  ));

  return (
    <div>
      <div className="mb-6 flex items-center gap-2 text-sm text-gray-500">
        <Link href="/laws" className="hover:text-gray-700">
          Legal Library
        </Link>
        <span>/</span>
        <Link href={`/laws/${version.law.id}`} className="hover:text-gray-700">
          Legea {version.law.law_number}/{version.law.law_year}
        </Link>
        <span>/</span>
        <span className="text-gray-700">
          Version {version.date_in_force || version.ver_id}
        </span>
      </div>

      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">
          {version.law.title}
        </h1>
        <div className="flex items-center gap-3 mt-2">
          <span className="text-gray-600">
            Version in force: {version.date_in_force || "Unknown date"}
          </span>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
              version.is_current
                ? "bg-green-100 text-green-700"
                : "bg-gray-100 text-gray-500"
            }`}
          >
            {version.is_current ? "Current version" : version.state}
          </span>
        </div>
      </div>

      <LawToolbar />

      {/* Preamble and other orphan articles before structure */}
      {orphanCards.length > 0 && (
        <div className="space-y-3 mb-6">
          {orphanCards.length > 40 ? (
            <ArticleList>{orphanCards}</ArticleList>
          ) : (
            orphanCards
          )}
        </div>
      )}

      {version.structure.length > 0 && (
        <div className="space-y-6">
          {version.structure.map((element) => (
            <StructuralSection key={element.id} element={element} />
          ))}
        </div>
      )}

      {version.annexes && version.annexes.length > 0 && (
        <div className="space-y-3 mt-8">
          <h3 className="text-lg font-semibold text-gray-800 mb-3">
            Anexe
          </h3>
          {version.annexes.map((annex) => (
            <AnnexCard key={annex.id} annex={annex} />
          ))}
        </div>
      )}

      {version.structure.length === 0 && version.articles.length === 0 && (!version.annexes || version.annexes.length === 0) && (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <p className="text-gray-500">
            No content found for this version
          </p>
        </div>
      )}
    </div>
  );
}
