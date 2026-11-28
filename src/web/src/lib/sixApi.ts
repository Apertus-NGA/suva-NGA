// The UI against src/api (FastAPI on the six-schema data layer, docs/API.md). Used by api.ts when the UI is built
// with VITE_BACKEND=api. Every function here turns src/api JSON into the UI types of api.ts, so the components do
// not know which backend answers. What src/api does not have yet is filled with neutral values (empty lists,
// zeros, null), never invented.

import type {
  Facets,
  FacetValue,
  Learning,
  Relevance,
  RelevanceAction,
  RuleRow,
  Ruling,
  RulingDetail,
  RulingPage,
  Scoring,
  Status,
  Summary,
  SummaryLanguage,
  UpdatesStatus,
} from "./api";
import { ApiError, failure } from "./http";

type Json = Record<string, unknown>;

const CORE_AREAS = ["UV", "MV", "IV"] as const;
// src/api/queries.py AREAS and STATUSES: a value outside these answers 422, so the UI never sends one.
const API_AREAS = new Set(["UV", "MV", "IV", "KV", "BV", "CONTRACT", "LIABILITY", "other"]);
const API_SORTS = new Set(["score", "decision_date", "publication_date", "docket", "status"]);
const LANGUAGES = new Set(["de", "fr", "it"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** src/api status -> the UI's five statuses. */
const STATUS_TO_UI: Record<string, Status> = {
  expert_relevant: "expert_confirmed",
  expert_not_relevant: "not_relevant",
  ai_relevant: "ai_relevant",
  potentially_relevant: "potentially_relevant",
  ai_not_relevant: "not_relevant",
  filtered_out: "not_relevant",
  not_assessed: "not_assessed",
};

/** The UI's status filter -> the src/api statuses it covers. */
const STATUS_FROM_UI: Record<string, string[]> = {
  expert_confirmed: ["expert_relevant"],
  not_relevant: ["expert_not_relevant", "ai_not_relevant", "filtered_out"],
  ai_relevant: ["ai_relevant"],
  potentially_relevant: ["potentially_relevant"],
  not_assessed: ["not_assessed"],
};

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const list = (v: unknown): Json[] => (Array.isArray(v) ? (v.filter((x) => x && typeof x === "object") as Json[]) : []);
const obj = (v: unknown): Json | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Json) : null);

export const uiStatus = (value: unknown): Status => STATUS_TO_UI[String(value)] ?? "not_assessed";

// --- reads ---------------------------------------------------------------------------------------------------------

export function toRuling(r: Json): Ruling {
  const area = str(r.area);
  const status = uiStatus(r.status);
  const score = num(r.score);
  const expert = obj(r.expert) ?? {};
  const language = str(r.language);
  return {
    id: String(r.id),
    docket: str(r.docket) ?? "",
    decision_date: str(r.decision_date) ?? "",
    publication_date: str(r.publication_date),
    division: str(r.court) ?? "",
    language: language === "de" || language === "fr" || language === "it" ? language : null,
    starred: typeof r.star === "boolean" ? r.star : null,
    area: str(r.rubric) ?? area,
    topic: area === "UV" || area === "MV" || area === "IV" ? area : null,
    subject: str(r.subject),
    title: str(r.subject),
    publication_source: r.publication_quality === "exact" ? "bger_list" : null,
    ingested_at: null,
    is_new: r.is_new === true,
    outcome: str(r.outcome),
    official_url: str(r.bger_url),
    label: expert.label === true ? "relevant" : expert.label === false ? "not_relevant" : "unknown",
    label_basis: expert.verdict ? "expert_override" : "pipeline",
    status,
    score,
    predicted_relevant: status === "ai_relevant" ? true : score === null ? null : false,
    has_gold_summary: r.has_reference === true,
    has_summary: r.has_summary === true,
  };
}

/** The UI's list query (filters.ts toApiParams + the view's scope) -> the parameters src/api knows. */
export function toApiQuery(ui: URLSearchParams): URLSearchParams {
  const p = new URLSearchParams();
  const q = ui.get("q");
  if (q) p.set("q", q);
  for (const key of ["decided_from", "decided_to", "published_from", "published_to"]) {
    const value = ui.get(key);
    if (value && ISO_DATE.test(value)) p.set(key, value);
  }
  for (const key of ["score_min", "score_max"]) {
    const value = ui.get(key);
    const n = value === null || value === "" ? NaN : Number(value);
    if (Number.isFinite(n) && n >= 0 && n <= 100) p.set(key, String(n));
  }
  const statuses = new Set(ui.getAll("status").flatMap((s) => STATUS_FROM_UI[s] ?? []));
  for (const s of statuses) p.append("status", s);
  // The topic (UV / MV / IV) and the area facet both read src/api's area code.
  const areas = new Set([...ui.getAll("topic"), ...ui.getAll("area")].filter((a) => API_AREAS.has(a)));
  for (const a of areas) p.append("area", a);
  for (const court of ui.getAll("division")) p.append("court", court);
  for (const lang of ui.getAll("language")) if (LANGUAGES.has(lang)) p.append("language", lang);
  if (ui.get("summarised") === "true") p.set("has_summary", "true");
  if (ui.get("inbox") === "true") p.set("inbox", "true");
  const sort = ui.get("sort");
  if (sort && API_SORTS.has(sort)) p.set("sort", sort);
  const order = ui.get("order");
  if (order === "asc" || order === "desc") p.set("order", order);
  const limit = Number(ui.get("limit"));
  if (Number.isInteger(limit) && limit >= 1) p.set("limit", String(Math.min(limit, 200)));
  const offset = Number(ui.get("offset"));
  if (Number.isInteger(offset) && offset >= 0) p.set("offset", String(offset));
  return p;
}

