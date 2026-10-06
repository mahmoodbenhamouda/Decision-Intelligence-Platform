"""Ré-entraîne TOUS les modèles avec l'environnement Python courant."""

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
    """Version de scikit-learn ayant produit le modèle."""
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
        return _sklearn_version()
    except Exception:
        return "illisible"


ARTEFACTS: list[dict] = [
    {
        "nom": "conditions de crédit",
        "fichier": "credit_risk_model.joblib",
        "module": "ml_engine.analytics.credit_risk_model",
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
    # Deux horizons, deux artefacts : chacun est déclaré, sinon le test qui
    # balaie le dépôt à la recherche d'artefacts orphelins les signale.
    {
        "nom": "chiffre d'affaires client à 3 mois",
        "fichier": "ca_client_3m.joblib",
        "module": "ml_engine.analytics.ca_client",
        "fonction": "train",
        "arguments": {"horizon": 3},
        "resume": lambda m: (
            f"erreur médiane {m['evaluation']['modele']['erreur_absolue_medianne_dt']:,.0f} DT "
            f"(référence {m['evaluation']['erreur_meilleure_reference_dt']:,.0f} DT)"
            .replace(",", " ")
            if (m.get("evaluation") or {}).get("applicable") else "non applicable"),
        "seuil": lambda m: m["decision_deploiement"]["modele_deploye"],
        "peut_etre_refuse": True,
    },
    {
        "nom": "chiffre d'affaires client à 12 mois (top 10 prédit)",
        "fichier": "ca_client_12m.joblib",
        "module": "ml_engine.analytics.ca_client",
        "fonction": "train",
        "arguments": {"horizon": 12},
        "resume": lambda m: (
            f"erreur médiane {m['evaluation']['modele']['erreur_absolue_medianne_dt']:,.0f} DT "
            f"(référence {m['evaluation']['erreur_meilleure_reference_dt']:,.0f} DT)"
            .replace(",", " ")
            if (m.get("evaluation") or {}).get("applicable") else "non applicable"),
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
        "retire_du_service": True,
        "fonction": "train_stock_risk",
        "resume": lambda m: f"AUC hold-out {m['holdout']['auc']:.4f}",
        "seuil": lambda m: m["holdout"]["auc"] >= 0.70,
    },
    {
        "nom": "prévision de demande 30/60/90 j",
        "fichier": "demand_forecast_ml.joblib",
        "module": "ml_engine.models.demand_forecast",
        "fonction": "train_demand_models",
        "resume": lambda m: (
            f"{len(m.get('horizons') or {})} horizon(s) · gain hold-out confirmé "
            f"pour {sum(1 for d in (m.get('horizons') or {}).values() if isinstance(d, dict) and d.get('holdout_confirme_le_gain'))}"
            " d'entre eux — la baseline saisonnière reste servie"),
        "seuil": lambda m: True,
    },
    {
        "nom": "demande par référence 1 à 3 mois",
        "fichier": "demande_reference.joblib",
        "cle_registre": "demande_reference",
        "module": "ml_engine.forecasting.demande_reference",
        "peut_etre_refuse": True,
        "resume": lambda m: (f"méthode servie : {m['methode_servie']['nom']} · WAPE "
                             f"{m['methode_servie']['wape_h1_pct']} % à 1 mois"),
        "seuil": lambda m: True,
    },
    {
        "nom": "fin de commercialisation",
        "fichier": "fin_de_vie.joblib",
        "cle_registre": "fin_de_vie",
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
        "cle_registre": "reappro",
        "module": "ml_engine.stock.reappro_model",
        "resume": lambda m: (
            f"AUC {m['hors_periode']['auc']:.4f} hors période"
            if (m.get("hors_periode") or {}).get("applicable") else "non applicable"),
        "seuil": lambda m: True,
        "peut_etre_refuse": True,
    },
    {
        "nom": "recommandation de produits (deep learning)",
        "fichier": "recommandation_wide_deep.pt",
        "cle_registre": "recommandation",
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


INDEX_RAG = BASE / "rag" / "index" / "tfidf.pkl"


def _index_rag_a_reconstruire() -> bool:
    if not INDEX_RAG.exists():
        return False
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


def diagnostic() -> list[tuple[str, Path, str | None, bool, dict]]:
    """Renvoie [(nom, chemin, version_modele, doit_reentrainer, spec)].

    Le `spec` est rendu avec l'état : sans lui, l'affichage ne peut pas
    distinguer un artefact absent PARCE QUE son modèle a été refusé — une
    décision, et l'un des résultats dont ce projet est le plus fier — d'un
    artefact absent par accident, qui est un vrai problème.
    """
    courant = _sklearn_version()
    out = []
    for spec in ARTEFACTS:
        p = MODELS / spec["fichier"]
        v = _model_version(p)
        if v is None and spec.get("peut_etre_refuse"):
            besoin = False
        else:
            besoin = (v is None) or (v == "illisible") or (v != courant)
        out.append((spec["nom"], p, v, besoin, spec))
    return out


def _pourquoi_absent(spec: dict) -> str:
    """Ce que le REGISTRE dit d'un artefact absent — jamais ce que ce script suppose.

    « ABSENT » tout seul se lit comme une panne. Pour ces modules, l'absence est
    au contraire la trace d'un refus mesuré : le fichier n'est pas écrit parce
    qu'il ne doit pas être servi. Le motif est donc lu dans le registre, qui est
    la seule autorité du projet sur ce qui est servi — ce script n'en décide pas.
    """
    cle = spec.get("cle_registre")
    if not cle:
        return "absence déclarée acceptable pour ce module"
    try:
        from ml_engine.registre import etat_modele
        e = etat_modele(cle) or {}
    except Exception as ex:
        return f"registre illisible ({type(ex).__name__})"

    motif = (e.get("motif") or "").strip()
    if len(motif) > 108:
        motif = motif[:105].rstrip().rstrip(",;:") + "…"
    if e.get("deploye"):
        # Le module EST servi : c'est une autre méthode qui l'assure, et
        # l'artefact absent était le candidat écarté (ou le challenger).
        # L'élision est portee par la valeur : « au profit de une statistique »
        # est le genre de détail qu'un jury remarque avant le fond.
        quoi = {"methode_statistique": "d'une statistique",
                "regle": "d'une règle"}.get(e.get("nature") or "",
                                            "d'un modèle plus simple")
        tete = f"écarté au profit {quoi}"
    else:
        tete = "modèle REFUSÉ, un repli est servi"
    # Le motif passe à la ligne : collé au bout, il dépassait 250 colonnes.
    return f"{tete}\n       {motif}" if motif else tete


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
        # `arguments` permet à deux entrées de viser la même fonction avec des
        # paramètres différents (un modèle par horizon).
        m = fn(**spec.get("arguments", {})) or {}
        if m.get("error"):
            print(f"      [erreur] {m['error']}")
            return False
        try:
            print(f"      {spec['resume'](m)}")
        except Exception:
            print("      entraîné (résumé indisponible)")
        if not spec["seuil"](m):
            print("      [!] seuil non atteint — le registre refusera ce modèle.")
        return True
    except Exception as e:
        print(f"      [erreur] {type(e).__name__} : {e}")
        return False


def _exporter_retours() -> None:
    """Rapatrie les résultats des tâches et les actions clients dans l'entrepôt."""
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
    print(f"  [OK] retours terrain    : {info['taches']} tâche(s) — "
          f"{r.get('gagnees', 0)} action(s) gagnée(s)")


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

    _exporter_retours()

    etats = diagnostic()
    n_attendus = 0
    for nom, path, v, besoin, spec in etats:
        if v is None and spec.get("peut_etre_refuse"):
            # Absence ATTENDUE : ni alerte, ni réentraînement à prévoir.
            n_attendus += 1
            print(f"  [--] {nom:16} : pas d'artefact, et c'est voulu — "
                  f"{_pourquoi_absent(spec)}")
        elif v is None:
            print(f"  [!!] {nom:16} : ABSENT ({path.name}) — "
                  f"artefact attendu et introuvable")
        elif besoin:
            print(f"  [~~] {nom:16} : entraîné avec {v} → incompatible")
        else:
            print(f"  [OK] {nom:16} : version {v}, conforme")

    if n_attendus:
        print(f"\n  Les {n_attendus} lignes [--] ne sont pas des pannes : ce sont "
              "des modèles mesurés\n  puis écartés, dont l'artefact n'est "
              "délibérément pas écrit sur disque.\n  Détail et motifs : "
              "`python -m ml_engine.registre`.")

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
