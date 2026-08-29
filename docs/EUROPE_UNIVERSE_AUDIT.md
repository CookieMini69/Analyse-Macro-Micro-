# Audit de l'univers européen

Date d'observation : 2026-08-29  
Version : 1.2.0

## Périmètre effectivement chargé

Le fichier `config/universe_europe.csv` contient 439 cotations uniques et 481
appartenances, car Airbus et ArcelorMittal appartiennent à deux indices. Après
fusion avec les 44 lignes internationales existantes, le scanner charge 483
titres primaires.

| Indice | Constituants |
|---|---:|
| CAC 40 | 40 |
| DAX 40 | 40 |
| FTSE 100 | 100 |
| AEX 25 | 25 |
| BEL 20 | 20 |
| SMI 20 | 20 |
| IBEX 35 | 35 |
| FTSE MIB 40 | 40 |
| OMX Stockholm 30 | 30 |
| OMX Copenhagen 25 | 25 |
| OMX Helsinki 25 | 25 |
| OBX 25 | 25 |
| PSI | 16 |

Les champs `listing_country` et `country_basis=listing_market` décrivent la
place de cotation, pas nécessairement le domicile juridique de l'émetteur.

## Provenance et corrections de symboles

Le générateur public conserve l'URL de chaque table et la date du snapshot.
La composition PSI provient de la page officielle Euronext. Des avis officiels
Nasdaq/Euronext/émetteur complètent les tables publiques lorsqu'une opération
sur titre est plus récente : Nordea `NDA-DK.CO`, Lumo Homes `LUMO.HE`, CMB.TECH
`CMBTO.OL` et Roche `ROP.SW`.

Yahoo exprime les cotations de Londres en pence. Les 100 lignes FTSE 100 portent
un facteur 0,01 traçable ; le moteur convertit OHLC/adjusted close en GBP sans
modifier les volumes. Le cache inclut le facteur pour empêcher la réutilisation
d'une ancienne série dans la mauvaise unité.

Yahoo ne fournit pas une série OBX officielle stable. `OBXD.OL`, ETF DNB OBX,
est utilisé uniquement comme proxy de performance relative. Il ne doit pas être
présenté comme l'indice officiel.

## Validation réelle

- chargement : 483 titres, 25 pays de cotation, 7 devises ;
- collisions : aucune collision de ticker après fusion ;
- prix court terme : 514/514 séries disponibles, benchmarks auxiliaires inclus ;
- tests : contrôle des 13 appartenances, dates, URLs et conversion GBp/GBP.

## Limite point-in-time

Ce fichier est un snapshot live daté, pas un historique officiel de composition.
Les pages publiques secondaires peuvent accuser un retard ; les corrections
connues sont sourcées, mais une licence d'index ou des snapshots archivés restent
nécessaires pour un backtest sans biais de survivance.
