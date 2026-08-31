# Audit interne des phases 1 à 12

Version : 2.0.0 (addendum univers mondial)
Date : 2026-08-30

## Conclusion exécutive

Les douze phases de la stratégie de développement sont implémentées et
testables. Cela ne signifie pas que chaque résultat final demandé par la
spécification est disponible pour chaque société : le système respecte la règle
`data_unavailable` lorsque les sources point-in-time nécessaires manquent.

Le changement de périmètre demandé par l'utilisateur est appliqué : l'univers
par défaut contient désormais 17 041 cotations vérifiées sur les annuaires US,
européens, JPX, NSE, ASX et HKEX. Son sous-ensemble contient 319 cotations natives
de l'EEE. Elles sont des **candidates géographiques PEA à confirmer**, jamais des
éligibilités juridiques affirmées automatiquement.

## Audit par phase

| Phase | Statut | Preuve principale | Limite restante |
|---|---|---|---|
| 1 Architecture/config/modèles | Conforme | `src/models.py`, configuration Pydantic stricte, `.env.example` | SQLite n'est pas requis par le flux courant |
| 2 Prix/univers/drawdowns | Conforme | prix OHLCV, cutoff commun, métriques V1 et classement | Yahoo reste une source unique non officielle |
| 3 Fondamentaux | Conforme pour déclarants SEC | faits XBRL as-filed, accession, `accepted_at`/`filed_date`, croissance/rentabilité/bilan/cash-flow/FQS | 319 titres PEA incluent de nombreux émetteurs sans corpus SEC/ESEF intégré |
| 4 Valorisation | Conforme selon couverture | P/E, EV/EBITDA, P/FCF, DCF, reverse DCF, score | market cap, actions et hypothèses DCF souvent absents |
| 5 Macro/news/chocs | Conforme et conservateur | FRED/ALFRED, BCE, Cboe, CFTC, GDELT, taxonomie et corroboration | pas d'archive news exhaustive ni preuve causale complète |
| 6 Analogues | Conforme sur le même titre | épisodes peak/trough/recovery et contexte point-in-time | pas de catalogue causal multi-sociétés |
| 7 Scénarios/targets | Conforme selon données | bear/base/bull, 3–24 mois, TP1–TP3, invalidations fondamentales | pas de consensus/guidance datés complets |
| 8 Scoring | Conforme, non calibré | sept sous-scores, couverture et confiance distinctes | poids heuristiques, donc aucune probabilité de gain |
| 9 Backtest | Moteur conforme, couche univers européen acquise | 32 snapshots trimestriels officiels ESMA FIRDS, 58 archives hachées, contrôles anti-look-ahead/survivorship/leakage | mapping historique ISIN/MIC→ticker, prix ajustés, fondamentaux et signaux datés manquants |
| 10 Excel | Conforme | `Candidates`, `All Results`, `Run Metadata`, champs requis | narratifs IA/catalyseurs restent explicitement indisponibles |
| 11 Streamlit | Conforme | Top 5 avec statut décisionnel, tri PEA, pagination, recherche, détail et graphiques | analyse IA critique inactive et aucun achat validé avec la couverture courante |
| 12 Automatisation/alertes | Conforme au périmètre gratuit | runner verrouillé, tâche Windows optionnelle, alertes JSON/CSV/Markdown dédupliquées | email/Telegram/Discord non configurés par choix |

La composition mondiale v2 est isolée dans
`data/raw/backtest_global_v2_0_0`, afin de ne jamais écraser les lignées PEA
v1.4.0 et mondiale v1.3.0 avec une appartenance différente à la même date.

## Validation réelle mondiale du 2026-08-30

- 17 041 titres uniques et 35 benchmarks ;
- 17 016/17 076 historiques de prix disponibles, dont 16 981 titres primaires ;
- 22/22 paires FX et 9/9 séries macro disponibles ;
- 8 871 candidats de baisse, tous traités par les étapes prix/fondamentaux ;
- 3 001 historiques fondamentaux SEC et 1 185 valorisations exploitables ;
- 250 dossiers d'actualité/choc présélectionnés ; GDELT indisponible sur ce run ;
- 7 021 candidats avec analogues historiques terminés ;
- 1 256 candidats avec scénarios dérivés des données ;
- 1 427 scores à couverture suffisante ;
- 319 présélections PEA, 73 candidats techniques PEA et un seul score PEA
  couvert (SAP.DE, 26,10/100, sous le seuil de 50) ;
- 0 alerte PEA émise ;
- archive point-in-time mondiale v2 écrite sans collision ;
- rapports : `stock_opportunity_scan_20260830T203518Z.csv` et `.xlsx` ;
- 150 tests automatisés réussis ;
- test Streamlit réel : 17 041 lignes visibles, Top 5 de 5 lignes, pagination de
  50 lignes, passage PEA à 319 lignes et réinitialisation à 17 041.

Le Top 5 analytique calculé est PTC, INTU, ADBE, META et IDXX, avec des scores
entre 53,52 et 56,36 et une couverture de 75 %. Ce sont des priorités de
recherche non calibrées, pas des recommandations d'achat. Le scanner ne
transforme pas les absences de fondamentaux mondiaux en scores artificiels.

## Correctifs de passage à l'échelle

- prix de présélection sur deux ans par lots de 100, historique maximal réservé
  aux candidats par lots de 250 ;
