"use client";

import { useState } from "react";
import { AmendmentNoteData } from "@/lib/api";

function NoteItem({ note }: { note: AmendmentNoteData }) {
  return (
    <div className="text-xs text-gray-500 mb-1">
      {note.date && <span className="font-medium">[{note.date}]</span>}{" "}
      {note.text}
      {note.original_text && note.replacement_text && (
        <div className="mt-1 pl-2 border-l-2 border-amber-200">
          <div className="line-through text-red-400">{note.original_text}</div>
          <div className="text-green-600">{note.replacement_text}</div>
        </div>
      )}
    </div>
  );
}

export function AmendmentNotes({ notes }: { notes: AmendmentNoteData[] }) {
  const [expanded, setExpanded] = useState(false);

  if (notes.length === 0) return null;

  const totalLength = notes.reduce(
    (sum, n) => sum + (n.text?.length || 0),
    0
  );
  const shouldCollapse = totalLength > 300 && notes.length > 1;
  const visible = shouldCollapse && !expanded ? notes.slice(0, 1) : notes;

  return (
    <div className="mt-3 pt-3 border-t border-gray-100">
      <p className="text-xs font-medium text-amber-700 mb-1">
        Amendment Notes
      </p>
      {visible.map((note) => (
        <NoteItem key={note.id} note={note} />
      ))}
      {shouldCollapse && !expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="text-xs text-amber-600 hover:text-amber-800 mt-1 cursor-pointer"
        >
          Afișează toate notele ({notes.length - 1} mai mult)
        </button>
      )}
      {shouldCollapse && expanded && (
        <button
          onClick={() => setExpanded(false)}
          className="text-xs text-amber-600 hover:text-amber-800 mt-1 cursor-pointer"
        >
          Ascunde notele
        </button>
      )}
    </div>
  );
}
