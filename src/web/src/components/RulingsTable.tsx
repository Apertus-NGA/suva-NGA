import { ArrowDown, ArrowUp, Star } from "lucide-react";
import type { ReactNode } from "react";
import type { RelevanceAction, Ruling } from "../lib/api";
import type { Order, SortKey } from "../lib/filters";
import { areaLabel } from "../lib/areas";
import { useI18n, type I18n, type Key, type Lang } from "../lib/i18n";
import { StatusCell } from "./StatusCell";
import { Score } from "./Score";
import { cn } from "./ui/cn";

type Props = {
  rulings: Ruling[];
  sort: SortKey;
  order: Order;
  onSort: (sort: SortKey, order: Order) => void;
  onDecide: (ruling: Ruling, action: RelevanceAction) => void;
  onOpen: (ruling: Ruling) => void;
};

/** `wide`: only shown on wide windows (1280px and up), so the subject keeps its room on smaller ones. */
type Column = { title: Key; width?: number; sort?: SortKey; firstOrder?: Order; wide?: boolean };

const COLUMNS: Column[] = [
  { title: "col.score", width: 96, sort: "score", firstOrder: "desc" },
  { title: "col.docket", width: 148, sort: "docket", firstOrder: "asc" },
  { title: "col.subject", sort: "area", firstOrder: "asc" },
  { title: "col.decided", width: 108, sort: "decision_date", firstOrder: "desc" },
  { title: "col.published", width: 108, sort: "publication_date", firstOrder: "desc" },
  { title: "col.outcome", width: 136, wide: true },
  { title: "col.status", width: 280, sort: "status", firstOrder: "desc" },
];

export function RulingsTable({ rulings, sort, order, onSort, onDecide, onOpen }: Props) {
  const { t, tx, lang, formatDate } = useI18n();
  return (
    <table className="w-full table-fixed border-separate border-spacing-0">
      <colgroup>
        {COLUMNS.map((column) => (
          <col key={column.title} className={column.wide ? "hidden xl:table-column" : undefined} style={column.width ? { width: column.width } : undefined} />
        ))}
      </colgroup>
      <thead>
        <tr>
          {COLUMNS.map((column, i) => {
            const active = column.sort === sort;
            return (
              <th
                key={column.title}
                scope="col"
                aria-sort={active ? (order === "asc" ? "ascending" : "descending") : undefined}
                className={cn(
                  "sticky top-0 z-10 h-10 whitespace-nowrap border-b border-line bg-surface text-left text-[12px] font-normal text-faint",
                  i === 0 ? "pl-5 pr-3" : "px-3",
                  column.wide && "hidden xl:table-cell",
                )}
              >
                {column.sort ? (
                  <button
                    type="button"
                    onClick={() => onSort(column.sort!, active ? (order === "asc" ? "desc" : "asc") : column.firstOrder!)}
                    className={cn("-mx-1 flex h-6 items-center gap-1 rounded px-1 hover:text-ink", active && "font-medium text-ink")}
                  >
                    {t(column.title)}
                    {active && (order === "asc" ? <ArrowUp size={12} strokeWidth={2} aria-hidden /> : <ArrowDown size={12} strokeWidth={2} aria-hidden />)}
                  </button>
                ) : (
                  t(column.title)
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rulings.map((ruling) => (
          <tr
            key={ruling.id}
            className="group cursor-pointer"
            tabIndex={0}
            onClick={() => onOpen(ruling)}
            onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && onOpen(ruling)}
          >
            <Cell first>
              <Score score={ruling.score} relevant={ruling.predicted_relevant} />
            </Cell>
            <Cell>
              <span className="flex items-center gap-1.5">
                <span className="font-medium tabular-nums text-ink">{ruling.docket}</span>
                {ruling.starred && (
                  <span title={t("ruling.starred")} className="text-ink">
                    <Star size={12} strokeWidth={1.75} fill="currentColor" aria-label={t("ruling.starred")} />
                  </span>
                )}
              </span>
            </Cell>
            <Cell>
              <div className="flex items-center gap-2">
                <span className="truncate text-ink" title={ruling.subject ?? undefined}>
                  {ruling.title ?? (areaLabel(ruling.area, lang) || "–")}
                </span>
              </div>
              <div className="truncate text-[12px] leading-[18px] text-faint">{meta(ruling, tx, lang)}</div>
            </Cell>
            <Cell className="tabular-nums text-muted">{formatDate(ruling.decision_date)}</Cell>
            <Cell className="tabular-nums text-muted">{formatDate(ruling.publication_date)}</Cell>
            <Cell className="hidden truncate text-muted xl:table-cell">{tx("outcome", ruling.outcome)}</Cell>
            <Cell>
              <StatusCell ruling={ruling} onDecide={(action) => onDecide(ruling, action)} />
            </Cell>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Second line under the title: the area of law (unless it already is the title) and the language. */
function meta(ruling: Ruling, tx: I18n["tx"], lang: Lang): string {
  const parts: string[] = [];
  if (ruling.area && ruling.title) parts.push(areaLabel(ruling.area, lang));
  if (ruling.language) parts.push(tx("language", ruling.language));
  return parts.join(" · ");
}

function Cell({ children, className, first = false }: { children: ReactNode; className?: string; first?: boolean }) {
  return (
    <td className={cn("h-[54px] border-b border-line align-middle group-hover:bg-wash/70", first ? "pl-5 pr-3" : "px-3", className)}>
      {children}
    </td>
  );
}
