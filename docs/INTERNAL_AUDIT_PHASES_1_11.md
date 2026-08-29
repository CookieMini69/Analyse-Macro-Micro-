# Audit interne des phases 1 à 11

Version : 1.2.0  
Date : 2026-08-29

## Conclusion

Les moteurs et interfaces des phases 1 à 11 sont implémentés dans les limites
des sources gratuites autorisées. Une valeur absente n'est jamais remplacée par
une hypothèse silencieuse. Le score reste un indicateur de recherche ajusté de
sa couverture, jamais une probabilité de gain ou un conseil d'achat.

| Phase | Résultat | Limite structurante |
|---|---|---|
| 1 Architecture | Conforme | aucune bloquante |
| 2 Prix et drawdowns | Conforme | Yahoo, source publique unique |
| 3 Fondamentaux | Conforme pour déclarants SEC | pas de corpus ESEF européen complet |
| 4 Valorisation | Conforme selon couverture | market caps et hypothèses DCF souvent absents |
| 5 Chocs/macro/news | Conforme et conservateur | GDELT n'est pas une archive news licenciée exhaustive |
| 6 Analogues | Conforme sur le même titre | pas de catalogue causal multi-sociétés |
| 7 Scénarios | Conforme selon données | pas de consensus/guidance datés |
| 8 Scoring | Conforme, non calibré | poids heuristiques |
| 9 Backtest | Moteur conforme | vraie étude 2018–2025 impossible sans univers historiques |
| 10 Excel | Conforme | verdict volontairement `NOT_CALIBRATED` |
| 11 Streamlit | Conforme | analyste IA explicitement désactivé |

## Corrections issues de l'audit

1. expansion à 439 cotations européennes et 13 indices, avec date et sources ;
2. mise à jour des symboles après opérations 2025–2026 ;
3. conversion traçable des cours Londres GBp vers GBP et cache versionné ;
4. préférence pour la devise locale dans les faits SEC IFRS multi-unités ;
5. parallélisme GDELT borné pour l'univers élargi ;
6. champs Phase 10 complets, sans inventer les narratifs IA ;
7. remplacement du placeholder Phase 11 par une application testable.

## Ce qui empêche encore une analyse complète

- snapshots officiels historiques de constituants avec radiations, faillites et
  dates d'entrée/sortie ;
- historiques point-in-time de prix corporate-action-clean et de signaux pour
  2018–2025 ;
- agrégateur ESEF/IFRS autorisé couvrant les sociétés européennes non SEC ;
- capitalisations datées et nombre d'actions pour tout l'univers ;
- consensus, guidance, carnet de commandes et parts de marché historiques ;
- actualités historiques exhaustives et mesure causale des impacts ;
- hypothèses DCF datées pour chaque titre ;
- calibration empirique des scores et seuils ;
- clé/fournisseur distinct pour l'analyste IA critique si l'utilisateur veut
  activer cette fonction ;
- source de prix/exchange de secours et calendriers de séance complets.

SEC et FRED sont configurés ; ECB/Frankfurter, BCE, Cboe, CFTC et GDELT ne
nécessitent pas de nouvelle clé. Ces limites réduisent la couverture, elles ne
bloquent pas le scan prix mondial ni le dashboard.