const values = (v: unknown): FacetValue[] =>
  list(v)
    .filter((x) => x.value !== null && x.value !== undefined)
    .map((x) => ({ value: String(x.value), n: num(x.n) ?? 0 }));

export function toFacets(f: Json): Facets {
  const areas = values(f.areas);
  const merged = new Map<string, number>();
  for (const s of values(f.statuses)) {
    const status = uiStatus(s.value);
    merged.set(status, (merged.get(status) ?? 0) + s.n);
  }
  const statuses = [...merged.entries()].map(([value, n]) => ({ value, n })).sort((a, b) => b.n - a.n);
  return {
    total: num(f.total) ?? 0,
    decided_min: str(f.decided_min),
    decided_max: str(f.decided_max),
    published_min: str(f.published_min),
    published_max: str(f.published_max),
    scored: statuses.filter((s) => s.value !== "not_assessed").reduce((sum, s) => sum + s.n, 0),
    stub_scores: false,
    divisions: values(f.courts),
    areas,
    topics: areas.filter((a) => (CORE_AREAS as readonly string[]).includes(a.value)),
    languages: values(f.languages),
    outcomes: [],
    labels: [],
    statuses,
  };
}

/** The current summary_version_id per ruling and language, as last read: sent with an edit (409 if stale). */
const currentVersion = new Map<string, Partial<Record<SummaryLanguage, string>>>();

function toSummary(s: Json | null): Summary | null {
  if (!s) return null;
  const validated = s.validated === true;
  return {
    id: str(s.summary_version_id) ?? "",
    version: num(s.version) ?? 0,
    origin: s.origin === "expert_edit" ? "expert" : "model",
    body: str(s.body) ?? "",
    confirmed: validated,
    validated,
    category: null,
    // src/api gives sentences without sources yet: the body alone is shown (lib/provenance.ts).
    sentences: [],
    mode: str(s.mode),
  };
}

function toRelevance(rel: Json | null, ruling: Ruling, row: Json): Relevance | null {
  if (!rel) return null;
  if (rel.state === "not_assessed") {
    // rel.reason is a sentence, not a code: the UI's own text for a ruling no run has scored yet is shown.
    return { state: "not_assessed", reason: str(row.reason_code) ?? "not_scored_yet", criterion: null };
  }
  const rules: RuleRow[] = list(rel.rules).map((r) => ({
    rule: str(r.rule) ?? "",
    source: r.source === "apertus" ? "apertus" : "code",
    direction: r.direction === -1 ? -1 : 1,
    applies: r.applies !== false,
    value: num(r.value) ?? 0,
    effect: num(r.effect) ?? 0,
  }));
  return {
    state: "scored",
    score: num(rel.score) ?? 0,
    suspected: ruling.status === "ai_relevant",
    sentence_de: str(rel.explanation_de),
    rules,
    read_by_apertus: !!rel.read_by_apertus,
    readings: list(rel.readings).map((x) => ({ reading: str(x.reading) ?? "", level: num(x.level) })),
    facts: { appeal_upheld: null, core_topics: [], bench_size: null, suva_appellant: null },
  };
}

export function toDetail(d: Json): RulingDetail {
  const row = obj(d.ruling) ?? {};
  const ruling = toRuling(row);
  const summaries = obj(d.summaries) ?? {};
  const de = obj(summaries.de);
  const fr = obj(summaries.fr);
  currentVersion.set(ruling.id, {
    de: str(de?.summary_version_id) ?? undefined,
    fr: str(fr?.summary_version_id) ?? undefined,
  });
  const reference = obj(d.reference);
  return {
    ruling,
    relevance: toRelevance(obj(d.relevance), ruling, row),
    text: str(d.text),
    text_source: str(d.text_source),
    prompt_category: "",
    summaries: { de: toSummary(de), fr: toSummary(fr) },
    reference: { de: str(reference?.de), fr: str(reference?.fr) },
    revisions: [],
  };
}

