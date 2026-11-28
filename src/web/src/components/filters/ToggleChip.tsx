import type { ReactNode } from "react";
import { cn } from "../ui/cn";

type Props = { pressed: boolean; onChange: (pressed: boolean) => void; icon?: ReactNode; children: string };

/** An on/off filter with no panel. */
export function ToggleChip({ pressed, onChange, icon, children }: Props) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onChange(!pressed)}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded-md border px-2 text-[12px] transition-colors",
        pressed ? "border-ink bg-ink font-medium text-white" : "border-line-strong/70 bg-surface text-ink hover:border-line-strong",
      )}
    >
      {icon}
      {children}
    </button>
  );
}
