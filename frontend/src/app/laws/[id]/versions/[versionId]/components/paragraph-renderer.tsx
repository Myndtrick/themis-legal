import { ParagraphData } from "@/lib/api";
import { Fragment, ReactNode } from "react";

// Matches text whose meaningful content is just "Abrogat/Eliminată" etc.
// Allows a short prefix (like "... 2^1.") and a trailing "(la ...)" note.
// Must not match long paragraphs that merely contain the word mid-text.
const ABROGAT_RE = /^(?:\.{3}\s*\d+(?:\^\d+)?\.\s*)?(?:abrogat|abrogat[ăe]|eliminat|eliminat[ăe])[.;]?\s*(?:\(la\s[\s\S]*)?$/i;

export function isAbrogat(text: string): boolean {
  return ABROGAT_RE.test(text.trim());
}

// Splits text into segments of plain text, (la ...) amendment refs, and Notă... blocks.
// Notă... blocks have no explicit end — they run until the next Notă... or end of text.
// (la ...) refs are parenthetical and end at the matching ")".

const LA_START = /\(la \d{2}-\d{2}-\d{4},/;
const NOTA_START = /Not[aă][\.\:]+|Not[aă]\.\.\./;

type Segment = { type: "plain" | "la" | "nota"; text: string };

function splitNotes(text: string): Segment[] {
  const segments: Segment[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    // Find the earliest note marker
    const laMatch = remaining.match(LA_START);
    const notaMatch = remaining.match(NOTA_START);

    const laIdx = laMatch ? laMatch.index! : Infinity;
    const notaIdx = notaMatch ? notaMatch.index! : Infinity;
    const nextIdx = Math.min(laIdx, notaIdx);

    if (nextIdx === Infinity) {
      // No more markers — rest is plain text
      if (remaining) segments.push({ type: "plain", text: remaining });
      break;
    }

    // Push plain text before the marker
    if (nextIdx > 0) {
      segments.push({ type: "plain", text: remaining.slice(0, nextIdx) });
    }

    if (notaIdx <= laIdx) {
      // Notă block: runs until the next Notă or end of text
      const afterNota = remaining.slice(notaIdx + notaMatch![0].length);
      const nextNotaInRest = afterNota.match(NOTA_START);
      if (nextNotaInRest) {
        const endIdx = notaIdx + notaMatch![0].length + nextNotaInRest.index!;
        segments.push({ type: "nota", text: remaining.slice(notaIdx, endIdx).trimEnd() });
        remaining = remaining.slice(endIdx);
      } else {
        segments.push({ type: "nota", text: remaining.slice(notaIdx).trimEnd() });
        break;
      }
    } else {
      // (la ...) block: ends at a 4-digit year followed by ")"
      const laText = remaining.slice(laIdx);
      const endMatch = laText.match(/\d{4}\)/g);
      let end: number;
      if (endMatch) {
        // Find the LAST year+) occurrence to get the full note
        let lastPos = 0;
        let searchFrom = 0;
        const yearEndRe = /\d{4}\)/g;
        let m;
        while ((m = yearEndRe.exec(laText)) !== null) {
          lastPos = m.index + m[0].length;
        }
        end = laIdx + lastPos;
      } else {
        // Fallback: take until end of text
        end = remaining.length;
      }
      // Include trailing period if present
      if (end < remaining.length && remaining[end] === ".") end++;
      segments.push({ type: "la", text: remaining.slice(laIdx, end) });
      remaining = remaining.slice(end);
    }
  }

  return segments;
}

function renderTextWithNotes(text: string): ReactNode {
  const segments = splitNotes(text);
  if (segments.length === 1 && segments[0].type === "plain") return text;

  return segments.map((seg, i) => {
    if (seg.type === "plain") {
      return <Fragment key={i}>{seg.text}</Fragment>;
    }
    const isNota = seg.type === "nota";
    return (
      <span
        key={i}
        className={`block mt-1 text-xs rounded px-2 py-1 leading-relaxed ${
          isNota
            ? "text-purple-700 bg-purple-50"
            : "text-amber-700 bg-amber-50"
        }`}
      >
        {seg.text}
      </span>
    );
  });
}

