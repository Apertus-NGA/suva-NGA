// Interface language: English (default), German, French.
//
// RULE FOR NEW FEATURES: no user-visible text in components. Add a key to `en` below, translate it in
// `de` and `fr` (TypeScript refuses to build if one is missing), and read it with `t("key")`.
// Text that comes from the database (rulings, summaries, subject lines) is never translated.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Lang = "en" | "de" | "fr";
export const LANGS: Lang[] = ["en", "de", "fr"];

const en = {
  "app.name": "Case law",
  "app.title": "Federal Supreme Court rulings",
  "app.count": "{n} rulings",
  "app.countOf": "{n} of {total} rulings",
  "app.search": "Search case number or subject",
  "app.clearSearch": "Clear search",
  "app.loadError": "The rulings could not be loaded.",
  "app.retry": "Try again",
  "app.empty": "No rulings match these filters.",
  "app.resetFilters": "Reset filters",
  "app.placeholderScores": "Scores are placeholders until triage has run.",
  "app.language": "Language",

  "views.title": "Views",
  "views.all": "All rulings",
  "views.core": "Suva core areas",
  "views.predicted": "Rated relevant by the system",
  "views.june": "June 2026 by score",
  "views.labelled": "Marked relevant by Suva",

  "filter.decided": "Decision date",
  "filter.published": "Publication date",
  "filter.area": "Area of law",
  "filter.area.core": "Suva core areas",
  "filter.area.all": "All areas of law",
  "filter.area.search": "Search area of law",
  "filter.division": "Division",
  "filter.language": "Language",
  "filter.outcome": "Outcome",
  "filter.label": "Suva label",
  "filter.assessment": "Assessment",
  "filter.assessment.decision": "System decision",
  "filter.assessment.all": "All",
  "filter.assessment.scoreFrom": "Score from",
  "filter.assessment.scoreTo": "Score to",
  "filter.starred": "Marked for publication",
  "filter.reset": "Reset",
  "filter.remove": "{label}: remove filter",
  "filter.search": "Search",
  "filter.noMatches": "No matches",
  "filter.from": "From",
  "filter.to": "To",
  "filter.since": "from {date}",
  "filter.until": "until {date}",
  "filter.june2026": "June 2026",

  "col.score": "Score",
  "col.docket": "Case number",
  "col.subject": "Subject",
  "col.decided": "Decided",
  "col.published": "Published",
  "col.outcome": "Outcome",
  "col.label": "Suva label",

  "ruling.starred": "Marked for publication in the official collection",
  "score.relevant": "Rated relevant by the system",
  "score.notRelevant": "Rated not relevant by the system",

  "page.range": "{first}–{last} of {total}",
  "page.of": "Page {page} of {pages}",
  "page.previous": "Previous page",
  "page.next": "Next page",

  "topic.UV": "Accident insurance",
  "topic.MV": "Military insurance",
  "topic.IV": "Invalidity insurance",

  "language.de": "German",
  "language.fr": "French",
  "language.it": "Italian",

  "outcome.dismissed": "Dismissed",
  "outcome.inadmissible": "Inadmissible",
  "outcome.approved": "Upheld",
  "outcome.partial_approval": "Partly upheld",
  "outcome.moot": "Moot",
  "outcome.consolidated": "Joined",

  "label.relevant": "Relevant",
  "label.not_relevant": "Not relevant",
  "label.unknown": "Open",
};

export type Key = keyof typeof en;
type Messages = Record<Key, string>;

