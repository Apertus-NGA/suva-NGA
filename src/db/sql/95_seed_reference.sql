-- ============================================================================
-- File: 95_seed_reference.sql (reference data the schema needs on day one)
-- Date: 2026-11-28
-- Description: The reason-code vocabulary (German and French labels shown to lawyers; a layer-1 drop label
--              states only its own condition, F-03), the perspective anchors (draft until the summarise
--              owner writes their rubrics), the mandatory preset suva_house (anchor 5), and the review payload
--              schemas (V1.0.0 empty; scope_review.payload V1.1.0 records what the expert saw, D-093).
--              Step versions, rules, prompts and profiles are NOT seeded here: the registry loader writes
--              them from reviewed seed files, and models come from MODELS.md (D-064).
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §7.5, §12.2, §13.2-§13.4
-- ============================================================================
-- PREREQUISITE: 90_roles.sql. Idempotent (ON CONFLICT DO NOTHING): a changed label reaches an existing database
-- only through make db-reset (labels may be edited in place, so a deploy never overwrites them).
-- ============================================================================

SET ROLE suva_owner;
SET app.actor = 'seed';

INSERT INTO ops.reason_code (code, domain, label_de, label_fr) VALUES
  -- layer 1 (src/layer1, rules in src/layer1/registry/layer1_filter.json) and window
  ('L1_KEEP_RUBRIC',             'triage', 'Rechtsgebiet in der Liste der Abteilung', 'Domaine juridique retenu pour cette cour'),
  ('L1_KEEP_RUBRIC_MISSING',     'triage', 'Rechtsgebiet fehlt: vorsorglich behalten', 'Domaine juridique absent : conservé par prudence'),
  ('L1_KEEP_ACCIDENT_TERM',      'triage', 'Text nennt die Suva oder die Unfall- oder Militärversicherung', 'Le texte mentionne la Suva ou l''assurance-accidents ou militaire'),
  ('L1_KEEP_CONTRACT_TERM',      'triage', 'Text nennt das VVG oder eine Taggeldversicherung', 'Le texte mentionne la LCA ou une assurance d''indemnités journalières'),
  ('L1_KEEP_TEXT_UNAVAILABLE',   'triage', 'Kein Urteilstext verfügbar: vorsorglich behalten', 'Texte de l''arrêt indisponible : conservé par prudence'),
  ('L1_KEEP_TITLE_RUBRIC',       'triage', 'Rechtsgebiet laut Gegenstand in der Liste der Abteilung', 'Domaine juridique selon l''objet retenu pour cette cour'),
  ('L1_FLAG_CLOSED_RUBRIC',      'triage', 'VVG-Begriff im Text, aber Rechtsgebiet ausgeschlossen (z. B. Arbeitslosenversicherung)', 'Terme LCA dans le texte, mais domaine exclu (p. ex. assurance-chômage)'),
  -- a drop label states only its own condition; the explanation states what the text check found (F-03). Labels are
  -- shared by every version: they never name a configured value (a court list, a rubric); the ledger shows it.
  ('L1_DROP_WRONG_COURT',        'triage', 'Abteilung nicht in der Liste der Vorauswahl', 'Cour hors de la liste du filtre'),
  ('L1_DROP_WRONG_LETTER',       'triage', 'Verfahrensart in dieser Abteilung nicht berücksichtigt', 'Type de procédure non retenu pour cette cour'),
  ('L1_DROP_RUBRIC_OUT',         'triage', 'Rechtsgebiet nicht in der Liste der Abteilung', 'Domaine juridique hors de la liste de cette cour'),
  ('L1_SIGNAL_RUBRIC_FROM_TITLE','triage', 'Rechtsgebiet aus dem Gegenstand gelesen', 'Domaine lu dans l''objet'),
  ('OUT_OF_WINDOW',              'triage', 'Ausserhalb aller Zeitfenster', 'Hors de toutes les périodes'),
  -- layer 2, justification, ranking
  ('L2_FAILED_CALL',             'triage', 'Beurteilung durch Apertus fehlgeschlagen, wird wiederholt', 'Évaluation par Apertus échouée, nouvel essai prévu'),
  ('L2_FAIL_NO_YESNO_TOKEN',     'triage', 'Antwort ohne Ja/Nein: nicht verwertbar', 'Réponse sans Ja/Nein : inexploitable'),
  ('JUS_JSON_INVALID',           'triage', 'Begründung nicht im erwarteten Format', 'Justification hors du format attendu'),
  ('JUS_PARTY_SUVA_ACTING_ONLY_IF_PARTY', 'triage', 'Der Suva wird nur eine Handlung zugeschrieben, wenn sie Partei ist', 'Un acte n''est attribué à la Suva que si elle est partie'),
  ('JUS_ACTING_PARTY_IN_BLOCK',  'triage', 'Handelnde Partei steht im Rubrum', 'La partie agissante figure dans le rubrum'),
  ('JUS_EVIDENCE_IN_SET',        'triage', 'Zitierte Erwägungen stammen aus dem Urteil', 'Les considérants cités proviennent de l''arrêt'),
  ('RANK_BELOW_THRESHOLD',       'triage', 'Relevanzwert unter der Schwelle', 'Score de pertinence sous le seuil'),
  ('RANK_AT_OR_ABOVE_THRESHOLD', 'triage', 'Relevanzwert auf oder über der Schwelle', 'Score de pertinence au seuil ou au-dessus'),
  -- the Suva Scout scorer as layer 2 and its promotion as the ranking step (src/scorer, D-094)
  ('SC_AREA_UVMV', 'triage', 'Unfall- oder Militärversicherung', 'Assurance-accidents ou assurance militaire'),
  ('SC_AREA_IV', 'triage', 'Invalidenversicherung', 'Assurance-invalidité'),
  ('SC_APPEAL_BY_INSTITUTION', 'triage', 'Beschwerde eines Versicherers oder einer Behörde', 'Recours d''un assureur ou d''une autorité'),
  ('SC_FIVE_JUDGES', 'triage', 'Fünferbesetzung', 'Composition à cinq juges'),
  ('SC_PUBLICATION', 'triage', 'zur Publikation vorgesehen', 'Destiné à la publication'),
  ('SC_MANIFESTLY_UNFOUNDED', 'triage', 'als offensichtlich unbegründet erledigt', 'Liquidé comme manifestement infondé'),
  ('SC_SUVA_PARTY', 'triage', 'Suva ist Partei', 'La Suva est partie'),
  ('SC_SINGLE_JUDGE', 'triage', 'Einzelrichterentscheid', 'Décision du juge unique'),
  ('SC_CONSENSUS', 'triage', 'Apertus-Lesungen: rechtliche Aussage über den Einzelfall hinaus', 'Lectures d''Apertus : énoncé juridique au-delà du cas d''espèce'),
  ('SC_CORE_TOPICS', 'triage', 'Kernthemen der Unfallversicherung im Text', 'Thèmes centraux de l''assurance-accidents dans le texte'),
  ('SC_LONG_ACCIDENT', 'triage', 'ausführliches Urteil in der Unfall- oder Militärversicherung', 'Arrêt détaillé en assurance-accidents ou en assurance militaire'),
  ('SC_OTHER_ACCIDENT_INSURER', 'triage', 'anderer Unfallversicherer ist Partei', 'Un autre assureur-accidents est partie'),
  ('RANK_PROMOTED_BY_SCORER',    'triage', 'Vom Bewertungsmodell als vermutlich relevant eingestuft', 'Classé comme probablement pertinent par le modèle de score'),
  -- ingest, segmentation, parse
  ('ING_TWIN_SAME_DATE',               'ingest', 'Doppelte Zeile der Quelle (gleiches Datum)', 'Ligne en double dans la source (même date)'),
  ('ING_DOCKET_MALFORMED',             'ingest', 'Geschäftsnummer nicht im Format des Bundesgerichts', 'Numéro de dossier hors du format du Tribunal fédéral'),
  ('ING_DECISION_DATE_MISSING',        'ingest', 'Entscheiddatum fehlt in der Quelle', 'Date de l''arrêt absente de la source'),
  ('ING_SOURCE_ID_MISSING',            'ingest', 'Zeile der Quelle ohne Kennung', 'Ligne de la source sans identifiant'),
  ('ING_SOURCE_ID_DUPLICATE',          'ingest', 'Kennung der Quelle doppelt vergeben', 'Identifiant de la source en double'),
  ('ING_TEXT_MISSING',                 'ingest', 'Kein Urteilstext verfügbar', 'Texte de l''arrêt indisponible'),
  ('ING_CONSIDERATIONS_MISSING',       'ingest', 'Erwägungen fehlen in der Quelle', 'Considérants absents de la source'),
  ('ING_CONSIDERATIONS_COUNT_MISMATCH','ingest', 'Anzahl Erwägungen weicht ab', 'Nombre de considérants divergent'),
  ('ING_CONSIDERATION_NOT_LOCATED',    'ingest', 'Erwägung im Text nicht gefunden', 'Considérant introuvable dans le texte'),
  ('ING_PUBLICATION_UNKNOWN',          'ingest', 'Publikationsdatum unbekannt', 'Date de publication inconnue'),
  ('SEG_COUNT_MATCH',                  'ingest', 'Anzahl Erwägungen stimmt', 'Nombre de considérants conforme'),
  ('SEG_COVERAGE',                     'ingest', 'Erwägungsteil vollständig abgedeckt', 'Partie des considérants entièrement couverte'),
  ('SEG_OFFSET_FOUND',                 'ingest', 'Position der Erwägung gefunden', 'Position du considérant trouvée'),
  ('PAR_OUTCOME_PATTERN',              'ingest', 'Ausgang aus dem Dispositiv', 'Issue tirée du dispositif'),
  -- verifier and summaries
  ('V1_IDS_IN_SET',              'verify',  'Zitierte Erwägungen gehören zum Urteil', 'Les considérants cités appartiennent à l''arrêt'),
  ('V2_QUOTE_VERBATIM',          'verify',  'Zitat wörtlich im Urteil', 'Citation littérale de l''arrêt'),
  ('V3_NUMBERS_PRESENT',         'verify',  'Zahlen, Daten und Beträge stehen in der zitierten Erwägung', 'Chiffres, dates et montants présents dans le considérant cité'),
  ('V4_CANONICAL_REFS',          'verify',  'Artikel, BGE und Dossiernummern stehen im Urteil', 'Articles, ATF et numéros de dossier présents dans l''arrêt'),
  ('V5_HAS_CITATION',            'verify',  'Jede Aussage hat einen Beleg', 'Chaque affirmation est étayée'),
  ('V6_ACTING_PARTY',            'verify',  'Handelnde Partei ist Verfahrensbeteiligte', 'La partie agissante est partie à la procédure'),
  ('SUM_NON_PRACTICE_INVARIANT', 'summary', 'Ausser «Praxis» identisch mit der Suva-Fassung', 'Identique à la version Suva, hormis la « pratique »'),
  ('SUM_PAIR_REQUIRED',          'summary', 'Deutsche und französische Fassung vorhanden', 'Versions allemande et française présentes'),
  -- work
  ('WORK_TIMEOUT',               'work', 'Zeitüberschreitung', 'Délai dépassé'),
  ('WORK_RATE_LIMITED',          'work', 'Anfragelimit erreicht', 'Limite de requêtes atteinte'),
  ('WORK_HTTP_ERROR',            'work', 'Fehler des Dienstes', 'Erreur du service'),
  ('WORK_PARSE_ERROR',           'work', 'Antwort nicht lesbar', 'Réponse illisible'),
  ('WORK_CIRCUIT_OPEN',          'work', 'Lauf pausiert (Schutzschalter)', 'Exécution en pause (disjoncteur)'),
  ('WORK_MODEL_MISMATCH',        'work', 'Geliefertes Modell nicht zugelassen', 'Modèle servi non autorisé')
