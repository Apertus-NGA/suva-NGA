import { Check, ChevronDown, LoaderCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { RefineCheck, Summary, SummaryLanguage } from "../lib/api";
import { useI18n, type Key } from "../lib/i18n";
import { Popover } from "./ui/Popover";
import { cn } from "./ui/cn";

type Props = {
  language: SummaryLanguage;
  summary: Summary | null;
  revisions: string[];
  busy: boolean;
  onConfirm: () => void;
  onUnconfirm: () => void;
  onSave: (body: string, confirm: boolean) => void;
  onRevise: (reason: string, note: string) => void;
};

const NEEDS_NOTE = ["key_point", "wrong_statement", "other"];

/** One language of a ruling's summary: read it, edit it, ask Apertus for a defined change, confirm it as gold. */
export function SummaryCard({ language, summary, revisions, busy, onConfirm, onUnconfirm, onSave, onRevise }: Props) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<string | null>(null); // not null while editing
  useEffect(() => setDraft(null), [summary?.id]);
  const editing = draft !== null;

  const state = !summary ? null : summary.confirmed ? "summary.gold" : summary.origin === "expert" ? "summary.edited" : "summary.draft";

  return (
    <section className="rounded-xl bg-surface">
      <header className="flex h-12 items-center justify-between gap-3 border-b border-line px-5">
        <h3 className="text-[13px] font-medium text-ink">{t(`summary.${language}` as Key)}</h3>
        {summary && state && (
          <span className="flex items-center gap-2 text-[12px] text-faint">
            <span>{t("summary.version", { n: summary.version })}</span>
            <span
              className={cn(
                "inline-flex h-[22px] items-center gap-1 rounded-full px-2 font-medium",
                summary.confirmed ? "bg-accent-wash text-accent-text" : "border border-line-strong text-ink",
              )}
            >
              {summary.confirmed && <Check size={12} strokeWidth={2.5} aria-hidden />}
              {t(state as Key)}
            </span>
          </span>
        )}
      </header>

      <div className="px-5 py-4">
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={Math.min(22, Math.max(8, Math.ceil(draft.length / 70)))}
            className="w-full resize-y rounded-md border border-line-strong bg-surface p-3 font-serif text-[14px] leading-[23px] text-ink focus:border-ink focus:outline-none"
          />
        ) : summary ? (
          <p className="whitespace-pre-wrap font-serif text-[14px] leading-[23px] text-ink">{summary.body}</p>
        ) : (
          <p className="text-[13px] text-faint">{t("summary.empty")}</p>
        )}
        {summary && !editing && summary.problems.length > 0 && (
          <p className="mt-3 text-[12px] leading-[18px] text-muted">
            {t("summary.checker")}: {summary.problems.join(" · ")}
          </p>
        )}
        {summary && !editing && (summary.checks?.length ?? 0) > 0 && <Checks checks={summary.checks} />}
      </div>

      {summary && (
        <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          {busy ? (
            <span className="flex h-8 items-center gap-2 text-[13px] text-muted">
              <LoaderCircle size={14} strokeWidth={2} className="animate-spin" aria-hidden />
              {t("page.generating")}
            </span>
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
              {summary.confirmed ? (
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