const de: Messages = {
  "app.name": "Rechtsprechung",
  "app.title": "Entscheide des Bundesgerichts",
  "app.count": "{n} Entscheide",
  "app.countOf": "{n} von {total} Entscheiden",
  "app.search": "Geschäftsnummer oder Betreff suchen",
  "app.clearSearch": "Suche leeren",
  "app.loadError": "Die Entscheide konnten nicht geladen werden.",
  "app.retry": "Erneut versuchen",
  "app.empty": "Keine Entscheide für diese Filter.",
  "app.resetFilters": "Filter zurücksetzen",
  "app.placeholderScores": "Scores sind Platzhalter, bis die Triage läuft.",
  "app.language": "Sprache",

  "views.title": "Ansichten",
  "views.all": "Alle Entscheide",
  "views.core": "Kernbereiche der Suva",
  "views.predicted": "Vom System als relevant bewertet",
  "views.june": "Juni 2026 nach Score",
  "views.labelled": "Von der Suva als relevant markiert",

  "filter.decided": "Entscheiddatum",
  "filter.published": "Publikationsdatum",
  "filter.area": "Rechtsgebiet",
  "filter.area.core": "Kernbereiche der Suva",
  "filter.area.all": "Alle Rechtsgebiete",
  "filter.area.search": "Rechtsgebiet suchen",
  "filter.division": "Abteilung",
  "filter.language": "Sprache",
  "filter.outcome": "Ausgang",
  "filter.label": "Suva-Label",
  "filter.assessment": "Bewertung",
  "filter.assessment.decision": "Entscheid des Systems",
  "filter.assessment.all": "Alle",
  "filter.assessment.scoreFrom": "Score von",
  "filter.assessment.scoreTo": "Score bis",
  "filter.starred": "Zur Publikation vorgesehen",
  "filter.reset": "Zurücksetzen",
  "filter.remove": "{label}: Filter entfernen",
  "filter.search": "Suchen",
  "filter.noMatches": "Keine Treffer",
  "filter.from": "Von",
  "filter.to": "Bis",
  "filter.since": "ab {date}",
  "filter.until": "bis {date}",
  "filter.june2026": "Juni 2026",

  "col.score": "Score",
  "col.docket": "Geschäftsnummer",
  "col.subject": "Betreff",
  "col.decided": "Entscheid",
  "col.published": "Publiziert",
  "col.outcome": "Ausgang",
  "col.label": "Suva-Label",

  "ruling.starred": "Zur Publikation in der amtlichen Sammlung vorgesehen",
  "score.relevant": "Vom System als relevant bewertet",
  "score.notRelevant": "Vom System als nicht relevant bewertet",

  "page.range": "{first}–{last} von {total}",
  "page.of": "Seite {page} von {pages}",
  "page.previous": "Vorherige Seite",
  "page.next": "Nächste Seite",

  "topic.UV": "Unfallversicherung",
  "topic.MV": "Militärversicherung",
  "topic.IV": "Invalidenversicherung",

  "language.de": "Deutsch",
  "language.fr": "Französisch",
  "language.it": "Italienisch",

  "outcome.dismissed": "Abgewiesen",
  "outcome.inadmissible": "Nichteintreten",
  "outcome.approved": "Gutgeheissen",
  "outcome.partial_approval": "Teilweise gutgeheissen",
  "outcome.moot": "Gegenstandslos",
  "outcome.consolidated": "Vereinigt",

  "label.relevant": "Relevant",
  "label.not_relevant": "Nicht relevant",
  "label.unknown": "Offen",
};

