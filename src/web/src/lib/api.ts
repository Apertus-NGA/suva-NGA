// Types and calls for the backend API. By default Suva Scout (src/suva_app/main.py); built with VITE_BACKEND=api,
// src/api (the six-schema data layer, docs/API.md) through the adapters of sixApi.ts. The types are the UI's.

import { ApiError, failure } from "./http";
import * as six from "./sixApi";

export { ApiError };

/** True when the UI was built against src/api. */
export const SIX_BACKEND = import.meta.env.VITE_BACKEND === "api";

export type Label = "relevant" | "not_relevant" | "unknown";
export type Topic = "UV" | "MV" | "IV";
export type Status = "not_assessed" | "potentially_relevant" | "ai_relevant" | "expert_confirmed" | "not_relevant";
export type RelevanceAction = "confirm_relevant" | "mark_not_relevant" | "reopen";

export type Ruling = {
  id: string; // Scout's numeric id as text, or src/api's UUID
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

export const fetchUpdates = (signal?: AbortSignal): Promise<UpdatesStatus> =>
  SIX_BACKEND ? six.fetchUpdates() : get<UpdatesStatus>("/api/updates", signal);

/** Start an update: a range of publication dates, or nothing for "since the last update". */
export async function startUpdate(range?: { published_from: string; published_to: string }): Promise<UpdatesStatus> {
  if (SIX_BACKEND) return six.startUpdate();
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
export async function decideRelevance(rulingId: string, action: RelevanceAction): Promise<void> {
  if (SIX_BACKEND) return six.decideRelevance(rulingId, action);
  const response = await fetch(`/api/rulings/${rulingId}/relevance`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ action }),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
}

export const fetchLearning = (signal?: AbortSignal): Promise<Learning> =>
  SIX_BACKEND ? six.fetchLearning(signal) : get<Learning>("/api/learning", signal);

export const fetchFacets = (signal?: AbortSignal): Promise<Facets> =>
  SIX_BACKEND ? six.fetchFacets(signal) : get<Facets>("/api/facets", signal);

/** Scout's numeric ids become text, so the UI handles one id type for both backends. */
const withTextId = (ruling: Ruling): Ruling => ({ ...ruling, id: String(ruling.id) });

export const fetchRulings = (query: URLSearchParams, signal?: AbortSignal): Promise<RulingPage> =>
  SIX_BACKEND
    ? six.fetchRulings(query, signal)
    : get<RulingPage>(`/api/rulings?${query.toString()}`, signal).then((page) => ({ ...page, items: page.items.map(withTextId) }));

// --- the ruling page and the summary workspace ---------------------------------------------------------------

export type SummaryLanguage = "de" | "fr";

export type Summary = {
  id: number | string; // Scout: a number; src/api: the summary_version_id
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

export const fetchScoring = (signal?: AbortSignal): Promise<Scoring> =>
  SIX_BACKEND ? six.fetchScoring(signal) : get<Scoring>("/api/scoring", signal);

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

const summaries = (id: string) => `/api/rulings/${id}/summaries`;
const withTextRulingId = (detail: RulingDetail): RulingDetail => ({ ...detail, ruling: withTextId(detail.ruling) });
const scout = <T extends RulingDetail>(call: Promise<T>): Promise<RulingDetail> => call.then(withTextRulingId);

export const fetchRuling = (id: string, signal?: AbortSignal): Promise<RulingDetail> =>
  SIX_BACKEND ? six.fetchRuling(id, signal) : scout(get<RulingDetail>(`/api/rulings/${id}/workspace`, signal));
export const generateSummaries = (id: string): Promise<RulingDetail> =>
  SIX_BACKEND ? six.generateSummaries(id) : scout(send<RulingDetail>("POST", summaries(id)));
export const saveSummary = (id: string, language: SummaryLanguage, body: string, confirm: boolean): Promise<RulingDetail> =>
  SIX_BACKEND
    ? six.saveSummary(id, language, body, confirm)
    : scout(send<RulingDetail>("PUT", `${summaries(id)}/${language}`, { body, confirm }));
export const confirmSummary = (id: string, language: SummaryLanguage): Promise<RulingDetail> =>
  SIX_BACKEND ? six.confirmSummary(id, language) : scout(send<RulingDetail>("POST", `${summaries(id)}/${language}/confirm`));
export const unconfirmSummary = (id: string, language: SummaryLanguage): Promise<RulingDetail> =>
  SIX_BACKEND
    ? six.unconfirmSummary(id, language)
    : scout(send<RulingDetail>("POST", `${summaries(id)}/${language}/unconfirm`));
export const reviseSummary = (id: string, language: SummaryLanguage, reason: string, note: string): Promise<RulingDetail> =>
  SIX_BACKEND
    ? six.reviseSummary()
    : scout(send<RulingDetail>("POST", `${summaries(id)}/${language}/revise`, { reason, note: note || null }));
