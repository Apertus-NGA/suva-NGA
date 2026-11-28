// Areas of law. The court names an area in the ruling's own language, so one area arrives under up to three
// names ("Strafprozess", "Procédure pénale", "Procedura penale"). This table brings them together and gives
// each one name per interface language. A value that is not in the table (a free-text subject the court wrote
// where the area is missing) is shown as the court wrote it.

import type { Lang } from "./i18n";

type Area = { en: string; de: string; fr: string; it?: string; also?: string[] };

const AREAS: Area[] = [
  { en: "Accident insurance", de: "Unfallversicherung", fr: "Assurance-accidents", it: "Assicurazione contro gli infortuni" },
  { en: "Military insurance", de: "Militärversicherung", fr: "Assurance militaire", it: "Assicurazione militare" },
  { en: "Invalidity insurance", de: "Invalidenversicherung", fr: "Assurance-invalidité", it: "Assicurazione per l'invalidità" },
  { en: "Health insurance", de: "Krankenversicherung", fr: "Assurance-maladie", it: "Assicurazione contro le malattie" },
  { en: "Occupational pensions", de: "Berufliche Vorsorge", fr: "Prévoyance professionnelle", it: "Previdenza professionale" },
  { en: "Unemployment insurance", de: "Arbeitslosenversicherung", fr: "Assurance-chômage", it: "Assicurazione contro la disoccupazione" },
  { en: "Old-age and survivors' insurance", de: "Alters- und Hinterlassenenversicherung", fr: "Assurance-vieillesse et survivants", it: "Assicurazione per la vecchiaia e per i superstiti" },
  { en: "Supplementary benefits", de: "Ergänzungsleistung", fr: "Prestations complémentaires à l'AVS/AI", it: "Prestazione complementari", also: ["Ergänzungsleistung zur AHV/IV", "Prestations complémentaires"] },
  { en: "Family allowances and cantonal social insurance", de: "Familienzulagen und kantonale Sozialversicherung", fr: "Allocations familiales et assurance sociale cantonale", it: "Assegni familiari e assicurazione sociale cantonale" },
  { en: "Social assistance", de: "Sozialhilfe", fr: "Aide sociale", it: "Assistenza sociale" },
  { en: "Health and social security", de: "Gesundheitswesen & soziale Sicherheit", fr: "Santé & sécurité sociale", it: "Sanità & sicurezza sociale" },
  { en: "Contract law", de: "Vertragsrecht", fr: "Droit des contrats", it: "Diritto contrattuale" },
  { en: "Liability law", de: "Haftpflichtrecht", fr: "Droit de la responsabilité civile", it: "Diritto della responsabilità civile" },
  { en: "Law of obligations (general)", de: "Obligationenrecht (allgemein)", fr: "Droit des obligations (en général)", it: "Diritto delle obbligazioni (in generale)" },
  { en: "Company law", de: "Gesellschaftsrecht", fr: "Droit des sociétés", it: "Diritto delle società" },
  { en: "Intellectual property, competition and cartel law", de: "Immaterialgüter-, Wettbewerbs- und Kartellrecht", fr: "Propriété intellectuelle, concurrence et cartels", it: "Proprietà intellettuale, concorrenza e cartelli" },
  { en: "Family law", de: "Familienrecht", fr: "Droit de la famille", it: "Diritto di famiglia" },
  { en: "Law of persons", de: "Personenrecht", fr: "Droit des personnes", it: "Diritto delle persone" },
  { en: "Inheritance law", de: "Erbrecht", fr: "Droit des successions", it: "Diritto successorio" },
  { en: "Property law", de: "Sachenrecht", fr: "Droits réels", it: "Diritti reali" },
  { en: "Debt enforcement and bankruptcy law", de: "Schuldbetreibungs- und Konkursrecht", fr: "Droit des poursuites et faillites", it: "Diritto delle esecuzioni e del fallimento" },
  { en: "Civil procedure", de: "Zivilprozess", fr: "Procédure civile", it: "Procedura civile" },
  { en: "Arbitration", de: "Schiedsgerichtsbarkeit", fr: "Juridiction arbitrale", it: "Giurisdizione arbitrale" },
  { en: "Criminal procedure", de: "Strafprozess", fr: "Procédure pénale", it: "Procedura penale" },
  { en: "Criminal offences", de: "Straftaten", fr: "Infractions", it: "Infrazione", also: ["Infrazioni"] },
  { en: "Criminal law (general)", de: "Strafrecht (allgemein)", fr: "Droit pénal (en général)", it: "Diritto penale (in generale)" },
  { en: "Execution of sentences and measures", de: "Straf- und Massnahmenvollzug", fr: "Exécution des peines et des mesures", it: "Esecuzione delle pene e delle misure" },
  { en: "Mutual legal assistance and extradition", de: "Rechtshilfe und Auslieferung", fr: "Entraide et extradition", it: "Assistenza giudiziaria e estradizione" },
  { en: "Citizenship and immigration law", de: "Bürgerrecht und Ausländerrecht", fr: "Droit de cité et droit des étrangers", it: "Cittadinanza e diritto degli stranieri" },
  { en: "Public finance and tax law", de: "Öffentliche Finanzen & Abgaberecht", fr: "Finances publiques & droit fiscal", it: "Finanze pubbliche & diritto tributario" },
  { en: "Spatial planning and public building law", de: "Raumplanung und öffentliches Baurecht", fr: "Aménagement du territoire et droit public des constructions", it: "Pianificazione territoriale e diritto pubblico edilizio" },
  { en: "Fundamental rights", de: "Grundrecht", fr: "Droit fondamental", it: "Diritto fondamentale" },
  { en: "Political rights", de: "Politische Rechte", fr: "Droits politiques", it: "Diritti politici" },
  {
    en: "Jurisdiction and the right to a lawful judge",
    de: "Zuständigkeitsfragen, Garantie des Wohnsitzrichters und des verfassungsmässigen Richters",
    fr: "Questions de compétences, garantie du juge du domicile et du juge naturel",
    also: ["Zuständigkeitsfragen, Garantie des Wohnsitzrichters und des v..."],
  },
  { en: "Roads and road traffic", de: "Strassenbau und Strassenverkehr", fr: "Construction des routes et circulation routière", it: "Costruzioni stradali e circolazione stradale" },
  { en: "Transport (excluding road traffic)", de: "Verkehr (ohne Strassenverkehr)", fr: "Transports (sans circulation routière)" },
  { en: "Post and telecommunications", de: "Post- und Fernmeldeverkehr", fr: "Poste et télécommunications" },
  { en: "Environmental protection", de: "Ökologisches Gleichgewicht", fr: "Équilibre écologique", it: "Equilibrio ecologico" },
  { en: "Energy", de: "Energie", fr: "Énergie", it: "Energia" },
  { en: "Economy", de: "Wirtschaft", fr: "Économie", it: "Economia" },
  { en: "Education and vocational training", de: "Unterrichtswesen und Berufsausbildung", fr: "Instruction et formation professionnelle", it: "Istruzione e formazione professionale" },
  { en: "Public employment", de: "Öffentliches Dienstverhältnis", fr: "Fonction publique", it: "Funzione pubblica" },
  { en: "State liability", de: "Staatshaftung", fr: "Responsabilité de l'État", it: "Responsabilità dello Stato" },
  { en: "Administrative procedure", de: "Verwaltungsverfahren", fr: "Procédure administrative", it: "Procedura amministrativa" },
  { en: "Expropriation", de: "Enteignung", fr: "Expropriation", it: "Espropriazione" },
];

