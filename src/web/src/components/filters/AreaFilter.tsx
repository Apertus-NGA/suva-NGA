import type { AreaOption } from "../../lib/areas";
import { useI18n } from "../../lib/i18n";
import { FilterChip } from "./FilterChip";
import { OptionList, summarize, type Option } from "./OptionList";

type Props = {
  topics: Option[];
  areas: AreaOption[];
  selectedTopics: string[];
  selectedAreas: string[];
  onChange: (next: { topic: string[]; area: string[] }) => void;
};

/**
 * Area of law. Two levels: Suva's core areas, and every area of law. Each is one entry, in the interface
 * language, whatever the language of the rulings; an entry stands for the names the court gives that area.
 */
export function AreaFilter({ topics, areas, selectedTopics, selectedAreas, onChange }: Props) {
  const { t } = useI18n();
  // The list is filtered on the court's own names; an entry is ticked when one of its names is.
  const ticked = areas.filter((area) => area.raws.some((raw) => selectedAreas.includes(raw))).map((area) => area.value);
  const namesOf = (values: string[]) => areas.filter((area) => values.includes(area.value)).flatMap((area) => area.raws);
  const value = summarize([...selectedTopics, ...ticked], [...topics, ...areas]);
  return (
    <FilterChip label={t("filter.area")} value={value} onClear={() => onChange({ topic: [], area: [] })} width={340}>
      <SectionTitle>{t("filter.area.core")}</SectionTitle>
      <OptionList options={topics} selected={selectedTopics} onChange={(topic) => onChange({ topic, area: selectedAreas })} />
      <div className="border-t border-line" />
      <SectionTitle>{t("filter.area.all")}</SectionTitle>
      <OptionList
        options={areas}
        selected={ticked}
        onChange={(values) => onChange({ topic: selectedTopics, area: namesOf(values) })}
        searchable
        searchPlaceholder={t("filter.area.search")}
      />
    </FilterChip>
  );
}

function SectionTitle({ children }: { children: string }) {
  return <div className="px-3 pb-0.5 pt-2.5 text-[12px] text-faint">{children}</div>;
}