function renderAbrogatedWithNotes(text: string): ReactNode {
  // For abrogated text that may also contain an inline note
  const noteMatch = text.match(/(\(la \d{2}-\d{2}-\d{4},[\s\S]*)/);
  if (noteMatch) {
    const before = text.slice(0, noteMatch.index).trim();
    const note = noteMatch[1];
    return (
      <>
        {before && <span>{before}</span>}
        <span className="block mt-1 text-xs text-amber-700 bg-amber-50 rounded px-2 py-1 leading-relaxed not-italic">
          {note}
        </span>
      </>
    );
  }
  return text;
}

// Splits inline numbered sub-items like "... 1. text;... 2. text;... 3^1. text"
// into separate rendered blocks. The "..." is the separator used by leropa.
const INLINE_NUM_SPLIT = /\.\.\.\s*(?=\d+(?:\^\d+)?\.)/g;

function renderTextBlock(text: string): ReactNode {
  // First split inline numbered items, then apply note rendering to each
  const items = text.split(INLINE_NUM_SPLIT);
  if (items.length <= 1) return renderTextWithNotes(text);

  return (
    <>
      {items.map((item, i) => {
        const trimmed = item.trim();
        if (!trimmed) return null;
        // Check if this sub-item starts with a number label like "2^1. Abrogat."
        const labelMatch = trimmed.match(/^(\d+(?:\^\d+)?\.)\s*/);
        if (labelMatch && i > 0) {
          const numLabel = labelMatch[1];
          const rest = trimmed.slice(labelMatch[0].length);
          const abrogat = isAbrogat(rest);
          return (
            <div key={i} className={`flex gap-2 mt-1 pl-4 ${abrogat ? "text-red-500 italic" : ""}`}>
              <span className={`font-mono text-xs leading-[1.75] shrink-0 ${abrogat ? "text-red-400" : "text-gray-400"}`}>
                {renderInlineNumLabel(numLabel)}
              </span>
              <span className="leading-[1.75]">
                {abrogat ? renderAbrogatedWithNotes(rest) : renderTextWithNotes(rest)}
              </span>
            </div>
          );
        }
        // First item (the intro text before numbered items)
        return <Fragment key={i}>{renderTextWithNotes(trimmed)}</Fragment>;
      })}
    </>
  );
}

function renderInlineNumLabel(label: string): ReactNode {
  // Handle "2^1." -> 2<sup>1</sup>.
  const match = label.match(/^(\d+)\^(\d+)(\..*)$/);
  if (match) {
    return (
      <>
        {match[1]}
        <sup>{match[2]}</sup>
        {match[3]}
      </>
    );
  }
  return label;
}

type ParagraphType =
  | "plain"
  | "numbered"
  | "republished"
  | "lettered"
  | "bullet";

function classifyLabel(label: string | null | undefined): ParagraphType {
  if (!label || label.trim() === "") return "plain";
  if (/^\(\(\d+\)\)/.test(label)) return "republished";
  if (/^\(\d+\)/.test(label)) return "numbered";
  if (/^[a-z]\^?\d*\)/.test(label)) return "lettered";
  if (/^[-•]/.test(label)) return "bullet";
  return "plain";
}

function renderLabel(label: string) {
  // Handle superscript notation like d^1) -> d<sup>1</sup>)
  const match = label.match(/^([a-z])\^(\d+)(\).*)$/);
  if (match) {
    return (
      <>
        {match[1]}
        <sup>{match[2]}</sup>
        {match[3]}
      </>
    );
  }
  return label;
}

export function extractTitle(paragraphs: ParagraphData[]): string | null {
  if (paragraphs.length < 2) return null;
  const first = paragraphs[0];
  if (first.label && first.label.trim() !== "") return null;
  // A title (denumire marginală) is always a short, unlabelled first paragraph
  // followed by the actual article content
  if (first.text.length <= 120 && first.subparagraphs.length === 0) {
    return first.text;
  }
  return null;
}

function SubparagraphItem({
  label,
  text,
}: {
  label: string | null;
  text: string;
}) {
  const type = classifyLabel(label);
  const abrogat = isAbrogat(text);

  if (type === "bullet") {
    return (
      <li className={`text-[15px] leading-[1.75] ${abrogat ? "text-red-500 italic" : "text-gray-600"}`}>
        {abrogat ? renderAbrogatedWithNotes(text) : renderTextBlock(text)}
      </li>
    );
  }

  return (
    <div className="flex gap-2 pl-6">
      {label && (
        <span className={`font-mono text-xs leading-[1.75] shrink-0 ${abrogat ? "text-red-400" : "text-gray-500"}`}>
          {renderLabel(label)}
        </span>
      )}
      <span className={`text-[15px] leading-[1.75] ${abrogat ? "text-red-500 italic" : "text-gray-600"}`}>
        {abrogat ? renderAbrogatedWithNotes(text) : renderTextBlock(text)}
      </span>
    </div>
  );
}

function ParagraphItem({ paragraph }: { paragraph: ParagraphData }) {
  const type = classifyLabel(paragraph.label);
  const abrogat = isAbrogat(paragraph.text);
  const hasBulletSubs = paragraph.subparagraphs.some((sp) =>
    classifyLabel(sp.label) === "bullet"
  );

  const content = (
    <>
      <div className="flex gap-2">
        {paragraph.label && (
          <span className={`font-mono text-xs leading-[1.75] shrink-0 ${abrogat ? "text-red-400" : "text-gray-500"}`}>
            {renderLabel(paragraph.label)}
          </span>
        )}
        <span className={`text-[15px] leading-[1.75] ${abrogat ? "text-red-500 italic" : "text-gray-700"}`}>
          {abrogat ? renderAbrogatedWithNotes(paragraph.text) : renderTextBlock(paragraph.text)}
        </span>
      </div>
      {paragraph.subparagraphs.length > 0 && (
        hasBulletSubs ? (
          <ul className="list-disc pl-12 mt-1 space-y-0.5">
            {paragraph.subparagraphs.map((sp) => (
              <SubparagraphItem key={sp.id} label={sp.label} text={sp.text} />
            ))}
          </ul>
        ) : (
          <div className="mt-1 space-y-1">
            {paragraph.subparagraphs.map((sp) => (
              <SubparagraphItem key={sp.id} label={sp.label} text={sp.text} />
            ))}
          </div>
        )
      )}
    </>
  );

  if (type === "republished") {
    return (
      <div className="border-l-2 border-indigo-200 bg-indigo-50/30 rounded-r pl-2 py-0.5">
        {content}
      </div>
    );
  }

  if (type === "lettered") {
    return <div className="pl-6">{content}</div>;
  }

  return <div>{content}</div>;
}

export function ParagraphRenderer({
  paragraphs,
  hasTitle,
}: {
  paragraphs: ParagraphData[];
  hasTitle: boolean;
}) {
  const items = hasTitle ? paragraphs.slice(1) : paragraphs;

  return (
    <div className="space-y-2">
      {items.map((p) => (
        <ParagraphItem key={p.id} paragraph={p} />
      ))}
    </div>
  );
}