const norm = (name: string) => name.trim().toLowerCase();
const BY_NAME = new Map<string, Area>();
for (const area of AREAS) for (const name of [area.de, area.fr, area.it, ...(area.also ?? [])]) if (name) BY_NAME.set(norm(name), area);

/** An area of law in the interface language; a name the table does not know is returned as the court wrote it. */
export function areaLabel(raw: string | null | undefined, lang: Lang): string {
  if (!raw) return "";
  return BY_NAME.get(norm(raw))?.[lang] ?? raw;
}

export type AreaOption = { value: string; label: string; count: number; raws: string[] };

/**
 * The court's area names as filter options: one option per area, whatever the language of the rulings, with the
 * counts added up. `raws` are the names the option stands for: they are what the list is filtered on.
 */
export function areaOptions(values: Array<{ value: string; n: number }> | undefined, lang: Lang): AreaOption[] {
  const known = new Map<Area, AreaOption>();
  const others: AreaOption[] = [];
  for (const { value, n } of values ?? []) {
    const area = BY_NAME.get(norm(value));
    if (!area) {
      others.push({ value, label: value, count: n, raws: [value] });
      continue;
    }
    const option = known.get(area) ?? { value: `area:${area.en}`, label: area[lang], count: 0, raws: [] };
    option.count += n;
    option.raws.push(value);
    known.set(area, option);
  }
  const byCount = (a: AreaOption, b: AreaOption) => b.count - a.count || a.label.localeCompare(b.label);
  return [...[...known.values()].sort(byCount), ...others.sort(byCount)];
}