ON CONFLICT (code) DO NOTHING;

INSERT INTO summ.perspective_anchor (perspective, label_de, label_fr) VALUES
  (0,  'Sicht der versicherten Person',       'Point de vue de la personne assurée'),
  (3,  'Eher Sicht der versicherten Person',  'Plutôt le point de vue de la personne assurée'),
  (5,  'Neutral (Suva-Stil)',                 'Neutre (style Suva)'),
  (7,  'Eher Sicht des Versicherers',         'Plutôt le point de vue de l''assureur'),
  (10, 'Sicht des Versicherers',              'Point de vue de l''assureur')
ON CONFLICT (perspective) DO NOTHING;

INSERT INTO summ.preset (preset_code, name_de, name_fr, description, perspective, style, is_mandatory, selectable, created_by_actor) VALUES
  ('suva_house', 'Suva-Stil', 'Style Suva',
   'The graded output: reads like Suva''s 55 exports (Q-30 style by ruling language, D-053 length). Mandatory for every in-scope ruling of the default pipeline (D-067, D-068).',
   5, 'by_ruling_language', true, true, 'seed')
ON CONFLICT (preset_code) DO NOTHING;

INSERT INTO ops.json_schema (subject, schema_code, v_major, v_minor, v_patch, json_schema, template, schema_sha256, status, bump_kind, changelog, created_by_actor)
SELECT 'review_payload', s.code, 1, 0, 0, s.js, '{}'::jsonb,
       encode(sha256(convert_to(s.js::text, 'UTF8')), 'hex'), 'active', 'initial', s.changelog, 'seed'
