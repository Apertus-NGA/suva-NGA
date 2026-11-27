# Démarrer l'agent propriétaire du tool calling

Ce fichier sert à la personne qui lance l'agent. Le prompt à coller est en anglais, comme le kit,
parce qu'il pilote la production de fichiers anglais. Le brief de rôle est
`reference/docs/agents/tool-calling.md` : il entre dans le repo et y fait foi. `HANDOFF.md` reste la
référence détaillée, hors du repo.

## Procédure en 3 étapes

1. **Poser le dossier dans le clone.**
   - Prérequis : le starter kit est dans le repo (`AGENTS.md` à la racine) avec son bloc
     `.gitignore`, qui ignore `tmp/`.
   - Télécharger `handoff/json-tool-protocol_2026-11-27.zip` et le décompresser dans `tmp/` à la
     racine du clone de suva-NGA. On obtient `tmp/json-tool-protocol/HANDOFF.md`.
   - Vérifier : `git check-ignore tmp/json-tool-protocol/HANDOFF.md` doit afficher le chemin.
     S'il n'affiche rien, le dossier serait commité : s'arrêter là.
2. **Lancer l'agent.**
   - Ouvrir une session de code à la racine du clone, avec les variables `LLM_*` dans `.env`
     (jamais commité).
   - Coller le prompt ci-dessous tel quel. L'agent demandera le handle GitHub du membre pour qui il
     travaille, s'il ne le connaît pas.
   - Sa première PR ne contient que de la documentation : son brief, sa ligne dans `AGENTS.md` §5,
     les exclusions dans les lignes platform et évaluation, et les entrées D-054 à D-058 de
     `docs/DECISIONS.md`. Viennent ensuite une PR par étape de son brief.
3. **Valider au fil des PR.**
   - En tant que lead, approuver la PR 1. D-058, qui crée le domaine, est votre décision du 27 novembre.
   - Trancher, quand l'agent les soulève, D-055 (forme du label et des signaux), D-056 (le
     validateur) et D-057 (ce que stocke le cache de rejeu). Le lead les tranche avec le
     propriétaire de la plateforme, et le lead tient ce rôle tant que D-024 reste ouverte.
   - Annoncer à l'équipe un créneau d'environ 25 minutes pour le banc complet, hors du run de nuit et
     avant le gel des fonctionnalités de samedi 12:00.
   - Dans chaque PR, vérifier les preuves demandées : compteurs de tests, logs rouge puis vert,
     nombre d'appels live, rapport du banc.

Ce que l'agent ne fait pas sans vous :
- modifier un fichier partagé sans une PR approuvée par son propriétaire ;
- trancher une question ouverte ;
- lancer le banc complet hors d'un créneau annoncé ;
- dépasser sa part de concurrence.

## Prompt à coller

```text
You own Apertus tool calling in our hackathon repository (Suva challenge, HackApertus Zurich,
27-28 Nov 2026): the JSON tool protocol (src/llm/tool_protocol/), its benchmark against native tool
calling (eval/tool_bench/), and their tests. The lead created this area on 27 Nov.

A handoff folder sits in tmp/json-tool-protocol/ of this clone. It is git-ignored and is never
committed. It holds:
- HANDOFF.md, the detailed reference;
- NOTICE.fragment;
- the reference implementation v0.2.1 under reference/, whose paths mirror the repo.
Your role brief is reference/docs/agents/tool-calling.md.

1. Check first. AGENTS.md must exist at the repo root, and
   `git check-ignore -q tmp/json-tool-protocol/HANDOFF.md` must succeed. If either check fails,
   stop and report: the starter kit and its .gitignore block must land first
   (docs/agents/platform.md step 3). If you do not know the GitHub handle of the team member you
   work for, ask for it now.
2. Read, in this order: AGENTS.md, docs/STATE.md, docs/EVENT.md, docs/DOCTRINE.md,
   docs/DECISIONS.md, your brief, then HANDOFF.md sections 3, 5 to 11 and 12. Follow the
   onboarding protocol of AGENTS.md section 2. At the top of your first PR, list the open questions
   your work touches (the brief's "Open questions" section), each with its options and your
   recommendation. Never answer one in code.
3. Execute your brief's "Steps, in order": one small PR per step, in that order. Respect "You own"
   and "You contribute by PR to another owner": a shared file changes only through a PR its owner
   approves (G7). When a step's input is missing (no client yet, no DS3 yet, no announced slot, an
   open question not yet settled), stop at that step and report it. Do not work around it.
4. Rules:
   - Never commit anything the brief's "Never commit" section lists.
   - No key, internal hostname or gateway URL in any file (G13).
   - No gateway call outside src/llm/ (G2).
   - No Suva text, DS7 text or Suva-derived data in fixtures or golden files.
   - No team member's name outside the places G13 allows.
   - No destructive command.
   - At most 3 sub-agents, no recursive delegation (D-023 while open).
   - Live calls stay within your concurrency share (D-030 while open).
   - The full benchmark runs only in a slot the team announced.
5. After each PR, report as CLAUDE.md asks:
   - what changed;
   - the make check counts;
   - the make run result, once the protocol is called from make run;
   - the 3 real rulings used, from step 12 on;
   - every live call you made: how many, on which model;
   - the open questions you raised, with your recommendation;
   - the AGENTS.md section 7 boxes still pending, and why;
   - any golden rule (G1-G15) you could not apply.
```
