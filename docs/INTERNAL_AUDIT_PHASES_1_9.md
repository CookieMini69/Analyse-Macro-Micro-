# Audit interne des phases 1 à 9

Version : 1.0.1
Date d'audit : 2026-08-29

## Résultat exécutif

Le dépôt respecte la progression 1 à 9 du cahier des charges pour le périmètre
de données effectivement disponible. Les valeurs absentes restent nulles et
traçables. Les audits ont corrigé cinq écarts internes :

1. collecte FX datée ECB/Frankfurter et conversion effective des prix et
   capitalisations en USD/EUR, avec conservation de la devise originale ;
2. réinjection des durées de récupération et précédents de la phase 6 dans le
   Temporary Shock Score de la phase 5 ;
3. moteur de backtest strict, exports, benchmarks, coûts et archives live
   immuables vérifiées par SHA-256.
4. sélection de la dernière clôture exploitable lorsque Yahoo expose une bougie
   courante incomplète ;
5. sélection auditable du premier signal journalier si le scanner est relancé
   plusieurs fois le même jour, sans doublon ni sélection rétrospective.

La suite de régression finale contient 110 tests. Un résultat synthétique de
test ne constitue pas une validation statistique de la stratégie.

## Matrice de conformité

| Phase | État | Contrôles principaux |
|---|---|---|
| 1 — architecture/config/modèles | Conforme | Arborescence, YAML, `.env.example`, Pydantic strict, provenance et statuts |
| 2 — prix/univers/drawdowns | Conforme sur univers fourni | OHLCV, adjusted close, dates, devise/place, tous les horizons, MA/RSI/volatilité/bêta/relatifs |
| 3 — fondamentaux | Conforme SEC US annuel | Dates réelles d'acceptation, 10-K/10-K/A, croissance, marges, ROE/ROIC, bilan, cash-flow, score qualité |
| 4 — valorisation | Conforme selon couverture | P/E, EV/EBITDA, P/FCF, historique/secteur, DCF sourcé, reverse DCF, normalisé |
| 5 — macro/news/choc | Conforme avec limites de source | Vintages ALFRED, expositions configurables, GDELT, taxonomie, corroboration et critères manquants explicites |
| 6 — analogues | Conforme même titre | Baisse, durée, fondamentaux/valorisation point-in-time, récupération et rendements ultérieurs |
| 7 — scénarios | Conforme selon données | Bear/base/bull, 3/6/12/18/24 mois, targets modèles, invalidations fondamentales, risk/reward |
| 8 — scoring | Conforme, non calibré | Sept sous-scores, poids 20/20/15/15/10/10/10, couverture, qualité, score ≠ probabilité |
| 9 — backtest | Moteur conforme, étude réelle en attente de données | 2018–2025 configurable, cinq buckets, métriques requises, benchmark régional fourni par signal, coûts et contrôles anti-biais |

## Contrôles point-in-time de la phase 9

Le moteur refuse de calculer une performance si l'un des contrôles suivants
échoue :

- disponibilité du signal postérieure à sa date ;
- signal non validé point-in-time ;
- archive source absente, identifiant absent ou empreinte SHA-256 incorrecte ;
- titre absent de l'instantané daté de l'univers ;
- prix invalides, non positifs ou dupliqués ;
- benchmark régional sans historique ;
- absence de séance d'entrée strictement postérieure au signal ou de séance de
  sortie au terme de la durée de détention.

Les exécutions live du scanner archivent automatiquement le résultat complet,
le CSV des signaux et l'univers du jour sous `data/raw/backtest/`. Une relance
actuelle avec un ancien `--as-of` n'est jamais marquée comme archive historique
valide. Le chargeur recalcule le SHA-256 du JSON avant de valider le signal.

Le portefeuille applique une pondération égale entre positions actives, place
le portefeuille en cash (rendement nul) lorsqu'aucune position n'est active,
entre à la première séance après le signal, sort au premier cours disponible au
terme configuré et déduit les coûts à l'entrée et à la sortie. Le benchmark suit
la même fenêtre, sans coûts de transaction.

