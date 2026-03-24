"use client";

import { useState, useEffect, useCallback, useRef } from "react";

export function LawToolbar() {
  const [articleNumber, setArticleNumber] = useState("");
  const [keyword, setKeyword] = useState("");
  const [matchCount, setMatchCount] = useState<number | null>(null);
  const [currentMatch, setCurrentMatch] = useState(0);
  const [showScrollTop, setShowScrollTop] = useState(false);
  const matchedEls = useRef<HTMLElement[]>([]);

  // Show/hide back-to-top button
  useEffect(() => {
    const onScroll = () => setShowScrollTop(window.scrollY > 400);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Jump to article by number
  const goToArticle = useCallback(() => {
    const num = articleNumber.trim().replace(/^art\.?\s*/i, "");
    if (!num) return;

    // Try exact id match first
    const el = document.getElementById(`art-${num}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      el.classList.add("ring-2", "ring-blue-400");
      setTimeout(() => el.classList.remove("ring-2", "ring-blue-400"), 2000);
    }
  }, [articleNumber]);

  // Remove all <mark> highlights from the DOM
  const removeMarks = useCallback(() => {
    document.querySelectorAll("mark[data-kw-highlight]").forEach((mark) => {
      const parent = mark.parentNode;
      if (!parent) return;
      parent.replaceChild(document.createTextNode(mark.textContent || ""), mark);
      parent.normalize(); // merge adjacent text nodes
    });
  }, []);

  // Clear previous highlights
  const clearHighlights = useCallback(() => {
    matchedEls.current.forEach((el) => {
      el.classList.remove("ring-2", "ring-amber-400");
    });
    removeMarks();
    matchedEls.current = [];
    setMatchCount(null);
    setCurrentMatch(0);
  }, [removeMarks]);

  // Highlight matched words inside a container element
  const highlightTextIn = useCallback((container: HTMLElement, query: string) => {
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const textNodes: Text[] = [];
    let node: Node | null;
    while ((node = walker.nextNode())) {
      textNodes.push(node as Text);
    }

    const lowerQ = query.toLowerCase();

    for (const textNode of textNodes) {
      const text = textNode.textContent || "";
      const lowerText = text.toLowerCase();
      if (!lowerText.includes(lowerQ)) continue;

      const fragment = document.createDocumentFragment();
      let lastIdx = 0;
      let searchFrom = 0;

      while (true) {
        const idx = lowerText.indexOf(lowerQ, searchFrom);
        if (idx === -1) break;

        // Text before match
        if (idx > lastIdx) {
          fragment.appendChild(document.createTextNode(text.slice(lastIdx, idx)));
        }

        // Highlighted match
        const mark = document.createElement("mark");
        mark.setAttribute("data-kw-highlight", "");
        mark.className = "bg-yellow-300 text-inherit rounded-sm px-0.5";
        mark.textContent = text.slice(idx, idx + query.length);
        fragment.appendChild(mark);

        lastIdx = idx + query.length;
        searchFrom = lastIdx;
      }

      // Remaining text after last match
      if (lastIdx < text.length) {
        fragment.appendChild(document.createTextNode(text.slice(lastIdx)));
      }

      textNode.parentNode?.replaceChild(fragment, textNode);
    }
  }, []);

  // Keyword search
  const searchKeyword = useCallback(() => {
    clearHighlights();
    const q = keyword.trim();
    if (!q) return;

    const lowerQ = q.toLowerCase();
    const articles = document.querySelectorAll<HTMLElement>("[data-article-number]");
    const matches: HTMLElement[] = [];

    articles.forEach((el) => {
      const text = el.textContent?.toLowerCase() || "";
      if (text.includes(lowerQ)) {
        matches.push(el);
        el.classList.add("ring-2", "ring-amber-400");
        highlightTextIn(el, q);
      }
    });

    matchedEls.current = matches;
    setMatchCount(matches.length);

    if (matches.length > 0) {
      setCurrentMatch(0);
      matches[0].scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [keyword, clearHighlights, highlightTextIn]);

  // Navigate between keyword matches
  const goToMatch = useCallback(
    (direction: "next" | "prev") => {
      const matches = matchedEls.current;
      if (matches.length === 0) return;

      let idx = currentMatch;
      if (direction === "next") {
        idx = (idx + 1) % matches.length;
      } else {
        idx = (idx - 1 + matches.length) % matches.length;
      }

      setCurrentMatch(idx);
      matches[idx].scrollIntoView({ behavior: "smooth", block: "start" });
    },
    [currentMatch]
  );

  // Clear keyword highlights when input is emptied
  useEffect(() => {
    if (!keyword.trim()) clearHighlights();
  }, [keyword, clearHighlights]);

  return (
    <>
      {/* Search toolbar */}
      <div className="sticky top-0 z-30 bg-white/95 backdrop-blur border-b border-gray-200 py-3 px-4 mb-6 -mx-4 flex flex-wrap items-center gap-3">
        {/* Article number jump */}
        <div className="flex items-center gap-1.5">
          <label className="text-sm font-medium text-gray-600 whitespace-nowrap">
            Art. nr:
          </label>
          <input
            type="text"
            value={articleNumber}
            onChange={(e) => setArticleNumber(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && goToArticle()}
            placeholder="e.g. 15"
            className="w-24 px-2.5 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-blue-400"
          />
          <button
            onClick={goToArticle}
            className="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 transition-colors"
          >
            Go
          </button>
        </div>

        {/* Divider */}
        <div className="h-6 w-px bg-gray-300 hidden sm:block" />

        {/* Keyword search */}
        <div className="flex items-center gap-1.5">
          <label className="text-sm font-medium text-gray-600 whitespace-nowrap">
            Search:
          </label>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && searchKeyword()}
            placeholder="keyword..."
            className="w-40 sm:w-56 px-2.5 py-1.5 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-amber-400"
          />
          <button
            onClick={searchKeyword}
            className="px-3 py-1.5 text-sm font-medium text-white bg-amber-600 rounded-md hover:bg-amber-700 transition-colors"
          >
            Find
          </button>
          {matchCount !== null && (
            <div className="flex items-center gap-1 text-sm text-gray-600">
              <span>
                {matchCount === 0
                  ? "No matches"
                  : `${currentMatch + 1}/${matchCount}`}
              </span>
              {matchCount > 1 && (
                <>
                  <button
                    onClick={() => goToMatch("prev")}
                    className="p-1 rounded hover:bg-gray-100"
                    title="Previous match"
                  >
                    &#x25B2;
                  </button>
                  <button
                    onClick={() => goToMatch("next")}
                    className="p-1 rounded hover:bg-gray-100"
                    title="Next match"
                  >
                    &#x25BC;
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Back to top button */}
      {showScrollTop && (
        <button
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          className="fixed bottom-6 right-6 z-40 p-3 bg-blue-600 text-white rounded-full shadow-lg hover:bg-blue-700 transition-all hover:scale-105"
          title="Back to top"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-5 w-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M5 15l7-7 7 7"
            />
          </svg>
        </button>
      )}
    </>
  );
}
