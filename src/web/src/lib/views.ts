// The four places of work in the sidebar. A list view is the ruling table with a fixed scope:
// the scope is always applied on top of whatever filters the user sets, and its filter chips are hidden.

import { Inbox, Library, Scale, type LucideIcon } from "lucide-react";
import type { Filters, Order, SortKey } from "./filters";
import type { Key } from "./i18n";

export type ViewKey = "inbox" | "rulings" | "scoring";

export type View = {
  key: ViewKey;
  icon: LucideIcon;
  name: Key;
  title: Key;
  hint: Key | null;
  /** Fixed filters of this view, sent to the API in addition to the user's. Absent for a page that is not a list. */
  scope?: Record<string, string | string[]>;
  /** Filter chips that make no sense here because the scope already fixes them. */
  hiddenFilters?: Array<"status" | "assessment">;
  sort?: { sort: SortKey; order: Order };
};

export const VIEWS: View[] = [
  {
    key: "inbox",
    icon: Inbox,
    name: "nav.inbox",
    title: "nav.inbox",
    hint: "view.inbox.hint",
    // Assessed relevant and not reviewed, plus everything the latest update added until an expert decides on it.
    scope: { inbox: "true" },
    hiddenFilters: ["status", "assessment"],
    sort: { sort: "score", order: "desc" },
  },
  { key: "rulings", icon: Library, name: "nav.rulings", title: "app.title", hint: null, scope: {} },
  { key: "scoring", icon: Scale, name: "nav.scoring", title: "nav.scoring", hint: "view.scoring.hint" },
];

export const DEFAULT_VIEW: ViewKey = "rulings";
export const viewOf = (key: string | null): View => VIEWS.find((v) => v.key === key) ?? VIEWS.find((v) => v.key === DEFAULT_VIEW)!;

/** The API query for a view: the user's filters with the view's scope laid over them. */
export function scoped(query: URLSearchParams, view: View): URLSearchParams {
  const result = new URLSearchParams(query);
  for (const [name, value] of Object.entries(view.scope ?? {})) {
    result.delete(name);
    for (const v of Array.isArray(value) ? value : [value]) result.append(name, v);
  }
  return result;
}

/** The filters a view opens with: nothing set, in the view's own sort order. */
export const openingFilters = (view: View, base: Filters): Filters => ({ ...base, ...(view.sort ?? {}) });
