# Plan d'accès mondial gratuit

Date de vérification : 2026-08-30

## Limite à ne pas masquer

Il n'existe pas de source gratuite unique qui fournisse simultanément toutes
les actions cotées dans le monde, les titres radiés, des prix ajustés garantis,
les fondamentaux point-in-time, les consensus datés et les actualités
historiques avec des droits de réutilisation homogènes. « Tout le monde » doit
donc être construit exchange par exchange et chaque couverture doit être
mesurée séparément.

## Sources gratuites exploitables

| Besoin | Source | Clé | Utilisation et limite |
|---|---|---:|---|
| Cotations US actuelles | [Nasdaq Trader](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs) + [mapping SEC](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) | non | Intégré : snapshot actuel, pas historique anti-survivance. |
| Identifiants mondiaux | [OpenFIGI](https://www.openfigi.com/api/documentation) | facultative mais recommandée | Mapping ISIN/FIGI/MIC/ticker ; ce n'est ni un flux de prix ni un corpus fondamental. Sans clé : 25 requêtes/minute et 10 mappings/requête ; avec clé gratuite : 25/6 secondes et 100 mappings/requête. |
| Fondamentaux US/ADR | [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | non, User-Agent obligatoire | Intégré avec date réelle d'acceptation/dépôt. |
| Fondamentaux Europe | [filings.xbrl.org](https://filings.xbrl.org/docs/api) | non | API ESEF/xBRL-JSON gratuite. Le dépôt reconnaît lui-même qu'il n'est pas complet et que la date d'ajout peut être retardée par rapport au dépôt officiel. |
| Comptes UK | [Companies House](https://developer.company-information.service.gov.uk/) | gratuite | Historique de dépôts et documents ; normalisation des comptes et correspondance avec les titres cotés à construire. |
| Titres radiés US | [Alpha Vantage LISTING_STATUS](https://www.alphavantage.co/documentation/) | gratuite | États actif/radié et date historique depuis 2010. Ce n'est pas un historique mondial et les quotas gratuits empêchent un prix quotidien massif. |
| Liste japonaise actuelle | [JPxData Portal](https://www.jpx.co.jp/english/markets/data-catalog/) | non pour le CSV actuel | Liste actuelle téléchargeable ; l'historique, certaines références et les prix complets relèvent d'offres distinctes. |
| Rapports UE futurs | [ESAP](https://finance.ec.europa.eu/financial-markets/company-reporting-and-auditing/company-reporting/transparency-requirements-listed-companies_en) | non | Déploiement public à partir de mi-2027 ; ne résout pas aujourd'hui l'historique mondial. |
| Macro/FX/options | FRED/ALFRED, BCE, Cboe, CFTC | FRED seulement | Déjà intégré ; aucune clé additionnelle pour BCE/Cboe/CFTC. |
| Analyste IA local | [Ollama](https://docs.ollama.com/windows) | non | API locale gratuite ; nécessite installation, espace disque et assez de RAM/GPU. Le texte doit rester contraint aux preuves du pipeline. |

## Ce que l'utilisateur peut faire

Priorité 1 — créer gratuitement un compte OpenFIGI et placer la clé uniquement
dans `.env` :

```dotenv
OPENFIGI_API_KEY=...
```

Priorité 2 — créer une clé Alpha Vantage gratuite afin de figer les listes
actives/radiées US par date :

```dotenv
ALPHAVANTAGE_API_KEY=...
```

Priorité 3 — si la couverture britannique est importante, créer une application
Companies House et ajouter sa clé :

```dotenv
COMPANIES_HOUSE_API_KEY=...
```

Priorité 4 — pour un analyste IA sans coût par appel, installer Ollama sur
Windows, choisir un modèle adapté à la mémoire disponible et communiquer le nom
exact du modèle. L'intégration restera locale et désactivée tant que son
évaluation anti-hallucination n'est pas validée.

Ne jamais envoyer ces clés dans une capture, un rapport ou Git. Le fichier
`.env` est ignoré par le dépôt.

## Ordre d'extension recommandé

1. OpenFIGI pour stabiliser ISIN/FIGI/MIC et dédupliquer les doubles cotations.
2. ESEF pour la croissance, les marges, le bilan et le cash-flow européens.
3. Répertoires officiels JPX, HKEX, ASX, TSX, NSE/BSE, SGX, KRX et JSE, chacun
   avec un snapshot daté et ses conditions d'utilisation.
4. Prix quotidiens par lots avec cache, reprise et contrôle d'ajustement.
5. Alpha Vantage uniquement pour reconstruire les entrées/sorties US ; ne pas
   le présenter comme une solution mondiale exhaustive.
6. Consensus, guidance et causalité : collectes IR/réglementaires datées au cas
   par cas tant qu'aucun corpus gratuit complet n'existe.


