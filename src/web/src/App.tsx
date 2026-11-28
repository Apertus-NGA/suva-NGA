import { useCallback, useEffect, useRef, useState } from "react";
import { FilterBar } from "./components/FilterBar";
import { Pagination } from "./components/Pagination";
import { RulingPage } from "./components/RulingPage";
import { RulingsTable } from "./components/RulingsTable";
import { ScoringPage } from "./components/ScoringPage";
import { SearchInput } from "./components/SearchInput";
import { Sidebar } from "./components/Sidebar";
import { UpdateControl } from "./components/UpdateControl";
import { cn } from "./components/ui/cn";
import { DEFAULT_FILTERS, fromUrlParams, PAGE_SIZE, toUrlParams, type Filters } from "./lib/filters";
import { useI18n } from "./lib/i18n";
import { decideRelevance } from "./lib/api";
import { useFacets, useRulings } from "./lib/useRulings";
import { useUpdates } from "./lib/useUpdates";
import { DEFAULT_VIEW, openingFilters, viewOf, type ViewKey } from "./lib/views";

/** `ruling` is set while one ruling is open; the list it was opened from stays in view and filters. */
type Place = { view: ViewKey; filters: Filters; ruling: number | null };

/** Where the user is, read from the address bar: the view (?view=) and its filters. */
function placeFromUrl(): Place {
  const params = new URLSearchParams(window.location.search);
  const view = viewOf(params.get("view"));
  const filters = fromUrlParams(params);
  // A link without a sort opens the view in its own order (the inbox by score).
  const ruling = Number(params.get("ruling"));
  return {
    view: view.key,
    filters: params.has("sort") ? filters : openingFilters(view, filters),
    ruling: Number.isInteger(ruling) && ruling > 0 ? ruling : null,
  };
}

function urlOf({ view, filters, ruling }: Place): string {
  const params = toUrlParams(filters);
  if (ruling !== null) params.set("ruling", String(ruling));
  if (view !== DEFAULT_VIEW) params.set("view", view);
  if (viewOf(view).sort) {
    // This view has its own opening order, so the order in use is always spelled out.
    params.set("sort", filters.sort);
    params.set("order", filters.order);
  }
  return params.toString();
}

export default function App() {
  const { t, formatNumber } = useI18n();
  const [place, setPlace] = useState<Place>(placeFromUrl);
  const [attempt, setAttempt] = useState(0);
  const view = viewOf(place.view);
  const filters = place.filters;
  const isList = view.scope !== undefined;
  const facets = useFacets(attempt);
  // When an update ends, the list and the filter counts are read again.
  const updates = useUpdates(() => setAttempt((n) => n + 1));
  const { page, loading, error } = useRulings(filters, view, attempt);
  const scroller = useRef<HTMLDivElement>(null);

  // Keep the address bar in step with the place, and follow the browser's back / forward buttons.
  useEffect(() => {
    const query = urlOf(place);
    if (new URLSearchParams(window.location.search).toString() !== query) {
      window.history.pushState(null, "", query ? `?${query}` : window.location.pathname);
    }
  }, [place]);
  useEffect(() => {
    const onPop = () => setPlace(placeFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const toTop = () => scroller.current?.scrollTo({ top: 0 });
  /** Change filters or sort within the view: always back to the first page. */
  const patch = useCallback((change: Partial<Filters>) => {
    setPlace((p) => ({ ...p, filters: { ...p.filters, ...change, page: 1 } }));
    toTop();
  }, []);
  /** Go to a view, with its opening sort and no filters unless some are given. */
  const open = useCallback((key: ViewKey, withFilters?: Partial<Filters>) => {
    setPlace({ view: key, filters: { ...openingFilters(viewOf(key), DEFAULT_FILTERS), ...withFilters, page: 1 }, ruling: null });
    toTop();
  }, []);
  const onSearch = useCallback((q: string) => patch({ q }), [patch]);

  const total = page?.total ?? 0;
  const count = !isList || !facets || !page ? "" : total === facets.total
    ? t("app.count", { n: formatNumber(total) })
    : t("app.countOf", { n: formatNumber(total), total: formatNumber(facets.total) });
  const subtitle = [view.hint ? t(view.hint) : "", count].filter(Boolean).join(" · ");

  return (
    <div className="flex h-full min-w-[960px]">
      <Sidebar current={view.key} onSelect={open} placeholderScores={facets?.stub_scores ?? false} />
      <main className="flex min-w-0 flex-1 flex-col bg-canvas">
        {place.ruling !== null ? (
          <RulingPage
            rulingId={place.ruling}
            onBack={() => setPlace((p) => ({ ...p, ruling: null }))}
            onChanged={() => setAttempt((n) => n + 1)}
            onShowScoring={() => open("scoring")}
          />
        ) : (
          <>
        <header className="shrink-0 px-6 pb-4 pt-7">
          <div className="flex items-end justify-between gap-8">
            <div className="min-w-0 shrink">
              <h1 className="font-serif text-[25px] leading-8 tracking-[-0.01em] text-ink">{t(view.title)}</h1>
              <p className="mt-0.5 h-5 truncate text-[12px] tabular-nums text-faint">{subtitle}</p>
            </div>
            <div className="flex min-w-0 flex-1 items-center justify-end gap-3">
              {isList && <SearchInput value={filters.q} onChange={onSearch} placeholder={t("app.search")} clearLabel={t("app.clearSearch")} />}
              {view.key === "inbox" && (
                <UpdateControl
                  status={updates.status}
                  failedToStart={updates.error}
                  onStart={updates.start}
                />
              )}
            </div>
          </div>
          {isList && (
            <div className="mt-4">
              <FilterBar
                filters={filters}
                facets={facets}
                hidden={view.hiddenFilters}
                onChange={patch}
                onReset={() => open(view.key, { sort: filters.sort, order: filters.order })}
              />
            </div>
          )}
        </header>

        {!isList ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ScoringPage />
          </div>
        ) : (
          <section className="mx-6 mb-6 flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-surface">
            <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
              {error ? (
                <Message text={t("app.loadError")} action={t("app.retry")} onAction={() => setAttempt((n) => n + 1)} />
              ) : page && page.items.length === 0 ? (
                <Message text={t("app.empty")} action={t("app.resetFilters")} onAction={() => open(view.key)} />
              ) : page ? (
                <div className={cn("transition-opacity duration-150", loading && "opacity-60")}>
                  <RulingsTable
                    rulings={page.items}
                    sort={filters.sort}
                    order={filters.order}
                    onSort={(sort, order) => patch({ sort, order })}
                    // After a decision the list, the counts and the learning numbers are read again.
                    onDecide={(ruling, action) => decideRelevance(ruling.id, action).finally(() => setAttempt((n) => n + 1))}
                    onOpen={(ruling) => setPlace((p) => ({ ...p, ruling: ruling.id }))}
                  />
                </div>
              ) : null}
            </div>
            {page && page.total > 0 && !error && (
              <Pagination
                page={filters.page}
                pageSize={PAGE_SIZE}
                total={page.total}
                onPage={(next) => {
                  setPlace((p) => ({ ...p, filters: { ...p.filters, page: next } }));
                  toTop();
                }}
              />
            )}
          </section>
        )}
          </>
        )}
      </main>
    </div>
  );
}

function Message({ text, action, onAction }: { text: string; action: string; onAction: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <p className="font-serif text-[17px] text-ink">{text}</p>
      <button type="button" onClick={onAction} className="h-8 rounded-md bg-ink px-3 text-[13px] font-medium text-white hover:bg-ink/85">
        {action}
      </button>
    </div>
  );
}
