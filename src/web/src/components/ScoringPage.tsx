import { useEffect, useState } from "react";
import { fetchScoring, type Scoring } from "../lib/api";
import { useI18n, type Key } from "../lib/i18n";
import { cn } from "./ui/cn";

const STEPS: Array<{ title: Key; body: Key; by: Key }> = [
  { title: "scoring.step1.title", body: "scoring.step1.body", by: "scoring.by.both" },
  { title: "scoring.step2.title", body: "scoring.step2.body", by: "scoring.source.code" },
  { title: "scoring.step3.title", body: "scoring.step3.body", by: "scoring.source.apertus" },
  { title: "scoring.step4.title", body: "scoring.step4.body", by: "scoring.source.code" },
];

/** The open box: the steps from a ruling to its score, and the rule table of the current run. */
export function ScoringPage() {
  const { t, tx, formatNumber, formatDate } = useI18n();
  const [scoring, setScoring] = useState<Scoring | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetchScoring(controller.signal).then(setScoring).catch(() => !controller.signal.aborted && setFailed(true));
    return () => controller.abort();
  }, []);

  if (failed) return <p className="px-6 font-serif text-[17px] text-ink">{t("scoring.loadError")}</p>;
  if (!scoring) return null;

  const rules = [...scoring.rules].sort((a, b) => Math.abs(b.effect) - Math.abs(a.effect));
  const widest = Math.max(...rules.map((r) => Math.abs(r.effect)), 1);
  const counts = { n: rules.length, facts: rules.filter((r) => r.source === "code").length, share: Math.round(scoring.share_promoted * 100) };
  const percent = (share: number) => `${formatNumber(Math.round(share * 100))}%`;

  return (
    <div className="flex flex-col gap-4 px-6 pb-6">
      <p className="max-w-[78ch] text-[14px] leading-6 text-ink">{t("scoring.intro", counts)}</p>

      <ol className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {STEPS.map((step, index) => (
          <li key={step.title} className="rounded-xl bg-surface px-5 py-4">
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-serif text-[21px] leading-7 tabular-nums text-ink">{index + 1}</span>
              <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-faint">{t(step.by)}</span>
            </div>
            <div className="mt-1.5 text-[13px] font-medium text-ink">{t(step.title)}</div>
            <p className="mt-1 text-[12px] leading-[18px] text-muted">{t(step.body, counts)}</p>
          </li>
        ))}
      </ol>

      <section className="rounded-xl bg-surface">
        <header className="border-b border-line px-5 py-4">
          <h2 className="text-[13px] font-medium text-ink">{t("scoring.rules", { n: rules.length })}</h2>
          <p className="mt-0.5 max-w-[86ch] text-[12px] leading-[18px] text-faint">{t("scoring.rules.note")}</p>
        </header>
        <table className="w-full table-fixed text-[13px]">
          <thead>
            <tr className="h-9 border-b border-line text-left text-[11px] font-medium uppercase tracking-[0.06em] text-faint">
              <th className="px-5 font-medium">{t("scoring.col.rule")}</th>
              <th className="w-[110px] font-medium">{t("scoring.col.source")}</th>
              <th className="w-[170px] font-medium">{t("scoring.col.direction")}</th>
              <th className="w-[290px] font-medium">{t("scoring.col.strength")}</th>
              <th className="w-[120px] pr-5 text-right font-medium">{t("scoring.col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => {
              const up = rule.direction > 0;
              const none = rule.effect === 0;
              return (
                <tr key={rule.rule} className="h-10 border-b border-line last:border-b-0">
                  <td className="truncate px-5 text-ink">{tx("rule", rule.rule)}</td>
                  <td className="text-muted">
                    {rule.source === "apertus" ? (
                      <span className="rounded-full border border-line-strong px-2 py-0.5 text-[11px] font-medium text-ink">{t("scoring.source.apertus")}</span>
                    ) : (
                      t("scoring.source.code")
                    )}
                  </td>
                  <td className={none ? "text-faint" : "text-muted"}>
                    <span aria-hidden className="mr-1.5 inline-block w-3 text-center text-ink">
                      {none ? "·" : up ? "↑" : "↓"}
                    </span>
                    {t(none ? "rel.noWeight" : up ? "scoring.raises" : "scoring.lowers")}
                  </td>
                  <td>
                    <div className="flex items-center gap-3">
                      <span className="h-[5px] w-[120px] overflow-hidden rounded-full bg-line" aria-hidden>
                        <span
                          className={cn("block h-full rounded-full", up ? "bg-ink" : "bg-faint")}
                          style={{ width: `${none ? 0 : Math.max(4, (Math.abs(rule.effect) / widest) * 100)}%` }}
                        />
                      </span>
                      {rule.source === "apertus" && <span className="whitespace-nowrap text-[11px] text-faint">{t("scoring.perStep")}</span>}
                    </div>
                  </td>
                  <td className="pr-5 text-right tabular-nums text-muted">{rule.share === null ? "–" : percent(rule.share)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <div>
        <section className="rounded-xl bg-surface px-5 py-5">
          <h2 className="text-[13px] font-medium text-ink">{t("scoring.formula")}</h2>
          <p className="mt-1.5 max-w-[86ch] text-[13px] leading-5 text-muted">{t("scoring.formula.body")}</p>
          <p className="mt-3 max-w-[86ch] rounded-md bg-wash px-3 py-2 font-mono text-[12px] leading-5 text-ink">
            score = 100 / (1 + e<sup>−(start + Σ rules)</sup>)
            {scoring.intercept !== null && <span className="text-muted"> · start = {scoring.intercept.toFixed(2)}</span>}
          </p>
          <p className="mt-3 text-[12px] leading-[18px] text-faint">
            {t("scoring.run", { id: scoring.run_id, pipeline: scoring.pipeline ?? "", date: formatDate(scoring.created_at.slice(0, 10)) })}
            {" · "}
            {t("scoring.scored", { n: formatNumber(scoring.scored), suspected: formatNumber(scoring.suspected) })}
          </p>
        </section>
      </div>
    </div>
  );
}
