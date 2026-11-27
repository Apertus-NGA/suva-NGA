import type { Label } from "../lib/api";
import { useI18n } from "../lib/i18n";

/** The human label: Suva's list, or an expert's correction. */
export function LabelBadge({ label }: { label: Label }) {
  const { tx } = useI18n();
  if (label === "relevant") {
    return (
      <span className="inline-flex h-[22px] items-center rounded-full bg-accent-wash px-2 text-[12px] font-medium text-accent-text">
        {tx("label", label)}
      </span>
    );
  }
  return <span className={label === "unknown" ? "text-faint" : "text-muted"}>{tx("label", label)}</span>;
}
