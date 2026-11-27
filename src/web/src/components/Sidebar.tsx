import { BadgeCheck, CalendarDays, List, ShieldCheck, Sparkles, type LucideIcon } from "lucide-react";
import { DEFAULT_FILTERS, sameFilters, type Filters } from "../lib/filters";
import { useI18n, type Key } from "../lib/i18n";
import { LanguageSwitch } from "./LanguageSwitch";
import { cn } from "./ui/cn";

type View = { name: Key; icon: LucideIcon; filters: Filters };

/** Saved views: one click to the lists the team opens most. Each is just a set of filters. */
export const VIEWS: View[] = [
  { name: "views.all", icon: List, filters: DEFAULT_FILTERS },
  { name: "views.core", icon: ShieldCheck, filters: { ...DEFAULT_FILTERS, topic: ["UV", "MV", "IV"] } },
  { name: "views.predicted", icon: Sparkles, filters: { ...DEFAULT_FILTERS, predicted_relevant: "true", sort: "score" } },
  { name: "views.june", icon: CalendarDays, filters: { ...DEFAULT_FILTERS, decided_from: "2026-06-01", decided_to: "2026-06-30", sort: "score" } },
  { name: "views.labelled", icon: BadgeCheck, filters: { ...DEFAULT_FILTERS, label: ["relevant"] } },
];

type Props = { filters: Filters; onSelect: (filters: Filters) => void; placeholderScores: boolean };

export function Sidebar({ filters, onSelect, placeholderScores }: Props) {
  const { t } = useI18n();
  return (
    <aside className="flex w-[224px] shrink-0 flex-col bg-night text-night-text xl:w-[244px]">
      <div className="flex h-[76px] items-center px-5">
        <span className="mr-2.5 size-2.5 rounded-full bg-accent" aria-hidden />
        <span className="font-serif text-[21px] leading-none tracking-[-0.01em]">Suva</span>
        <span className="ml-2.5 border-l border-night-line pl-2.5 text-[12px] text-night-muted">{t("app.name")}</span>
      </div>
      <nav aria-label={t("views.title")} className="flex flex-col gap-px px-2.5">
        <div className="px-2.5 pb-2 pt-1 text-[12px] text-night-muted">{t("views.title")}</div>
        {VIEWS.map((view) => {
          const current = sameFilters(filters, view.filters);
          return (
            <button
              key={view.name}
              type="button"
              aria-current={current ? "page" : undefined}
              onClick={() => onSelect(view.filters)}
              className={cn(
                "flex min-h-8 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] leading-5 transition-colors focus-visible:outline-night-text",
                current ? "bg-night-raised text-night-text" : "text-night-text/80 hover:bg-night-raised/60 hover:text-night-text",
              )}
            >
              <view.icon size={15} strokeWidth={1.5} className={cn("shrink-0", current ? "text-accent" : "text-night-muted")} aria-hidden />
              {t(view.name)}
            </button>
          );
        })}
      </nav>
      <div className="mt-auto px-5 pb-4">
        {placeholderScores && <p className="pb-4 text-[12px] leading-[18px] text-night-muted">{t("app.placeholderScores")}</p>}
        <div className="-mx-2">
          <LanguageSwitch />
        </div>
      </div>
    </aside>
  );
}