## Éléments non implémentables sans données ou accès supplémentaires

Ces éléments ne sont pas remplacés par des estimations :

- **Backtest réel 2018–2025** : il manque les instantanés d'univers de chaque
  date, incluant titres radiés/faillis, ainsi que les archives immuables des
  signaux reconstruits avec les données disponibles à l'époque. Tester le seul
  univers actuel créerait un biais de survivance et le moteur le refuse.
- **Fondamentaux hors SEC US** : les rapports IFRS, 20-F/40-F, rapports
  trimestriels et données IR multi-pays ne disposent pas encore d'un fournisseur
  normalisé. Il faut un fournisseur autorisé ou un corpus daté de documents.
- **Actualités historiques strictes** : GDELT récent ne garantit ni une archive
  complète ancienne ni toujours l'heure originale de publication. Il faut une
  archive news point-in-time licenciée ou fournie par l'utilisateur.
- **Guidance, consensus analystes et impacts causaux quantifiés du choc** : il
  faut des historiques datés de guidance/estimations et des documents primaires.
  Ces critères restent `data_unavailable` et réduisent la couverture.
- **Analyste IA critique** : les fichiers `src/ai/` restent une frontière ; une
  implémentation réelle requiert le choix d'un fournisseur/modèle et une clé API
  distincte. Aucun texte pseudo-IA n'est généré pour donner une fausse impression
  de conformité.
- **Référentiel causal multi-entreprises** : la phase 6 compare des épisodes du
  même titre ; les analogues COVID/2008/chocs pétroliers étiquetés exigent un
  catalogue événementiel daté et sourcé.

Les phases 10 (reporting Excel final), 11 (dashboard Streamlit) et 12
(automatisation/alertes) sont volontairement futures selon l'ordre imposé par le
cahier des charges.

## Accès précis à fournir pour lever ces limites

1. un jeu d'instantanés d'univers 2018–2025, avec titres retirés de cote et dates
   d'appartenance ;
2. des archives de signaux/données brutes réellement conservées à chaque date,
   ou un fournisseur historique point-in-time couvrant fondamentaux et news ;
3. si le périmètre devient mondial, l'accès choisi aux états financiers IFRS et
   rapports trimestriels ;
4. si l'analyste critique doit être activé, le fournisseur, le modèle autorisé
   et sa clé API ;
5. facultativement, un flux officiel/licencié de prix et de constituants pour
   remplacer ou corroborer Yahoo.

Les accès SEC EDGAR et FRED sont déjà configurés localement. Le FX
ECB/Frankfurter ne nécessite pas de clé.

## Nouvel audit d'accès du 2026-08-29

Une source exploitable a été retenue et intégrée : Sharadar Direct Bundle avec
au moins dix ans d'historique. Le bootstrap contrôle séparément `tickers`,
`sp500`, `stocks`, `fundamentals`, `daily`, `actions` et `events`, puis vérifie
les schémas et empreintes SHA-256 locales. Le rapport machine courant est
`reports/historical_access_audit.json`.

Résultat réel de la machine : `SHARADAR_API_KEY` absente, sept tables
inaccessibles, `core_backtest_ready=false`, `full_spec_ready=false`. La phase 10
n'est donc pas ouverte. Cette décision respecte l'exigence de ne passer à la
phase suivante que lorsque la phase actuelle fonctionne sur ses données réelles.

Les accès complémentaires sélectionnés sont LSEG Worldscope/Financials
Point-in-Time (IFRS mondial), I/B/E/S Point-in-Time + Guidance, LSEG
MarketPsych/Machine Readable News (archives causales datées), et OpenAI Responses
API avec `gpt-5.6-terra` pour l'analyste critique. Voir
`docs/HISTORICAL_DATA_ACCESS.md`.
