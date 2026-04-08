const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let cachedToken: { token: string; expires: number } | null = null;

export async function getAuthToken(): Promise<string | null> {
  if (cachedToken && cachedToken.expires > Date.now()) {
    return cachedToken.token;
  }
  try {
    const res = await fetch("/api/token");
    if (!res.ok) return null;
    const data = await res.json();
    if (data.token) {
      cachedToken = { token: data.token, expires: Date.now() + 4 * 60 * 1000 };
      return data.token;
    }
  } catch {
    return null;
  }
  return null;
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  let res: Response;
  try {
    const token = await getAuthToken();
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options?.headers,
      },
    });
  } catch {
    throw new Error(
      `Cannot reach the backend at ${API_BASE}. Is the server running?`
    );
  }
  if (!res.ok) {
    let errorMessage: string;
    let errorCode: string | undefined;
    try {
      const errorBody = await res.json();
      errorCode = errorBody.code;
      errorMessage = errorBody.message || errorBody.detail || res.statusText;
    } catch {
      const body = await res.text().catch(() => "");
      errorMessage = body || res.statusText;
    }
    const error = new Error(errorMessage);
    (error as any).code = errorCode;
    (error as any).statusCode = res.status;
    throw error;
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
  unimported_version_count: number;
  source?: string;
  language?: string;
  current_version: {
    id: number;
    state: string;
  } | null;
}

export interface SuggestedLaw {
  id: number;
  title: string;
  law_number: string | null;
  celex_number: string | null;
  category_id: number;
  category_slug: string;
  group_slug: string;
}

export interface LawMappingResponse {
  id: number;
  title: string;
  category_id: number;
  source: "system" | "user";
  source_url: string | null;
  source_ver_id: string | null;
  celex_number: string | null;
  law_number: string | null;
  law_year: number | null;
  document_type: string | null;
}

export interface LawMappingRow {
  id: number;
  title: string;
  law_number: string | null;
  law_year: number | null;
  document_type: string | null;
  celex_number: string | null;
  source_url: string | null;
  source_ver_id: string | null;
  category_id: number;
  category_name: string | null;
  category_slug: string | null;
  group_slug: string | null;
  group_name: string | null;
  group_color: string | null;
  source: "system" | "user";
  is_imported: boolean;
}

export interface ProbeUrlResult {
  kind: "ro" | "eu" | "unknown";
  identifier: string | null;
  title: string | null;
  error: string | null;
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
  favorite_law_ids: number[];
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
  last_checked_at: string | null;
  unimported_version_count: number;
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
  is_favorite: boolean;
}

export interface LawVersionSummary {
  id: number;
  ver_id: string;
  date_in_force: string | null;
  date_imported: string;
  state: string;
  is_current: boolean;
  diff_summary: { modified: number; added: number; removed: number } | null;
}

export interface KnownVersionData {
  id: number;
  ver_id: string;
  date_in_force: string;
  is_current: boolean;
  is_imported: boolean;
  discovered_at: string;
}

export interface KnownVersionsResponse {
  law_id: number;
  last_checked_at: string | null;
  versions: KnownVersionData[];
  unimported_count: number;
}

export interface NewVersionDetail {
  ver_id: string;
  date_in_force: string;
  is_latest: boolean;
}

