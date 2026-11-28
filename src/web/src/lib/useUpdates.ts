import { useCallback, useEffect, useRef, useState } from "react";
import { fetchUpdates, startUpdate, type UpdatesStatus } from "./api";

const POLL_MS = 2000;

/**
 * The state of live updates. While one is running the status is re-read every two seconds;
 * `onFinished` is called once when a run ends, so the list can be reloaded.
 */
export function useUpdates(onFinished: () => void) {
  const [status, setStatus] = useState<UpdatesStatus | null>(null);
  const [error, setError] = useState(false);
  const wasRunning = useRef(false);
  const finished = useRef(onFinished);
  finished.current = onFinished;

  const accept = useCallback((next: UpdatesStatus) => {
    setStatus(next);
    setError(false);
    if (wasRunning.current && !next.running) finished.current();
    wasRunning.current = next.running;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchUpdates(controller.signal).then(accept).catch(() => undefined);
    return () => controller.abort();
  }, [accept]);

  const running = status?.running ?? false;
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => fetchUpdates().then(accept).catch(() => undefined), POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, accept]);

  const start = useCallback(
    (range?: { published_from: string; published_to: string }) =>
      startUpdate(range)
        .then(accept)
        .catch(() => setError(true)),
    [accept],
  );

  return { status, start, error };
}
