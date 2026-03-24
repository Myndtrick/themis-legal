import Link from "next/link";
import { api } from "@/lib/api";
import DiffSelector from "./diff-selector";
import DeleteVersionsButton from "./delete-versions-button";
import CheckUpdatesButton from "./check-updates-button";
import StatusBadge from "./status-badge";

export default async function LawDetailPage(props: PageProps<"/laws/[id]">) {
  const { id } = await props.params;
  const lawId = parseInt(id, 10);

  let law;
  try {
    law = await api.laws.get(lawId);
  } catch {
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
            <span className="bg-amber-100 text-amber-700 px-2 py-0.5 rounded text-xs">Necategorizat</span>
          </div>
        )}
        <h1 className="text-2xl font-bold text-gray-900">{law.title}</h1>
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
          <CheckUpdatesButton lawId={law.id} />
        </div>
      </div>

      <DiffSelector lawId={law.id} versions={law.versions} />

      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">
            Versions ({law.versions.length})
          </h2>
          <DeleteVersionsButton
            lawId={law.id}
            oldVersionCount={law.versions.filter((v) => !v.is_current).length}
          />
        </div>
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-200">
          {law.versions.map((version) => (
            <Link
              key={version.id}
              href={`/laws/${law.id}/versions/${version.id}`}
              className="block p-4 hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-gray-900">
                    {version.date_in_force || "Date unknown"}
                  </span>
                  <span className="ml-2 text-sm text-gray-500">
                    (ver_id: {version.ver_id})
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      version.is_current
                        ? "bg-green-100 text-green-700"
                        : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {version.is_current ? "Current" : version.state}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
