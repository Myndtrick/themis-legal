import Link from "next/link";
import { api, LawSummary } from "@/lib/api";
import ImportForm from "./import-form";

export const dynamic = "force-dynamic";

export default async function LawsPage() {
  let laws: LawSummary[] = [];
  let error: string | null = null;

  try {
    laws = await api.laws.list();
  } catch {
    error = "Could not connect to the backend. Make sure the API server is running.";
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Legal Library</h1>
          <p className="mt-2 text-gray-600">
            Browse Romanian laws with full version history
          </p>
        </div>
      </div>

      <ImportForm />

      {error && (
        <div className="rounded-md bg-red-50 border border-red-200 p-4 mb-6">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {!error && laws.length === 0 && (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <h3 className="text-lg font-medium text-gray-900 mb-2">
            No laws imported yet
          </h3>
          <p className="text-gray-600">
            Laws will appear here once they are imported from legislatie.just.ro
          </p>
        </div>
      )}

      {laws.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-200">
          {laws.map((law) => (
            <Link
              key={law.id}
              href={`/laws/${law.id}`}
              className="block p-4 hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-medium text-gray-900">{law.title}</h3>
                  <p className="text-sm text-gray-500 mt-1">
                    Legea {law.law_number}/{law.law_year}
                    {law.current_version?.state && (
                      <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                        {law.current_version.state}
                      </span>
                    )}
                  </p>
                </div>
                <div className="text-sm text-gray-400">
                  {law.version_count} version{law.version_count !== 1 ? "s" : ""}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