export function toScoring(s: Json): Scoring {
  const profile = obj(s.profile);
  const judge = list(s.steps).find((x) => x.step === "layer2_judge");
  return {
    run_id: 0,
    created_at: "",
    pipeline: profile ? `${str(profile.code) ?? ""} ${str(profile.version) ?? ""}`.trim() : null,
    scorer: judge ? `${str(judge.component_name) ?? ""} ${str(judge.component_version) ?? ""}`.trim() : null,
    rules: list(s.rules).map((r) => ({
      rule: str(r.rule) ?? "",
      source: r.source === "apertus" ? "apertus" : "code",
      direction: r.direction === -1 ? -1 : 1,
      weight: num(r.weight) ?? 0,
      effect: num(r.effect) ?? 0,
      share: num(r.share),
    })),
    intercept: num(s.intercept),
    readings: [],
    share_promoted: 0,
    scored: 0,
    suspected: 0,
  };
}

/** src/api's expert counters, loosely: zeros where it has no counterpart. */
export function toLearning(l: Json): Learning {
  const transitions = list(l.transitions).map((x) => {
    const after = x.after === "in_scope" ? "expert_confirmed" : x.after === "out_of_scope" ? "not_relevant" : uiStatus(x.after);
    return { before: uiStatus(x.before), after: after as Status, n: num(x.n) ?? 0 };
  });
  const sum = (status: Status) => transitions.filter((x) => x.after === status).reduce((s, x) => s + x.n, 0);
  return {
    relevant_rulings: 0,
    confirmed_by_experts: sum("expert_confirmed"),
    rejected_by_experts: sum("not_relevant"),
    reference_summaries: 0,
    generated_summaries: num(l.summaries_generated) ?? 0,
    expert_summaries: num(l.summaries_edited) ?? 0,
    decisions: num(l.decisions) ?? 0,
    revision_requests: 0,
    accepted_unchanged: num(l.summaries_validated) ?? 0,
    revision_reasons: [],
    transitions,
  };
}

// --- calls ---------------------------------------------------------------------------------------------------------

async function call(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Json> {
  const response = await fetch(path, {
    method,
    signal,
    headers: body === undefined ? { Accept: "application/json" } : { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await failure(response);
  const data: unknown = await response.json();
  return obj(data) ?? {};
}

const ruling = (id: string) => `/api/rulings/${encodeURIComponent(id)}`;

export const fetchRulings = async (query: URLSearchParams, signal?: AbortSignal): Promise<RulingPage> => {
  const page = await call("GET", `/api/rulings?${toApiQuery(query).toString()}`, undefined, signal);
  return { total: num(page.total) ?? 0, items: list(page.items).map(toRuling) };
};

export const fetchFacets = async (signal?: AbortSignal): Promise<Facets> => toFacets(await call("GET", "/api/facets", undefined, signal));

export const fetchRuling = async (id: string, signal?: AbortSignal): Promise<RulingDetail> =>
  toDetail(await call("GET", ruling(id), undefined, signal));

export const fetchScoring = async (signal?: AbortSignal): Promise<Scoring> => toScoring(await call("GET", "/api/scoring", undefined, signal));

export const fetchLearning = async (signal?: AbortSignal): Promise<Learning> =>
  toLearning(await call("GET", "/api/learning", undefined, signal));

export async function decideRelevance(id: string, action: RelevanceAction): Promise<void> {
  await call("POST", `${ruling(id)}/relevance`, { action: action === "confirm_relevant" ? "mark_relevant" : action });
}

export async function generateSummaries(id: string): Promise<RulingDetail> {
  await call("POST", `${ruling(id)}/summaries`);
  return fetchRuling(id);
}

export async function saveSummary(id: string, language: SummaryLanguage, body: string, confirm: boolean): Promise<RulingDetail> {
  const parent = currentVersion.get(id)?.[language] ?? null;
  await call("PUT", `${ruling(id)}/summaries/${language}`, { body, parent_version_id: parent });
  if (confirm) await call("POST", `${ruling(id)}/summaries/${language}/validate`, {});
  return fetchRuling(id);
}

export async function confirmSummary(id: string, language: SummaryLanguage): Promise<RulingDetail> {
  await call("POST", `${ruling(id)}/summaries/${language}/validate`, {});
  return fetchRuling(id);
}

export async function unconfirmSummary(id: string, language: SummaryLanguage): Promise<RulingDetail> {
  await call("POST", `${ruling(id)}/summaries/${language}/unvalidate`);
  return fetchRuling(id);
}

export async function reviseSummary(): Promise<RulingDetail> {
  throw new ApiError(501, "Revision is not available on this backend yet");
}

/** src/api has no updates route: the update control is hidden, and its status reads as idle. */
export const IDLE_UPDATES: UpdatesStatus = {
  running: false,
  current: null,
  last: null,
  last_error: null,
  last_assessment: null,
  next_range: null,
  ingested_rulings: 0,
};

export const fetchUpdates = async (): Promise<UpdatesStatus> => IDLE_UPDATES;

export async function startUpdate(): Promise<UpdatesStatus> {
  throw new ApiError(501, "Updates are not available on this backend yet");
}
