# Les scripts : à quoi sert chacun

Vingt et un scripts, dont **trois seulement servent au quotidien**. Un mémoire n'a
pas à les énumérer : il cite ce tableau, et détaille éventuellement ces trois-là.

## 1. Au quotidien — trois commandes, rien de plus

| Commande | Quand la lancer | Ce qu'elle fait |
|---|---|---|
| `python scripts/maintenance.py` | après un nouvel export ERP | reconstruit l'entrepôt (ETL `python -m etl.construire`, contrôles compris), recalcule les indicateurs, signale les écarts |
| `python scripts/retrain_all.py` | après une mise à jour de scikit-learn, ou pour rafraîchir les modèles | ré-entraîne les modèles, vérifie que les métriques tiennent, **et rapatrie les résultats du terrain** (boucle d'action) |
| `python scripts/preflight_demo.py` | 30 minutes avant une soutenance | contrôle un par un tous les points qui peuvent faire échouer la démo |

## 2. Générateurs de documents — la documentation n'est jamais recopiée à la main

| Commande | Document produit | Pourquoi c'est généré |
|---|---|---|
| `python scripts/tableau_metriques.py` | le tableau des modèles (AUC, accuracy, statut) | les chiffres sont relus dans `reports/*.json` : un tableau recopié finit toujours par mentir |
| `python scripts/tableau_tests.py` | `docs/TESTS.md` | les comptages viennent de la suite elle-même |
| `python scripts/generer_grille_validation.py` | `reports/validation_metier.csv` | pré-remplit la grille de validation avec de vrais cas de la plateforme |
| `python scripts/schema_entrepot.py` | `docs/data_warehouse/schema_etoile.{svg,png}` | le schéma est lu dans l'entrepôt construit : il ne peut pas décrire des tables qui n'existent pas |
| `python scripts/diagnostics_shap.py` | `reports/explicabilite_marge.json` | les quatre chiffres publiables sur l'explication SHAP : additivité, valeur de base, importance globale, accord avec une méthode indépendante |

## 3. Les analyses qui ont fondé une décision — à ne pas relancer, à citer

Ces scripts ne tournent pas en production : chacun a tranché une question, une
fois, et son résultat est cité dans le mémoire. Les garder, c'est garder la
**preuve** que la décision a été mesurée et non supposée.

| Script | La question tranchée | Où le résultat est cité |
|---|---|---|
| `audit_ca_corrige.py` | de combien le chiffre d'affaires brut était-il faux ? | `docs/NOTE_SOUTENANCE.md`, `docs/DEMO.md` |
| `audit_toutes_sources.py` | le même défaut existe-t-il sur les achats et les lignes ? | `docs/NOTE_SOUTENANCE.md` |
| `audit_trou_temporel.py` | pourquoi 27 mois sans facture, et l'effondrement de 2020 ? | `docs/NOTE_SOUTENANCE.md` |
| `diag_famille_produit.py` | la famille produit est-elle réellement renseignée ? | `reports/METRICS_REPORT.md` |
| `diag_maturite.py` | y a-t-il quelque chose à apprendre du taux de maturité du carnet ? | `reports/METRICS_REPORT.md` |
| `verif_carnet_h3.py` | une contradiction interne du carnet d'échéances | `reports/METRICS_REPORT.md` |
| `verif_pic_echeances.py` | d'où vient le pic d'échéances de début 2026 ? | `reports/METRICS_REPORT.md` |
| `verif_reproductibilite.py` | deux exécutions donnent-elles le même résultat ? | `reports/METRICS_REPORT.md` |

## 4. Installation ponctuelle

| Script | Usage |
|---|---|
| `setup_tesseract_fr.py` | installe le pack français de Tesseract, sans droits administrateur (`docs/OCR.md`) |
| `setup_avatar.py` | installe un modèle 3D local pour l'avatar (`docs/AVATAR_3D.md`) |

## 5. Consultation et entretien du dépôt

| Script | Usage |
|---|---|
| `voir_base.py` | ouvre l'interface web de DuckDB sur l'entrepôt, en lecture seule (http://localhost:4213) |
| `nettoyer_projet.ps1` | PowerShell, depuis la racine : `.\scripts\nettoyer_projet.ps1 -Simulation`. Range hors du projet ce que le code n'utilise plus : rien n'est effacé, tout part dans `_a_supprimer\` avant une purge explicite (`-Purger`) |

## 6. Délégation autonome sans l'API — facultatif

| Commande | Usage |
|---|---|
| `python scripts/delegation_auto.py --si-du` | à confier au Planificateur de tâches Windows (ou à cron) quand l'API ne tourne pas en permanence : lance le passage du jour **s'il est dû** — même réglage que l'écran du directeur, un seul passage par jour même si l'API tourne aussi (`docs/BOUCLE_ACTION.md`) |
| `python scripts/delegation_auto.py` | un passage tout de suite, comme le bouton « Lancer maintenant » |

---

## Ce qu'il faut retenir pour le mémoire

> « La plateforme s'entretient avec **trois commandes** : mise à jour,
> ré-entraînement, contrôle avant démonstration. Les tableaux de la
> documentation sont **générés** depuis les rapports et la suite de tests, donc
> toujours exacts. Les autres scripts sont les **analyses qui ont fondé les
> décisions** du projet ; ils sont conservés comme pièces justificatives, et
> chacun est cité à l'endroit où sa conclusion est utilisée. »
