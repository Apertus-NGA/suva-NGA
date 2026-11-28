import { Star } from "lucide-react";
import { areaOptions } from "../lib/areas";
import { useMemo } from "react";
import type { Facets, FacetValue } from "../lib/api";
import { hasActiveFilters, type Filters } from "../lib/filters";
import { useI18n, type Group, type I18n } from "../lib/i18n";
import { AreaFilter } from "./filters/AreaFilter";
import { AssessmentFilter } from "./filters/AssessmentFilter";
import { DateRangeFilter } from "./filters/DateRangeFilter";
import { MultiSelectFilter } from "./filters/MultiSelectFilter";
import type { Option } from "./filters/OptionList";
import { ToggleChip } from "./filters/ToggleChip";

type Props = {
  filters: Filters;
  facets: Facets | null;
  onChange: (patch: Partial<Filters>) => void;
  onReset: () => void;
  /** Chips left out because the current view already fixes what they filter. */
  hidden?: Array<"status" | "assessment">;
};

/** Facet values as options. With a `group`, the database code is shown in the interface language. */
const toOptions = (values: FacetValue[] | undefined, tx?: I18n["tx"], group?: Group): Option[] =>
  (values ?? []).map((v) => ({ value: v.value, label: tx && group ? tx(group, v.value) : v.value, count: v.n }));

const TOPIC_ORDER = ["UV", "MV", "IV"];
const STATUS_ORDER = ["expert_confirmed", "ai_relevant", "potentially_relevant", "not_relevant", "not_assessed"];
const byOrder = (order: string[]) => (a: Option, b: Option) => order.indexOf(a.value) - order.indexOf(b.value);

/** Every way to narrow the list, in one row. */
export function FilterBar({ filters, facets, onChange, onReset, hidden = [] }: Props) {
  const { t, tx, lang } = useI18n();
  const options = useMemo(
    () => ({
      // The three core areas are fixed, so their names are known before the counts arrive.
      topics: facets
        ? toOptions(facets.topics, tx, "topic").sort(byOrder(TOPIC_ORDER))
        : TOPIC_ORDER.map((value) => ({ value, label: tx("topic", value) })),
      areas: areaOptions(facets?.areas, lang),
      divisions: toOptions(facets?.divisions),
      languages: toOptions(facets?.languages, tx, "language"),
      outcomes: toOptions(facets?.outcomes, tx, "outcome"),
      statuses: toOptions(facets?.statuses, tx, "status").sort(byOrder(STATUS_ORDER)),
    }),
    [facets, tx],
  );

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <DateRangeFilter
        label={t("filter.decided")}
        value={{ from: filters.decided_from, to: filters.decided_to }}
        min={facets?.decided_min}
        max={facets?.decided_max}
        onChange={({ from, to }) => onChange({ decided_from: from, decided_to: to })}
      />
      <DateRangeFilter
        label={t("filter.published")}
        value={{ from: filters.published_from, to: filters.published_to }}
        min={facets?.published_min}
        max={facets?.published_max}
        onChange={({ from, to }) => onChange({ published_from: from, published_to: to })}
      />
      <AreaFilter
        topics={options.topics}
        areas={options.areas}
        selectedTopics={filters.topic}
        selectedAreas={filters.area}
        onChange={onChange}
      />
      <MultiSelectFilter label={t("filter.division")} options={options.divisions} selected={filters.division} onChange={(division) => onChange({ division })} width={220} />
      <MultiSelectFilter label={t("filter.language")} options={options.languages} selected={filters.language} onChange={(language) => onChange({ language })} width={220} />
      <MultiSelectFilter label={t("filter.outcome")} options={options.outcomes} selected={filters.outcome} onChange={(outcome) => onChange({ outcome })} />
      {!hidden.includes("status") && (
        <MultiSelectFilter label={t("filter.status")} options={options.statuses} selected={filters.status} onChange={(status) => onChange({ status })} width={270} />
      )}
      {!hidden.includes("assessment") && (
        <AssessmentFilter
          value={{ predicted_relevant: filters.predicted_relevant, score_min: filters.score_min, score_max: filters.score_max }}
          onChange={onChange}
        />
      )}
      <ToggleChip
        pressed={filters.starred}
        onChange={(starred) => onChange({ starred })}
        icon={<Star size={12} strokeWidth={1.75} fill={filters.starred ? "currentColor" : "none"} aria-hidden />}
      >
        {t("filter.starred")}
      </ToggleChip>
      {hasActiveFilters(filters) && (
        <button type="button" onClick={onReset} className="h-7 rounded-md px-1.5 text-[12px] text-muted hover:text-ink">
          {t("filter.reset")}
        </button>
      )}
    </div>
  );
}
