"""Ce qu'on peut légitimement publier sur une explication SHAP."""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

SORTIE = BASE / "reports" / "explicabilite_marge.json"
N_PERMUTATION = 400
N_REPETITIONS = 5


def mesurer() -> dict:
    warnings.filterwarnings("ignore")
    import joblib
    import numpy as np
    import shap
    from scipy.stats import spearmanr
    from sklearn.inspection import permutation_importance

    from ml_engine.analytics.marge_client import construire_panel

    paquet = joblib.load(BASE / "models" / "marge_client.joblib")
    modele, variables = paquet["modele"], paquet["features"]

    panel = construire_panel(pour_prediction=True)
    dernier = panel.sort_values("mois").groupby("client", as_index=False).tail(1)
    X = dernier[variables].to_numpy(dtype=float)

    debut = time.time()
    explicateur = shap.TreeExplainer(modele)
    valeurs = np.asarray(explicateur.shap_values(X))
    if valeurs.ndim == 3:
        valeurs = valeurs[:, :, -1]
    duree = time.time() - debut
    base = float(np.ravel(explicateur.expected_value)[-1])

    proba = modele.predict_proba(X)[:, 1]
    logit = np.log(proba / (1 - proba))
    erreur = np.abs(base + valeurs.sum(axis=1) - logit)

    importance = np.abs(valeurs).mean(axis=0)
    total = float(importance.sum()) or 1.0
    ordre = np.argsort(-importance)

    cible = (dernier["y"].to_numpy() if "y" in dernier
             else (proba > 0.5).astype(int))
    echantillon = np.random.RandomState(42).choice(
        len(X), size=min(N_PERMUTATION, len(X)), replace=False)
    perm = permutation_importance(modele, X[echantillon], cible[echantillon],
                                  n_repeats=N_REPETITIONS, random_state=42,
                                  scoring="roc_auc")
    accord = float(spearmanr(importance, perm.importances_mean).statistic)

    return {
        "genere_le": date.today().isoformat(),
        "modele": "marge_client (gradient boosting)",
        "methode": "TreeSHAP (shap.TreeExplainer)",
        "perimetre": {"n_clients_expliques": int(len(X)),
                      "n_variables": len(variables)},
        "additivite": {
            "propriete": "valeur_de_base + somme(contributions) = logit du modèle",
            "erreur_maximale": float(erreur.max()),
            "erreur_moyenne": float(erreur.mean()),
            "lecture": ("De l'ordre du flottant : pour un modèle d'arbres, TreeSHAP "
                        "calcule les valeurs de Shapley exactement. Une erreur "
                        "sensible signalerait une attribution qui ne décrit plus "
                        "le modèle."),
        },
        "valeur_de_base": {
            "logit": round(base, 4),
            "probabilite": round(float(1 / (1 + np.exp(-base))), 4),
            "lecture": ("Sortie moyenne du modèle — le client dont on ne saurait "
                        "rien. Chaque contribution est un écart à cette référence."),
        },
        "importance_globale": [
            {"variable": variables[i],
             "moyenne_abs_shap": round(float(importance[i]), 4),
             "part_pct": round(float(importance[i]) / total * 100, 1)}
            for i in ordre],
        "accord_avec_permutation": {
            "spearman": round(accord, 3),
            "protocole": (f"importance par permutation sur {len(echantillon)} clients, "
                          f"{N_REPETITIONS} répétitions, AUC comme critère"),
            "lecture": ("Deux méthodes indépendantes qui classent les variables de "
                        "la même façon. Un accord faible signalerait que l'une des "
                        "deux décrit mal le modèle."),
        },
        "cout": {
            "secondes_pour_tout_le_parc": round(duree, 3),
            "millisecondes_par_client": round(duree / max(1, len(X)) * 1000, 3),
            "lecture": ("Assez rapide pour être calculé À LA DEMANDE : l'API "
                        "n'explique que les lignes affichées, sans précalcul ni "
                        "fichier à maintenir."),
        },
        "limite_assumee": (
            "SHAP suppose une manière particulière de traiter les variables "
            "corrélées. Entre marge à 3 mois et marge à 12 mois, qui varient "
            "ensemble, la répartition du mérite dépend de cette hypothèse — c'est "
            "la limite réelle de la méthode, et non une imprécision de calcul."),
    }


def afficher(d: dict) -> None:
    print("\n" + "=" * 74)
    print("  EXPLICABILITÉ DU MODÈLE DE MARGE — ce que SHAP permet de publier")
    print("=" * 74)
    p = d["perimetre"]
    print(f"\n  {p['n_clients_expliques']} clients · {p['n_variables']} variables · {d['methode']}")

    a = d["additivite"]
    print(f"\n  1. Additivité      erreur max {a['erreur_maximale']:.2e}"
          f"   (moyenne {a['erreur_moyenne']:.2e})")
    b = d["valeur_de_base"]
    print(f"  2. Valeur de base  {b['logit']} en log-odds → probabilité {b['probabilite']:.3f}")
    print("\n  3. Importance globale (moyenne des |contributions|) :")
    for ligne in d["importance_globale"][:6]:
        print(f"       {ligne['variable']:26s} {ligne['moyenne_abs_shap']:.4f}"
              f"   {ligne['part_pct']:5.1f} %")
    print(f"\n  4. Accord avec l'importance par permutation : "
          f"Spearman {d['accord_avec_permutation']['spearman']}")
    c = d["cout"]
    print(f"\n  Coût : {c['secondes_pour_tout_le_parc']} s pour tout le parc "
          f"({c['millisecondes_par_client']} ms par client)")
    print(f"\n  Limite : {d['limite_assumee']}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnostics de l'explication SHAP")
    ap.add_argument("--afficher", action="store_true", help="ne pas écrire le rapport")
    args = ap.parse_args()
    try:
        d = mesurer()
    except ImportError as e:
        print(f"[shap] dépendance absente ({e}) — `pip install shap`")
        return 1
    afficher(d)
    if not args.afficher:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  → {SORTIE.relative_to(BASE)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
