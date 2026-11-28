// Types and calls for the backend API (src/suva_app/main.py).

export type Label = "relevant" | "not_relevant" | "unknown";
export type Topic = "UV" | "MV" | "IV";
export type Status = "not_assessed" | "potentially_relevant" | "ai_relevant" | "expert_confirmed" | "not_relevant";
export type RelevanceAction = "confirm_relevant" | "mark_not_relevant" | "reopen";

export type Ruling = {
  id: number;
  docket: string;
  decision_date: string;
  publication_date: string | null;
  division: string;
  language: "de" | "fr" | "it" | null;
  starred: boolean | null;
  area: string | null;
  topic: Topic | null;
  subject: string | null; // the court's subject line, as published
  title: string | null; // the subject without the repeated area; null when it says no more than the area
  publication_source: string | null; // "bger_list" when the publication date is confirmed by bger.ch
  ingested_at: string | null; // set when the ruling was added by an update
  is_new: boolean; // added by the latest update
  outcome: string | null;
  official_url: string | null;
  label: Label;
  label_basis: string; // "expert_override" when the decision was made in this workspace
  status: Status;
  score: number | null; // 0..100
  predicted_relevant: boolean | null;
  has_gold_summary: boolean;
  has_summary: boolean;
};

export type RulingPage = { total: number; items: Ruling[] };

export type FacetValue = { value: string; n: number };

export type Facets = {
  total: number;
  decided_min: string | null;
  decided_max: string | null;
  published_min: string | null;
  published_max: string | null;
  scored: number;
  stub_scores: boolean;
  divisions: FacetValue[];
  areas: FacetValue[];
  topics: FacetValue[];
  languages: FacetValue[];
  outcomes: FacetValue[];
  labels: FacetValue[];
  statuses: FacetValue[];
};

/** A failed call: the HTTP status and, when the server gave one, its `{detail}` text. */
export class ApiError extends Error {
  status: number;
  detail: string | null;
  constructor(status: number, detail: string | null) {
    super(detail ?? String(status));
    this.status = status;
    this.detail = detail;
  }
}

async function failure(response: Response): Promise<ApiError> {
  let detail: string | null = null;
  try {
    const body: unknown = await response.json();
    const value = body && typeof body === "object" ? (body as { detail?: unknown }).detail : null;
    if (typeof value === "string") detail = value;
  } catch {
    // no JSON body: the status alone is reported
  }
  return new ApiError(response.status, detail);
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw await failure(response);
  return response.json() as Promise<T>;
}

export type SourceStatus = "complete" | "blocked" | "incomplete" | "failed" | null;

export type UpdateRun = {
  run_id: number;
  status: "ok" | "partial" | "failed";
  published_from: string;
  published_to: string;
  finished_at: string | null;
  new_rulings: number | null;
  known_rulings: number | null;
  not_confirmed_by_bger: number | null;
  new_with_two_texts: number | null;
  text_mismatches: number;
  sources: { bger: SourceStatus; daily: SourceStatus; mirror: SourceStatus };
  error: string | null;
};

export type UpdatesStatus = {
  running: boolean;
  current: { published_from: string; published_to: string } | null;
  last: UpdateRun | null;
  last_error: string | null;
  /** How the assessment (triage) after the last update went; null before any, or while it runs. */
  last_assessment:
    | { status: "ok"; mode: "LIVE" | "REPLAY"; assessed: number; suspected_relevant: number }
    | { status: "failed"; error: string }
    | null;
  next_range: { published_from: string; published_to: string } | null;
  ingested_rulings: number;
};

export const fetchUpdates = (signal?: AbortSignal) => get<UpdatesStatus>("/api/updates", signal);

