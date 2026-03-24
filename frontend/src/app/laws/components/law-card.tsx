import Link from "next/link";
import { LibraryLaw } from "@/lib/api";

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

export default function LawCard({ law, showAssignButton, onAssign }: LawCardProps) {
  const state = law.current_version?.state;
  const colorClass = state ? STATE_COLORS[state] || "bg-gray-100 text-gray-600" : "";
  const prefix = DOC_TYPE_PREFIX[law.document_type] || "Legea";

  return (
    <div className="border border-gray-200 rounded-lg bg-white p-3 flex justify-between items-center hover:bg-gray-50 transition-colors">
      <Link href={`/laws/${law.id}`} className="flex-1 min-w-0">
        <div className="font-semibold text-sm text-gray-900">{law.title}</div>
        <div className="text-xs text-gray-500 mt-0.5">
          {prefix} {law.law_number}/{law.law_year}
          {state && (
            <span className={`ml-2 inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${colorClass}`}>
              {state}
            </span>
          )}
        </div>
      </Link>
      <div className="flex items-center gap-2 ml-3 flex-shrink-0">
        <span className="text-xs text-gray-400">
          {law.version_count} version{law.version_count !== 1 ? "s" : ""}
        </span>
        {showAssignButton && onAssign && (
          <button
            onClick={(e) => { e.preventDefault(); onAssign(law.id); }}
            className="text-xs border border-amber-500 text-amber-600 px-2.5 py-1 rounded hover:bg-amber-50 transition-colors"
          >
            Assign category
          </button>
        )}
      </div>
    </div>
  );
}
