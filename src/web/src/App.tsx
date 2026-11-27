import { useCallback, useEffect, useRef, useState } from "react";
import { FilterBar } from "./components/FilterBar";
import { Pagination } from "./components/Pagination";
import { RulingsTable } from "./components/RulingsTable";
import { SearchInput } from "./components/SearchInput";
import { Sidebar } from "./components/Sidebar";
import { cn } from "./components/ui/cn";
import { DEFAULT_FILTERS, fromUrlParams, PAGE_SIZE, toUrlParams, type Filters } from "./lib/filters";
import { useI18n } from "./lib/i18n";
import { useFacets, useRulings } from "./lib/useRulings";

export default function App() {
  const { t, formatNumber } = useI18n();
  const [filters, setFilters] = useState<Filters>(() => fromUrlParams(new URLSearchParams(window.location.search)));
  const [attempt, setAttempt] = useState(0);
  const facets = useFacets();
  const { page, loading, error } = useRulings(filters, attempt);
  const scroller = useRef<HTMLDivElement>(null);

  // Keep the address bar in step with the filters, and follow the browser's back / forward buttons.
  useEffect(() => {
    const query = toUrlParams(filters).toString();
    if (new URLSearchParams(window.location.search).toString() !== query) {
      window.history.pushState(null, "", query ? `?${query}` : window.location.pathname);
    }
  }, [filters]);
  useEffect(() => {
    const onPop = () => setFilters(fromUrlParams(new URLSearchParams(window.location.search)));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const toTop = () => scroller.current?.scrollTo({ top: 0 });
  /** Change filters or sort: always back to the first page. */
  const patch = useCallback((change: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...change, page: 1 }));
    toTop();
  }, []);
  const replace = useCallback((next: Filters) => {
    setFilters({ ...next, page: 1 });
    toTop();
  }, []);
  const onSearch = useCallback((q: string) => patch({ q }), [patch]);

  const total = page?.total ?? 0;
  const count = !facets || !page ? "" : total === facets.total
    ? t("app.count", { n: formatNumber(total) })
    : t("app.countOf", { n: formatNumber(total), total: formatNumber(facets.total) });

  return (
    <div className="flex h-full min-w-[960px]">
      <Sidebar filters={filters} onSelect={replace} placeholderScores={facets?.stub_scores ?? false} />
      <main className="flex min-w-0 flex-1 flex-col bg-canvas">
        <header className="shrink-0 px-6 pb-4 pt-7">
          <div className="flex items-end justify-between gap-8">
            <div className="shrink-0">
              <h1 className="font-serif text-[25px] leading-8 tracking-[-0.01em] text-ink">{t("app.title")}</h1>
              <p className="mt-0.5 h-5 text-[12px] tabular-nums text-faint">{count}</p>
            </div>
            <SearchInput value={filters.q} onChange={onSearch} placeholder={t("app.search")} clearLabel={t("app.clearSearch")} />
          </div>
          <div className="mt-4">
            <FilterBar filters={filters} facets={facets} onChange={patch} onReset={() => replace({ ...DEFAULT_FILTERS, sort: filters.sort, order: filters.order })} />
          </div>
        </header>

        <section className="mx-6 mb-6 flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl bg-surface">
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
          {error ? (
            <Message text={t("app.loadError")} action={t("app.retry")} onAction={() => setAttempt((n) => n + 1)} />
          ) : page && page.items.length === 0 ? (
            <Message text={t("app.empty")} action={t("app.resetFilters")} onAction={() => replace(DEFAULT_FILTERS)} />
          ) : page ? (
            <div className={cn("transition-opacity duration-150", loading && "opacity-60")}>
              <RulingsTable rulings={page.items} sort={filters.sort} order={filters.order} onSort={(sort, order) => patch({ sort, order })} />
            </div>
          ) : null}
        </div>

        {page && page.total > 0 && !error && (
          <Pagination
            page={filters.page}
            pageSize={PAGE_SIZE}
            total={page.total}
            onPage={(next) => {
              setFilters((f) => ({ ...f, page: next }));
              toTop();
            }}
          />
        )}
        </section>
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
