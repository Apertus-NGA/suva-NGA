import { useI18n } from "../lib/i18n";
import { cn } from "./ui/cn";

type Props = { score: number | null; relevant: boolean | null };

/** Relevance score 0..100 with a bar. Orange when the system decided "relevant", grey otherwise. */
export function Score({ score, relevant }: Props) {
  const { t } = useI18n();
  if (score === null) return <span className="text-faint">–</span>;
  return (
    <div className="flex items-center gap-2.5" title={t(relevant ? "score.relevant" : "score.notRelevant")}>
      <span className={cn("w-[22px] text-right font-medium tabular-nums", relevant ? "text-ink" : "text-faint")}>{score}</span>
      <span className="h-[3px] w-10 overflow-hidden rounded-full bg-line" aria-hidden>
        <span className={cn("block h-full rounded-full", relevant ? "bg-accent" : "bg-line-strong")} style={{ width: `${score}%` }} />
      </span>
    </div>
  );
}
