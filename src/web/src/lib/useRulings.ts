import { useEffect, useState } from "react";
import { fetchFacets, fetchRulings, type Facets, type RulingPage } from "./api";
import { toApiParams, type Filters } from "./filters";

type State = { page: RulingPage | null; loading: boolean; error: string | null };

/** The current page of rulings for a set of filters. The previous page stays visible while the next one loads. */
export function useRulings(filters: Filters, attempt: number): State {
  const [state, setState] = useState<State>({ page: null, loading: true, error: null });
  const query = toApiParams(filters).toString();
  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    fetchRulings(new URLSearchParams(query), controller.signal)
      .then((page) => setState({ page, loading: false, error: null }))
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setState((s) => ({ ...s, loading: false, error: e instanceof Error ? e.message : String(e) }));
      });
    return () => controller.abort();
  }, [query, attempt]);
  return state;
}

/** Filter options and counts. Loaded once. */
export function useFacets(): Facets | null {
  const [facets, setFacets] = useState<Facets | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchFacets(controller.signal).then(setFacets).catch(() => undefined);
    return () => controller.abort();
  }, []);
  return facets;
}
