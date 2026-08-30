# Phase 11 — dashboard Streamlit

Date d'audit : 2026-08-30
État : implémenté et testé

## Fonctions livrées

- chargement automatique du dernier scan complet ;
- repli sur le dernier rapport complet si le CSV le plus récent est tronqué ;
- date de mise à jour, compteurs et classement des opportunités ;
- filtres pays, secteur, indice, score, drawdown, capitalisation, nature du choc,
  résilience et horizon ;
- fiche entreprise avec cours, MM50, MM200, fondamentaux SEC point-in-time,
  ratios de valorisation, preuves/sources, scénarios Bear/Base/Bull et
  invalidations ;
- affichage explicite de la couverture et de toute donnée indisponible ;
- panneau analyste IA désactivé sans fabrication de texte.
- recherche globale, remise à zéro déterministe et pagination de toutes les
  lignes (aucune limite silencieuse à 50 titres) ;
- comparaison entre la taille du rapport affiché et l'univers actuellement
  configuré, avec alerte explicite si le rapport est ancien ou incomplet ;
- recherche de fiche bornée pour rester utilisable avec plusieurs milliers de
  titres et cache de lecture invalidé par la date du rapport.

L'interface est une vue en lecture seule des artefacts du pipeline. Modifier un
filtre ne recalcule pas un signal et ne change aucune archive.

## Lancement

```powershell
python -m streamlit run dashboard/app.py
```

Ouvrir ensuite `http://localhost:8501`. Pour actualiser les données, exécuter
`python -m src.pipeline`, puis rafraîchir la page.

## Tests

Les fonctions de découverte, validation, décodage JSON, filtrage, lecture des prix,
sélection du dernier fondamental et extraction d'un horizon sont couvertes par
pytest. Un test Streamlit et un parcours réel dans le navigateur vérifient le
rendu, les widgets, la pagination et l'absence d'exception.

Audit réel final : le dashboard charge le rapport de 6 289 lignes, expose les
6 288 cours disponibles, les 3 189 candidats et les 1 427 scores qualifiés sans
tronquer le tableau. La lecture utilise `low_memory=False` afin de stabiliser les
types des 147 colonnes du rapport et d'éviter les avertissements Pandas.

