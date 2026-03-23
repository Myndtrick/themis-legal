import Link from "next/link";
import { api, StructuralElementData, ArticleData } from "@/lib/api";

function ArticleCard({ article }: { article: ArticleData }) {
  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white">
      <div className="flex items-start justify-between mb-2">
        <h4 className="font-medium text-gray-900">
          Art. {article.article_number}
        </h4>
        <span className="text-xs text-gray-400 font-mono">
          {article.citation}
        </span>
      </div>
      <div className="text-sm text-gray-700 whitespace-pre-wrap">
        {article.full_text}
      </div>
      {article.paragraphs.length > 0 && (
        <div className="mt-3 space-y-2 pl-4 border-l-2 border-gray-100">
          {article.paragraphs.map((p) => (
            <div key={p.id} className="text-sm">
              <span className="font-medium text-gray-600">
                ({p.paragraph_number})
              </span>{" "}
              <span className="text-gray-700">{p.text}</span>
              {p.subparagraphs.length > 0 && (
                <div className="pl-4 mt-1 space-y-1">
                  {p.subparagraphs.map((sp) => (
                    <div key={sp.id} className="text-sm text-gray-600">
                      {sp.label && (
                        <span className="font-medium">{sp.label}</span>
                      )}{" "}
                      {sp.text}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {article.amendment_notes.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <p className="text-xs font-medium text-amber-700 mb-1">
            Amendment Notes
          </p>
          {article.amendment_notes.map((note) => (
            <div
              key={note.id}
              className="text-xs text-gray-500 mb-1"
            >
              {note.date && <span className="font-medium">[{note.date}]</span>}{" "}
              {note.text}
              {note.original_text && note.replacement_text && (
                <div className="mt-1 pl-2 border-l-2 border-amber-200">
                  <div className="line-through text-red-400">
                    {note.original_text}
                  </div>
                  <div className="text-green-600">{note.replacement_text}</div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StructuralSection({ element }: { element: StructuralElementData }) {
  const typeLabels: Record<string, string> = {
    book: "Cartea",
    title: "Titlul",
    chapter: "Capitolul",
    section: "Secțiunea",
    subsection: "Subsecțiunea",
  };

  return (
    <div className="mb-6">
      <h3 className="text-base font-semibold text-gray-800 mb-3">
        {typeLabels[element.type] || element.type}{" "}
        {element.number && <span>{element.number}</span>}
        {element.title && (
          <span className="font-normal text-gray-600">
            {" "}
            — {element.title}
          </span>
        )}
      </h3>
      {element.articles.length > 0 && (
        <div className="space-y-3 mb-4">
          {element.articles.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}
      {element.children.length > 0 && (
        <div className="pl-4 border-l-2 border-gray-200">
          {element.children.map((child) => (
            <StructuralSection key={child.id} element={child} />
          ))}
        </div>
      )}
    </div>
  );
}

export default async function VersionDetailPage(
  props: PageProps<"/laws/[id]/versions/[versionId]">
) {
  const { id, versionId } = await props.params;
  const lawId = parseInt(id, 10);
  const verIdNum = parseInt(versionId, 10);

  let version;
  try {
    version = await api.laws.getVersion(lawId, verIdNum);
  } catch {
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

      {version.structure.length > 0 && (
        <div className="space-y-6">
          {version.structure.map((element) => (
            <StructuralSection key={element.id} element={element} />
          ))}
        </div>
      )}

      {version.articles.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-lg font-semibold text-gray-800 mb-3">
            Articles
          </h3>
          {version.articles.map((article) => (
            <ArticleCard key={article.id} article={article} />
          ))}
        </div>
      )}

      {version.structure.length === 0 && version.articles.length === 0 && (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <p className="text-gray-500">
            No content found for this version
          </p>
        </div>
      )}
    </div>
  );
}
