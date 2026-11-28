import { LANGS, useI18n } from "../lib/i18n";
import { cn } from "./ui/cn";

/** Interface language, for the dark sidebar. Rulings and summaries keep their own language. */
export function LanguageSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div role="radiogroup" aria-label={t("app.language")} className="flex gap-0.5">
      {LANGS.map((code) => (
        <button
          key={code}
          type="button"
          role="radio"
          aria-checked={code === lang}
          onClick={() => setLang(code)}
          className={cn(
            "h-7 rounded-md px-2 text-[12px] font-medium uppercase tracking-[0.04em] transition-colors focus-visible:outline-night-text",
            code === lang ? "bg-night-raised text-night-text" : "text-night-muted hover:text-night-text",
          )}
        >
          {code}
        </button>
      ))}
    </div>
  );
}
