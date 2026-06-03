"""
run_advanced_pipeline.py
========================
Point d'entrée pour le pipeline avancé Finance AI Agent (9 phases).

Usage :
    python run_advanced_pipeline.py [--no-optuna] [--no-dl] [--no-shap]

Options :
    --no-optuna   Désactive l'optimisation Optuna (phase 6)
    --no-dl       Désactive les modèles Deep Learning LSTM/GRU (phase 5.3)
    --no-shap     Désactive SHAP explainability (phase 7)
    --trials N    Nombre d'essais Optuna (défaut : 30)
"""

import argparse
import sys
import time
from pathlib import Path

# ── Résolution des imports locaux ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from data_preparation_pipeline import prepare_data_layer
from ml_advanced_pipeline import run_advanced_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Advanced ML Pipeline — Finance AI Agent")
    parser.add_argument("--no-optuna", action="store_true", help="Disable Optuna optimization")
    parser.add_argument("--no-dl",     action="store_true", help="Disable Deep Learning models")
    parser.add_argument("--no-shap",   action="store_true", help="Disable SHAP explainability")
    parser.add_argument("--trials",    type=int, default=30, help="Number of Optuna trials (default: 30)")
    parser.add_argument("--data-dir",  default="data_pfe",  help="Directory with source CSV files")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"[ERROR] Répertoire de données introuvable : {data_dir}")
        sys.exit(1)

    # ── Chargement des données ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("CHARGEMENT DES DONNÉES (data_preparation_pipeline)")
    print(f"{'='*60}")
    t0 = time.perf_counter()
    tables_clean, warehouse = prepare_data_layer(data_dir=data_dir)
    elapsed = time.perf_counter() - t0
    print(f"  ✓ Données chargées en {elapsed:.1f}s")
    print(f"  Tables nettoyées : {list(tables_clean.keys())}")
    print(f"  Warehouse        : {list(warehouse.keys())}")

    if not warehouse:
        print("[ERROR] Warehouse vide — vérifiez les données source")
        sys.exit(1)

    # ── Pipeline avancé ───────────────────────────────────────────────────────
    t1 = time.perf_counter()
    results = run_advanced_pipeline(
        warehouse=warehouse,
        data_dir=data_dir,
        run_dl=not args.no_dl,
        run_optuna=not args.no_optuna,
        run_shap=not args.no_shap,
        n_optuna_trials=args.trials,
    )
    elapsed_total = time.perf_counter() - t1

    print(f"\nPipeline terminé en {elapsed_total:.1f}s")
    print(f"Phases complétées : {list(results.keys())}")


if __name__ == "__main__":
    main()
