# Audit de conformité — version 0.6.1, phases 1 à 5

Date de l'audit : 2026-08-28

Légende :

- `[x]` implémenté et couvert par des tests ;
- `[~]` implémenté dans le périmètre actuel avec une limite explicite ;
- `[ ]` volontairement différé selon l'ordre des phases de la spécification.

Ce document ne présente pas les phases 6 à 12 comme terminées.

## Règles transversales

- [x] Aucune donnée manquante n'est remplacée par une valeur inventée.
- [x] Les valeurs indisponibles sont `null` avec un statut explicite.
- [x] Les observations externes conservent source, URL, date/période,
  récupération, unité/devise quand le fournisseur les expose, confiance et
  qualité.
- [x] `.env` est ignoré par Git et les clés ne sont pas codées en dur.
- [x] Les erreurs d'un fournisseur sont isolées par titre/série et n'arrêtent
  pas les autres étapes.
- [x] Les données synthétiques sont confinées aux tests.
- [x] Les scores sont présentés sur 100 et jamais comme probabilités de gain.

## Phase 1 — architecture, configuration et modèles

- [x] Architecture demandée présente et maintenable.
- [x] Configuration YAML validée avec Pydantic.
- [x] Modèles de provenance, sécurité, prix, fondamentaux, valorisation, macro,
  nouvelles et choc.
- [x] Installation Python 3.11+, `pyproject.toml`, `requirements.txt` et CLI.
- [x] Univers YAML/CSV configurable et filtre de capitalisation configurable.
- [x] Liste par défaut des pays/régions demandés dans le filtre d'univers.
- [~] L'univers est vide par défaut pour éviter de distribuer une liste périmée ;
  l'utilisateur doit fournir un snapshot daté.

## Phase 2 — prix, univers et détection des baisses

- [x] OHLCV quotidien, adjusted close, exchange/devise, date et provenance.
- [x] Drawdown ATH, 52 semaines, 1M, 3M, 6M, YTD et 1Y.
- [x] Rendements 1M/3M/6M/YTD/1Y séparés des drawdowns.
- [x] MA50, MA200, RSI de Wilder, volatilité, bêta et performances relatives.
- [x] `OpportunityCandidate`, règles de sélection et classement de sévérité.
- [x] CSV et classeur Excel avec candidats, tous résultats et métadonnées.
- [x] Un cutoff historique filtre les prix avant calcul, persistance et
  valorisation ; une exécution intrajournalière exclut la clôture du même jour.
- [~] Yahoo Finance est une source gratuite unique, donc qualité maximale
  `MEDIUM`, jamais `HIGH`.
- [~] Le système accepte plusieurs milliers de lignes via CSV, mais la collecte
  Yahoo par titre n'est pas encore une infrastructure de production massive.

## Phase 3 — fondamentaux SEC EDGAR point-in-time

- [x] SEC EDGAR prioritaire pour les émetteurs US.
- [x] Conservation accession, formulaire, date de dépôt, timestamp d'acceptation
  et précision de disponibilité.
- [x] Exclusion de toute publication disponible après le cutoff.
- [x] Amendements/retraitements admissibles seulement après leur disponibilité.
- [x] Croissance : CAGR revenue, EPS dilué, EBITDA calculé et FCF.
- [x] Rentabilité : marges brute, EBITDA, opérationnelle et nette, ROE, ROIC.
- [x] Bilan : dette, dette nette, debt/equity, net debt/EBITDA, couverture des
  intérêts, cash/debt et current ratio.
- [x] Cash-flow : OCF, capex, FCF, marge FCF, FCF/action, conversion et années FCF
  positives.
- [x] Fundamental Quality Score avec sous-scores et couverture.
- [~] Les extensions XBRL spécifiques, IFRS/20-F/40-F, trimestriels/TTM et les
  émetteurs non-US restent hors du moteur SEC actuel.

## Phase 4 — valorisation

