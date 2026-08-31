# Audit des sources gratuites et de l'univers mondial

Date de l'audit : 2026-08-30

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

## Univers mondial v2 livré

Le fichier `config/universe.yaml` charge désormais **17 041 cotations uniques** :

- 5 806 actions US supplémentaires issues de Nasdaq Trader et jointes au
  mapping CIK/ticker/exchange SEC, auxquelles s'ajoutent les lignes US/ADR
  enrichies dans le YAML ;
- 439 cotations de 13 grands indices européens ;
- 3 903 actions JPX, 2 287 actions NSE India, 1 759 actions ASX et 2 803 actions
  HKEX, soit 10 752 cotations natives issues de fichiers officiels.

`scripts/update_us_universe.py` et `scripts/update_world_universe.py`
reconstruisent ces snapshots. Le fichier
`config/universe_world_native.manifest.json` conserve URL, date d'observation,
date de récupération, taille brute, nombre de lignes et SHA-256 de chaque
annuaire. Les ETF, produits structurés, options, droits et dettes identifiables
sont exclus ; les actions ordinaires et certificats d'actions explicitement
admis restent retenus. Cette construction permet :

1. un téléchargement de prix homogène ;
2. les dépôts 20-F/40-F gratuits ;
3. la taxonomie standard IFRS quand elle est publiée dans Company Facts ;
4. l'absence de conversion implicite dans les valorisations.

Il ne s'agit toujours pas littéralement de toutes les actions du monde, ni d'un
historique anti-survivance. Canada natif, Chine continentale, Corée, Taïwan,
Amérique latine, Afrique et plusieurs petites places ne sont pas encore couverts
par un mapping officiel gratuit vers les tickers Yahoo. Aucun fournisseur
gratuit unique ne garantit l'identité, les prix
ajustés, les fondamentaux point-in-time et les retraits de cote mondiaux.

Le changement de méthodologie ouvre une nouvelle lignée d'archives immuables
dans `data/raw/backtest_global_v2_0_0`. Les anciennes lignées restent conservées
intactes et ne sont jamais réécrites.

## Stratégie d'exécution mondiale

Tous les titres passent le même filtre prix sur deux ans, par lots de 100 avec
cache individuel et provenance. Après détection des baisses, seuls les candidats
rechargent l'historique maximal nécessaire aux analogues. Tous les candidats
ayant un CIK passent SEC EDGAR ; un titre non-SEC reste explicitement sans
fondamentaux au lieu de recevoir une valeur inventée. Les actualités publiques
restent plafonnées à 250 candidats selon la sélection reproductible décrite
ci-dessous.

Le classement profond appelle les actualités publiques pour 250 titres au plus.
Tous les titres passent le filtre prix et tous les candidats prix passent les
fondamentaux/valorisations ; le plafond ne concerne que l'étape externe GDELT.
La sélection est reproductible : 80 % par composite préliminaire ajusté de sa
couverture et 20 % réservés aux baisses les plus sévères.
