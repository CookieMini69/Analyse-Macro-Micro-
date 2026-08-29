# Phase 10 — reporting Excel

Date d'audit : 2026-08-29  
État : implémenté et testé

Le pipeline produit un classeur horodaté avec trois feuilles : `Candidates`,
`All Results` et `Run Metadata`. Les en-têtes sont stylés, les filtres et volets
figés, les formats monétaires/pourcentages appliqués, et les pistes d'audit JSON
restent disponibles dans le CSV complet.

Les colonnes minimales du cahier des charges sont couvertes, notamment cause,
type de choc, scores, juste valeur, Bear/Base/Bull, TP1/TP2/TP3, invalidation,
horizon, risque/rendement, sources et timestamp. Les champs narratifs IA
(`Critical Verdict`, catalyseurs et risques) restent explicitement
`AI_ANALYST_DISABLED` ou `data_unavailable`.

Le champ `verdict` vaut `NOT_CALIBRATED`. Le logiciel ne transforme pas un score
heuristique en `BUY` tant que le backtest 2018–2025 sans biais de survivance n'a
pas pu être exécuté. Les cas Bull/Bear textuels ne font que résumer les objectifs
et rendements modélisés déjà auditables.

Contrôles automatisés : sérialisation des champs imbriqués, colonnes de Phase
10, statut non calibré, création CSV/XLSX et présence des trois feuilles.
