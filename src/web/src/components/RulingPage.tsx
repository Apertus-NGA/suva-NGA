import { ArrowLeft, Check, ExternalLink, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError, confirmSummary, decideRelevance, fetchRuling, generateSummaries, reviseSummary, saveSummary, unconfirmSummary,
  type RelevanceAction, type RulingDetail, type Status, type SummaryLanguage,
} from "../lib/api";
import { useI18n } from "../lib/i18n";
import { locate, merge, sentencesOf, type Range } from "../lib/provenance";
import { RelevanceCard } from "./RelevanceCard";
import { Button, SummaryCard, Working } from "./SummaryCard";
import { cn } from "./ui/cn";

type Props = { rulingId: number; onBack: () => void; onChanged: () => void; onShowScoring: () => void };

const LANGUAGES: SummaryLanguage[] = ["de", "fr"];
/** A summary sentence: the one whose sources are marked in the ruling text. */
type Sentence = { language: SummaryLanguage; index: number };
type Busy = { scope: "all" | SummaryLanguage | null; writing: boolean };
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
  const [busy, setBusy] = useState<Busy | null>(null);
  /** A failed action: `unavailable` when the model could not be used (502/503), with the server's reason. */
  const [actionError, setActionError] = useState<{ unavailable: boolean; detail: string | null } | null>(null);
  const [selected, setSelected] = useState<Sentence | null>(null);
  const [hovered, setHovered] = useState<Sentence | null>(null);
  const [scrollTo, setScrollTo] = useState(0); // counts selections: each one scrolls the ruling text to its source

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setFailed(false);
    setActionError(null);
    setSelected(null);
    setHovered(null);
    fetchRuling(rulingId, controller.signal).then(setDetail).catch(() => !controller.signal.aborted && setFailed(true));
    return () => controller.abort();
  }, [rulingId]);

  /** Run an action that returns the refreshed page; show a short notice if it fails. `writing`: Apertus is called. */
  const act = useCallback(
    (scope: "all" | SummaryLanguage | null, action: () => Promise<RulingDetail>, writing = false) => {
      setBusy({ scope, writing });
      setActionError(null);
      action()
        .then((next) => {
          setDetail(next);
          setSelected(null);
          setHovered(null);
          onChanged();
        })
        .catch((e: unknown) => {
          const status = e instanceof ApiError ? e.status : 0;
          setActionError({ unavailable: status === 502 || status === 503, detail: e instanceof ApiError ? e.detail : null });
        })
        .finally(() => setBusy(null));
    },
    [onChanged],
  );
  const decide = (action: RelevanceAction) => act(null, () => decideRelevance(rulingId, action).then(() => fetchRuling(rulingId)));

  // The passages of the ruling the hovered (else the selected) summary sentence rests on.
  const focus = hovered ?? selected;
  const marks = useMemo<Range[]>(() => {
    const text = detail?.text;
    if (!focus || !text) return [];
    const sentence = sentencesOf(detail.summaries?.[focus.language])[focus.index];
    return merge((sentence?.sources ?? []).map((source) => locate(text, source)).filter((r): r is Range => r !== null));
  }, [detail, focus]);

  if (failed) return <Centered>{t("page.loadError")}</Centered>;
  if (!detail) return <Centered>{null}</Centered>;

  const { ruling } = detail;
  const summaries = detail.summaries ?? { de: null, fr: null };
  const hasSummary = LANGUAGES.some((l) => summaries[l]);
  const officialUrl = ruling.official_url && /^https?:\/\/\S+$/.test(ruling.official_url) ? ruling.official_url : null;
  const busyFor = (language: SummaryLanguage) =>
    busy && (busy.scope === language || busy.scope === "all") ? (busy.writing ? "writing" : "saving") : false;
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
            <span title={tx("statusHint", ruling.status)} className={cn("inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-[12px] font-medium", STATUS_STYLE[ruling.status])}>
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
            {officialUrl && (
              <a href={officialUrl} target="_blank" rel="noreferrer" className="flex items-center gap-1.5 text-[12px] text-muted hover:text-ink">
                {t("page.source")}
                <ExternalLink size={12} strokeWidth={1.75} aria-hidden />
              </a>
            )}
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            {detail.text ? (
              <RulingText text={detail.text} marks={marks} scrollTo={scrollTo} />
            ) : (
              <p className="text-[13px] text-faint">{t("page.noText")}</p>
            )}
          </div>
        </section>

        <div className="flex min-h-0 flex-col gap-4 overflow-y-auto">
          {actionError && (
            <p role="alert" title={actionError.detail ?? undefined} className="rounded-md bg-surface px-4 py-2.5 text-[13px] text-ink">
              {t(actionError.unavailable ? "page.modelUnavailable" : "page.actionError")}
            </p>
          )}
          <RelevanceCard relevance={detail.relevance} onShowScoring={onShowScoring} />
          {!hasSummary && (
            <section className="rounded-xl bg-surface px-5 py-5">
              <h2 className="text-[13px] font-medium text-ink">{t("page.summaries")}</h2>
              <p className="mt-1.5 text-[13px] leading-5 text-muted">{t("page.none")}</p>
              <div className="mt-4">
                {busy?.scope === "all" ? (
                  <Working writing />
                ) : (
                  <Button primary disabled={!detail.text} onClick={() => act("all", () => generateSummaries(rulingId), true)}>
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
                text={detail.text}
                revisions={detail.revisions ?? []}
                busy={busyFor(language)}
                active={focus?.language === language ? focus.index : null}
                selected={selected?.language === language ? selected.index : null}
                onHover={(index) => setHovered(index === null ? null : { language, index })}
                onSelect={(index) => {
                  setSelected(index === null ? null : { language, index });
                  if (index !== null) setScrollTo((n) => n + 1);
                }}
                onConfirm={() => act(language, () => confirmSummary(rulingId, language))}
                onUnconfirm={() => act(language, () => unconfirmSummary(rulingId, language))}
                onSave={(body, confirm) => act(language, () => saveSummary(rulingId, language, body, confirm))}
                onRevise={(reason, note) => act(language, () => reviseSummary(rulingId, language, reason, note), true)}
              />
            ))}
          {LANGUAGES.some((l) => detail.reference?.[l]) && (
            <section className="rounded-xl bg-surface">
              <header className="flex h-12 items-center border-b border-line px-5">
                <h2 className="text-[13px] font-medium text-ink">{t("page.reference")}</h2>
              </header>
              {LANGUAGES.filter((l) => detail.reference?.[l]).map((language) => (
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

/** The full text of the ruling, with the source passages of the chosen summary sentence marked. */
function RulingText({ text, marks, scrollTo }: { text: string; marks: Range[]; scrollTo: number }) {
  const first = useRef<HTMLElement>(null);
  // A new selection brings its first passage into view; hovering only marks.
  useEffect(() => {
    if (scrollTo > 0) first.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [scrollTo]);
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  marks.forEach(([start, end], i) => {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <mark key={start} ref={i === 0 ? first : undefined} className="rounded-[2px] bg-accent-wash box-decoration-clone text-ink">
        {text.slice(start, end)}
      </mark>,
    );
    cursor = end;
  });
  parts.push(text.slice(cursor));
  return <div className="mx-auto max-w-[68ch] whitespace-pre-wrap font-serif text-[14px] leading-[23px] text-ink">{parts}</div>;
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-1 items-center justify-center font-serif text-[17px] text-ink">{children}</div>;
}
