import { FilterChip } from "./FilterChip";
import { OptionList, summarize, type Option } from "./OptionList";

type Props = {
  label: string;
  options: Option[];
  selected: string[];
  onChange: (selected: string[]) => void;
  width?: number;
};

/** Filter on one field with several allowed values. */
export function MultiSelectFilter({ label, options, selected, onChange, width = 260 }: Props) {
  return (
    <FilterChip label={label} value={summarize(selected, options)} onClear={() => onChange([])} width={width}>
      <OptionList options={options} selected={selected} onChange={onChange} searchable={options.length > 8} />
    </FilterChip>
  );
}
