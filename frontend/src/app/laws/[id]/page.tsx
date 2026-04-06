"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, LawDetail } from "@/lib/api";
import DiffSelector from "./diff-selector";
import DeleteVersionsButton from "./delete-versions-button";
import StatusBadge from "./status-badge";
import VersionsSection from "./versions-section";

export default function LawDetailPage() {
  const params = useParams();
  const lawId = parseInt(params.id as string, 10);
  const [law, setLaw] = useState<LawDetail | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [isFavorite, setIsFavorite] = useState(false);
  const [favoriteBusy, setFavoriteBusy] = useState(false);

  useEffect(() => {
    api.laws.get(lawId)
      .then((result) => {
        setLaw(result);
        setIsFavorite(result.is_favorite);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [lawId]);

  async function handleToggleFavorite() {
    if (favoriteBusy) return;
    const next = !isFavorite;
    setIsFavorite(next);
    setFavoriteBusy(true);
    try {
      if (next) {
        await api.laws.favoriteAdd(lawId);
      } else {
        await api.laws.favoriteRemove(lawId);
      }
    } catch {
      setIsFavorite(!next);
      alert("Failed to update favorite.");
    } finally {
      setFavoriteBusy(false);
    }
  }

  if (loading) {
    return <div className="text-center py-12 text-gray-400">Loading...</div>;
  }

  if (error || !law) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-medium text-gray-900">Law not found</h2>
        <Link href="/laws" className="text-blue-600 hover:underline mt-2 inline-block">
          Back to Legal Library
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <Link
          href="/laws"
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          &larr; Back to Legal Library
        </Link>
      </div>

      <div className="mb-8">
        {law.category ? (
          <div className="flex items-center gap-2 text-sm mb-2">
            <div
              className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: law.category.group_color_hex }}
            />
            <span className="text-gray-500">{law.category.group_name_en}</span>
            <span className="text-gray-300">&rsaquo;</span>
            <span className="text-gray-700">{law.category.name_en}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm mb-2">
            <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded text-xs">Uncategorized</span>
          </div>
        )}
        <div className="flex items-start gap-3">
          <h1 className="text-2xl font-bold text-gray-900 flex-1">{law.title}</h1>
          <button
            onClick={handleToggleFavorite}
            disabled={favoriteBusy}
            className="p-1.5 rounded hover:bg-pink-50 transition-colors flex-shrink-0 disabled:opacity-50"
            title={isFavorite ? "Remove from favorites" : "Add to favorites"}
            aria-label={isFavorite ? "Remove from favorites" : "Add to favorites"}
          >
            {isFavorite ? (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6 text-pink-500">
                <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0112 5.052 5.5 5.5 0 0116.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.219l-.022.012-.007.004-.003.001a.752.752 0 01-.704 0l-.003-.001z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6 text-gray-400 hover:text-pink-400">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
              </svg>
            )}
          </button>
        </div>
        <p className="text-gray-600 mt-1">
          Legea {law.law_number}/{law.law_year}
        </p>
        {law.description && (
          <p className="text-sm text-gray-500 mt-2">{law.description}</p>
        )}
        {law.issuer && (
          <p className="text-sm text-gray-500 mt-1">Issuer: {law.issuer}</p>
        )}
        <div className="mt-3 flex items-center gap-4">
          <StatusBadge
            lawId={law.id}
            initialStatus={law.status}
            initialOverride={law.status_override}
          />
          <DeleteVersionsButton
            lawId={law.id}
            oldVersionCount={law.versions.filter((v) => !v.is_current).length}
          />
        </div>
      </div>

      <div id="diff-selector">
        <DiffSelector lawId={law.id} versions={law.versions} />
      </div>

      <VersionsSection
        lawId={law.id}
        lastCheckedAt={law.last_checked_at}
        versions={law.versions}
      />
    </div>
  );
}
