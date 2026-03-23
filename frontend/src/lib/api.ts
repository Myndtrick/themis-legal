const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface LawSummary {
  id: number;
  title: string;
  law_number: string;
  law_year: number;
  document_type: string;
  description: string | null;
  version_count: number;
  current_version: {
    id: number;
    ver_id: string;
    date_in_force: string | null;
    state: string;
  } | null;
}

export interface LawDetail {
  id: number;
  title: string;
  law_number: string;
  law_year: number;
  document_type: string;
  description: string | null;
  keywords: string | null;
  issuer: string | null;
  source_url: string | null;
  versions: LawVersionSummary[];
}

export interface LawVersionSummary {
  id: number;
  ver_id: string;
  date_in_force: string | null;
  date_imported: string;
  state: string;
  is_current: boolean;
}

export interface ArticleData {
  id: number;
  article_number: string;
  label: string | null;
  full_text: string;
  citation: string;
  paragraphs: ParagraphData[];
  amendment_notes: AmendmentNoteData[];
}

export interface ParagraphData {
  id: number;
  paragraph_number: string;
  label: string | null;
  text: string;
  subparagraphs: { id: number; label: string | null; text: string }[];
}

export interface AmendmentNoteData {
  id: number;
  text: string | null;
  date: string | null;
  subject: string | null;
  original_text: string | null;
  replacement_text: string | null;
}

export interface StructuralElementData {
  id: number;
  type: string;
  number: string | null;
  title: string | null;
  description: string | null;
  children: StructuralElementData[];
  articles: ArticleData[];
}

export interface LawVersionDetail {
  id: number;
  ver_id: string;
  date_in_force: string | null;
  state: string;
  is_current: boolean;
  law: {
    id: number;
    title: string;
    law_number: string;
    law_year: number;
  };
  structure: StructuralElementData[];
  articles: ArticleData[];
}

export interface NotificationData {
  id: number;
  title: string;
  message: string;
  type: string;
  is_read: boolean;
  created_at: string;
}

export interface DiffChange {
  article_number: string;
  change_type: "added" | "removed" | "modified" | "unchanged";
  text_a: string | null;
  text_b: string | null;
  diff_html: string | null;
}

export interface DiffResult {
  law_id: number;
  version_a: { id: number; ver_id: string; date_in_force: string | null };
  version_b: { id: number; ver_id: string; date_in_force: string | null };
  summary: {
    added: number;
    removed: number;
    modified: number;
    unchanged: number;
  };
  changes: DiffChange[];
}

// API functions
export const api = {
  laws: {
    list: () => apiFetch<LawSummary[]>("/api/laws/"),
    get: (id: number) => apiFetch<LawDetail>(`/api/laws/${id}`),
    getVersion: (lawId: number, versionId: number) =>
      apiFetch<LawVersionDetail>(
        `/api/laws/${lawId}/versions/${versionId}`
      ),
    diff: (lawId: number, versionA: number, versionB: number) =>
      apiFetch<DiffResult>(
        `/api/laws/${lawId}/diff?version_a=${versionA}&version_b=${versionB}`
      ),
    delete: (id: number) =>
      apiFetch<{ message: string }>(`/api/laws/${id}`, { method: "DELETE" }),
    deleteOldVersions: (id: number) =>
      apiFetch<{ message: string; deleted_count: number }>(
        `/api/laws/${id}/versions/old`,
        { method: "DELETE" }
      ),
    checkUpdates: (id: number) =>
      apiFetch<{ has_update: boolean; message: string }>(
        `/api/laws/${id}/check-updates`,
        { method: "POST" }
      ),
  },
  notifications: {
    list: (unreadOnly = false) =>
      apiFetch<NotificationData[]>(
        `/api/notifications/?unread_only=${unreadOnly}`
      ),
    unreadCount: () =>
      apiFetch<{ count: number }>("/api/notifications/unread-count"),
    markAsRead: (id: number) =>
      apiFetch<{ ok: boolean }>(`/api/notifications/${id}/read`, {
        method: "PUT",
      }),
    markAllAsRead: () =>
      apiFetch<{ ok: boolean }>("/api/notifications/read-all", {
        method: "PUT",
      }),
  },
};
