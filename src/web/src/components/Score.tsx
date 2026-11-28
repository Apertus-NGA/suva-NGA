import { useI18n } from "../lib/i18n";
import { cn } from "./ui/cn";

type Props = { score: number | null; relevant: boolean | null };

/** Relevance score 0..100 with a bar, always in the accent colour; the tooltip says what the system decided. */
export function Score({ score, relevant }: Props) {
  const { t } = useI18n();
  if (score === null) return <span className="text-faint">–</span>;
  return (
    <div className="flex items-center gap-2.5" title={t(relevant ? "score.relevant" : "score.notRelevant")}>
      <span className={cn("w-[22px] text-right font-medium tabular-nums", "text-ink")}>{score}</span>
      <span className="h-[3px] w-10 overflow-hidden rounded-full bg-line" aria-hidden>
        <span className={"block h-full rounded-full bg-accent"} style={{ width: `${score}%` }} />
      </span>
    </div>
  );
}
