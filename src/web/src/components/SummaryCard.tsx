import { Check, ChevronDown, LoaderCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { RefineCheck, Summary, SummaryLanguage, SummarySentence } from "../lib/api";
import { useI18n, type Key } from "../lib/i18n";
import { confidenceOf, hasTrace, isRemoved, locate, pieces, sentencesOf } from "../lib/provenance";
import { Popover } from "./ui/Popover";
import { cn } from "./ui/cn";

type Props = {
  language: SummaryLanguage;
  summary: Summary | null;
  /** The ruling text the sources point into. */
  text: string | null;
  revisions: string[];
  /** "writing": Apertus is at work (up to a minute); "saving": a quick change is being stored. */
  busy: false | "writing" | "saving";
  /** The sentence whose sources are highlighted in the ruling text (hovered, else selected), and the selected one. */
  active: number | null;
  selected: number | null;
  onHover: (sentence: number | null) => void;
  onSelect: (sentence: number | null) => void;
  onConfirm: () => void;
  onUnconfirm: () => void;
  onSave: (body: string, confirm: boolean) => void;
  onRevise: (reason: string, note: string) => void;
};

const NEEDS_NOTE = ["key_point", "wrong_statement", "other"];
const BADGE = "inline-flex h-[22px] shrink-0 items-center gap-1 rounded-full px-2 font-medium";

/**
 * One language of a ruling's summary: read it sentence by sentence against the ruling, edit it, ask Apertus for a
 * defined change, validate it. Selecting a sentence shows its considerations and marks its source in the ruling.
 */
export function SummaryCard({ language, summary, text, revisions, busy, active, selected, onHover, onSelect, onConfirm, onUnconfirm, onSave, onRevise }: Props) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<string | null>(null); // not null while editing
  useEffect(() => setDraft(null), [summary?.id]);
  const editing = draft !== null;

  const validated = !!summary && (summary.validated ?? summary.confirmed) === true;
  const state = !summary ? null : validated ? "summary.gold" : summary.origin === "expert" ? "summary.edited" : "summary.draft";
  const sentences = sentencesOf(summary);
  const confidence = confidenceOf(summary);
  const mode = summary?.mode?.toLowerCase();
  const problems = summary?.problems ?? [];
  // With the sentence view, the sentence-level findings of the trace are shown there, not twice.
  const checks = (summary?.checks ?? [])
    .map((c) => (sentences.length > 0 ? { ...c, findings: (c.findings ?? []).filter((f) => !f.text) } : c))
    .filter((c) => sentences.length === 0 || c.step !== "verify" || c.findings.length > 0 || !!c.note);

  return (
    <section className="rounded-xl bg-surface">
      <header className="flex h-12 items-center justify-between gap-3 border-b border-line px-5">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="text-[13px] font-medium text-ink">{t(`summary.${language}` as Key)}</h3>
          {(mode === "live" || mode === "replay") && (
            <span title={t(`summary.mode.${mode}.hint` as Key)} className="rounded border border-line-strong px-1 text-[10px] font-medium uppercase leading-4 tracking-[0.06em] text-muted">
              {t(`summary.mode.${mode}` as Key)}
            </span>
          )}
        </div>
        {summary && state && (
          <span className="flex min-w-0 items-center gap-2 text-[12px] text-faint">
            <span className="shrink-0">{t("summary.version", { n: summary.version })}</span>
            {summary.needs_review === true && !validated && (
              <span title={t("summary.needsReview.hint")} className={cn(BADGE, "border border-line text-muted")}>
                {t("summary.needsReview")}
              </span>
            )}
            <span
              title={validated ? t("summary.gold.hint") : undefined}
              className={cn(BADGE, validated ? "bg-accent-wash text-accent-text" : "border border-line-strong text-ink")}
            >
              {validated && <Check size={12} strokeWidth={2.5} aria-hidden />}
              {t(state as Key)}
            </span>
          </span>
        )}
      </header>

      <div className="px-5 py-4">
        {summary && !editing && confidence && (
          <div className="mb-3 flex items-center gap-2.5 text-[12px]" title={[t("summary.confidence.hint"), ...confidence.reasons].join("\n")}>
            <span className="text-faint">{t("summary.confidence")}</span>
            <span className="h-[3px] w-[96px] overflow-hidden rounded-full bg-line" aria-hidden>
              <span className="block h-full rounded-full bg-ink" style={{ width: `${confidence.score}%` }} />
            </span>
            <span className="tabular-nums text-muted">
              {confidence.score} · {t(`summary.level.${confidence.level}` as Key)}
            </span>
          </div>
        )}
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(22, Math.max(8, Math.ceil(draft.length / 70)))}
            className="w-full resize-y rounded-md border border-line-strong bg-surface p-3 font-serif text-[14px] leading-[23px] text-ink focus:border-ink focus:outline-none"
          />
        ) : summary && sentences.length > 0 ? (
          <Traced body={summary.body} sentences={sentences} text={text} active={active} selected={selected} onHover={onHover} onSelect={onSelect} />
        ) : summary ? (
          <p className="whitespace-pre-wrap font-serif text-[14px] leading-[23px] text-ink">{summary.body}</p>
        ) : (
          <p className="text-[13px] text-faint">{t("summary.empty")}</p>
        )}
        {summary && !editing && problems.length > 0 && (
          <p className="mt-3 text-[12px] leading-[18px] text-muted">
            {t("summary.checker")}: {problems.join(" · ")}
          </p>
        )}
        {summary && !editing && checks.length > 0 && <Checks checks={checks} />}
      </div>

      {summary && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          {busy ? (
            <Working writing={busy === "writing"} />
          ) : editing ? (
            <>
              <Button primary onClick={() => onSave(draft, true)}>
                <Check size={14} strokeWidth={2} aria-hidden />
                {t("summary.saveConfirm")}
              </Button>
              <Button onClick={() => onSave(draft, false)}>{t("summary.save")}</Button>
              <Button quiet onClick={() => setDraft(null)}>
                {t("summary.cancel")}
              </Button>
            </>
          ) : (
            <>
              {validated ? (
                <Button onClick={onUnconfirm}>{t("summary.unconfirm")}</Button>
              ) : (
                <Button primary onClick={onConfirm}>
                  <Check size={14} strokeWidth={2} aria-hidden />
                  {t("summary.confirm")}
                </Button>
              )}
              <Button onClick={() => setDraft(summary.body)}>{t("summary.edit")}</Button>
              <ReviseMenu revisions={revisions} onRevise={onRevise} />
            </>
          )}
        </footer>
      )}
    </section>
  );
}

