import { ArticleData } from "@/lib/api";
import { ParagraphRenderer, extractTitle, isAbrogat } from "./paragraph-renderer";
import { AmendmentNotes } from "./amendment-notes";

function isArticleAbrogat(article: ArticleData, title: string | null): boolean {
  // If the extracted title says "Abrogat", the whole article is abrogated
  if (title && isAbrogat(title)) return true;
  if (article.paragraphs.length > 0) {
    // Check labeled (content) paragraphs — if all are abrogat
    const contentParagraphs = article.paragraphs.filter(
      (p) => p.label && p.label.trim() !== ""
    );
    if (contentParagraphs.length > 0) {
      return contentParagraphs.every((p) => isAbrogat(p.text));
    }
    return article.paragraphs.every((p) => isAbrogat(p.text));
  }
  return isAbrogat(article.full_text || "");
}

export function ArticleCard({ article }: { article: ArticleData }) {
  const title = article.paragraphs.length > 0
    ? extractTitle(article.paragraphs)
    : null;
  const abrogat = isArticleAbrogat(article, title);

  return (
    <div
      id={`art-${article.article_number}`}
      data-article-number={article.article_number}
      className={`border rounded-lg p-4 ${abrogat ? "border-red-200 bg-red-50/50" : "border-gray-200 bg-white"}`}
    >
      <div className="flex items-start justify-between mb-2">
        <h4 className={`font-medium ${abrogat ? "text-red-600" : "text-gray-900"}`}>
          Art. {article.article_number}
          {title && (
            <span className="font-bold">
              {" "}&mdash; {title}
            </span>
          )}
        </h4>
        <span className="text-xs text-gray-400 font-mono shrink-0 ml-4">
          {article.citation}
        </span>
      </div>
      {article.paragraphs.length > 0 ? (
        <ParagraphRenderer paragraphs={article.paragraphs} hasTitle={!!title} />
      ) : (
        <div className={`text-[15px] whitespace-pre-wrap leading-[1.75] ${abrogat ? "text-red-500 italic" : "text-gray-700"}`}>
          {article.full_text}
        </div>
      )}
      <AmendmentNotes notes={article.amendment_notes} />
    </div>
  );
}