- [x] P/E, EV/EBITDA et P/FCF actuels.
- [x] Médianes historiques point-in-time et médianes sectorielles sans la cible.
- [x] Alignement du prix sur la première séance postérieure à la publication.
- [x] DCF bear/base/bull configurable, sans hypothèse livrée par défaut.
- [x] DCF normalisé uniquement si une hypothèse normalisée datée et sourcée est
  fournie.
- [x] Reverse DCF et croissance implicite avec bornes explicites.
- [x] Valuation Score avec sous-scores et couverture.
- [x] Les hypothèses postérieures au cutoff sont rejetées.
- [~] Sans hypothèses utilisateur, les valeurs DCF restent `null`, ce qui est le
  comportement attendu.
- [ ] Conversion FX USD/EUR : moteur réservé, non implémenté dans cette version.

## Phase 5 — macro, nouvelles et détection du choc

- [x] FRED/ALFRED avec `realtime_start = realtime_end = cutoff`.
- [x] Filtrage défensif de la date d'observation et de la période de disponibilité
  de chaque vintage.
- [x] Variations macro brutes 30/90/365 jours, sans affirmation causale.
- [x] Expositions configurables par secteur et entreprise, obligatoirement
  datées, sourcées et non nulles.
- [x] Les hypothèses d'exposition futures sont rejetées.
- [x] GDELT uniquement pour les candidats au filtre de baisse.
- [x] Conservation du titre, URL, domaine, langue/pays et `seendate`, sans corps
  d'article ni contournement de paywall.
- [x] Limite historique GDELT explicite ; aucun faux historique n'est créé.
- [x] Toutes les catégories de choc demandées et `UNKNOWN`.
- [x] Toutes les natures demandées ; `TEMPORARY` n'est jamais produit
  automatiquement par la couche de preuves actuelle.
- [x] Corroboration par domaines indépendants avant `PROBABLY_TEMPORARY`.
- [x] Précédence des éléments structurels et sévèrement structurels.
- [x] Temporary Shock Score avec composants, score observé, couverture et statut.
- [x] Couverture distincte des dix critères de la spécification et liste de tous
  les critères encore indisponibles.
- [~] Les titres sont des signaux de triage et non une preuve causale ou une
  analyse complète du contenu.
- [ ] Durée historique et précédents comparables : phase 6.
- [ ] Impacts chiffrés du choc sur revenue, margins, FCF et bilan : nécessitent
  des données/estimations datées supplémentaires ; ils restent indisponibles.
- [ ] Attentes analystes point-in-time : source légale et historique non ajoutée.

## Phases volontairement non commencées

- [ ] Phase 6 : analogues historiques.
- [ ] Phase 7 : scénarios temporels complets et targets.
- [ ] Phase 8 : Normalization/Catalyst/Risk/Opportunity Scores et verdict.
- [ ] Phase 9 : backtest sans survivorship/look-ahead bias.
- [ ] Phase 10 : reporting final professionnel de toutes les phases.
- [ ] Phase 11 : dashboard Streamlit et page entreprise.
- [ ] Phase 12 : automatisation et alertes.

## Interface disponible

L'interface utilisable en phase 5 est le classeur Excel généré dans `reports/`.
Le fichier `dashboard/app.py` est seulement une frontière d'architecture pour la
phase 11. Il n'existe donc pas encore d'URL locale Streamlit légitime à ouvrir.

## Contrôles de livraison

La validation de chaque livraison doit comprendre :

```powershell
python -m pytest -q
python -m compileall -q src tests
python -m pip check
python -m src.pipeline --help
git diff --check
```

Un smoke test du pipeline avec l'univers vide doit aussi terminer proprement et
exporter les indisponibilités au lieu d'échouer. Les adaptateurs réseau sont
testés hors ligne avec des payloads synthétiques ; un test réel SEC/FRED nécessite
les identifiants configurés par l'utilisateur.
