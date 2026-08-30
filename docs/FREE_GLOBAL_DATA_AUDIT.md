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

## Univers élargi livré

Le fichier `config/universe.yaml` charge désormais 6 289 lignes uniques : 5 850
actions cotées aux États-Unis et déclarantes SEC, dont 44 lignes globales/ADR
enrichies manuellement, plus 439 cotations européennes appartenant à 13 indices.
Le snapshot US daté du 2026-08-28 est reconstruit par
`scripts/update_us_universe.py` depuis les répertoires officiels Nasdaq Trader
et le mapping CIK/ticker/exchange de la SEC. Les ETF, tests, warrants, droits,
unités, préférentielles et instruments de dette identifiables sont exclus.
Cette construction permet :

1. un téléchargement de prix homogène ;
2. les dépôts 20-F/40-F gratuits ;
3. la taxonomie standard IFRS quand elle est publiée dans Company Facts ;
4. l'absence de conversion implicite dans les valorisations.

Il ne s'agit toujours ni de « toutes les actions du monde », ni d'un historique
anti-survivance. Les cotations locales hors Europe/États-Unis, les sociétés sans
dépôt SEC et les radiations historiques nécessitent des catalogues d'exchanges
séparés. Aucun fournisseur gratuit unique ne garantit l'identité, les prix
ajustés, les fondamentaux point-in-time et les retraits de cote mondiaux.

Le changement de méthodologie ouvre une nouvelle lignée d'archives immuables
dans `data/raw/backtest_global_v1_3_0`. Les anciennes lignées restent conservées
intactes et ne sont jamais réécrites.

## Vérification réelle

- 134 tests automatisés réussis, sans avertissement après correction de la
  lecture du grand CSV ;
- 6 319/6 320 historiques de prix disponibles lors du scan mondial réel, soit
  6 288/6 289 titres primaires et 31/31 références ;
- 3 189 candidats techniques, 3 000 historiques fondamentaux disponibles,
  1 183 valorisations exploitables, 2 464 analyses avec analogues historiques,
  1 254 scénarios et 1 427 Opportunity Scores qualifiés par leur couverture ;
- VIX, taux BCE, put/call Cboe et COT CFTC récupérés avec succès ;
- contrôles SEC réels réussis sur ASML, Novo Nordisk, TSMC et Shopify, incluant
  les formulaires étrangers et les unités IFRS locales.

Le classement profond appelle les actualités publiques pour 250 titres au plus.
Tous les titres passent le filtre prix et tous les candidats prix passent les
fondamentaux/valorisations ; le plafond ne concerne que l'étape externe GDELT.
La sélection est reproductible : 80 % par composite préliminaire ajusté de sa
couverture et 20 % réservés aux baisses les plus sévères.

