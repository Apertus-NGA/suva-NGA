import type { InputHTMLAttributes } from "react";
import { cn } from "./cn";

type Props = InputHTMLAttributes<HTMLInputElement> & { label: string };

/** Labelled input used inside filter panels. */
export function Field({ label, className, ...input }: Props) {
  return (
    <label className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-faint">{label}</span>
      <input
        {...input}
        className={cn(
          "h-8 w-full rounded-md border border-line bg-surface px-2 text-[13px] text-ink tabular-nums",
          "placeholder:text-faint hover:border-line-strong focus:border-ink focus:outline-none",
          className,
        )}
      />
    </label>
  );
}
