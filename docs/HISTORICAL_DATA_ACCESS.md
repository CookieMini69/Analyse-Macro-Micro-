# Accès aux données historiques point-in-time

Date de décision : 2026-08-29

## Décision actuelle : mode gratuit, sans abonnement

Le scanner live et l'archivage progressif fonctionnent sans abonnement payant.
Le socle gratuit est désormais : SEC EDGAR (10-K/20-F/40-F), FRED/ALFRED, BCE,
Cboe, CFTC, Yahoo, GDELT et ECB/Frankfurter FX. Les réponses datées sont mises
en cache et chaque exécution live peut produire une archive immuable avec hash.

Ce mode ne prétend toutefois pas recréer aujourd'hui un véritable univers
2018–2025 sans biais de survivance : aucune source gratuite identifiée ne réunit
à elle seule les radiations, changements d'identifiants, compositions historiques
mondiales et fondamentaux as-reported. Le moteur strict conserve donc
`data_unavailable` tant que ces archives ne sont pas réellement présentes. Il
construira gratuitement son propre historique prospectif à partir des scans.

Les séries contextuelles historiques gratuites disponibles immédiatement sont :

- VIX via FRED/ALFRED, donc avec vintage connu au cutoff ;
- taux BCE via SDMX et `VALID_FROM`/`VALID_TO` ;
- put/call Cboe depuis la page quotidienne datée (historique visible depuis 2019) ;
- positions CFTC COT, avec délai prudent de sept jours après la date de position ;
- fondamentaux SEC filtrés par heure d'acceptation/date de dépôt.

## Option payante conservée mais non requise

L'adaptateur **Sharadar Direct — Bundle, historique 10 ans** reste disponible si
le choix change un jour, mais il n'est ni activé ni requis actuellement.

Lien d'abonnement : <https://sharadar.com/subscribe>

Le niveau 10 ans suffit à couvrir 2018–2025 à la date de cet audit. Il réunit
les deux ensembles indispensables (Fundamentals et Prices) dans un seul accès.
Le tarif affiché par le fournisseur au jour de l'audit est de 49 USD par mois
ou 399 USD par an. Le plan à 29 USD par mois ne donne que cinq ans d'historique
et ne convient donc pas.

SEC EDGAR demeure prioritaire pour les fondamentaux américains et surtout pour
les horodatages réels d'acceptation des publications. Sharadar sert de
référentiel historique anti-survivance, de source de cours/valorisations et de
contre-vérification `as-reported`. Si Sharadar ne fournit qu'une date journalière,
le signal n'est éligible qu'à la séance suivante ; il ne remplace jamais une
heure SEC plus précise par une heure inventée.

Tables requises par l'intégration :

| Table | Usage anti-biais |
|---|---|
| `tickers` | référentiel actif/radié et identifiant permanent |
| `sp500` | ajouts, retraits et instantanés historiques de l'univers |
| `stocks` | cours ajustés et non ajustés, titres radiés inclus |
| `fundamentals` | dimensions as-reported `ARQ`, `ARY`, `ART` et date de publication |
| `daily` | capitalisation et multiples quotidiens point-in-time |
| `actions` | splits, dividendes, changements de ticker, cotations/radiations |
| `events` | événements matériels issus des formulaires SEC 8-K |

La clé doit être ajoutée uniquement au fichier local `.env` :

```dotenv
SHARADAR_API_KEY=la_cle_personnelle
```

Elle ne doit jamais être envoyée dans Git, un rapport ou une capture. Le client
utilise les paramètres HTTP séparément, n'enregistre pas les URL signées et
produit un manifeste SHA-256 sans secret pour chaque archive.

## Commandes préparées

Contrôler la clé et les droits sur les sept tables, sans téléchargement :

```powershell
python -m src.backtest.dataset access
```

Télécharger les archives complètes et créer les manifestes d'intégrité :

```powershell
python -m src.backtest.dataset download
```

Recontrôler les archives locales et leurs schémas :

```powershell
python -m src.backtest.dataset audit-local
```

Le rapport est écrit dans `reports/historical_access_audit.json`. Même si les
archives sont valides, `core_backtest_ready` reste faux jusqu'à la reconstruction
des signaux datés et l'exécution réussie du moteur strict de phase 9. Une simple
présence de fichiers n'est donc jamais présentée comme un backtest validé.

## Accès complémentaires

Sharadar résout le noyau américain et apporte les événements SEC matériels,
mais ne fournit pas tout le périmètre mondial/analystes/news demandé.

### Hors États-Unis

Pour un univers mondial IFRS, le choix institutionnel cohérent est **LSEG
Worldscope/Financials Point-in-Time**. SEC EDGAR reste utilisable pour les
émetteurs étrangers déposant des 20-F/40-F/6-K aux États-Unis, mais ne constitue
pas une couverture mondiale complète.

Demande d'accès : <https://www.lseg.com/en/data-catalogue/company-data>

### Consensus et guidance

Le choix est **LSEG I/B/E/S Point-in-Time + I/B/E/S Guidance**. Il faut demander
explicitement les instantanés historiques datés, pas seulement le consensus
actuel.

Demande d'accès :
<https://www.lseg.com/en/data-analytics/financial-data/company-data/ibes-estimates>

### Actualités et impacts causaux

Pour les variables de choc historiques, le choix est **LSEG MarketPsych Research
Accelerator / Machine Readable News**, avec archive point-in-time et identifiants
d'entités stables. Les codes 8-K de Sharadar constituent une preuve primaire
utile mais ne remplacent pas l'actualité externe ni une mesure causale.

Demande d'accès :
<https://www.lseg.com/en/data-analytics/market-data/quantitative-economic-data-solutions/marketpsych-analytics-and-models>

### Analyste IA critique

La configuration retenue, encore désactivée, est :

- fournisseur : OpenAI ;
- API : Responses API ;
- modèle : `gpt-5.6-terra` ;
- secret distinct : `OPENAI_API_KEY` ;
- stockage fournisseur : `false` dans la configuration prévue.

Création de clé : <https://platform.openai.com/api-keys>

Le modèle équilibre qualité et coût pour une analyse bull/bear structurée. La
clé API ne doit pas être confondue avec l'abonnement ChatGPT et doit être
alimentée séparément avant activation.

## Accès utilisateur requis actuellement

**Aucun nouvel accès n'est requis** pour le mode gratuit actuel. La clé FRED et
le SEC User-Agent déjà configurés suffisent ; BCE, Cboe et CFTC sont sans clé.

Sharadar, LSEG et une clé OpenAI restent des extensions facultatives. Elles ne
seront demandées que si l'utilisateur décide explicitement d'activer ces briques.