/** Start an update: a range of publication dates, or nothing for "since the last update". */
export async function startUpdate(range?: { published_from: string; published_to: string }): Promise<UpdatesStatus> {
  const response = await fetch("/api/updates", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(range ?? {}),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<UpdatesStatus>;
}

export type Learning = {
  relevant_rulings: number;
  confirmed_by_experts: number;
  rejected_by_experts: number;
  reference_summaries: number;
  generated_summaries: number;
  expert_summaries: number;
  decisions: number;
  revision_requests: number;
  accepted_unchanged: number;
  revision_reasons: Array<{ reason: string; n: number }>;
  transitions: Array<{ before: Status; after: Status; n: number }>;
};

/** Record an expert decision on a ruling's relevance. Confirming creates a gold label. */
export async function decideRelevance(rulingId: number, action: RelevanceAction): Promise<void> {
  const response = await fetch(`/api/rulings/${rulingId}/relevance`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
}

export const fetchLearning = (signal?: AbortSignal) => get<Learning>("/api/learning", signal);

export const fetchFacets = (signal?: AbortSignal) => get<Facets>("/api/facets", signal);

export const fetchRulings = (query: URLSearchParams, signal?: AbortSignal) =>
  get<RulingPage>(`/api/rulings?${query.toString()}`, signal);

// --- the ruling page and the summary workspace ---------------------------------------------------------------

export type SummaryLanguage = "de" | "fr";

export type Summary = {
  id: number;
  version: number;
  origin: "model" | "expert";
  body: string;
  confirmed: boolean; // confirmed by an expert as final: a gold summary
  category: string | null; // the matter whose prompt wrote it
  problems?: string[]; // what the code-side checker found
  checks?: RefineCheck[]; // what the refine loop checked, step by step (empty when refine did not run)
  // Provenance (newer summaries). Any of these may be missing: read them through lib/provenance.ts.
  sentences?: SummarySentence[] | null; // [] for older or expert-edited summaries: then only the body is shown
  confidence?: number | null; // 0..100: how far the checks verified it; null without a trace
  confidence_level?: string | null; // "high" | "medium" | "low"
  confidence_reasons?: string[] | null;
  needs_review?: boolean | null;
  validated?: boolean | null; // same meaning as `confirmed`
  writer?: string | null;
  mode?: string | null; // "LIVE" | "REPLAY"
};

export type SummarySource = { quote?: string | null; start?: number | null; end?: number | null };

/** One sentence of a summary with where the ruling says it. Offsets count characters of the page's `text`. */
export type SummarySentence = {
  text: string;
  status?: "written" | "repaired" | "removed" | null;
  accepted?: boolean | null;
  considerations?: string[] | null; // e.g. "E.4.2"
  sources?: SummarySource[] | null;
  why_not?: string[] | null;
};

export type RefineCheck = {
  step: string; // form, facts, context, holding, economy, terms, language, length, form_final
  status: "passed" | "corrected" | "needs_review" | "skipped";
  findings: { reason: string; accepted?: boolean; evidence?: string; quote?: string; why_not?: string; text?: string }[];
  note?: string | null;
};

/** One rule of the score for one ruling. `effect`: its push on the score (0 when the rule does not apply). */
export type RuleRow = {
  rule: string;
  source: "code" | "apertus";
  direction: 1 | -1;
  applies: boolean;
  value: number;
  effect: number;
};

/** Why a ruling has its score, or why it has none. Built by code from the stored triage run. */
export type Relevance =
  | { state: "not_assessed"; reason: string; criterion: string | null }
  | {
      state: "scored";
      score: number;
      suspected: boolean;
      sentence_de: string | null;
      rules: RuleRow[];
      read_by_apertus: boolean;
      readings: Array<{ reading: string; level: number | null }>; // each between 0 and 1
      facts: { appeal_upheld: boolean | null; core_topics: string[]; bench_size: number | null; suva_appellant: boolean | null };
    };

/** The rule table of the current triage run and what it measured. */
export type Scoring = {
  run_id: number;
  created_at: string;
  pipeline: string | null;
  scorer: string | null;
  rules: Array<{ rule: string; source: "code" | "apertus"; direction: 1 | -1; weight: number; effect: number; share: number | null }>;
  intercept: number | null;
  readings: string[];
  share_promoted: number;
  scored: number;
  suspected: number;
};

export const fetchScoring = (signal?: AbortSignal) => get<Scoring>("/api/scoring", signal);

export type RulingDetail = {
  ruling: Ruling;
  relevance: Relevance | null;
  text: string | null;
  text_source: string | null;
  prompt_category: string;
  summaries: Record<SummaryLanguage, Summary | null>;
  reference: Record<SummaryLanguage, string | null>; // Suva's own summary, where one exists
  revisions: string[];
};

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await failure(response);
  return response.json() as Promise<T>;
}

const summaries = (id: number) => `/api/rulings/${id}/summaries`;

export const fetchRuling = (id: number, signal?: AbortSignal) => get<RulingDetail>(`/api/rulings/${id}/workspace`, signal);
export const generateSummaries = (id: number) => send<RulingDetail>("POST", summaries(id));
export const saveSummary = (id: number, language: SummaryLanguage, body: string, confirm: boolean) =>
  send<RulingDetail>("PUT", `${summaries(id)}/${language}`, { body, confirm });
export const confirmSummary = (id: number, language: SummaryLanguage) =>
  send<RulingDetail>("POST", `${summaries(id)}/${language}/confirm`);
export const unconfirmSummary = (id: number, language: SummaryLanguage) =>
  send<RulingDetail>("POST", `${summaries(id)}/${language}/unconfirm`);
export const reviseSummary = (id: number, language: SummaryLanguage, reason: string, note: string) =>
  send<RulingDetail>("POST", `${summaries(id)}/${language}/revise`, { reason, note: note || null });
