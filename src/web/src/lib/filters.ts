// The list's state: filters, sort and page. It lives in the URL, so a filtered view can be bookmarked or shared.

export type SortKey = "score" | "docket" | "area" | "decision_date" | "publication_date" | "status"; // status: by tier
export type Order = "asc" | "desc";

export type Filters = {
  q: string;
  decided_from: string; // ISO date or ""
  decided_to: string;
  published_from: string;
  published_to: string;
  topic: string[];
  area: string[];
  division: string[];
  language: string[];
  outcome: string[];
  label: string[];
  status: string[];
  starred: boolean; // true = only rulings marked for publication
  ingested: boolean; // true = only rulings added by an update
  summarised: boolean; // true = only rulings with a summary (Suva's or a generated one)
  predicted_relevant: "" | "true" | "false";
  score_min: string; // "" or 0..100
  score_max: string;
  sort: SortKey;
  order: Order;
  page: number; // 1-based
};

export const PAGE_SIZE = 50;

export const DEFAULT_FILTERS: Filters = {
  q: "",
  decided_from: "",
  decided_to: "",
  published_from: "",
  published_to: "",
  topic: [],
  area: [],
  division: [],
  language: [],
  outcome: [],
  label: [],
  status: [],
  starred: false,
  ingested: false,
  summarised: false,
  predicted_relevant: "",
  score_min: "",
  score_max: "",
  sort: "status",
  order: "desc",
  page: 1,
};

const TEXT_KEYS = ["q", "decided_from", "decided_to", "published_from", "published_to", "score_min", "score_max"] as const;
const LIST_KEYS = ["topic", "area", "division", "language", "outcome", "label", "status"] as const;
const SORT_KEYS: SortKey[] = ["score", "docket", "area", "decision_date", "publication_date", "status"];

/** Query string for the address bar: only what differs from the defaults. */
export function toUrlParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams();
  for (const key of TEXT_KEYS) if (f[key]) p.set(key, f[key]);
  for (const key of LIST_KEYS) for (const value of f[key]) p.append(key, value);
  if (f.starred) p.set("starred", "true");
  if (f.ingested) p.set("ingested", "true");
  if (f.summarised) p.set("summarised", "true");
  if (f.predicted_relevant) p.set("predicted_relevant", f.predicted_relevant);
  if (f.sort !== DEFAULT_FILTERS.sort || f.order !== DEFAULT_FILTERS.order) {
    p.set("sort", f.sort);
    p.set("order", f.order);
  }
  if (f.page > 1) p.set("page", String(f.page));
  return p;
}

export function fromUrlParams(p: URLSearchParams): Filters {
  const f: Filters = { ...DEFAULT_FILTERS };
  for (const key of TEXT_KEYS) f[key] = p.get(key) ?? "";
  for (const key of LIST_KEYS) f[key] = p.getAll(key);
  f.starred = p.get("starred") === "true";
  f.ingested = p.get("ingested") === "true";
  f.summarised = p.get("summarised") === "true";
  const predicted = p.get("predicted_relevant");
  f.predicted_relevant = predicted === "true" || predicted === "false" ? predicted : "";
  const sort = p.get("sort") as SortKey | null;
  if (sort && SORT_KEYS.includes(sort)) f.sort = sort;
  f.order = p.get("order") === "asc" ? "asc" : p.get("order") === "desc" ? "desc" : f.order;
  const page = Number(p.get("page"));
  f.page = Number.isInteger(page) && page > 1 ? page : 1;
  return f;
}

/** Query string for the API: the same filters, with the page turned into limit / offset. */
export function toApiParams(f: Filters): URLSearchParams {
  const p = toUrlParams({ ...f, page: 1 });
  p.set("sort", f.sort);
  p.set("order", f.order);
  p.set("limit", String(PAGE_SIZE));
  p.set("offset", String((f.page - 1) * PAGE_SIZE));
  return p;
}

/** True if anything narrows the list (sort and page do not count). */
export function hasActiveFilters(f: Filters): boolean {
  return toUrlParams({ ...f, sort: DEFAULT_FILTERS.sort, order: DEFAULT_FILTERS.order, page: 1 }).toString() !== "";
}

/** Same filters, ignoring sort and page: used to tell which saved view is showing. */
export function sameFilters(a: Filters, b: Filters): boolean {
  const strip = (f: Filters) => {
    const p = toUrlParams({ ...f, sort: DEFAULT_FILTERS.sort, order: DEFAULT_FILTERS.order, page: 1 });
    p.sort();
    return p.toString();
  };
  return strip(a) === strip(b);
}
