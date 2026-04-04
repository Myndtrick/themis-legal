import { useState } from "react";
import Link from "next/link";
import { api, LibraryLaw } from "@/lib/api";

const STATE_COLORS: Record<string, string> = {
  actual: "bg-green-100 text-green-800",
  republished: "bg-blue-100 text-blue-800",
  amended: "bg-yellow-100 text-yellow-800",
  deprecated: "bg-red-100 text-red-800",
};

interface LawCardProps {
  law: LibraryLaw;
  showAssignButton?: boolean;
  onAssign?: (lawId: number) => void;
  onDelete?: () => void;
  isFavorite?: boolean;
  onToggleFavorite?: (lawId: number) => void;
}

const DOC_TYPE_PREFIX: Record<string, string> = {
  law: "Legea",
  code: "Codul",
  government_ordinance: "OG",
  government_resolution: "HG",
  decree: "Decretul",
  order: "Ordinul",
  regulation: "Regulamentul",
  norm: "Norma",
  decision: "Decizia",
  other: "Legea",
};

function issuerColor(issuer: string): string {
  const s = issuer.toUpperCase();
  if (s.includes("PARLAMENT")) return "bg-purple-100 text-purple-800";
  if (s.includes("GUVERN")) return "bg-amber-100 text-amber-800";
  if (s.includes("MINISTER")) return "bg-teal-100 text-teal-800";
  if (s.includes("AGENȚI") || s.includes("AGENTI") || s.includes("AGENȚIA") || s.includes("AGENTIA")) return "bg-cyan-100 text-cyan-800";
  if (s.includes("DIRECȚI") || s.includes("DIRECTI") || s.includes("DIRECȚIA") || s.includes("DIRECTIA")) return "bg-indigo-100 text-indigo-800";
  if (s.includes("COMISI")) return "bg-blue-100 text-blue-800";
  if (s.includes("CONSILIU")) return "bg-yellow-100 text-yellow-800";
  if (s.includes("BANC")) return "bg-emerald-100 text-emerald-800";
  return "bg-gray-100 text-gray-700";
}

export default function LawCard({ law, showAssignButton, onAssign, onDelete, isFavorite, onToggleFavorite }: LawCardProps) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState<"all" | "old" | false>(false);
  const [hidden, setHidden] = useState(false);
  const state = law.current_version?.state;
  const colorClass = state ? STATE_COLORS[state] || "bg-gray-100 text-gray-600" : "";
  const prefix = DOC_TYPE_PREFIX[law.document_type] || "Legea";

  async function handleDelete() {
    setDeleting("all");
    try {
      await api.laws.delete(law.id);
      setHidden(true);
      onDelete?.();
    } catch {
      alert("Failed to delete law.");
      setDeleting(false);
      setConfirming(false);
    }
  }

  async function handleDeleteOldVersions() {
    setDeleting("old");
    try {
      await api.laws.deleteOldVersions(law.id);
      onDelete?.();
    } catch {
      alert("Failed to delete old versions.");
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  }

  if (hidden) return null;

  return (
    <div className={`border border-gray-200 rounded-lg bg-white p-3 flex justify-between items-center transition-colors ${deleting ? "opacity-50 pointer-events-none" : "hover:bg-gray-50"}`}>
      <Link href={`/laws/${law.id}`} className="flex-1 min-w-0">
        <div className="font-semibold text-sm text-gray-900 line-clamp-2">
          {law.title}
          {law.description && (
            <span className="font-normal text-gray-900"> — {law.description}</span>
          )}
        </div>
        <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-2">
          {law.source === "eu" ? (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300">
              EU
            </span>
          ) : (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300">
              RO
            </span>
          )}
          {law.language === "en" && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400">
              EN
            </span>
          )}
          {state && (
            <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${colorClass}`}>
              {state}
            </span>
          )}
          {law.issuer && law.issuer.split(",").map((iss) => iss.trim()).filter(Boolean).map((iss, i) => (
            <span key={i} className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${issuerColor(iss)}`}>{iss}</span>
          ))}
        </div>
      </Link>
      <div className="flex items-center gap-2 ml-3 flex-shrink-0">
        <span className="text-xs text-gray-400">
          {law.version_count} version{law.version_count !== 1 ? "s" : ""}
        </span>
        {law.unimported_version_count > 0 && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
            {law.unimported_version_count} new
          </span>
        )}
        {onToggleFavorite && (
          <button
            onClick={(e) => { e.preventDefault(); onToggleFavorite(law.id); }}
            className="p-1 rounded hover:bg-pink-50 transition-colors"
            title={isFavorite ? "Remove from favorites" : "Add to favorites"}
          >
            {isFavorite ? (
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-pink-500">
                <path d="M11.645 20.91l-.007-.003-.022-.012a15.247 15.247 0 01-.383-.218 25.18 25.18 0 01-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0112 5.052 5.5 5.5 0 0116.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 01-4.244 3.17 15.247 15.247 0 01-.383.219l-.022.012-.007.004-.003.001a.752.752 0 01-.704 0l-.003-.001z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4 text-gray-400 hover:text-pink-400">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
              </svg>
            )}
          </button>
        )}
        {showAssignButton && onAssign && (
          <button
            onClick={(e) => { e.preventDefault(); onAssign(law.id); }}
            className="text-xs border border-amber-500 text-amber-600 px-2.5 py-1 rounded hover:bg-amber-50 transition-colors"
          >
            Assign category
          </button>
        )}
        {confirming ? (
          <div className="flex items-center gap-1.5" onClick={(e) => e.preventDefault()}>
            <button
              onClick={handleDelete}
              disabled={!!deleting}
              className="px-2 py-1 text-xs font-medium text-white bg-red-600 rounded hover:bg-red-700 disabled:bg-gray-300"
            >
              {deleting === "all" ? "Deleting…" : "Delete all"}
            </button>
            {law.version_count > 1 && (
              <button
                onClick={handleDeleteOldVersions}
                disabled={!!deleting}
                className="px-2 py-1 text-xs font-medium text-red-700 bg-red-50 border border-red-200 rounded hover:bg-red-100 disabled:bg-gray-300"
              >
                {deleting === "old" ? "Deleting…" : "Old only"}
              </button>
            )}
            {!deleting && (
              <button
                onClick={(e) => { e.preventDefault(); setConfirming(false); }}
                className="px-2 py-1 text-xs font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200"
              >
                Cancel
              </button>
            )}
          </div>
        ) : (
          <button
            onClick={(e) => { e.preventDefault(); setConfirming(true); }}
            className="px-2 py-1 text-xs font-medium text-red-600 bg-red-50 rounded hover:bg-red-100 transition-colors"
          >
            Delete
          </button>
        )}
      </div>
    </div>
  );
}