/** A spinner with what is going on; while Apertus writes, the seconds so far, since a summary can take a minute. */
export function Working({ writing }: { writing: boolean }) {
  const { t } = useI18n();
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <span className="flex h-8 items-center gap-2 text-[13px] text-muted" role="status">
      <LoaderCircle size={14} strokeWidth={2} className="animate-spin" aria-hidden />
      {t(writing ? "page.generating" : "page.saving")}
      {writing && <span className="tabular-nums text-faint">{t("page.generatingHint", { s: seconds })}</span>}
    </span>
  );
}

type TracedProps = {
  body: string;
  sentences: SummarySentence[];
  text: string | null;
  active: number | null;
  selected: number | null;
  onHover: (sentence: number | null) => void;
  onSelect: (sentence: number | null) => void;
};

/** The summary with each sentence selectable, and under it what the selected sentence rests on. */
function Traced({ body, sentences, text, active, selected, onHover, onSelect }: TracedProps) {
  const { t } = useI18n();
  const removed = sentences.filter(isRemoved);
  const shown = active !== null ? sentences[active] : undefined;
  const sources = shown?.sources ?? [];
  // Passages that cannot be marked in the text shown are quoted here instead.
  const unlocated = sources.filter((source) => source.quote && !(text && locate(text, source)));
  const notes = [
    shown?.status === "repaired" ? t("summary.trace.repaired") : null,
    shown && shown.accepted === false ? t("summary.trace.unverified") : null,
    shown && sources.length === 0 ? t("summary.trace.noSource") : null,
  ].filter(Boolean);

  return (
    <>
      <p className="whitespace-pre-wrap font-serif text-[14px] leading-[23px] text-ink">
        {pieces(body, sentences).map((piece, i) => {
          const index = piece.sentence;
          if (index === null || !hasTrace(sentences[index])) return <span key={i}>{piece.text}</span>;
          const toggle = () => onSelect(selected === index ? null : index);
          return (
            <span
              key={i}
              role="button"
              tabIndex={0}
              aria-pressed={selected === index}
              onMouseEnter={() => onHover(index)}
              onMouseLeave={() => onHover(null)}
              onClick={toggle}
              onKeyDown={(e) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                e.preventDefault();
                toggle();
              }}
              className={cn(
                "cursor-pointer rounded-[3px] box-decoration-clone transition-colors",
                index === active ? "bg-accent-wash" : "hover:bg-wash",
                index === selected && "underline decoration-accent decoration-1 underline-offset-4",
              )}
            >
              {piece.text}
            </span>
          );
        })}
      </p>

      <div className="mt-3 text-[12px] leading-[18px]" aria-live="polite">
        {!shown ? (
          <p className="flex min-h-[22px] items-center text-faint">{t("summary.trace.hint")}</p>
        ) : (
          <>
            <div className="flex min-h-[22px] flex-wrap items-center gap-x-2 gap-y-1 text-muted">
              {(shown.considerations ?? []).map((label) => (
                <span key={label} className="inline-flex h-[22px] items-center rounded-full border border-line-strong px-2 font-medium tabular-nums text-ink">
                  {label}
                </span>
              ))}
              {notes.length > 0 && <span>{notes.join(" · ")}</span>}
            </div>
            {unlocated.length > 0 && (
              <div className="mt-2 rounded-md border border-line px-3 py-2">
                <div className="text-faint">{t("summary.trace.notLocated")}</div>
                {unlocated.map((source, i) => (
                  <blockquote key={i} className="mt-1 font-serif text-[13px] leading-5 text-ink">
                    “{source.quote}”
                  </blockquote>
                ))}
              </div>
            )}
            {(shown.why_not ?? []).map((reason, i) => (
              <p key={i} className="mt-1 text-muted">
                {reason}
              </p>
            ))}
          </>
        )}
      </div>

      {removed.length > 0 && (
        <details className="mt-2 text-[12px] leading-[18px] text-muted">
          <summary className="cursor-pointer select-none">{t("summary.removed", { n: removed.length })}</summary>
          <ul className="mt-2 space-y-2">
            {removed.map((sentence, i) => (
              <li key={i}>
                <span className="font-serif text-[13px] leading-5 text-ink line-through decoration-line-strong">{sentence.text}</span>
                {(sentence.why_not ?? []).map((reason, j) => (
                  <span key={j} className="block">
                    {reason}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

/** The defined changes an expert can ask of Apertus. Each request is stored with its reason. */
function ReviseMenu({ revisions, onRevise }: { revisions: string[]; onRevise: (reason: string, note: string) => void }) {
  const { t } = useI18n();
  const [picked, setPicked] = useState<string | null>(null);
  const [note, setNote] = useState("");
  return (
    <Popover
      width={320}
      trigger={
        <button type="button" className="flex h-8 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-3 text-[13px] text-ink hover:border-ink/40">
          {t("summary.revise")}
          <ChevronDown size={14} strokeWidth={1.75} className="text-faint" aria-hidden />
        </button>
      }
    >
      <ul className="p-1">
        {revisions.map((reason) => (
          <li key={reason}>
            <button
              type="button"
              onClick={() => (NEEDS_NOTE.includes(reason) ? setPicked(reason) : onRevise(reason, ""))}
              className={cn("flex h-8 w-full items-center rounded-md px-2 text-left text-[13px] text-ink hover:bg-wash", picked === reason && "bg-wash font-medium")}
            >
              {t(`revise.${reason}` as Key)}
            </button>
          </li>
        ))}
      </ul>
      {picked && (
        <div className="flex flex-col gap-2 border-t border-line p-3">
          <textarea
            autoFocus
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("summary.note")}
            rows={3}
            className="w-full resize-none rounded-md border border-line-strong p-2 text-[13px] text-ink placeholder:text-faint focus:border-ink focus:outline-none"
          />
          <Button primary disabled={!note.trim()} onClick={() => onRevise(picked, note.trim())}>
            {t("summary.send")}
          </Button>
        </div>
      )}
    </Popover>
  );
}

export function Button({ primary = false, quiet = false, disabled = false, onClick, children }: { primary?: boolean; quiet?: boolean; disabled?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        primary ? "bg-ink text-white hover:bg-ink/85" : quiet ? "text-muted hover:text-ink" : "border border-line-strong bg-surface text-ink hover:border-ink/40",
      )}
    >
      {children}
    </button>
  );
}


const MARK: Record<RefineCheck["status"], string> = { passed: "✓", corrected: "✎", needs_review: "!", skipped: "–" };

/** The refine trace: each step, what it found, what it changed and on which passage of the ruling. */
function Checks({ checks }: { checks: RefineCheck[] }) {
  const { t } = useI18n();
  const changed = checks.filter((c) => c.status === "corrected").length;
  const review = checks.filter((c) => c.status === "needs_review").length;
  return (
    <details className="mt-3 text-[12px] leading-[18px] text-muted">
      <summary className="cursor-pointer select-none">
        {t("summary.checks")}: {changed} {t("summary.checks.corrected")} · {review} {t("summary.checks.review")}
      </summary>
      <ul className="mt-2 space-y-1">
        {checks.map((c) => (
          <li key={c.step}>
            <span className="font-medium text-ink">
              {MARK[c.status]} {c.step}
            </span>
            {c.findings.map((f, i) => (
              <div key={i} className="ml-4">
                {f.accepted ? "✎ " : "· "}
                {f.reason}
                {f.evidence && ` (${f.evidence})`}
                {f.quote && <span className="block italic">“{f.quote}”</span>}
                {f.why_not && <span className="block">{f.why_not}</span>}
              </div>
            ))}
            {c.note && <div className="ml-4">{c.note}</div>}
          </li>
        ))}
      </ul>
    </details>
  );
}
