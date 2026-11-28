import { LoaderCircle, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { SourceStatus, UpdatesStatus } from "../lib/api";
import { useI18n, type Key } from "../lib/i18n";
import { Field } from "./ui/Field";
import { Popover } from "./ui/Popover";
import { cn } from "./ui/cn";

type Range = { published_from: string; published_to: string };
type Props = {
  status: UpdatesStatus | null;
  failedToStart: boolean;
  onStart: (range?: Range) => void;
  onShowAdded: () => void;
};

const SOURCES: Array<{ key: "bger" | "daily" | "mirror"; label: Key }> = [
  { key: "bger", label: "update.source.bger" },
  { key: "daily", label: "update.source.daily" },
  { key: "mirror", label: "update.source.mirror" },
];

/** Brings newly published rulings into the list: since the last update, or for chosen publication dates. */
export function UpdateControl({ status, failedToStart, onStart, onShowAdded }: Props) {
  const { t, formatDate } = useI18n();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const running = status?.running ?? false;
  const last = status?.last ?? null;
  const next = status?.next_range ?? null;
  const rangeReady = from !== "" && to !== "" && from <= to;

  return (
    <div className="flex shrink-0 items-center gap-3">
      {last?.finished_at && !running && (
        <span className="text-[12px] tabular-nums text-faint">{t("update.lastUpdated", { date: formatDate(last.finished_at.slice(0, 10)) })}</span>
      )}
      <Popover
        width={340}
        align="end"
        trigger={
          <button
            type="button"
            className="flex h-8 items-center gap-1.5 rounded-md bg-ink px-3 text-[13px] font-medium text-white hover:bg-ink/85"
          >
            {running ? (
              <LoaderCircle size={14} strokeWidth={2} className="animate-spin" aria-hidden />
            ) : (
              <RefreshCw size={14} strokeWidth={1.75} aria-hidden />
            )}
            {t(running ? "update.running" : "update.button")}
          </button>
        }
      >
        <Section title={t("update.sinceLast")}>
          {next && <p className="tabular-nums text-muted">{t("update.range", { from: formatDate(next.published_from), to: formatDate(next.published_to) })}</p>}
          <ActionButton disabled={running || !next} onClick={() => onStart()}>
            {t("update.now")}
          </ActionButton>
        </Section>

        <Section title={t("update.choose")} divided>
          <div className="flex gap-2">
            <Field label={t("filter.from")} type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
            <Field label={t("filter.to")} type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
          </div>
          <p className="text-[12px] text-faint">{t("update.chooseHint")}</p>
          <ActionButton secondary disabled={running || !rangeReady} onClick={() => onStart({ published_from: from, published_to: to })}>
            {t("update.add")}
          </ActionButton>
        </Section>

        {(last || failedToStart || status?.last_error) && (
          <Section title={t("update.lastRun")} divided>
            {failedToStart || status?.last_error || last?.status === "failed" ? (
              <p className="text-ink">{t("update.failed")}</p>
            ) : (
              last && (
                <>
                  <p className="tabular-nums text-ink">
                    {t("update.result", { added: last.new_rulings ?? 0, known: last.known_rulings ?? 0 })}
                    <span className="text-faint"> · {formatDate(last.published_from)} – {formatDate(last.published_to)}</span>
                  </p>
                  <ul className="flex flex-col gap-0.5">
                    {SOURCES.map((source) => (
                      <SourceLine key={source.key} name={t(source.label)} status={last.sources[source.key]} />
                    ))}
                  </ul>
                  {!!last.not_confirmed_by_bger && <p className="text-muted">{t("update.unconfirmed", { n: last.not_confirmed_by_bger })}</p>}
                </>
              )
            )}
            {!!status?.ingested_rulings && (
              <button type="button" onClick={onShowAdded} className="self-start text-[13px] font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
                {t("update.showNew")}
              </button>
            )}
          </Section>
        )}
        <p className="border-t border-line px-4 py-3 text-[12px] leading-[18px] text-faint">{t("update.safe")}</p>
      </Popover>
    </div>
  );
}

function Section({ title, divided = false, children }: { title: string; divided?: boolean; children: React.ReactNode }) {
  return (
    <div className={cn("flex flex-col gap-2.5 px-4 py-3.5 text-[13px]", divided && "border-t border-line")}>
      <div className="text-[12px] text-faint">{title}</div>
      {children}
    </div>
  );
}

function ActionButton({ secondary = false, disabled, onClick, children }: { secondary?: boolean; disabled: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "h-8 rounded-md px-3 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        secondary ? "border border-line-strong bg-surface text-ink hover:border-ink/40" : "bg-ink text-white hover:bg-ink/85",
      )}
    >
      {children}
    </button>
  );
}

function SourceLine({ name, status }: { name: string; status: SourceStatus }) {
  const { t } = useI18n();
  const ok = status === "complete";
  return (
    <li className="flex items-center gap-2 text-muted">
      <span className={cn("size-1.5 rounded-full", ok ? "bg-ink" : "bg-line-strong")} aria-hidden />
      <span>{name}</span>
      <span className="ml-auto text-faint">{status ? t(`update.status.${status}` as Key) : "–"}</span>
    </li>
  );
}
