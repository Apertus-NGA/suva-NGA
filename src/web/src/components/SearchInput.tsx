import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";

type Props = { value: string; onChange: (value: string) => void; placeholder: string; clearLabel: string };

/** Search box. Typing is passed on after a short pause, so the list does not reload on every key. */
export function SearchInput({ value, onChange, placeholder, clearLabel }: Props) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (draft === value) return;
    const timer = window.setTimeout(() => onChange(draft), 250);
    return () => window.clearTimeout(timer);
  }, [draft, value, onChange]);

  return (
    <div className="relative w-full max-w-[300px]">
      <Search size={15} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" aria-hidden />
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="h-8 w-full rounded-md border border-transparent bg-surface pl-9 pr-8 text-[13px] placeholder:text-faint hover:border-line-strong focus:border-ink focus:outline-none"
      />
      {draft && (
        <button
          type="button"
          onClick={() => { setDraft(""); onChange(""); }}
          aria-label={clearLabel}
          className="absolute right-2 top-1/2 flex size-5 -translate-y-1/2 items-center justify-center rounded text-faint hover:bg-wash hover:text-ink"
        >
          <X size={13} strokeWidth={2} aria-hidden />
        </button>
      )}
    </div>
  );
}
