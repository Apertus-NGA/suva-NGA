import { useI18n, type I18n, type Key } from "../../lib/i18n";
import { Field } from "../ui/Field";
import { FilterChip } from "./FilterChip";

type Range = { from: string; to: string };
type Props = { label: string; value: Range; onChange: (value: Range) => void; min?: string | null; max?: string | null };

/** Quarter names are the same in every language; month names are translated. */
const PRESETS: Array<Range & ({ label: string } | { key: Key })> = [
  { label: "Q4 2025", from: "2025-10-01", to: "2025-12-31" },
  { label: "Q1 2026", from: "2026-01-01", to: "2026-03-31" },
  { label: "Q2 2026", from: "2026-04-01", to: "2026-06-30" },
  { key: "filter.june2026", from: "2026-06-01", to: "2026-06-30" },
];

const presetName = (preset: (typeof PRESETS)[number], t: I18n["t"]) => ("key" in preset ? t(preset.key) : preset.label);

function summary({ from, to }: Range, { t, formatDate }: I18n): string | null {
  if (!from && !to) return null;
  // The most specific preset wins: "June 2026" before "Q2 2026" can never clash, as their dates differ.
  const preset = PRESETS.find((p) => p.from === from && p.to === to);
  if (preset) return presetName(preset, t);
  if (from && to) return `${formatDate(from)} – ${formatDate(to)}`;
  return from ? t("filter.since", { date: formatDate(from) }) : t("filter.until", { date: formatDate(to) });
}

/** A date window, both ends inclusive and optional. Used once for the decision date and once for the publication date. */
export function DateRangeFilter({ label, value, onChange, min, max }: Props) {
  const i18n = useI18n();
  const { t } = i18n;
  return (
    <FilterChip label={label} value={summary(value, i18n)} onClear={() => onChange({ from: "", to: "" })} width={300}>
      <div className="flex gap-2 p-3">
        <Field label={t("filter.from")} type="date" value={value.from} min={min ?? undefined} max={value.to || max || undefined}
               onChange={(e) => onChange({ ...value, from: e.target.value })} />
        <Field label={t("filter.to")} type="date" value={value.to} min={value.from || min || undefined} max={max ?? undefined}
               onChange={(e) => onChange({ ...value, to: e.target.value })} />
      </div>
      <div className="flex flex-wrap gap-1.5 border-t border-line p-3">
        {PRESETS.map((preset) => {
          const selected = preset.from === value.from && preset.to === value.to;
          return (
            <button
              key={preset.from + preset.to}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange({ from: preset.from, to: preset.to })}
              className={
                selected
                  ? "h-7 rounded-md bg-ink px-2.5 text-[12px] font-medium text-white"
                  : "h-7 rounded-md bg-wash px-2.5 text-[12px] font-medium text-muted hover:text-ink"
              }
            >
              {presetName(preset, t)}
            </button>
          );
        })}
      </div>
    </FilterChip>
  );
}
