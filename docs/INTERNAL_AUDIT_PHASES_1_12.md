# Audit interne des phases 1 à 12

Version : 1.4.0  
Date : 2026-08-30

## Conclusion exécutive

Les douze phases de la stratégie de développement sont implémentées et
testables. Cela ne signifie pas que chaque résultat final demandé par la
spécification est disponible pour chaque société : le système respecte la règle
`data_unavailable` lorsque les sources point-in-time nécessaires manquent.

Le changement de périmètre demandé par l'utilisateur est appliqué : l'univers
par défaut n'est plus mondial. Il contient 319 cotations natives de 11 indices
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
| 9 Backtest | Moteur conforme | contrôles anti-look-ahead/survivorship/leakage et métriques | aucune conclusion 2018–2025 sans archives historiques valides |
| 10 Excel | Conforme | `Candidates`, `All Results`, `Run Metadata`, champs requis | narratifs IA/catalyseurs restent explicitement indisponibles |
| 11 Streamlit | Conforme | pagination, recherche, filtres PEA, détail et graphiques | analyse IA critique inactive |
| 12 Automatisation/alertes | Conforme au périmètre gratuit | runner verrouillé, tâche Windows optionnelle, alertes JSON/CSV/Markdown dédupliquées | email/Telegram/Discord non configurés par choix |

Le run réel post-audit a aussi isolé la nouvelle composition PEA dans
`data/raw/backtest_pea_v1_4_0`, afin de ne jamais écraser la lignée mondiale
v1.3.0 avec une appartenance différente à la même date.

## Validation réelle du 2026-08-30

- 319 titres PEA présélectionnés et 11 benchmarks ;
- 330/330 historiques de prix disponibles ;
- 8/8 paires FX et 9/9 séries macro disponibles ;
- 73 candidats de baisse ;
- 1/73 historique fondamental SEC et 1/73 valorisation disponibles ;
- 73 analyses de choc et 71/73 analogues historiques terminés ;
- 0/73 scénario suffisamment documenté ;
- 1/73 score à couverture suffisante, SAP à 26,05/100 ;
- 0 alerte, puisque le seuil local est 50/100 ;
- archive point-in-time PEA écrite sans collision ;
- rapports créés : `stock_opportunity_scan_20260830T140553Z.csv` et `.xlsx`.

Ces résultats confirment le comportement attendu : le scanner ne transforme pas
les 72 absences de fondamentaux européens en scores artificiels.

## Audit transversal des sections 1 à 40

- Sections 1, 6, 17, 24, 30, 31, 32, 33, 37, 38 et 39 : conformes.
- Sections 8 à 11, 13, 16, 18, 19 et 21 : moteurs implémentés, résultats
  conditionnés à la disponibilité des données réelles.
- Section 7 : écart volontaire demandé après la spécification initiale ; le
  moteur reste configurable et le snapshot mondial est conservé, mais le
  défaut est désormais PEA/EEE.
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
- Dès qu'une nouvelle tâche expose leurs outils, ils peuvent compléter les
  transcripts, événements, filings, consensus, guidance et catalyseurs. Ces
  contenus doivent rester datés, cités et séparés des faits SEC/FRED.

## Éléments empêchant encore une analyse « complète »

1. confirmation titre par titre de l'éligibilité PEA ;
2. fondamentaux ESEF/IFRS point-in-time couvrant tout l'univers PEA ;
3. capitalisations et nombres d'actions datés pour chaque société ;
4. consensus, guidance, carnets de commandes et parts de marché historiques ;
5. actualités/transcripts historiques exhaustifs avec dates de disponibilité ;
6. catalogue causal multi-sociétés pour les analogues ;
7. analyste IA critique activé et alimenté uniquement par preuves citées ;
8. univers historiques sans biais de survivance et titres radiés pour 2018–2025 ;
9. calibration empirique des scores et seuils ;
10. deuxième source de prix et calendriers de marché complets.

## Décision de passage

La phase 12 peut être considérée terminée pour le périmètre gratuit/local prévu
par la spécification. Il n'existe pas de phase 13 dans le document maître. La
suite recommandée est un cycle de durcissement des données et de calibration,
pas l'invention d'une nouvelle phase.

