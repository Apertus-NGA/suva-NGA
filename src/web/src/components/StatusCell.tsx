import { Check, Undo2, X } from "lucide-react";
import type { ReactNode } from "react";
import type { RelevanceAction, Ruling, Status } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { cn } from "./ui/cn";

type Props = { ruling: Ruling; onDecide: (action: RelevanceAction) => void };

/** How each status looks. Orange is kept for what an expert confirmed: the gold label. */
const STYLE: Record<Status, string> = {
  expert_confirmed: "bg-accent-wash text-accent-text",
  ai_relevant: "border border-line-strong text-ink",
  potentially_relevant: "text-muted",
  not_relevant: "text-muted",
  not_assessed: "text-faint",
};

/**
 * A ruling's status, and on hover the expert's actions: confirm (gold label), not relevant, or undo.
 * Any ruling can be decided either way; a decision made here is taken back with undo.
 */
export function StatusCell({ ruling, onDecide }: Props) {
  const { t, tx } = useI18n();
  const { status } = ruling;
  const pill = status === "expert_confirmed" || status === "ai_relevant";
  const decidedHere = ruling.label_basis === "expert_override";
  return (
    // Clicks on the decision buttons must not open the ruling page of the row.
    <div className="flex items-center justify-between gap-2" onClick={(e) => e.stopPropagation()}>
      <span title={tx("statusHint", status)} className={cn("truncate text-[12px]", pill && "inline-flex h-[22px] shrink-0 whitespace-nowrap items-center gap-1 rounded-full px-2 font-medium", STYLE[status])}>
        {status === "expert_confirmed" && <Check size={12} strokeWidth={2.5} aria-hidden />}
        {tx("status", status)}
      </span>
      <span className="flex shrink-0 gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        {decidedHere ? (
          <Action label={t("action.reopen")} onClick={() => onDecide("reopen")}>
            <Undo2 size={14} strokeWidth={1.75} aria-hidden />
          </Action>
        ) : (
          <>
            {status !== "expert_confirmed" && (
              <Action label={t("action.confirm")} onClick={() => onDecide("confirm_relevant")} gold>
                <Check size={14} strokeWidth={2} aria-hidden />
              </Action>
            )}
            {status !== "not_relevant" && (
              <Action label={t("action.reject")} onClick={() => onDecide("mark_not_relevant")}>
                <X size={14} strokeWidth={2} aria-hidden />
              </Action>
            )}
          </>
        )}
      </span>
    </div>
  );
}

function Action({ label, onClick, gold = false, children }: { label: string; onClick: () => void; gold?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={cn(
        "flex size-7 items-center justify-center rounded-md border border-line-strong bg-surface text-ink transition-colors",
        gold ? "hover:border-accent hover:bg-accent-wash hover:text-accent-text" : "hover:border-ink/40",
      )}
    >
      {children}
    </button>
  );
}
