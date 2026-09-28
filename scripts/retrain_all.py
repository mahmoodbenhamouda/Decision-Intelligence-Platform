"""
scripts/retrain_all.py
======================
Ré-entraîne TOUS les modèles avec l'environnement Python courant.

    python scripts/retrain_all.py            # ré-entraîne ce qui est nécessaire
    python scripts/retrain_all.py --force    # ré-entraîne tout
    python scripts/retrain_all.py --check    # diagnostic seulement

## Pourquoi c'est nécessaire

Un modèle scikit-learn sérialisé avec joblib embarque la version de la
bibliothèque qui l'a produit. Le recharger avec une version différente déclenche
`InconsistentVersionWarning` — et, comme scikit-learn le précise lui-même, peut
produire des **résultats invalides** (structures internes modifiées entre
versions). Ce n'est pas un avertissement cosmétique.

Ce script détecte l'écart de version, ré-entraîne les modèles concernés et
vérifie que les métriques restent conformes.

## Le défaut que ce fichier corrigeait lui-même

La première version ne ré-entraînait QUE le modèle de crédit, alors que cinq
artefacts sérialisés vivent dans `models/`. Lancer « retrain_all » laissait donc
quatre modèles sur une version périmée de scikit-learn tout en affichant
« Terminé » — un script de maintenance qui certifie un état qu'il n'a pas vérifié
est pire que pas de script.

Modèles couverts :
  - `models/credit_risk_model.joblib`   (conditions de crédit)
  - `models/churn_model.joblib`         (décrochage client)
  - `models/segmentation.joblib`        (typologie de clientèle)
  - `models/stock_risk.joblib`          (risque produit)
  - `models/reappro_model.joblib`       (réapprovisionnement à 3 mois)

Chaque entrée déclare son module et sa fonction d'entraînement : ajouter un
modèle au projet sans l'ajouter ici est la seule manière de recréer le défaut,
et `tests/test_modules_branches.py` la ferme.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

MODELS = BASE / "models"
REPORTS = BASE / "reports"


def _sklearn_version() -> str:
    try:
        import sklearn
        return sklearn.__version__
    except Exception:
        return "?"


def _model_version(path: Path) -> str | None:
    """Version de scikit-learn ayant produit le modèle.

    scikit-learn retire `_sklearn_version` de l'objet après désérialisation :
    la seule source fiable est l'avertissement `InconsistentVersionWarning`
    qu'il émet lorsque les versions diffèrent (il porte
    `original_sklearn_version`). Absence d'avertissement = versions alignées.
    """
    if not path.exists():
        return None
    try:
        import joblib
        try:
            from sklearn.exceptions import InconsistentVersionWarning
        except Exception:
            InconsistentVersionWarning = None

        with warnings.catch_warnings(record=True) as capture:
            warnings.simplefilter("always")
            joblib.load(path)
        for w in capture:
            if InconsistentVersionWarning and issubclass(w.category, InconsistentVersionWarning):
                return getattr(w.message, "original_sklearn_version", "autre version")
            if "InconsistentVersion" in w.category.__name__:
                return "autre version"
        return _sklearn_version()          # aucun avertissement → conforme
    except Exception:
        return "illisible"


# ── Table des modèles sérialisés ────────────────────────────────────────────
#
# Un seul endroit décrit ce qui existe, où le ré-entraîner et comment lire le
# résultat. `resume` reçoit le dictionnaire de métriques et renvoie une ligne
# lisible ; il renvoie `None` si le modèle a été refusé — auquel cas l'absence
# d'artefact est le comportement CORRECT, pas une panne.
ARTEFACTS: list[dict] = [
    {
        "nom": "conditions de crédit",
        "fichier": "credit_risk_model.joblib",
        "module": "ml_engine.analytics.credit_risk_model",
        # Ce module ne renvoie PAS d'AUC au premier niveau : ce qui est servi est
        # une règle déterministe, dont la performance vit dans le bloc
        # `production`. Lire `m['auc']` était l'erreur héritée de la version v1,
        # quand un modèle appris était encore déployé ici.
        "resume": lambda m: (
            f"règle servie — AUC hors période "
            f"{m['production']['auc_hors_periode']:.4f} · couverture "
            f"{m['production']['couverture_par_la_regle_pct']} % du portefeuille"),
        "seuil": lambda m: m["production"]["statut"] == "servi",
    },
    {
        "nom": "décrochage client",
        "fichier": "churn_model.joblib",
        "module": "ml_engine.analytics.churn_model",
        "resume": lambda m: (f"AUC {m['hors_periode']['auc']:.4f} hors période "
                             f"(référence {m['hors_periode']['auc_meilleure_reference_triviale']:.4f})"),
        "seuil": lambda m: m["decision_deploiement"]["modele_deploye"],
    },
    {
        "nom": "érosion de marge",
        "fichier": "marge_client.joblib",
        "module": "ml_engine.analytics.marge_client",
        "resume": lambda m: (
            f"AUC {m['evaluation']['auc']:.4f} "
            f"(référence {m['evaluation']['auc_meilleure_reference_triviale']:.4f})"
            if (m.get("evaluation") or {}).get("applicable") else "non applicable"),
        "seuil": lambda m: m["decision_deploiement"]["modele_deploye"],
        "peut_etre_refuse": True,
    },
    {
        "nom": "conversion devis",
        "fichier": "conversion_devis.joblib",
        "module": "ml_engine.analytics.conversion_devis",
        "resume": lambda m: (
            f"AUC {m['hors_periode']['auc']:.4f} hors période "
            f"(référence {m['hors_periode']['auc_meilleure_reference_triviale']:.4f})"
            if (m.get("hors_periode") or {}).get("applicable") else "non applicable"),
        "seuil": lambda m: m["decision_deploiement"]["modele_deploye"],
        "peut_etre_refuse": True,
    },
    {
        "nom": "typologie clientèle",
        "fichier": "segmentation.joblib",
        "module": "ml_engine.analytics.segmentation",
        "resume": lambda m: (
            f"silhouette {m['qualite']['silhouette']:.3f} | "
            f"stabilité {m['qualite'].get('stabilite_rand_ajuste', 0):.3f}"),
        "seuil": lambda m: bool(m.get("servi")),
    },
    {
        "nom": "risque produit",
        "fichier": "stock_risk.joblib",
        "module": "ml_engine.models.stock_risk",
        # RETIRÉ du service par le registre : sa cible dépend de dates de
        # péremption simulées. Il reste réentraîné pour rester lisible — son
        # artefact ne doit pas devenir un pickle d'une version périmée de
        # scikit-learn — mais il ne sera pas servi pour autant.
        "retire_du_service": True,
        # Ce module n'expose pas `train` mais `train_stock_risk`. Le nom est
        # déclaré plutôt que supposé : c'est exactement l'erreur qui avait fait
        # échouer la synchronisation de l'échéancier au premier passage.
        "fonction": "train_stock_risk",
        "resume": lambda m: f"AUC hold-out {m['holdout']['auc']:.4f}",
        "seuil": lambda m: m["holdout"]["auc"] >= 0.70,
    },
    {
        "nom": "prévision de demande 30/60/90 j",
        "fichier": "demand_forecast_ml.joblib",
        "module": "ml_engine.models.demand_forecast",
        "fonction": "train_demand_models",
        # Les trois modèles de ce bundle sont REFUSÉS (gain hold-out négatif) et
        # c'est la baseline saisonnière qui est servie. Le bundle est néanmoins
        # ré-entraîné : il est chargé pour servir cette baseline, et un bundle
        # sérialisé par une version périmée de scikit-learn reste un risque de
        # résultat invalide, qu'il soit déployé ou non.
        "resume": lambda m: (
            f"{len(m.get('horizons') or {})} horizon(s) · gain hold-out confirmé "
            f"pour {sum(1 for d in (m.get('horizons') or {}).values() if isinstance(d, dict) and d.get('holdout_confirme_le_gain'))}"
            " d'entre eux — la baseline saisonnière reste servie"),
        "seuil": lambda m: True,
    },
    {
        "nom": "demande par référence 1 à 3 mois",
        "fichier": "demande_reference.joblib",
        "module": "ml_engine.forecasting.demande_reference",
        # L'artefact n'existe que si le modèle appris bat la règle simple ; sinon
        # la règle est servie et il n'y a rien à charger.
        "peut_etre_refuse": True,
        "resume": lambda m: (f"méthode servie : {m['methode_servie']['nom']} · WAPE "
                             f"{m['methode_servie']['wape_h1_pct']} % à 1 mois"),
        "seuil": lambda m: True,
    },
    {
        "nom": "fin de commercialisation",
        "fichier": "fin_de_vie.joblib",
        "module": "ml_engine.stock.fin_de_vie",
        "resume": lambda m: (
            f"AUC {m['hors_periode']['auc']:.4f} hors période "
            f"(référence {m['hors_periode']['auc_meilleure_reference_triviale']:.4f})"
            if (m.get("hors_periode") or {}).get("applicable") else "non applicable"),
        "seuil": lambda m: True,
        "peut_etre_refuse": True,
    },
    {
        "nom": "réapprovisionnement",
        "fichier": "reappro_model.joblib",
        "module": "ml_engine.stock.reappro_model",
        "resume": lambda m: (
            f"AUC {m['hors_periode']['auc']:.4f} hors période"
            if (m.get("hors_periode") or {}).get("applicable") else "non applicable"),
        # Ce modèle peut légitimement être refusé : son artefact est alors
        # volontairement absent, et ce n'est pas une erreur à signaler.
        "seuil": lambda m: True,
        "peut_etre_refuse": True,
    },
    {
        "nom": "recommandation de produits (deep learning)",
        # Artefact PyTorch écrit seulement si le Wide & Deep est la méthode
        # servie ; sinon il est volontairement absent et les recommandations
        # précalculées proviennent du modèle plus simple retenu par parcimonie.
        "fichier": "recommandation_wide_deep.pt",
        "module": "ml_engine.deep.recommandation",
        "resume": lambda m: (
            f"servi : {m['decision_deploiement']['methode_servie']} — NDCG@10 "
            f"{m['evaluation']['methode_servie']['ndcg_at_10']:.4f} · Wide & Deep "
            f"{((m['evaluation'].get('agrege') or {}).get('wide_deep') or {}).get('ndcg_at_10', float('nan')):.4f}"
            if (m.get("evaluation") or {}).get("applicable") else "non applicable"),
        "seuil": lambda m: bool((m.get("decision_deploiement") or {}).get("servi")),
        "peut_etre_refuse": True,
    },
]


# ── Artefacts sérialisés HORS models/ ───────────────────────────────────────
#
# L'index de recherche documentaire sérialise un `TfidfVectorizer` dans
# `rag/index/tfidf.pkl`. Ce n'est pas un `.joblib` de `models/`, donc le test de
# couverture ne le voyait pas — et c'était le dernier avertissement de version
# encore émis par la suite de tests, alors que ce script annonçait « Terminé ».
#
# Même risque que les autres : scikit-learn prévient qu'un objet désérialisé par
# une version différente peut produire des résultats invalides. Un index de
# recherche qui renvoie de mauvais passages est d'autant plus sournois qu'il ne
# lève aucune erreur.
INDEX_RAG = BASE / "rag" / "index" / "tfidf.pkl"


def _index_rag_a_reconstruire() -> bool:
    if not INDEX_RAG.exists():
        return False        # aucun index : rien à réaligner
    return _model_version(INDEX_RAG) != _sklearn_version()


def reconstruire_index_rag() -> bool:
    print("\n[index] Recherche documentaire (rag/index)…")
    try:
        from rag.rag_engine import build_index
        n = build_index()
        print(f"      {n} passage(s) réindexé(s) avec scikit-learn "
              f"{_sklearn_version()}")
        return True
    except Exception as e:
        print(f"      [erreur] {type(e).__name__} : {e}")
        return False


def diagnostic() -> list[tuple[str, Path, str | None, bool]]:
    """Renvoie [(nom, chemin, version_modele, doit_reentrainer)]."""
    courant = _sklearn_version()
    out = []
    for spec in ARTEFACTS:
        p = MODELS / spec["fichier"]
        v = _model_version(p)
        if v is None and spec.get("peut_etre_refuse"):
            # Artefact absent parce que le modèle est refusé : rien à faire.
            # Le distinguer d'un artefact manquant par erreur évite de relancer
            # sans fin un entraînement dont le refus est le résultat attendu.
            besoin = False
        else:
            besoin = (v is None) or (v == "illisible") or (v != courant)
        out.append((spec["nom"], p, v, besoin))
    return out


# Le modèle de pertinence des appels d'offres a été retiré du projet avec la
# veille externe (motif détaillé dans reports/METRICS_REPORT.md, §2).


def retrain_un(spec: dict, rang: str) -> bool:
    print(f"\n{rang} {spec['nom']}…")
    try:
        import importlib
        mod = importlib.import_module(spec["module"])
        fn = getattr(mod, spec.get("fonction", "train"), None)
        if fn is None:
            print(f"      [erreur] {spec['module']} n'expose pas "
                  f"`{spec.get('fonction', 'train')}`")
            return False
        m = fn() or {}
        if m.get("error"):
            print(f"      [erreur] {m['error']}")
            return False
        try:
            print(f"      {spec['resume'](m)}")
        except Exception:
            print("      entraîné (résumé indisponible)")
        if not spec["seuil"](m):
            print("      [!] seuil non atteint — le registre refusera ce modèle.")
            # Ce n'est pas une panne du script : la décision est correcte, et
            # c'est au registre de la rendre effective.
        return True
    except Exception as e:
        print(f"      [erreur] {type(e).__name__} : {e}")
        return False


def _exporter_retours() -> None:
    """Rapatrie les résultats des tâches et les actions clients dans l'entrepôt.

    Jamais bloquant : un entrepôt occupé par l'API ou une base applicative vide
    (projet fraîchement installé) ne doit pas empêcher un ré-entraînement.
    """
    try:
        from ml_engine.boucle import exporter_retours, resume
    except Exception as e:
        print(f"  [--] retours terrain    : module indisponible ({type(e).__name__})")
        return
    info = exporter_retours(verbose=False)
    if not info.get("ok"):
        print(f"  [--] retours terrain    : {info.get('motif', 'non exportés')}")
        return
    r = resume()
    print(f"  [OK] retours terrain    : {info['taches']} tâche(s), "
          f"{info['actions_client']} action(s) client — "
          f"{r.get('gagnees', 0)} action(s) gagnée(s), "
          f"{r.get('retours_produits', 0)} retour(s) produit")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Ré-entraîne les modèles ML")
    ap.add_argument("--force", action="store_true", help="ré-entraîner même si à jour")
    ap.add_argument("--check", action="store_true", help="diagnostic seulement")
    args = ap.parse_args()

    courant = _sklearn_version()
    print("=" * 70)
    print(f"  MODÈLES ML — scikit-learn installé : {courant}")
    print("=" * 70)

    # ── Retours du terrain ──
    # Avant toute chose : rapatrier dans l'entrepôt ce que les actions ont donné
    # (tâches clôturées, réponses des clients). Le faire APRÈS l'entraînement
    # reviendrait à entraîner sur des retours vieux d'une session.
    _exporter_retours()

    etats = diagnostic()
    for nom, path, v, besoin in etats:
        if v is None:
            print(f"  [!!] {nom:16} : ABSENT ({path.name})")
        elif besoin:
            print(f"  [~~] {nom:16} : entraîné avec {v} → incompatible")
        else:
            print(f"  [OK] {nom:16} : version {v}, conforme")

    index_a_faire = _index_rag_a_reconstruire()
    if not INDEX_RAG.exists():
        print(f"  [--] {'index recherche':16} : absent, rien à réaligner")
    elif index_a_faire:
        print(f"  [~~] {'index recherche':16} : "
              f"{_model_version(INDEX_RAG)} → incompatible")
    else:
        print(f"  [OK] {'index recherche':16} : version {courant}, conforme")

    a_faire = [e for e in etats if e[3]] if not args.force else etats
    if args.force and INDEX_RAG.exists():
        index_a_faire = True

    if args.check:
        print(f"\n  {len(a_faire)} modèle(s) à ré-entraîner"
              + (" + l'index de recherche." if index_a_faire else "."))
        return 1 if (a_faire or index_a_faire) else 0
    if not a_faire and not index_a_faire:
        print("\n  Tout est conforme. Rien à faire (--force pour forcer).")
        return 0

    print(f"\n  Ré-entraînement de {len(a_faire)} modèle(s)…")
    ok = True
    noms = {e[0] for e in a_faire}
    # L'ordre suit ARTEFACTS et non l'ordre de détection : le modèle de
    # réapprovisionnement lit une table que le domaine stock doit avoir
    # reconstruite, et un ordre dépendant du hasard des versions serait une
    # source de panne intermittente.
    a_lancer = [s for s in ARTEFACTS if s["nom"] in noms]
    for i, spec in enumerate(a_lancer, start=1):
        ok &= retrain_un(spec, f"[{i}/{len(a_lancer)}]")

    if index_a_faire:
        ok &= reconstruire_index_rag()

    print("\n" + "=" * 70)
    if ok:
        print("  Terminé. Les modèles sont alignés sur l'environnement courant.")
        print("  Redémarrez l'API : les avertissements de version disparaîtront.")
    else:
        print("  Terminé AVEC ERREURS — voir les messages ci-dessus.")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
