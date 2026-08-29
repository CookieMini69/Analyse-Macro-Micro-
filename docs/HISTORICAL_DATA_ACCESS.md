# Accès aux données historiques point-in-time

Date de décision : 2026-08-29

## Décision pour le backtest américain 2018–2025

La source retenue est **Sharadar Direct — Bundle, historique 10 ans**.

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

## Ce qui doit être fourni par l'utilisateur

Pour débloquer immédiatement le backtest américain :

1. souscrire le Bundle Sharadar 10 ans (ou Full History) ;
2. transmettre la clé `SHARADAR_API_KEY` par le canal local sécurisé prévu ;
3. confirmer que l'usage est personnel et conforme à la licence choisie.

Pour la couverture complète demandée, il faut ensuite les droits contractuels
et modalités de livraison LSEG pour Worldscope/Financials PIT, I/B/E/S PIT +
Guidance et MarketPsych/Machine Readable News, ainsi qu'une `OPENAI_API_KEY`.
L'intégration LSEG sera adaptée au mode réellement accordé (API, fichiers ou
SFTP) ; inventer un schéma avant le contrat rendrait le connecteur fragile.
