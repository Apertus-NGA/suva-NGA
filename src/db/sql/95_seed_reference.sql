-- ============================================================================
-- File: 95_seed_reference.sql (reference data the schema needs on day one)
-- Date: 2026-11-28
-- Description: The reason-code vocabulary (German and French labels shown to lawyers), the perspective
--              anchors (draft until the summarise owner writes their rubrics), the mandatory preset
--              suva_house (anchor 5), and the V1 review payload schemas (empty payloads).
--              Step versions, rules, prompts and profiles are NOT seeded here: the registry loader writes
--              them from reviewed seed files, and models come from MODELS.md (D-064).
-- SGBD: PostgreSQL 17
-- Doc: docs/DB_DDL_PLANNING.md §7.5, §12.2, §13.2-§13.4
-- ============================================================================
-- PREREQUISITE: 90_roles.sql. Idempotent (ON CONFLICT DO NOTHING).
-- ============================================================================

SET ROLE suva_owner;
SET app.actor = 'seed';

INSERT INTO ops.reason_code (code, domain, label_de, label_fr) VALUES
  -- layer 1 (src/layer1, rules in src/layer1/registry/layer1_filter.json) and window
  ('L1_KEEP_RUBRIC',             'triage', 'Rechtsgebiet in der Liste der Abteilung (4, 8 oder 9)', 'Domaine juridique retenu pour cette cour (4, 8 ou 9)'),
  ('L1_KEEP_RUBRIC_MISSING',     'triage', 'Rechtsgebiet fehlt: vorsorglich behalten', 'Domaine juridique absent : conservé par prudence'),
  ('L1_KEEP_ACCIDENT_TERM',      'triage', 'Text nennt die Suva oder die Unfall- oder Militärversicherung', 'Le texte mentionne la Suva ou l''assurance-accidents ou militaire'),
  ('L1_KEEP_CONTRACT_TERM',      'triage', 'Text nennt das VVG oder eine Taggeldversicherung', 'Le texte mentionne la LCA ou une assurance d''indemnités journalières'),
  ('L1_FLAG_CLOSED_RUBRIC',      'triage', 'VVG-Begriff im Text, aber Rechtsgebiet ausgeschlossen (z. B. Arbeitslosenversicherung)', 'Terme LCA dans le texte, mais domaine exclu (p. ex. assurance-chômage)'),
  ('L1_DROP_WRONG_COURT',        'triage', 'Andere Abteilung, und der Text nennt keinen Versicherungsbegriff', 'Autre cour, et le texte ne mentionne aucun terme d''assurance'),
  ('L1_DROP_WRONG_LETTER',       'triage', 'Verfahrensart hier nicht berücksichtigt, und kein Versicherungsbegriff im Text', 'Type de procédure non retenu, et aucun terme d''assurance dans le texte'),
  ('L1_DROP_RUBRIC_OUT',         'triage', 'Rechtsgebiet ausserhalb der Liste, und kein Versicherungsbegriff im Text', 'Domaine hors liste, et aucun terme d''assurance dans le texte'),
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
  -- ingest, segmentation, parse
  ('ING_TWIN_SAME_DATE',               'ingest', 'Doppelte Zeile der Quelle (gleiches Datum)', 'Ligne en double dans la source (même date)'),
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

RESET app.actor;
RESET ROLE;
