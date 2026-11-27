import { useI18n } from "../../lib/i18n";
import { FilterChip } from "./FilterChip";
import { OptionList, summarize, type Option } from "./OptionList";

type Props = {
  topics: Option[];
  areas: Option[];
  selectedTopics: string[];
  selectedAreas: string[];
  onChange: (next: { topic: string[]; area: string[] }) => void;
};

/**
 * Area of law. Two levels: Suva's core areas (one entry each, whatever the ruling's language),
 * and every area as the court names it (German, French or Italian).
 */
export function AreaFilter({ topics, areas, selectedTopics, selectedAreas, onChange }: Props) {
  const { t } = useI18n();
  const value = summarize([...selectedTopics, ...selectedAreas], [...topics, ...areas]);
  return (
    <FilterChip label={t("filter.area")} value={value} onClear={() => onChange({ topic: [], area: [] })} width={340}>
      <SectionTitle>{t("filter.area.core")}</SectionTitle>
      <OptionList options={topics} selected={selectedTopics} onChange={(topic) => onChange({ topic, area: selectedAreas })} />
      <div className="border-t border-line" />
      <SectionTitle>{t("filter.area.all")}</SectionTitle>
      <OptionList
        options={areas}
        selected={selectedAreas}
        onChange={(area) => onChange({ topic: selectedTopics, area })}
        searchable
        searchPlaceholder={t("filter.area.search")}
      />
    </FilterChip>
  );
}

function SectionTitle({ children }: { children: string }) {
  return <div className="px-3 pb-0.5 pt-2.5 text-[11px] font-medium uppercase tracking-[0.06em] text-faint">{children}</div>;
}
