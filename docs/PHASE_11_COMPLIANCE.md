# Phase 11 — dashboard Streamlit

Date d'audit : 2026-08-29  
État : implémenté et testé

## Fonctions livrées

- chargement automatique du dernier scan complet ;
- date de mise à jour, compteurs et classement des opportunités ;
- filtres pays, secteur, indice, score, drawdown, capitalisation, nature du choc,
  résilience et horizon ;
- fiche entreprise avec cours, MM50, MM200, fondamentaux SEC point-in-time,
  ratios de valorisation, preuves/sources, scénarios Bear/Base/Bull et
  invalidations ;
- affichage explicite de la couverture et de toute donnée indisponible ;
- panneau analyste IA désactivé sans fabrication de texte.

L'interface est une vue en lecture seule des artefacts du pipeline. Modifier un
filtre ne recalcule pas un signal et ne change aucune archive.

## Lancement

```powershell
python -m streamlit run dashboard/app.py
```

Ouvrir ensuite `http://localhost:8501`. Pour actualiser les données, exécuter
`python -m src.pipeline`, puis rafraîchir la page.

## Tests

Les fonctions de découverte, décodage JSON, filtrage, lecture des prix,
sélection du dernier fondamental et extraction d'un horizon sont couvertes par
pytest. Un test Streamlit et un parcours réel dans le navigateur vérifient le
rendu, les widgets et l'absence d'exception.