FROM (VALUES
  ('scope_review.payload',
   '{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": false, "properties": {}}'::jsonb,
   'V1: the verdict (correct | incorrect) is a column; the payload is empty. V2 may add an expert score from 0 to 100.'),
  ('summary_review.payload',
   '{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": false, "properties": {}}'::jsonb,
   'V1: the verdict (validated | rejected) is a column; the payload is empty.')
) AS s(code, js, changelog)
ON CONFLICT (schema_code, v_major, v_minor, v_patch) DO NOTHING;

-- scope_review.payload V1.1.0 (D-093): what the expert saw when deciding (the pipeline status and the score on screen),
-- so each (seen, given) pair is a training example. All optional. A minor bump of V1.0.0, which stays in place and
-- active (versions are immutable; readers take the highest active version, as gold.submit_review does). The DB checks
-- only that a payload is an object: the writer validates it against this schema (§7.4).
INSERT INTO ops.json_schema (subject, schema_code, v_major, v_minor, v_patch, json_schema, template, schema_sha256, status, bump_kind,
                             previous_version_id, changelog, created_by_actor)
SELECT 'review_payload', 'scope_review.payload', 1, 1, 0, s.js, s.template,
       encode(sha256(convert_to(s.js::text, 'UTF8')), 'hex'), 'active', 'minor',
       -- V1.0.0, inserted above; a missing one fails json_schema_bump_chk instead of skipping V1.1.0 silently
       (SELECT p.json_schema_id FROM ops.json_schema p
        WHERE p.schema_code = 'scope_review.payload' AND p.v_major = 1 AND p.v_minor = 0 AND p.v_patch = 0),
       s.changelog, 'seed'
FROM (VALUES (
   '{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": false,
     "properties": {
       "shown_status":      {"type": "string", "description": "the status the screen showed (the pipeline label, e.g. potentially)"},
       "shown_score_0_100": {"type": ["number", "null"], "minimum": 0, "maximum": 100, "description": "the displayed score, 0-100"},
       "shown_score_raw":   {"type": ["number", "null"], "description": "the stored raw score (e.g. layer 2''s logit)"}}}'::jsonb,
   '{"shown_status": "potentially", "shown_score_0_100": 64, "shown_score_raw": 0.58}'::jsonb,
   'V1.1 (D-093): optional shown_status, shown_score_0_100, shown_score_raw = what the expert saw when deciding. The verdict stays a column: relevant | not_relevant on any label, correct | incorrect on in_scope or out_of_scope, withdrawn.')
) AS s(js, template, changelog)
ON CONFLICT (schema_code, v_major, v_minor, v_patch) DO NOTHING;

RESET app.actor;
RESET ROLE;
