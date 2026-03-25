const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });
  } catch {
    throw new Error(
      `Cannot reach the backend at ${API_BASE}. Is the server running?`
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${body || res.statusText}`);
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
  status: string;
  status_override: boolean;
  current_version: {
    id: number;
    ver_id: string;
    date_in_force: string | null;
    state: string;
  } | null;
}

export interface CategoryData {
  id: number;
  slug: string;
  name_ro: string;
  name_en: string;
  description: string | null;
  law_count: number;
}

export interface CategoryGroupData {
  id: number;
  slug: string;
  name_ro: string;
  name_en: string;
  color_hex: string;
  sort_order: number;
  categories: CategoryData[];
}

export interface LibraryLaw {
  id: number;
  title: string;
  law_number: string;
  law_year: number;
  document_type: string;
  description: string | null;
  issuer: string | null;
  version_count: number;
  status: string;
  category_id: number | null;
  category_group_slug: string | null;
  category_confidence: string | null;
  current_version: {
    id: number;
    state: string;
  } | null;
}

export interface SuggestedLaw {
  id: number;
  title: string;
  law_number: string | null;
  category_id: number;
  category_slug: string;
  group_slug: string;
}

export interface LibraryData {
  groups: CategoryGroupData[];
  laws: LibraryLaw[];
  stats: {
    total_laws: number;
    total_versions: number;
    last_imported: string | null;
  };
  suggested_laws: SuggestedLaw[];
}

export interface LocalSearchResult {
  id: number;
  title: string;
  law_number: string;
  law_year: number;
  version_count: number;
  category_name: string | null;
  current_version: {
    id: number;
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
  status: string;
  status_override: boolean;
  versions: LawVersionSummary[];
  category: {
    id: number;
    slug: string;
    name_ro: string;
    name_en: string;
    group_name_ro: string;
    group_name_en: string;
    group_color_hex: string;
  } | null;
  category_confidence: string | null;
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

export interface AnnexData {
  id: number;
  source_id: string;
  title: string;
  full_text: string;
  order_index: number;
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
  annexes: AnnexData[];
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

export interface AdvancedSearchResult {
  ver_id: string;
  title: string;
  doc_type: string;
  number: string;
  date: string;
  date_iso: string | null;
  issuer: string;
  description: string;
  already_imported: boolean;
  local_law_id: number | null;
}

export interface AdvancedSearchResponse {
  results: AdvancedSearchResult[];
  total: number;
}

export interface EmitentsResponse {
  emitents: string[];
}

// --- Legal Assistant types ---

export interface ChatSession {
  id: string;
  title: string | null;
  created_at: string;
  last_active_at: string;
  message_count: number;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  mode: string | null;
  run_id: string | null;
  reasoning_data: string | null;
  created_at: string;
  clarification_type?: "missing_context" | "missing_law";
  missing_laws?: LawPreview[];
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[];
}

export interface StructuredAnswer {
  answer?: string;
  short_answer?: string;
  legal_basis?: string | null;
  version_logic?: string | null;
  nuances?: string | null;
  changes_over_time?: string | null;
  missing_info?: string | null;
  confidence: string;
  confidence_reason: string | null;
  sources: Array<{
    statement: string;
    label: string;
    law: string | null;
    article: string | null;
    version_date: string | null;
  }>;
}

export interface ReasoningStep {
  step: number;
  name: string;
  status: "running" | "done" | "paused";
  data?: Record<string, unknown>;
  duration?: number;
}

export interface MissingLaw {
  law_number: string;
  law_year: number;
  title: string;
  reason: string;
}

export interface LawPreview {
  law_number: string;
  law_year: string;
  title: string;
  role: "PRIMARY" | "SECONDARY";
  availability: "available" | "wrong_version" | "missing";
  version_info: string | null;
  reason?: string;
  needed_for_date?: string | null;
  date_reason?: string | null;
}

// --- Settings: Prompts types ---

export interface PromptSummary {
  prompt_id: string;
  description: string;
  version_number: number;
  status: string;
  modified_at: string | null;
}

export interface PromptDetail {
  prompt_id: string;
  description: string;
  version_number: number;
  status: string;
  prompt_text: string;
  created_at: string;
  created_by: string;
  modification_note: string | null;
}

export interface PromptVersionSummary {
  version_number: number;
  status: string;
  created_at: string;
  created_by: string;
  modification_note: string | null;
}

export interface PromptDiff {
  prompt_id: string;
  current_version: number;
  proposed_version: number;
  current_text: string;
  proposed_text: string;
  modification_note: string;
  pending_version_id: number;
}

// --- Settings: Pipeline types ---

export interface PipelineRunSummary {
  run_id: string;
  module: string;
  mode: string | null;
  question_summary: string | null;
  started_at: string;
  completed_at: string | null;
  overall_status: string;
  overall_confidence: string | null;
  total_duration_seconds: number | null;
  estimated_cost: number | null;
}

export interface StepLogData {
  step_name: string;
  step_number: number;
  status: string;
  duration_seconds: number | null;
  prompt_id: string | null;
  prompt_version: number | null;
  input_summary: string | null;
  output_summary: string | null;
  output_data: Record<string, unknown> | null;
  confidence: string | null;
  warnings: string | null;
}

export interface APICallLogData {
  step_name: string;
  tokens_in: number;
  tokens_out: number;
  duration_seconds: number;
  model: string;
}

export interface PipelineRunDetail extends PipelineRunSummary {
  flags: string | null;
  steps: StepLogData[];
  api_calls: APICallLogData[];
}

export interface HealthStats {
  total_runs: number;
  ok_count: number;
  warning_count: number;
  error_count: number;
  partial_count: number;
  ok_pct: number;
  warning_pct: number;
  error_pct: number;
  avg_confidence_high_pct: number;
  avg_duration_seconds: number;
  avg_cost: number;
  most_common_warnings: string[];
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
    advancedSearch: (params: Record<string, string>) => {
      const query = new URLSearchParams(params).toString();
      return apiFetch<AdvancedSearchResponse>(`/api/laws/advanced-search?${query}`);
    },
    emitents: (q: string) =>
      apiFetch<EmitentsResponse>(`/api/laws/emitents?q=${encodeURIComponent(q)}`),
    updateStatus: (id: number, status: string, override: boolean) =>
      apiFetch<{ status: string; status_override: boolean }>(
        `/api/laws/${id}/status`,
        {
          method: "PATCH",
          body: JSON.stringify({ status, override }),
        }
      ),
    library: () => apiFetch<LibraryData>("/api/laws/library"),
    localSearch: (q: string) =>
      apiFetch<{ results: LocalSearchResult[] }>(`/api/laws/local-search?q=${encodeURIComponent(q)}`),
    assignCategory: (lawId: number, categoryId: number) =>
      apiFetch<{ category_id: number; category_confidence: string }>(
        `/api/laws/${lawId}/category`,
        {
          method: "PATCH",
          body: JSON.stringify({ category_id: categoryId }),
        }
      ),
    importSuggestion: (mappingId: number, importHistory: boolean, signal?: AbortSignal) =>
      apiFetch<{ law_id: number; title: string }>("/api/laws/import-suggestion", {
        method: "POST",
        body: JSON.stringify({ mapping_id: mappingId, import_history: importHistory }),
        signal,
      }),
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
  assistant: {
    createSession: () =>
      apiFetch<ChatSession>("/api/assistant/sessions", { method: "POST" }),
    listSessions: () =>
      apiFetch<ChatSession[]>("/api/assistant/sessions"),
    getSession: (id: string) =>
      apiFetch<ChatSessionDetail>(`/api/assistant/sessions/${id}`),
    deleteSession: (id: string) =>
      apiFetch<{ message: string }>(`/api/assistant/sessions/${id}`, {
        method: "DELETE",
      }),
    // sendMessage is NOT here — it uses SSE streaming via fetch directly
    resume: (sessionId: string, runId: string, decisions: Record<string, string>) =>
      fetch(`${API_BASE}/api/assistant/sessions/${sessionId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, decisions }),
      }),
  },
  settings: {
    prompts: {
      list: () =>
        apiFetch<PromptSummary[]>("/api/settings/prompts/"),
      get: (promptId: string) =>
        apiFetch<PromptDetail>(`/api/settings/prompts/${promptId}`),
      versions: (promptId: string) =>
        apiFetch<PromptVersionSummary[]>(
          `/api/settings/prompts/${promptId}/versions`
        ),
      getVersion: (promptId: string, version: number) =>
        apiFetch<PromptDetail>(
          `/api/settings/prompts/${promptId}/versions/${version}`
        ),
      propose: (
        promptId: string,
        proposedText: string,
        note: string,
        source: string = "direct_edit"
      ) =>
        apiFetch<PromptDiff>(`/api/settings/prompts/${promptId}/propose`, {
          method: "POST",
          body: JSON.stringify({
            proposed_text: proposedText,
            modification_note: note,
            source,
          }),
        }),
      approve: (promptId: string, version: number) =>
        apiFetch<{ prompt_id: string; new_active_version: number }>(
          `/api/settings/prompts/${promptId}/approve/${version}`,
          { method: "POST" }
        ),
      discard: (promptId: string, version: number) =>
        apiFetch<{ status: string }>(
          `/api/settings/prompts/${promptId}/discard/${version}`,
          { method: "POST" }
        ),
      restore: (promptId: string, version: number) =>
        apiFetch<PromptDiff>(
          `/api/settings/prompts/${promptId}/restore/${version}`,
          { method: "POST" }
        ),
    },
    pipeline: {
      runs: (params?: Record<string, string>) => {
        const query = params ? `?${new URLSearchParams(params)}` : "";
        return apiFetch<PipelineRunSummary[]>(
          `/api/settings/pipeline/runs${query}`
        );
      },
      runDetail: (runId: string) =>
        apiFetch<PipelineRunDetail>(`/api/settings/pipeline/runs/${runId}`),
      health: () =>
        apiFetch<HealthStats>("/api/settings/pipeline/health"),
    },
  },
};
