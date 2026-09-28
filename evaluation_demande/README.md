# evaluation_demande — étude complète de la demande par référence

Phases 4 et 5 du CRISP-DM décrit dans `docs/CRISP_DM_DEMANDE_REFERENCE.md` :
31 méthodes (règles simples, Croston/SBA/TSB, ETS, Theta, ADIDA, IMAPA, Poisson,
LightGBM, XGBoost, CatBoost, MLP, N-HiTS, DeepAR, combinaison) mises en
concurrence dans le même walk-forward.

```bash
python evaluation_demande/comparer_modeles.py --phase validation   # tout se choisit ici (≈ 60 min)
python evaluation_demande/comparer_modeles.py --phase test         # lu une seule fois (≈ 15 min)
```

`--extrait output/demande_reference` rejoue l'étude sur l'extrait parquet
(`ml_engine.forecasting.demande_reference.exporter_extrait`) plutôt que sur
l'entrepôt.

Dépendances propres à l'étude, absentes de la production : `optuna`,
`catboost`, `statsforecast`, `neuralforecast`, `pyarrow` (prévisions en parquet). Le module servi n'a besoin que de
`numpy`, `pandas` et, pour le challenger, `lightgbm`.

| Fichier de `resultats/` | Contenu |
|---|---|
| `validation.json` | classement de validation, réglages retenus par Optuna, choix figés (date comprise) |
| `comparaison_test.json` | verdict du test, par méthode, par classe, par mois — copié dans `reports/demande_reference_comparaison.json` |
| `predictions_*.parquet` | toutes les prévisions (méthode, horizon, origine, référence) — pour rejouer n'importe quel chiffre |
| `diagnostic.json` | écart validation/test (plafonds oracles), décomposition de la WAPE du test, duel par observation |
| `propagation.json` | contributions TreeSHAP de la prévision de janvier 2026, contrefactuel, pics historiques, détecteur |
| `preenregistrement.json` | candidat retenu et règle, horodatés et hachés AVANT la phase de test |
| `pipeline_robuste_*.json` | candidats du diagnostic : développement (24 origines) puis test |
| `journal_*.log` | trace horodatée, y compris la première tentative de réglage (`journal_validation_essai1.log`) |
