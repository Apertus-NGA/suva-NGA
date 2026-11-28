import { ArrowLeft, Check, ExternalLink, LoaderCircle, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  confirmSummary, decideRelevance, fetchRuling, generateSummaries, reviseSummary, saveSummary, unconfirmSummary,
  type RelevanceAction, type RulingDetail, type Status, type SummaryLanguage,
} from "../lib/api";
import { useI18n } from "../lib/i18n";
import { RelevanceCard } from "./RelevanceCard";
import { Button, SummaryCard } from "./SummaryCard";
import { cn } from "./ui/cn";

type Props = { rulingId: number; onBack: () => void; onChanged: () => void; onShowScoring: () => void };

const LANGUAGES: SummaryLanguage[] = ["de", "fr"];
const STATUS_STYLE: Record<Status, string> = {
  expert_confirmed: "bg-accent-wash text-accent-text",
  ai_relevant: "border border-line-strong text-ink",
  potentially_relevant: "border border-line text-muted",
  not_relevant: "border border-line text-muted",
  not_assessed: "border border-line text-faint",
};

/** One ruling: its facts and full text on the left; on the right why it has its score, then its two summaries. Nothing here needs bger.ch. */
export function RulingPage({ rulingId, onBack, onChanged, onShowScoring }: Props) {
  const { t, tx, formatDate } = useI18n();
  const [detail, setDetail] = useState<RulingDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<"all" | SummaryLanguage | null>(null);
  const [actionFailed, setActionFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setFailed(false);
    fetchRuling(rulingId, controller.signal).then(setDetail).catch(() => !controller.signal.aborted && setFailed(true));
    return () => controller.abort();
  }, [rulingId]);

  /** Run an action that returns the refreshed page; show a short notice if it fails. */
  const act = useCallback(
    (scope: "all" | SummaryLanguage | null, action: () => Promise<RulingDetail>) => {
      setBusy(scope);
      setActionFailed(false);
      action()
        .then((next) => {
          setDetail(next);
          onChanged();
        })
        .catch(() => setActionFailed(true))
        .finally(() => setBusy(null));
    },
    [onChanged],
  );
  const decide = (action: RelevanceAction) => act(null, () => decideRelevance(rulingId, action).then(() => fetchRuling(rulingId)));

  if (failed) return <Centered>{t("page.loadError")}</Centered>;
  if (!detail) return <Centered>{null}</Centered>;

  const { ruling, summaries } = detail;
  const hasSummary = LANGUAGES.some((l) => summaries[l]);
  const decidedHere = ruling.label_basis === "expert_override";
  const facts = [
    [t("page.decided"), formatDate(ruling.decision_date)],
    [t("page.published"), formatDate(ruling.publication_date)],
    [t("page.division"), ruling.division],
    [t("filter.language"), tx("language", ruling.language)],
    [t("filter.outcome"), tx("outcome", ruling.outcome)],
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 px-6 pb-4 pt-5">
        <button type="button" onClick={onBack} className="-ml-1 flex h-7 items-center gap-1.5 rounded px-1 text-[12px] text-muted hover:text-ink">
          <ArrowLeft size={14} strokeWidth={1.75} aria-hidden />
          {t("page.back")}
        </button>
        <div className="mt-2 flex items-start justify-between gap-8">
          <div className="min-w-0">
            <h1 className="font-serif text-[25px] leading-8 tracking-[-0.01em] text-ink">{ruling.docket}</h1>
            <p className="mt-0.5 text-[14px] leading-6 text-ink">{ruling.title ?? ruling.area ?? ""}</p>
            <p className="text-[12px] leading-5 text-faint">{ruling.title ? ruling.area : ""}</p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2.5">
            <span className={cn("inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-[12px] font-medium", STATUS_STYLE[ruling.status])}>
              {ruling.status === "expert_confirmed" && <Check size={12} strokeWidth={2.5} aria-hidden />}
              {tx("status", ruling.status)}
              {ruling.score !== null && <span className="ml-1 font-normal tabular-nums opacity-70">· {ruling.score}</span>}
            </span>
            <div className="flex gap-2">
              {decidedHere ? (
                <Button onClick={() => decide("reopen")}>
                  <Undo2 size={14} strokeWidth={1.75} aria-hidden />
                  {t("page.undo")}
                </Button>
              ) : (
                <>
                  {ruling.status !== "expert_confirmed" && (
                    <Button primary onClick={() => decide("confirm_relevant")}>
                      <Check size={14} strokeWidth={2} aria-hidden />
                      {t("page.confirmRelevant")}
                    </Button>
                  )}
                  {ruling.status !== "not_relevant" && (
                    <Button onClick={() => decide("mark_not_relevant")}>
                      <X size={14} strokeWidth={2} aria-hidden />
                      {t("page.notRelevant")}
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
        <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-1 text-[12px]">
          {facts.map(([name, value]) => (
            <div key={name} className="flex gap-1.5">
              <dt className="text-faint">{name}</dt>
              <dd className="tabular-nums text-ink">{value}</dd>
            </div>
          ))}
        </dl>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4 px-6 pb-6">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-xl bg-surface">
          <header className="flex h-12 shrink-0 items-center justify-between border-b border-line px-5">
            <h2 className="text-[13px] font-medium text-ink">{t("page.ruling")}</h2>
            {ruling.official_url && (
              <a href={ruling.official_url} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 text-[12px] text-muted hover:text-ink">
                {t("page.source")}
                <ExternalLink size={12} strokeWidth={1.75} aria-hidden />
              </a>
            )}
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {detail.text ? (
              <div className="mx-auto max-w-[68ch] whitespace-pre-wrap font-serif text-[14px] leading-[23px] text-ink">{detail.text}</div>
            ) : (
              <p className="text-[13px] text-faint">{t("page.noText")}</p>
            )}
          </div>
        </section>

        <div className="flex min-h-0 flex-col gap-4 overflow-y-auto">
          {actionFailed && <p className="rounded-md bg-surface px-4 py-2.5 text-[13px] text-ink">{t("page.actionError")}</p>}
          <RelevanceCard relevance={detail.relevance} onShowScoring={onShowScoring} />
          {!hasSummary && (
            <section className="rounded-xl bg-surface px-5 py-5">
              <h2 className="text-[13px] font-medium text-ink">{t("page.summaries")}</h2>
              <p className="mt-1.5 text-[13px] leading-5 text-muted">{t("page.none")}</p>
              <div className="mt-4">
                {busy === "all" ? (
                  <span className="flex h-8 items-center gap-2 text-[13px] text-muted">
                    <LoaderCircle size={14} strokeWidth={2} className="animate-spin" aria-hidden />
                    {t("page.generating")}
                  </span>
                ) : (
                  <Button primary onClick={() => act("all", () => generateSummaries(rulingId))}>
                    {t("page.generate")}
                  </Button>
                )}
              </div>
            </section>
          )}
          {hasSummary &&
            LANGUAGES.map((language) => (
              <SummaryCard
                key={language}
                language={language}
                summary={summaries[language]}
                revisions={detail.revisions}
                busy={busy === language || busy === "all"}
                onConfirm={() => act(language, () => confirmSummary(rulingId, language))}
                onUnconfirm={() => act(language, () => unconfirmSummary(rulingId, language))}
                onSave={(body, confirm) => act(language, () => saveSummary(rulingId, language, body, confirm))}
                onRevise={(reason, note) => act(language, () => reviseSummary(rulingId, language, reason, note))}
              />
            ))}
          {LANGUAGES.some((l) => detail.reference[l]) && (
            <section className="rounded-xl bg-surface">
              <header className="flex h-12 items-center border-b border-line px-5">
                <h2 className="text-[13px] font-medium text-ink">{t("page.reference")}</h2>
              </header>
              {LANGUAGES.filter((l) => detail.reference[l]).map((language) => (
                <div key={language} className="border-b border-line px-5 py-4 last:border-b-0">
                  <div className="pb-1.5 text-[12px] text-faint">{tx("language", language)}</div>
                  <p className="whitespace-pre-wrap font-serif text-[14px] leading-[23px] text-ink">{detail.reference[language]}</p>
                </div>
              ))}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-1 items-center justify-center font-serif text-[17px] text-ink">{children}</div>;
}
