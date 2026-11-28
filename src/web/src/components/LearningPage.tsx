import { useEffect, useState } from "react";
import { fetchLearning, type Learning } from "../lib/api";
import { useI18n, type Key } from "../lib/i18n";
import { cn } from "./ui/cn";

type Count = Exclude<keyof Learning, "transitions" | "revision_reasons">;
type Tile = { value: Count; label: Key; note: Key };
const GROUPS: Array<{ title: Key; columns: string; tiles: Tile[] }> = [
  {
    title: "learning.group.relevance",
    columns: "xl:grid-cols-4",
    tiles: [
      { value: "relevant_rulings", label: "learning.relevant", note: "learning.relevant.note" },
      { value: "confirmed_by_experts", label: "learning.confirmed", note: "learning.confirmed.note" },
      { value: "rejected_by_experts", label: "learning.rejected", note: "learning.rejected.note" },
      { value: "decisions", label: "learning.decisions", note: "learning.decisions.note" },
    ],
  },
  {
    title: "learning.group.summaries",
    columns: "xl:grid-cols-5",
    tiles: [
      { value: "reference_summaries", label: "learning.reference", note: "learning.reference.note" },
      { value: "generated_summaries", label: "learning.generated", note: "learning.generated.note" },
      { value: "accepted_unchanged", label: "learning.unchanged", note: "learning.unchanged.note" },
      { value: "revision_requests", label: "learning.revisions", note: "learning.revisions.note" },
      { value: "expert_summaries", label: "learning.expert", note: "learning.expert.note" },
    ],
  },
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
    <div className="flex flex-col gap-4 px-6 pb-6">
      {GROUPS.map((group) => (
        <section key={group.title} className="overflow-hidden rounded-xl bg-surface">
          <h2 className="border-b border-line px-5 py-3.5 text-[13px] font-medium text-ink">{t(group.title)}</h2>
          {/* Hairlines between the figures: the grid's gaps show the line colour behind the cells. */}
          <div className={cn("grid grid-cols-2 gap-px bg-line", group.columns)}>
            {group.tiles.map((tile, index) => (
              <div key={tile.value} className={cn("bg-surface px-5 py-5", group.tiles.length % 2 === 1 && index === group.tiles.length - 1 && "col-span-2 xl:col-span-1")}>
                <div className="h-9 font-serif text-[30px] leading-9 tracking-[-0.02em] tabular-nums text-ink">
                  {numbers ? formatNumber(numbers[tile.value]) : ""}
                </div>
                <div className="mt-2.5 text-[13px] font-medium text-ink">{t(tile.label)}</div>
                <div className="mt-0.5 text-[12px] leading-[18px] text-faint">{t(tile.note)}</div>
              </div>
            ))}
          </div>
        </section>
      ))}
      <section className="rounded-xl bg-surface px-5 py-5">
        <h2 className="text-[13px] font-medium text-ink">{t("learning.paths")}</h2>
        {numbers && numbers.transitions.length === 0 ? (
          <p className="mt-3 text-[13px] text-faint">{t("learning.paths.empty")}</p>
        ) : (
          <ul className="mt-3 flex flex-col">
            {numbers?.transitions.map((path) => (
              <li key={path.before + path.after} className="flex h-9 items-center gap-3 border-t border-line text-[13px] first:border-t-0">
                <span className="w-[240px] truncate text-muted">{tx("status", path.before)}</span>
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
