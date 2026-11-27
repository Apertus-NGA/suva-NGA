import { useI18n, type I18n } from "../../lib/i18n";
import { Field } from "../ui/Field";
import { Segmented } from "../ui/Segmented";
import { FilterChip } from "./FilterChip";

type Decision = "" | "true" | "false";
type Value = { predicted_relevant: Decision; score_min: string; score_max: string };
type Props = { value: Value; onChange: (value: Value) => void };

function summary({ predicted_relevant, score_min, score_max }: Value, tx: I18n["tx"]): string | null {
  const parts: string[] = [];
  if (predicted_relevant) parts.push(tx("label", predicted_relevant === "true" ? "relevant" : "not_relevant"));
  if (score_min && score_max) parts.push(`${score_min}–${score_max}`);
  else if (score_min) parts.push(`≥ ${score_min}`);
  else if (score_max) parts.push(`≤ ${score_max}`);
  return parts.length ? parts.join(", ") : null;
}

/** Keep 0..100 whole numbers; anything else clears the bound. */
const clamp = (raw: string) => {
  if (raw.trim() === "") return "";
  const n = Math.round(Number(raw));
  return Number.isFinite(n) ? String(Math.min(100, Math.max(0, n))) : "";
};

/** The system's assessment: its relevant / not relevant decision and its score from 0 to 100. */
export function AssessmentFilter({ value, onChange }: Props) {
  const { t, tx } = useI18n();
  const decisions: Array<{ value: Decision; label: string }> = [
    { value: "", label: t("filter.assessment.all") },
    { value: "true", label: tx("label", "relevant") },
    { value: "false", label: tx("label", "not_relevant") },
  ];
  return (
    <FilterChip
      label={t("filter.assessment")}
      value={summary(value, tx)}
      onClear={() => onChange({ predicted_relevant: "", score_min: "", score_max: "" })}
      width={320}
    >
      <div className="flex flex-col gap-3 p-3">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-faint">{t("filter.assessment.decision")}</span>
          <Segmented
            label={t("filter.assessment.decision")}
            options={decisions}
            value={value.predicted_relevant}
            onChange={(predicted_relevant) => onChange({ ...value, predicted_relevant })}
          />
        </div>
        <div className="flex gap-2">
          <Field label={t("filter.assessment.scoreFrom")} type="number" inputMode="numeric" min={0} max={100} placeholder="0" value={value.score_min}
                 onChange={(e) => onChange({ ...value, score_min: clamp(e.target.value) })} />
          <Field label={t("filter.assessment.scoreTo")} type="number" inputMode="numeric" min={0} max={100} placeholder="100" value={value.score_max}
                 onChange={(e) => onChange({ ...value, score_max: clamp(e.target.value) })} />
        </div>
      </div>
    </FilterChip>
  );
}
