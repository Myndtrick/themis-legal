import { LibraryLaw } from "@/lib/api";
import LawCard from "./law-card";

interface UnclassifiedSectionProps {
  laws: LibraryLaw[];
  onAssign: (lawId: number) => void;
}

export default function UnclassifiedSection({ laws, onAssign }: UnclassifiedSectionProps) {
  if (laws.length === 0) return null;

  return (
    <div className="mt-8 border-t-2 border-dashed border-gray-200 pt-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="font-bold text-sm text-amber-700">Necategorizat</span>
        <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
          {laws.length} law{laws.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="space-y-1.5">
        {laws.map((law) => (
          <LawCard key={law.id} law={law} showAssignButton onAssign={onAssign} />
        ))}
      </div>
    </div>
  );
}
