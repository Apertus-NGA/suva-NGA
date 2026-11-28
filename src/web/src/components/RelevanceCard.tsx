import { ArrowUpRight, ChevronRight } from "lucide-react";
import type { Relevance, RuleRow } from "../lib/api";
import { useI18n, type Key } from "../lib/i18n";
import { cn } from "./ui/cn";

type Props = { relevance: Relevance | null; onShowScoring: () => void };

/** The widest bar: the strongest rules of the table are a little above 5. */
const FULL_BAR = 5.5;
const strength = (effect: number): Key =>
  Math.abs(effect) >= 2.5 ? "rel.strong" : Math.abs(effect) >= 1 ? "rel.moderate" : "rel.weak";

/**
 * Why this ruling has its score. Built by code from what the triage run stored: the rules that apply, what each
 * does to the score, what Apertus read, and the facts that carry no weight. For a ruling without a score, the
 * reason layer 1 did not keep it.
 */
export function RelevanceCard({ relevance, onShowScoring }: Props) {
  const { t, tx } = useI18n();
  if (!relevance) return null;

  const how = (
    <button type="button" onClick={onShowScoring} className="flex items-center gap-1 text-[12px] text-muted hover:text-ink">
      {t("rel.how")}
      <ArrowUpRight size={12} strokeWidth={1.75} aria-hidden />
    </button>
  );

  if (relevance.state === "not_assessed") {
    return (
      <section className="rounded-xl bg-surface">
        <header className="flex h-12 items-center justify-between border-b border-line px-5">
          <h2 className="text-[13px] font-medium text-ink">{t("rel.title")}</h2>
          {how}
        </header>
        <div className="px-5 py-4">
          <p className="text-[13px] font-medium text-ink">{t("rel.notAssessed")}</p>
          <p className="mt-1 max-w-[62ch] text-[13px] leading-5 text-muted">
            {t(`rel.reason.${relevance.reason}` as Key, { criterion: relevance.criterion ?? "" })}
          </p>
        </div>
      </section>
    );
  }

  // A backend may leave out rules, readings or facts: each reads as empty, never as a crash.
  const allRules = relevance.rules ?? [];
  const readings = relevance.readings ?? [];
  const shown = allRules.filter((r) => r.applies && r.effect !== 0);
  const pro = shown.filter((r) => r.effect > 0).sort((a, b) => b.effect - a.effect);
  const contra = shown.filter((r) => r.effect < 0).sort((a, b) => a.effect - b.effect);
  const facts = relevance.facts;
  const topics = (facts?.core_topics ?? []).map((name) => tx("topic", name)).join(", ");
  const topicsScored = shown.some((r) => r.rule === "core_topics");
  // Facts that carry no weight. The topics are listed with their rule when that rule counts.
  const notes = [
    facts?.appeal_upheld ? t("rel.fact.upheld") : null,
    topics && !topicsScored ? t("rel.fact.topics", { list: topics }) : null,
  ].filter(Boolean);

  return (
    <section className="rounded-xl bg-surface">
      <header className="flex h-12 items-center justify-between border-b border-line px-5">
        <h2 className="text-[13px] font-medium text-ink">{t("rel.title")}</h2>
        {how}
      </header>

      {/* Closed by default, so the summaries below are on screen at once; the score line opens the detail. */}
      <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-4 px-5 py-3.5 [&::-webkit-details-marker]:hidden">
        <span className="font-serif text-[34px] leading-10 tracking-[-0.02em] tabular-nums text-ink">{relevance.score}</span>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium text-ink">{t(relevance.suspected ? "rel.suspected" : "rel.possible")}</div>
          <div className="mt-1.5 h-[3px] w-full max-w-[220px] overflow-hidden rounded-full bg-line" aria-hidden>
            <span
              className="block h-full rounded-full bg-accent"
              style={{ width: `${relevance.score}%` }}
            />
          </div>
        </div>
        <span className="flex shrink-0 items-center gap-1 text-[12px] text-muted group-hover:text-ink">
          {t("rel.details")}
          <ChevronRight size={13} strokeWidth={1.75} className="transition-transform group-open:rotate-90" aria-hidden />
        </span>
      </summary>

      {allRules.length === 0 ? (
        <p className="px-5 pb-4 pt-2 text-[13px] leading-5 text-muted">{t("rel.oldRun")}</p>
      ) : (
        <div className="px-5 pb-2 pt-3">
          <RuleList title={t("rel.for")} rules={pro} empty={t("rel.noneFor")} tone="for" topics={topics} />
          {contra.length > 0 && <RuleList title={t("rel.against")} rules={contra} tone="against" topics={topics} />}
        </div>
      )}

      <div className="border-t border-line px-5 py-4">
        <h3 className="text-[12px] font-medium text-ink">{t("rel.readings")}</h3>
        {relevance.read_by_apertus ? (
          <>
            <p className="mt-0.5 max-w-[62ch] text-[12px] leading-[18px] text-faint">{t("rel.readings.note")}</p>
            <ul className="mt-2.5 grid grid-cols-1 gap-x-8 gap-y-1.5 xl:grid-cols-2">
              {readings.map((reading) => (
                <li key={reading.reading} className="flex items-start justify-between gap-3 text-[12px] leading-[18px]">
                  <span className="min-w-0 text-muted">{tx("reading", reading.reading)}</span>
                  <Level level={reading.level} label={t("rel.readingFailed")} />
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-0.5 max-w-[62ch] text-[12px] leading-[18px] text-faint">{t("rel.notRead")}</p>
        )}
      </div>

      {notes.length > 0 && (
        <div className="border-t border-line px-5 py-3.5">
          <h3 className="text-[12px] font-medium text-ink">{t("rel.facts")}</h3>
          <p className="mt-0.5 text-[12px] leading-[18px] text-muted">{notes.join(" · ")}</p>
        </div>
      )}

      </details>
    </section>
  );
}

type ListProps = { title: string; rules: RuleRow[]; empty?: string; tone: "for" | "against"; topics: string };

function RuleList({ title, rules, empty, tone, topics }: ListProps) {
  const { t, tx } = useI18n();
  return (
    <div className="pb-3">
      <h3 className="pb-1 text-[11px] font-medium uppercase tracking-[0.06em] text-faint">{title}</h3>
      {rules.length === 0 ? (
        <p className="text-[13px] leading-5 text-faint">{empty}</p>
      ) : (
        <ul>
          {rules.map((rule) => (
            <li key={rule.rule} className="flex min-h-8 items-center gap-3 border-t border-line py-1 first:border-t-0">
              <span className="min-w-0 flex-1 text-[13px] leading-5 text-ink">
                {tx("rule", rule.rule === "consensus" && rule.effect < 0 ? "consensus.low" : rule.rule)}
                {rule.rule === "core_topics" && topics && <span className="text-muted">: {topics}</span>}
                {rule.source === "apertus" && (
                  <span className="ml-2 rounded-full border border-line-strong px-1.5 py-px align-[1px] text-[10px] font-medium text-muted">
                    {t("rel.apertus")}
                  </span>
                )}
              </span>
              <span className="h-[5px] w-[96px] shrink-0 overflow-hidden rounded-full bg-line" aria-hidden>
                <span
                  className={cn("block h-full rounded-full", tone === "for" ? "bg-ink" : "bg-faint")}
                  style={{ width: `${Math.max(6, Math.min(100, (Math.abs(rule.effect) / FULL_BAR) * 100))}%` }}
                />
              </span>
              <span className="w-[62px] shrink-0 text-right text-[12px] text-muted">{t(strength(rule.effect))}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A reading as five steps, from "not at all" to "clearly yes". */
function Level({ level, label }: { level: number | null; label: string }) {
  if (level === null) return <span className="shrink-0 text-faint">{label}</span>;
  const filled = Math.round(level * 4) + 1;
  return (
    <span className="mt-[4px] flex shrink-0 gap-[3px]" role="img" aria-label={`${filled} / 5`} title={`${filled} / 5`}>
      {[1, 2, 3, 4, 5].map((step) => (
        <span key={step} className={cn("h-[9px] w-[9px] rounded-[2px]", step <= filled ? "bg-ink" : "bg-line")} />
      ))}
    </span>
  );
}
