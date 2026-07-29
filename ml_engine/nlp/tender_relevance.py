"""
Classifieur de PERTINENCE des appels d'offres (diagnostic médical vs hors domaine).

- Entrée  : le texte (titre) d'un appel d'offres scrappé.
- Sortie  : proba de pertinence ∈ [0,1] + décision.
- Modèle  : TF-IDF (mots + n-grammes de caractères) → régression logistique.
- Évaluation : validation croisée stratifiée (accuracy / précision / rappel / F1),
  comparée à une baseline non supervisée (similarité au domaine via tender_matcher).

Usage :
    python -m ml_engine.nlp.tender_relevance train    # entraîne + évalue + sauvegarde
    python -m ml_engine.nlp.tender_relevance test "Acquisition de réactifs ELISA"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

BASE = Path(__file__).resolve().parents[2]
MODEL_PATH = BASE / "models" / "tender_relevance.joblib"
METRICS_PATH = BASE / "reports" / "tender_relevance_metrics.json"


def _build_pipeline():
    from sklearn.pipeline import FeatureUnion, Pipeline
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    feats = FeatureUnion([
        ("mots", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)),
    ])
    return Pipeline([("feats", feats),
                     ("clf", LogisticRegression(max_iter=1000, class_weight="balanced"))])


# ── Entraînement + évaluation ───────────────────────────────────────────────
def train_and_evaluate(save: bool = True) -> dict:
    import numpy as np
    from sklearn.model_selection import StratifiedKFold, cross_validate
    from .tender_dataset import load

    texts, labels = load()
    X = np.array(texts, dtype=object)
    y = np.array(labels)

    pipe = _build_pipeline()
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scoring = ["accuracy", "precision", "recall", "f1", "roc_auc"]
    res = cross_validate(pipe, X, y, cv=cv, scoring=scoring)

    def ms(k):
        v = res[f"test_{k}"]
        return round(float(v.mean()), 4), round(float(v.std()), 4)

    # Baseline non supervisée : similarité au domaine (tender_matcher)
    baseline_acc = None
    try:
        from .tender_matcher import domain_relevance
        scores = np.array([domain_relevance(t) for t in texts])
        # meilleur seuil sur la grille
        best = 0.0
        for thr in np.linspace(0.05, 0.6, 45):
            acc = float(((scores >= thr).astype(int) == y).mean())
            best = max(best, acc)
        baseline_acc = round(best, 4)
    except Exception:
        pass

    # Modèle final sur tout le jeu
    pipe.fit(X, y)

    acc_m, acc_s = ms("accuracy")
    metrics = {
        "modele": "TF-IDF (mots + char n-grammes) + Régression logistique",
        "n_exemples": len(y),
        "n_pertinents": int(y.sum()),
        "validation": "StratifiedKFold 5 plis",
        "accuracy": acc_m, "accuracy_std": acc_s,
        "precision": ms("precision")[0], "recall": ms("recall")[0],
        "f1": ms("f1")[0], "roc_auc": ms("roc_auc")[0],
        "baseline_non_supervisee_accuracy": baseline_acc,
        "backend_matcher": _matcher_backend(),
    }

    if save:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            import joblib
            joblib.dump(pipe, MODEL_PATH)
        except Exception:
            pass
        METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def _matcher_backend() -> str:
    try:
        from .tender_matcher import backend_name
        return backend_name()
    except Exception:
        return "n/d"


# ── Prédiction ──────────────────────────────────────────────────────────────
_PIPE = None


def _load_pipe():
    """Charge le modèle ; le RÉ-ENTRAÎNE s'il est absent ou incompatible
    (ex. décalage de version scikit-learn entre entraînement et exécution)."""
    global _PIPE
    if _PIPE is not None:
        return _PIPE
    try:
        import joblib
        pipe = joblib.load(MODEL_PATH)
        # test de bon fonctionnement (un pickle incompatible lève ici)
        pipe.predict_proba(["réactifs de laboratoire diagnostic in vitro"])
        _PIPE = pipe
        return _PIPE
    except Exception:
        pass
    # (ré)entraînement dans l'environnement courant, puis rechargement
    train_and_evaluate(save=True)
    import joblib
    _PIPE = joblib.load(MODEL_PATH)
    return _PIPE


def predict_relevance(texts: List[str]) -> List[float]:
    """Proba de pertinence ∈ [0,1] pour chaque texte."""
    pipe = _load_pipe()
    try:
        return [float(p) for p in pipe.predict_proba(texts)[:, 1]]
    except Exception:
        return [0.0 for _ in texts]


def is_relevant(text: str, threshold: float = 0.5) -> bool:
    return predict_relevance([text])[0] >= threshold


# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    if cmd == "train":
        m = train_and_evaluate(save=True)
        print("=== Classifieur de pertinence des appels d'offres ===")
        for k, v in m.items():
            print(f"  {k:34} : {v}")
        print(f"\n✅ Modèle : {MODEL_PATH}\n✅ Métriques : {METRICS_PATH}")
    elif cmd == "test":
        q = " ".join(sys.argv[2:]) or "Acquisition de réactifs ELISA pour le CHU"
        print(f"pertinence = {predict_relevance([q])[0]:.3f}  →  {q}")
