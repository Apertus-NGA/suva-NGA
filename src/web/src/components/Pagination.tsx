import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useI18n } from "../lib/i18n";

type Props = { page: number; pageSize: number; total: number; onPage: (page: number) => void };

export function Pagination({ page, pageSize, total, onPage }: Props) {
  const { t, formatNumber } = useI18n();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  return (
    <div className="flex h-11 shrink-0 items-center justify-between border-t border-line px-5 text-[12px] text-muted">
      <span className="tabular-nums">
        {t("page.range", { first: formatNumber(first), last: formatNumber(last), total: formatNumber(total) })}
      </span>
      <div className="flex items-center gap-1">
        <PageButton label={t("page.previous")} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft size={16} strokeWidth={1.75} aria-hidden />
        </PageButton>
        <span className="px-2 tabular-nums">
          {t("page.of", { page: formatNumber(page), pages: formatNumber(pages) })}
        </span>
        <PageButton label={t("page.next")} disabled={page >= pages} onClick={() => onPage(page + 1)}>
          <ChevronRight size={16} strokeWidth={1.75} aria-hidden />
        </PageButton>
      </div>
    </div>
  );
}

function PageButton({ label, disabled, onClick, children }: { label: string; disabled: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded-md text-ink hover:bg-wash disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}
