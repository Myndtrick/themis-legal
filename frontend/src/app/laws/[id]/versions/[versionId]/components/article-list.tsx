"use client";

import { useRef, useState, useEffect, type ReactNode } from "react";

export function ArticleList({
  children,
  batchSize = 40,
}: {
  children: ReactNode[];
  batchSize?: number;
}) {
  const [visibleCount, setVisibleCount] = useState(batchSize);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setVisibleCount((prev) => Math.min(prev + batchSize, children.length));
        }
      },
      { rootMargin: "200px" }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [batchSize, children.length]);

  const visible = children.slice(0, visibleCount);

  return (
    <>
      {visible}
      {visibleCount < children.length && (
        <div ref={sentinelRef} className="h-1" />
      )}
    </>
  );
}
