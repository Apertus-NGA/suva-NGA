// Types and calls for the backend API (src/suva_app/main.py).

export type Label = "relevant" | "not_relevant" | "unknown";
export type Topic = "UV" | "MV" | "IV";

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
  subject: string | null;
  outcome: string | null;
  official_url: string | null;
  label: Label;
  label_basis: string;
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
};

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export const fetchFacets = (signal?: AbortSignal) => get<Facets>("/api/facets", signal);

export const fetchRulings = (query: URLSearchParams, signal?: AbortSignal) =>
  get<RulingPage>(`/api/rulings?${query.toString()}`, signal);
