import { useI18n } from "../lib/i18n";
import { VIEWS, type ViewKey } from "../lib/views";
import { LanguageSwitch } from "./LanguageSwitch";
import { cn } from "./ui/cn";

type Props = { current: ViewKey; onSelect: (view: ViewKey) => void; placeholderScores: boolean };

/** The places of work: inbox, all rulings, learning, scoring. */
export function Sidebar({ current, onSelect, placeholderScores }: Props) {
  const { t } = useI18n();
  return (
    <aside className="flex w-[208px] shrink-0 flex-col bg-night text-night-text xl:w-[228px]">
      <div className="flex h-[76px] items-center px-5">
        <span className="mr-2.5 size-2.5 rounded-full bg-accent" aria-hidden />
        <span className="font-serif text-[21px] leading-none tracking-[-0.01em]">{t("app.name")}</span>
      </div>
      <nav aria-label={t("nav.title")} className="flex flex-col gap-px px-2.5">
        {VIEWS.map((view) => {
          const active = view.key === current;
          return (
            <button
              key={view.key}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onSelect(view.key)}
              className={cn(
                "flex h-9 items-center gap-2.5 rounded-md px-2.5 text-left text-[13px] transition-colors focus-visible:outline-night-text",
                active ? "bg-night-raised text-night-text" : "text-night-text/80 hover:bg-night-raised/60 hover:text-night-text",
              )}
            >
              <view.icon size={16} strokeWidth={1.5} className={cn("shrink-0", active ? "text-accent" : "text-night-muted")} aria-hidden />
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