const fr: Messages = {
  "app.name": "Jurisprudence",
  "app.title": "Arrêts du Tribunal fédéral",
  "app.count": "{n} arrêts",
  "app.countOf": "{n} arrêts sur {total}",
  "app.search": "Rechercher un numéro de dossier ou un objet",
  "app.clearSearch": "Effacer la recherche",
  "app.loadError": "Les arrêts n'ont pas pu être chargés.",
  "app.retry": "Réessayer",
  "app.empty": "Aucun arrêt ne correspond à ces filtres.",
  "app.resetFilters": "Réinitialiser les filtres",
  "app.placeholderScores": "Les scores sont provisoires jusqu'à l'exécution du triage.",
  "app.language": "Langue",

  "views.title": "Vues",
  "views.all": "Tous les arrêts",
  "views.core": "Domaines clés de la Suva",
  "views.predicted": "Jugés pertinents par le système",
  "views.june": "Juin 2026 par score",
  "views.labelled": "Marqués pertinents par la Suva",

  "filter.decided": "Date de l'arrêt",
  "filter.published": "Date de publication",
  "filter.area": "Domaine juridique",
  "filter.area.core": "Domaines clés de la Suva",
  "filter.area.all": "Tous les domaines juridiques",
  "filter.area.search": "Rechercher un domaine",
  "filter.division": "Cour",
  "filter.language": "Langue",
  "filter.outcome": "Issue",
  "filter.label": "Évaluation Suva",
  "filter.assessment": "Évaluation du système",
  "filter.assessment.decision": "Décision du système",
  "filter.assessment.all": "Tous",
  "filter.assessment.scoreFrom": "Score dès",
  "filter.assessment.scoreTo": "Score jusqu'à",
  "filter.starred": "Destiné à la publication",
  "filter.reset": "Réinitialiser",
  "filter.remove": "{label} : supprimer le filtre",
  "filter.search": "Rechercher",
  "filter.noMatches": "Aucun résultat",
  "filter.from": "Du",
  "filter.to": "Au",
  "filter.since": "dès le {date}",
  "filter.until": "jusqu'au {date}",
  "filter.june2026": "Juin 2026",

  "col.score": "Score",
  "col.docket": "N° de dossier",
  "col.subject": "Objet",
  "col.decided": "Arrêt du",
  "col.published": "Publié le",
  "col.outcome": "Issue",
  "col.label": "Avis Suva",

  "ruling.starred": "Destiné à la publication au recueil officiel",
  "score.relevant": "Jugé pertinent par le système",
  "score.notRelevant": "Jugé non pertinent par le système",

  "page.range": "{first}–{last} sur {total}",
  "page.of": "Page {page} sur {pages}",
  "page.previous": "Page précédente",
  "page.next": "Page suivante",

  "topic.UV": "Assurance-accidents",
  "topic.MV": "Assurance militaire",
  "topic.IV": "Assurance-invalidité",

  "language.de": "Allemand",
  "language.fr": "Français",
  "language.it": "Italien",

  "outcome.dismissed": "Rejeté",
  "outcome.inadmissible": "Irrecevable",
  "outcome.approved": "Admis",
  "outcome.partial_approval": "Partiellement admis",
  "outcome.moot": "Sans objet",
  "outcome.consolidated": "Joint",

  "label.relevant": "Pertinent",
  "label.not_relevant": "Non pertinent",
  "label.unknown": "Ouvert",
};

const MESSAGES: Record<Lang, Messages> = { en, de, fr };
const LOCALES: Record<Lang, string> = { en: "en-GB", de: "de-CH", fr: "fr-CH" };
const STORAGE_KEY = "suva.lang";

/** Groups of database codes that have a translation: `tx("outcome", "dismissed")`. */
export type Group = "topic" | "language" | "outcome" | "label";

export type I18n = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  /** Text for a key, with {name} placeholders filled from `vars`. */
  t: (key: Key, vars?: Record<string, string | number>) => string;
  /** Text for a database code; an unknown code is shown as it is, a missing one as a dash. */
  tx: (group: Group, code: string | null) => string;
  formatDate: (iso: string | null) => string;
  formatNumber: (n: number) => string;
};

function initialLang(): Lang {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && (LANGS as string[]).includes(stored)) return stored as Lang;
  } catch {
    // storage unavailable: fall through to the default
  }
  return "en";
}

const Context = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = `Suva · ${MESSAGES[lang]["app.name"]}`;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // not remembered across visits, still applied now
    }
  }, []);

  const value = useMemo<I18n>(() => {
    const messages = MESSAGES[lang];
    const dates = new Intl.DateTimeFormat(LOCALES[lang], { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" });
    const numbers = new Intl.NumberFormat(LOCALES[lang]);
    return {
      lang,
      setLang,
      t: (key, vars) =>
        vars ? messages[key].replace(/\{(\w+)\}/g, (whole, name: string) => (name in vars ? String(vars[name]) : whole)) : messages[key],
      tx: (group, code) => (code ? ((messages as Record<string, string>)[`${group}.${code}`] ?? code) : "–"),
      formatDate: (iso) => (iso ? dates.format(new Date(iso + "T00:00:00Z")) : "–"),
      formatNumber: (n) => numbers.format(n),
    };
  }, [lang, setLang]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(Context);
  if (!value) throw new Error("useI18n must be used inside <I18nProvider>");
  return value;
}
