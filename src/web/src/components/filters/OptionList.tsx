import { Check, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useI18n } from "../../lib/i18n";
import { cn } from "../ui/cn";

export type Option = { value: string; label: string; count?: number };

type Props = {
  options: Option[];
  selected: string[];
  onChange: (selected: string[]) => void;
  /** Show a search box above the list. */
  searchable?: boolean;
  searchPlaceholder?: string;
};

/** Checkbox list with counts. Used by every multi-select filter. */
export function OptionList({ options, selected, onChange, searchable = false, searchPlaceholder }: Props) {
  const { t, formatNumber } = useI18n();
  const [query, setQuery] = useState("");
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? options.filter((o) => o.label.toLowerCase().includes(needle)) : options;
  }, [options, query]);

  const toggle = (value: string) =>
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value]);

  return (
    <div>
      {searchable && (
        <div className="relative border-b border-line">
          <Search size={14} strokeWidth={1.75} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" aria-hidden />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder ?? t("filter.search")}
            className="h-9 w-full bg-transparent pl-8 pr-3 text-[13px] placeholder:text-faint focus:outline-none"
          />
        </div>
      )}
      <ul className="max-h-[264px] overflow-y-auto p-1">
        {visible.map((option) => {
          const checked = selected.includes(option.value);
          return (
            <li key={option.value}>
              <button
                type="button"
                role="checkbox"
                aria-checked={checked}
                onClick={() => toggle(option.value)}
                className="flex h-8 w-full items-center gap-2.5 rounded-md px-2 text-left hover:bg-wash"
              >
                <span
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded-[4px] border",
                    checked ? "border-ink bg-ink text-white" : "border-line-strong bg-surface",
                  )}
                >
                  {checked && <Check size={12} strokeWidth={2.5} aria-hidden />}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink" title={option.label}>
                  {option.label}
                </span>
                {option.count !== undefined && (
                  <span className="shrink-0 text-[12px] tabular-nums text-faint">{formatNumber(option.count)}</span>
                )}
              </button>
            </li>
          );
        })}
        {visible.length === 0 && <li className="px-2 py-2 text-muted">{t("filter.noMatches")}</li>}
      </ul>
    </div>
  );
}

/** "Unfallversicherung", "Unfallversicherung +2", or null when nothing is selected. */
export function summarize(selected: string[], options: Option[]): string | null {
  if (selected.length === 0) return null;
  const first = options.find((o) => o.value === selected[0])?.label ?? selected[0];
  return selected.length === 1 ? first : `${first} +${selected.length - 1}`;
}
