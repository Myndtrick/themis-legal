import { StructuralElementData } from "@/lib/api";
import { ArticleCard } from "./article-card";
import { ArticleList } from "./article-list";

const typeLabels: Record<string, string> = {
  book: "Cartea",
  title: "Titlul",
  chapter: "Capitolul",
  section: "Secțiunea",
  subsection: "Subsecțiunea",
};

const typeStyles: Record<
  string,
  { heading: string; card: string; wrapper: string; description: string }
> = {
  book: {
    heading: "text-xl font-bold text-indigo-900 uppercase tracking-wide",
    card: "bg-indigo-50 border-2 border-indigo-300 rounded-xl px-6 py-4 shadow-sm",
    wrapper: "mt-10 mb-6",
    description: "text-indigo-600",
  },
  title: {
    heading: "text-lg font-bold text-blue-800",
    card: "bg-blue-50 border-2 border-blue-300 rounded-xl px-5 py-3 shadow-sm",
    wrapper: "mt-8 mb-5",
    description: "text-blue-600",
  },
  chapter: {
    heading: "text-base font-semibold text-teal-800",
    card: "bg-teal-50 border border-teal-300 rounded-lg px-5 py-3",
    wrapper: "mt-6 mb-4",
    description: "text-teal-600",
  },
  section: {
    heading: "text-sm font-semibold text-amber-800",
    card: "bg-amber-50 border border-amber-300 rounded-lg px-4 py-2.5",
    wrapper: "mt-4 mb-3",
    description: "text-amber-600",
  },
  subsection: {
    heading: "text-sm font-medium text-rose-700",
    card: "bg-rose-50 border border-rose-300 rounded-lg px-4 py-2",
    wrapper: "mt-3 mb-2",
    description: "text-rose-500",
  },
};

const defaultStyle = {
  heading: "text-sm font-semibold text-gray-700",
  card: "bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5",
  wrapper: "mt-4 mb-3",
  description: "text-gray-500",
};

export function StructuralSection({
  element,
}: {
  element: StructuralElementData;
}) {
  const style = typeStyles[element.type] || defaultStyle;
  const articleCards = element.articles.map((article) => (
    <ArticleCard key={article.id} article={article} />
  ));

  const label = typeLabels[element.type] || element.type;
  // Build heading: "Capitolul III — Drepturile persoanei vizate"
  // For Romanian laws, title already contains "Capitolul I" so don't duplicate
  const titleAlreadyHasLabel = element.title?.toLowerCase().startsWith(label.toLowerCase());
  let heading: string;
  if (titleAlreadyHasLabel) {
    // Romanian law pattern: title = "Capitolul I" — use as-is
    heading = element.title!;
  } else if (element.number && element.title) {
    // EU law pattern: number = "III", title = "Drepturile persoanei vizate"
    heading = `${label} ${element.number} — ${element.title}`;
  } else if (element.number) {
    heading = `${label} ${element.number}`;
  } else if (element.title) {
    heading = element.title;
  } else {
    heading = label;
  }

  return (
    <div className={style.wrapper}>
      <div className={`${style.card} text-center`}>
        <h3 className={style.heading}>
          {heading}
        </h3>
        {element.description && (
          <p className={`${style.description} text-sm mt-1 font-normal`}>
            {element.description}
          </p>
        )}
      </div>
      {articleCards.length > 0 && (
        <div className="space-y-3 mt-4 mb-4">
          {articleCards.length > 40 ? (
            <ArticleList>{articleCards}</ArticleList>
          ) : (
            articleCards
          )}
        </div>
      )}
      {element.children.length > 0 && (
        <div>
          {element.children.map((child) => (
            <StructuralSection key={child.id} element={child} />
          ))}
        </div>
      )}
    </div>
  );
}
