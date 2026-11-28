import { ChevronDown, X } from "lucide-react";
import type { ReactNode } from "react";
import { useI18n } from "../../lib/i18n";
import { Popover } from "../ui/Popover";
import { cn } from "../ui/cn";

type Props = {
  label: string;
  /** Short text for what is selected, or null when the filter is not set. */
  value: string | null;
  onClear: () => void;
  children: ReactNode;
  width?: number;
};

/** One filter in the filter bar: a button that opens its panel, and shows what is selected once set. */
export function FilterChip({ label, value, onClear, children, width }: Props) {
  const { t } = useI18n();
  const active = value !== null;
  return (
    <div
      className={cn(
        "flex h-7 items-center rounded-md border text-[12px] transition-colors",
        active ? "border-ink/30 bg-surface" : "border-line-strong/70 bg-surface hover:border-line-strong",
      )}
    >
      <Popover
        width={width}
        trigger={
          <button type="button" className={cn("flex h-full items-center gap-1.5 rounded-md pl-2", active ? "pr-1" : "pr-1.5")}>
            <span className={active ? "text-muted" : "text-ink"}>{label}</span>
            {active ? (
              <span className="max-w-[180px] truncate font-medium text-ink">{value}</span>
            ) : (
              <ChevronDown size={13} strokeWidth={1.75} className="text-faint" aria-hidden />
            )}
          </button>
        }
      >
        {children}
      </Popover>
      {active && (
        <button
          type="button"
          onClick={onClear}
          aria-label={t("filter.remove", { label })}
          className="mr-0.5 flex size-5 items-center justify-center rounded text-faint hover:bg-wash hover:text-ink"
        >
          <X size={13} strokeWidth={2} aria-hidden />
        </button>
      )}
    </div>
  );
}