export interface NewVersionEntry {
  law_id: number;
  title: string;
  description: string | null;
  law_number: string;
  law_year: number;
  source: string;
  version_number_offset: number;
  versions: NewVersionDetail[];
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

export interface DiffUnit {
  alineat_label: string | null;
  marker_kind: "alineat" | "numbered" | "litera" | "upper_litera" | "bullet" | "intro";
  label: string;
  change_type: "added" | "removed" | "modified" | "unchanged";
  text_a?: string;
  text_b?: string;
  diff_html?: string;
}

export interface DiffArticle {
  article_number: string;
  change_type: "added" | "removed" | "modified" | "unchanged";
  title?: string | null;
  renumbered_from: string | null;
  units: DiffUnit[];
  // For added/removed articles and the tokenizer-fallback path:
  text_a?: string;
  text_b?: string;
  diff_html?: string;
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
  changes: DiffArticle[];
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

export interface EUSearchResult {
  celex: string;
  title: string;
  date: string;
  doc_type: string;
  in_force: boolean;
  cellar_uri: string;
  already_imported: boolean;
  source: "eu";
}

export interface EUFilterOptions {
  doc_types: { value: string; label: string }[];
}

export interface EmitentsResponse {
  emitents: string[];
}

// --- Compare types ---

export interface CompareModelResult {
  model_id: string;
  model_label: string;
  status: "success" | "error";
  duration_ms: number;
  usage?: { input_tokens: number; output_tokens: number };
  cost_usd: number;
  answer?: string;
  citations?: any[];
  pipeline_steps?: Record<string, any>;
  error?: string;
}

export interface CompareResponse {
  question: string;
  results: CompareModelResult[];
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
  currency_status?: "current" | "stale" | "source_unavailable" | "not_checked";
  official_latest_date?: string | null;
  official_latest_ver_id?: string | null;
  db_latest_date?: string | null;
}

// --- Settings: Models types ---

export interface ModelConfig {
  id: string;
  provider: string;
  api_model_id: string;
  label: string;
  cost_tier: string;
  capabilities: string[];
  enabled: boolean;
}

export interface ModelAssignment {
  task: string;
  model_id: string;
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

// --- Settings: Scheduler types ---

export interface SchedulerSettingData {
  id: string;
  enabled: boolean;
  frequency: string;
  time_hour: number;
  time_minute: number;
  last_run_at: string | null;
  last_run_status: string | null;
  last_run_summary: { checked: number; discovered: number; errors: number } | null;
  next_run_utc: string | null;
}

export interface SchedulerSettingsUpdate {
  ro: { enabled: boolean; frequency: string; time_hour: number; time_minute: number };
  eu: { enabled: boolean; frequency: string; time_hour: number; time_minute: number };
}

export interface SchedulerRunLogData {
  id: number;
  scheduler_id: string;
  ran_at: string;
  trigger: "scheduled" | "manual";
  status: "ok" | "error";
  laws_checked: number;
  new_versions: number;
  errors: number;
}

export interface LawCheckLogData {
  id: number;
  law_id: number;
  source: string;
  law_label: string;
  checked_at: string;
  user_email: string | null;
  new_versions: number;
  status: "ok" | "error";
  error_message: string | null;
}

export interface LawCheckLogRowData {
  id: number;
  checked_at: string;
  user_email: string | null;
  new_versions: number;
  status: "ok" | "error";
  error_message: string | null;
}

export interface BackfillNotesReport {
  dry_run: boolean;
  versions_processed: number;
  versions_failed: number;
  paragraph_notes_to_insert: number;
  article_notes_to_insert: number;
  text_clean_writes: number;
  unknown_paragraph_labels: string[];
  errors: string[];
}

// Background-job tracking. Long-running operations on the backend create a Job
// row; the frontend polls /api/jobs/{id} so progress survives navigation.
export type JobStatus = "pending" | "running" | "succeeded" | "failed";

export interface JobData {
  id: string;
  kind: string;
  status: JobStatus;
  phase: string | null;
  current: number | null;
  total: number | null;
  params: unknown;
  result: unknown;
  error: { code?: string; message?: string } | null;
  entity_kind: string | null;
  entity_id: string | null;
  created_by_user_id: number | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export const TERMINAL_JOB_STATUSES: ReadonlySet<JobStatus> = new Set([
  "succeeded",
  "failed",
]);

export interface BulkImportProgress {
  current: number;
  total: number;
  title: string;
  status: string;
}

export interface BulkImportResult {
  total: number;
  imported: number;
  failed: number;
  skipped: number;
  items: Array<
    | { title: string; status: "imported"; law_id: number }
    | { title: string; status: "skipped"; reason: string }
    | { title: string; status: "error"; error: string }
  >;
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
    deleteVersion: (lawId: number, versionId: number) =>
      apiFetch<{ message: string }>(
        `/api/laws/${lawId}/versions/${versionId}`,
        { method: "DELETE" }
      ),
    checkUpdates: (id: number) =>
      apiFetch<{ discovered: number; last_checked_at: string | null }>(
        `/api/laws/${id}/check-updates`,
        { method: "POST" }
      ),
    getKnownVersions: (lawId: number) =>
      apiFetch<KnownVersionsResponse>(`/api/laws/${lawId}/known-versions`),
    listCheckLogs: (lawId: number, limit = 20) =>
      apiFetch<LawCheckLogRowData[]>(
        `/api/laws/${lawId}/check-logs?limit=${limit}`
      ),
    /**
     * Start a direct law import as a background job.
     * Returns the job_id immediately. Caller polls /api/jobs/{job_id} for
     * progress and result. Replaces importLawStreamSSE — it survives page
     * navigation because the work runs in the backend job pool.
     */
    startImport: (
      verId: string,
      importHistory: boolean,
      categoryId: number | null
    ) =>
      apiFetch<{ job_id: string }>("/api/laws/import/job", {
        method: "POST",
        body: JSON.stringify({
          ver_id: verId,
          import_history: importHistory,
          category_id: categoryId,
        }),
      }),
    /**
     * Start a bulk import of every unimported suggested law.
     * Returns the job_id immediately. Caller polls /api/jobs/{job_id} for
     * progress and the final BulkImportResult lives in the job's `result`.
     */
    startBulkImport: (importHistory: boolean) =>
      apiFetch<{ job_id: string; total: number }>(
        "/api/laws/import-all-suggestions/job",
        {
          method: "POST",
          body: JSON.stringify({ import_history: importHistory }),
        }
      ),
    importKnownVersion: (lawId: number, verId: string) =>
      apiFetch<{ status: string; ver_id: string; law_version_id: number }>(
        `/api/laws/${lawId}/known-versions/import`,
        { method: "POST", body: JSON.stringify({ ver_id: verId }) }
      ),
    importAllMissing: (lawId: number) =>
      apiFetch<{ status: string; imported: number; errors: Array<{ ver_id: string; error: string }> }>(
        `/api/laws/${lawId}/known-versions/import-all`,
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
    newVersions: () => apiFetch<{ new_versions: NewVersionEntry[] }>("/api/laws/new-versions"),
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
    /**
     * Start a single suggestion import as a background job. Returns the
     * job_id immediately. The runner mirrors importSuggestion's pin-on-import
     * behaviour and frontend polls /api/jobs/{job_id} for progress.
     */
    startImportSuggestion: (mappingId: number, importHistory: boolean) =>
      apiFetch<{ job_id: string }>(
        `/api/laws/import-suggestion/${mappingId}/job`,
        {
          method: "POST",
          body: JSON.stringify({ import_history: importHistory }),
        }
      ),
    euSearch: (params: {
      keyword?: string; doc_type?: string; year?: string;
      number?: string; in_force_only?: boolean;
    }) => {
      const searchParams = new URLSearchParams();
      if (params.keyword) searchParams.set("keyword", params.keyword);
      if (params.doc_type) searchParams.set("doc_type", params.doc_type);
      if (params.year) searchParams.set("year", params.year);
      if (params.number) searchParams.set("number", params.number);
      if (params.in_force_only) searchParams.set("in_force_only", "true");
      return apiFetch<EUSearchResult[]>(`/api/laws/eu/search?${searchParams}`);
    },
    euImport: (celexNumber: string, importHistory: boolean, signal?: AbortSignal) =>
      apiFetch<{ law_id: number; title: string; versions_imported: number }>(
        "/api/laws/eu/import",
        {
          method: "POST",
          body: JSON.stringify({ celex_number: celexNumber, import_history: importHistory }),
          signal,
        }
      ),
    /**
     * Start an EU law import as a background job. Returns the job_id
     * immediately. Caller polls /api/jobs/{job_id} for progress and result.
     * EU equivalent of startImport — survives page navigation.
     */
    startEuImport: (
      celexNumber: string,
      importHistory: boolean,
      categoryId: number | null
    ) =>
      apiFetch<{ job_id: string }>("/api/laws/eu/import/job", {
        method: "POST",
        body: JSON.stringify({
          celex_number: celexNumber,
          import_history: importHistory,
          category_id: categoryId,
        }),
      }),
    euFilterOptions: () => apiFetch<EUFilterOptions>("/api/laws/eu/filter-options"),
    favoriteAdd: (lawId: number) =>
      apiFetch<{ ok: boolean }>(`/api/laws/${lawId}/favorite`, { method: "POST" }),
    favoriteRemove: (lawId: number) =>
      apiFetch<{ ok: boolean }>(`/api/laws/${lawId}/favorite`, { method: "DELETE" }),
  },
  lawMappings: {
    list: (params: {
      group_slug?: string;
      category_id?: number;
      source?: "system" | "user" | "all";
      pinned?: "true" | "false" | "all";
      q?: string;
    } = {}) => {
      const qs = new URLSearchParams();
      if (params.group_slug) qs.set("group_slug", params.group_slug);
      if (params.category_id != null) qs.set("category_id", String(params.category_id));
      if (params.source) qs.set("source", params.source);
      if (params.pinned) qs.set("pinned", params.pinned);
      if (params.q) qs.set("q", params.q);
      const suffix = qs.toString() ? `?${qs}` : "";
      return apiFetch<LawMappingRow[]>(`/api/law-mappings${suffix}`);
    },
    create: (url: string, categoryId: number, title?: string) =>
      apiFetch<LawMappingResponse>("/api/law-mappings", {
        method: "POST",
        body: JSON.stringify({ url, category_id: categoryId, title }),
      }),
    update: (id: number, fields: Partial<{ title: string; category_id: number; law_number: string; law_year: number; document_type: string }>) =>
      apiFetch<LawMappingResponse>(`/api/law-mappings/${id}`, {
        method: "PUT",
        body: JSON.stringify(fields),
      }),
    remove: (id: number) =>
      apiFetch<void>(`/api/law-mappings/${id}`, { method: "DELETE" }),
    probeUrl: (url: string) =>
      apiFetch<ProbeUrlResult>("/api/law-mappings/probe-url", {
        method: "POST",
        body: JSON.stringify({ url }),
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
    compare: (question: string, models: string[], mode: "full" | "pipeline_steps" = "full") =>
      apiFetch<CompareResponse>("/api/assistant/compare", {
        method: "POST",
        body: JSON.stringify({ question, models, mode }),
      }),
    resume: async (sessionId: string, runId: string, decisions: Record<string, string>) => {
      const token = await getAuthToken();
      return fetch(`${API_BASE}/api/assistant/sessions/${sessionId}/resume`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ run_id: runId, decisions }),
      });
    },
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
    models: {
      list: () => apiFetch<ModelConfig[]>("/api/settings/models"),
      update: (id: string, update: { enabled?: boolean }) =>
        apiFetch<ModelConfig>(`/api/settings/models/${id}`, {
          method: "PUT",
          body: JSON.stringify(update),
        }),
    },
    assignments: {
      list: () => apiFetch<ModelAssignment[]>("/api/settings/model-assignments"),
      update: (task: string, modelId: string) =>
        apiFetch<ModelAssignment>("/api/settings/model-assignments", {
          method: "PUT",
          body: JSON.stringify({ task, model_id: modelId }),
        }),
    },
    schedulers: {
      list: () => apiFetch<SchedulerSettingData[]>("/api/admin/scheduler-settings"),
      save: (update: SchedulerSettingsUpdate) =>
        apiFetch<{ status: string }>("/api/admin/scheduler-settings", {
          method: "PUT",
          body: JSON.stringify(update),
        }),
      triggerDiscovery: (jobType: "ro" | "eu") =>
        apiFetch<{ status: string; job_type: string; job_id: string }>(
          `/api/admin/trigger-discovery/${jobType}`,
          { method: "POST" }
        ),
      listLogs: (schedulerId: "ro" | "eu", limit = 20) =>
        apiFetch<SchedulerRunLogData[]>(
          `/api/admin/scheduler-logs?scheduler_id=${schedulerId}&limit=${limit}`
        ),
      listLawCheckLogs: (limit = 20) =>
        apiFetch<LawCheckLogData[]>(`/api/admin/law-check-logs?limit=${limit}`),
    },
    maintenance: {
      backfillNotes: (dryRun: boolean) =>
        apiFetch<BackfillNotesReport>("/api/admin/backfill/notes", {
          method: "POST",
          body: JSON.stringify({ dry_run: dryRun }),
        }),
    },
  },
  jobs: {
    get: (jobId: string) => apiFetch<JobData>(`/api/jobs/${jobId}`),
    list: (params?: {
      kind?: string;
      entityKind?: string;
      entityId?: string | number;
      active?: boolean;
      limit?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.kind) qs.set("kind", params.kind);
      if (params?.entityKind) qs.set("entity_kind", params.entityKind);
      if (params?.entityId !== undefined && params.entityId !== null)
        qs.set("entity_id", String(params.entityId));
      if (params?.active !== undefined) qs.set("active", String(params.active));
      if (params?.limit !== undefined) qs.set("limit", String(params.limit));
      const query = qs.toString();
      return apiFetch<{ jobs: JobData[] }>(
        `/api/jobs${query ? `?${query}` : ""}`
      );
    },
  },
};
