# Audit des sources gratuites et de l'univers mondial

Date de l'audit : 2026-08-29

## Décision

Le mode par défaut ne dépend d'aucun abonnement payant. Les idées proposées ont
été ramenées à leurs sources primaires quand cela améliore la traçabilité.

| Élément | Décision | Intégration |
|---|---|---|
| [Trading Economics](https://docs.tradingeconomics.com/get_started/) | Optionnel seulement | API riche et mondiale, mais clé/plan requis par la documentation actuelle. Aucun appel obligatoire. |
| BCE | Retenu | API SDMX officielle sans clé ; révisions filtrées par `VALID_FROM` et `VALID_TO`. |
| [Tradingster](https://www.tradingster.com/help) | Non aspiré | Utile pour visualiser le COT, mais pas d'API officielle identifiée ; données récupérées directement auprès de la CFTC. |
| Put/call ratio | Retenu | Ratio total issu de la page quotidienne officielle Cboe, avec date de marché conservée. |
| VIX | Déjà retenu | `VIXCLS` via FRED/ALFRED pour disposer du vintage point-in-time ; CSV Cboe utilisé comme source primaire de contrôle. |
| Positionnement | Retenu | CFTC Public Reporting Environment, S&P 500 leveraged money net / open interest. |

## Règles point-in-time

- ALFRED : période temps réel renvoyée par l'API.
- BCE : seule la version valide au cutoff est conservée.
- Cboe : le jour sélectionné par le serveur est conservé ; week-ends et jours
  fériés remontent au dernier jour de marché disponible.
- CFTC : la date de position du mardi n'est jamais assimilée à sa publication ;
  un délai prudent de sept jours est appliqué, y compris dans les backtests.
- Une donnée absente reste `data_unavailable` ; aucune interpolation n'est faite.

## Univers mondial livré

Le fichier `config/universe.yaml` contient 44 titres de 18 pays émetteurs. Les
29 ajouts internationaux sont des ADR/actions cotés aux États-Unis, en USD, avec
CIK vérifié dans le mapping officiel SEC. Les comparaisons pays utilisent des ETF
en USD. Cette construction permet :

1. un téléchargement de prix homogène ;
2. les dépôts 20-F/40-F gratuits ;
3. la taxonomie standard IFRS quand elle est publiée dans Company Facts ;
4. l'absence de conversion implicite dans les valorisations.

Il ne s'agit pas d'un indice mondial exhaustif ni d'un historique anti-survivance.
Les titres natifs, les sociétés sans dépôt SEC et les radiations historiques
nécessitent toujours un corpus séparé avant un backtest strict.

Le changement de méthodologie ouvre une nouvelle lignée d'archives immuables
dans `data/raw/backtest_global_v1_0_2`. L'ancien snapshot 15 titres est conservé
intact dans `data/raw/backtest` et n'est jamais réécrit.

## Vérification réelle

- 117 tests automatisés réussis ;
- 44/44 titres et 18/18 ETF pays téléchargés avec succès lors du smoke test ;
- VIX, taux BCE, put/call Cboe et COT CFTC récupérés avec succès ;
- contrôles SEC réels réussis sur ASML, Novo Nordisk, TSMC et Shopify, incluant
  les formulaires étrangers et les unités IFRS locales.
