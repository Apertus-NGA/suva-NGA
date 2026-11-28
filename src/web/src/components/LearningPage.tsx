import { useEffect, useState } from "react";
import { fetchLearning, type Learning } from "../lib/api";
import { useI18n, type Key } from "../lib/i18n";

type Count = Exclude<keyof Learning, "transitions" | "revision_reasons">;
const TILES: Array<{ value: Count; label: Key; note: Key }> = [
  { value: "relevant_rulings", label: "learning.relevant", note: "learning.relevant.note" },
  { value: "confirmed_by_experts", label: "learning.confirmed", note: "learning.confirmed.note" },
  { value: "rejected_by_experts", label: "learning.rejected", note: "learning.rejected.note" },
  { value: "reference_summaries", label: "learning.reference", note: "learning.reference.note" },
  { value: "generated_summaries", label: "learning.generated", note: "learning.generated.note" },
  { value: "expert_summaries", label: "learning.expert", note: "learning.expert.note" },
  { value: "decisions", label: "learning.decisions", note: "learning.decisions.note" },
  { value: "revision_requests", label: "learning.revisions", note: "learning.revisions.note" },
  { value: "accepted_unchanged", label: "learning.unchanged", note: "learning.unchanged.note" },
];

/** What expert work has produced so far. Each number is data the system can learn from. */
export function LearningPage({ version }: { version: number }) {
  const { t, tx, formatNumber } = useI18n();
  const [numbers, setNumbers] = useState<Learning | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchLearning(controller.signal).then(setNumbers).catch(() => undefined);
    return () => controller.abort();
  }, [version]);

  return (
    <div className="grid grid-cols-2 gap-4 px-6 pb-6 xl:grid-cols-3">
      {TILES.map((tile) => (
        <section key={tile.value} className="rounded-xl bg-surface px-5 py-5">
          <div className="h-10 font-serif text-[34px] leading-10 tracking-[-0.02em] tabular-nums text-ink">
            {numbers ? formatNumber(numbers[tile.value]) : ""}
          </div>
          <div className="mt-3 text-[13px] font-medium text-ink">{t(tile.label)}</div>
          <div className="mt-0.5 text-[12px] leading-[18px] text-faint">{t(tile.note)}</div>
        </section>
      ))}
      <section className="col-span-2 rounded-xl bg-surface px-5 py-5">
        <div className="text-[13px] font-medium text-ink">{t("learning.paths")}</div>
        {numbers && numbers.transitions.length === 0 ? (
          <p className="mt-3 text-[13px] text-faint">{t("learning.paths.empty")}</p>
        ) : (
          <ul className="mt-3 flex flex-col">
            {numbers?.transitions.map((path) => (
              <li key={path.before + path.after} className="flex h-9 items-center gap-3 border-t border-line text-[13px] first:border-t-0">
                <span className="w-[200px] truncate text-muted">{tx("status", path.before)}</span>
                <span className="text-faint" aria-hidden>
                  →
                </span>
                <span className="flex-1 truncate text-ink">{tx("status", path.after)}</span>
                <span className="font-medium tabular-nums text-ink">{formatNumber(path.n)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