- lecture parallèle des caches et absence de recopie normalisée inutile ;
- provenance héritée explicitement pour les 44 lignes enrichies du YAML ;
- tableau complet restauré (le Top 5 était auparavant affiché deux fois) ;
- titres sans prix visibles lorsqu'aucun filtre n'est appliqué ;
- chargement dashboard limité aux colonnes utilisées : 76,5 Mo en mémoire pour
  le rapport de 404 Mo, chargé en environ huit secondes lors du contrôle ;
- serveur Streamlit redémarré pour charger les nouveaux modèles de configuration.

Le contrôle navigateur a identifié le serveur ancien. Après son redémarrage,
le navigateur intégré a bloqué localhost par sa politique de sécurité : aucun
contournement n'a été tenté. Le contrôle final des interactions a utilisé
`streamlit.testing.v1.AppTest` avec succès.

## Audit transversal des sections 1 à 40

- Sections 1, 6, 17, 24, 30, 31, 32, 33, 37, 38 et 39 : conformes.
- Sections 8 à 11, 13, 16, 18, 19 et 21 : moteurs implémentés, résultats
  conditionnés à la disponibilité des données réelles.
- Section 7 : l'univers par défaut est mondial sur les places vérifiées, avec
  un filtre PEA distinct. L'exhaustivité littérale de toutes les bourses reste
  non démontrée et est marquée fausse dans le manifeste de couverture.
- Sections 2, 12, 14, 15, 20, 22, 23, 25 et 27 : partielles au sens du résultat
  final complet. Les champs manquants sont signalés, pas inventés.
- Section 28 : architecture locale complète ; les canaux externes sont laissés
  derrière une interface de livraison, conformément à l'interdiction d'imposer
  une notification payante.
- Section 29 : `run_pipeline()` orchestre le flux complet. L'univers est chargé
  depuis un snapshot daté ; son rafraîchissement automatique reste volontairement
  désactivé pour éviter une mutation silencieuse des appartenances.
- Sections 34 et 40 : aucune logique VINCI ou donnée synthétique n'est codée
  dans le moteur ; les données synthétiques restent confinées aux tests.

## PEA : ce qui est et n'est pas garanti

La présélection retient les places de cotation de l'EEE, hors Royaume-Uni et
Suisse. Chaque ligne exporte :

- `pea_eligibility_status=review_required` ;
- la base prudente de classification ;
- l'URL de la règle AMF ;
- la date de vérification de la règle.

Une confirmation individuelle reste obligatoire avant achat : siège de
l'émetteur dans l'UE/EEE admissible, impôt sur les sociétés équivalent, nature
du titre, exclusions (notamment SIIC) et acceptation opérationnelle du courtier.

## Bigdata.com et Aiera

- Bigdata.com : plugin confirmé installé, activé et autorisé dans Codex.
- Aiera : bundle local confirmé installé.
- Dans la tâche ayant produit cet audit, aucun outil de données Bigdata.com ou
  Aiera n'était exposé au modèle. Aucune donnée de ces fournisseurs n'a donc été
  prétendue, copiée ou injectée dans les scores.
- Le pont `src/data/external_research.py` permet désormais d'importer leurs
  exports JSONL après validation stricte de `published_at`, `available_at`,
  `retrieved_at`, URL, fournisseur et ticker. L'archive normalisée et son
  manifeste SHA-256 sont ensuite fusionnés avec le flux news au même cutoff.
- Dès qu'une nouvelle tâche expose leurs outils, ils peuvent donc compléter les
  transcripts, événements, filings, consensus, guidance et catalyseurs sans
  casser le point-in-time. Aucun export réel n'était disponible dans cette tâche.

## Historique gratuit 2018–2025

- Le catalogue officiel ESMA a livré 32/32 fins de trimestre entre 2018 et 2025.
- 58 fichiers `FULINS_E` ont été téléchargés sous
  `data/raw/historical/esma_firds`, contrôlés puis hachés.
- Le constructeur de snapshots normalisés ISIN/MIC est disponible via
  `python -m src.backtest.free_history build`. Il conserve une disponibilité
  conservatrice à 09:00 Europe/Paris le jour de publication. La passe complète
  de normalisation XML, coûteuse en CPU, reste une étape locale reproductible ;
  les archives brutes officielles et leurs hashes sont déjà acquis.
- Cette couche corrige le biais de survivance de la liste d'instruments actifs.
  Elle ne contient ni historique d'indice, ni ticker fournisseur stable, ni prix
  ajusté, ni état financier IFRS, ni signal reconstruit. Le backtest strict reste
  donc bloqué par conception et aucun résultat 2018–2025 n'est inventé.

## Éléments empêchant encore une analyse « complète »

1. confirmation titre par titre de l'éligibilité PEA ;
2. fondamentaux ESEF/IFRS point-in-time couvrant tout l'univers PEA ;
3. capitalisations et nombres d'actions datés pour chaque société ;
4. consensus, guidance, carnets de commandes et parts de marché historiques ;
5. actualités/transcripts historiques exhaustifs avec dates de disponibilité ;
6. catalogue causal multi-sociétés pour les analogues ;
7. analyste IA critique activé et alimenté uniquement par preuves citées ;
8. jointure des univers FIRDS aux tickers historiques/radiés et aux prix ajustés ;
9. calibration empirique des scores et seuils ;
10. deuxième source de prix et calendriers de marché complets.

## Décision de passage

La phase 12 peut être considérée terminée pour le périmètre gratuit/local prévu
par la spécification. Il n'existe pas de phase 13 dans le document maître. La
suite recommandée est un cycle de durcissement des données et de calibration,
pas l'invention d'une nouvelle phase.
