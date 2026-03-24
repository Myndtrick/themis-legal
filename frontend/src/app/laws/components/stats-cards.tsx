interface StatsCardsProps {
  totalLaws: number;
  totalVersions: number;
  lastImported: string | null;
}

export default function StatsCards({ totalLaws, totalVersions, lastImported }: StatsCardsProps) {
  const formatted = lastImported
    ? new Date(lastImported).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
    : "—";

  return (
    <div className="flex gap-3 mb-5">
      <div className="flex-1 border border-gray-200 rounded-lg p-3 bg-white">
        <div className="text-xs text-gray-500">Total laws</div>
        <div className="text-2xl font-bold">{totalLaws}</div>
      </div>
      <div className="flex-1 border border-gray-200 rounded-lg p-3 bg-white">
        <div className="text-xs text-gray-500">Total versions</div>
        <div className="text-2xl font-bold">{totalVersions}</div>
      </div>
      <div className="flex-1 border border-gray-200 rounded-lg p-3 bg-white">
        <div className="text-xs text-gray-500">Last imported</div>
        <div className="text-2xl font-bold">{formatted}</div>
      </div>
    </div>
  );
}
