"""Garder les modèles alignés sur les données — sans que personne y pense."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[1]

REPORTS = BASE / "reports"
EMPREINTES = REPORTS / "empreintes.json"


def empreinte_actuelle(con=None) -> Dict[str, Any]:
    """Signature de l'état des données, stable et sensible aux vrais changements."""
    fermer = con is None
    if con is None:
        from ml_engine.analytics.kpi_engine import _connect
        con = _connect()
    try:
        v = con.execute("""
            SELECT count(*), min(date), max(date),
                   round(sum(ttc), 2), count(DISTINCT client)
            FROM sales WHERE date IS NOT NULL
        """).fetchone()
        l = con.execute("SELECT count(*), round(sum(montant), 2) FROM sales_lines").fetchone()
        a = con.execute("SELECT count(*), round(sum(ttc), 2) FROM purchases").fetchone()
    except Exception as e:
        if fermer:
            con.close()
        return {"erreur": f"{type(e).__name__}: {e}"}
    finally:
        if fermer and con:
            try:
                con.close()
            except Exception:
                pass

    detail = {
        "n_factures": int(v[0] or 0),
        "periode": f"{v[1]} → {v[2]}",
        "ca_total": float(v[3] or 0),
        "n_clients": int(v[4] or 0),
        "n_lignes_vente": int(l[0] or 0),
        "montant_lignes": float(l[1] or 0),
        "n_achats": int(a[0] or 0),
        "montant_achats": float(a[1] or 0),
    }
    brut = json.dumps(detail, sort_keys=True).encode()
    detail["empreinte"] = hashlib.sha256(brut).hexdigest()[:16]
    return detail


def _empreintes_enregistrees() -> Dict[str, Any]:
    if not EMPREINTES.exists():
        return {}
    try:
        return json.load(open(EMPREINTES, encoding="utf-8"))
    except Exception:
        return {}


def _enregistrer(nom: str, empreinte: str, detail: Dict[str, Any]) -> None:
    d = _empreintes_enregistrees()
    d[nom] = {
        "empreinte": empreinte,
        "date": datetime.now().isoformat(timespec="seconds"),
        "donnees": {k: v for k, v in detail.items() if k != "empreinte"},
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    json.dump(d, open(EMPREINTES, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)


def _churn() -> Dict[str, Any]:
    from ml_engine.analytics.churn_model import train
    m = train()
    return {"auc": m["hors_periode"]["auc"],
            "servi": m["decision_deploiement"]["modele_deploye"]}


def _marge_client() -> Dict[str, Any]:
    from ml_engine.analytics.marge_client import train
    m = train()
    if m.get("error"):
        raise RuntimeError(m["error"])
    return {"auc": (m.get("evaluation") or {}).get("auc"),
            "servi": m["decision_deploiement"]["modele_deploye"]}


def _ca_client(horizon: int) -> Dict[str, Any]:
    """La métrique est une ERREUR : sa dégradation se lit à la hausse."""
    from ml_engine.analytics.ca_client import train
    m = train(horizon)
    if m.get("error"):
        raise RuntimeError(m["error"])
    ev = m.get("evaluation") or {}
    return {"erreur_medianne_dt": (ev.get("modele") or {}).get(
                "erreur_absolue_medianne_dt"),
            "servi": m["decision_deploiement"]["modele_deploye"]}


def _conversion_devis() -> Dict[str, Any]:
    from ml_engine.analytics.conversion_devis import train
    m = train()
    if m.get("error"):
        raise RuntimeError(m["error"])
    return {"auc": (m.get("hors_periode") or {}).get("auc"),
            "servi": m["decision_deploiement"]["modele_deploye"]}


def _segmentation() -> Dict[str, Any]:
    from ml_engine.analytics.segmentation import train
    m = train()
    return {"silhouette": m["qualite"]["silhouette"], "servi": m["servi"]}


def _credit() -> Dict[str, Any]:
    from ml_engine.analytics.credit_risk_model import train
    m = train()
    return {"couverture_pct": m["production"]["couverture_par_la_regle_pct"],
            "servi": m["production"]["statut"] == "servi"}


def _flux_stock() -> Dict[str, Any]:
    """Flux réels + régénération du volet simulé."""
    from ml_engine.stock.flux_reels import construire

    m = construire()
    if m.get("error"):
        raise RuntimeError(m["error"])

    simule_ok = False

    positions_ok = False
    try:
        from ml_engine.stock.positions_historiques import construire as pos
        positions_ok = not (pos(con=None) or {}).get("error")
    except Exception:
        pass

    return {"valeur_dt": m["valeur_accumulee_dt"],
            "volet_simule_regenere": simule_ok,
            "positions_mensuelles_reconstruites": positions_ok,
            "servi": True}


def _fin_de_vie() -> Dict[str, Any]:
    """Fin de commercialisation à 6 mois."""
    from ml_engine.stock.fin_de_vie import train

    m = train()
    if m.get("error"):
        raise RuntimeError(m["error"])
    return {"auc": (m.get("hors_periode") or {}).get("auc"),
            "servi": m["decision_deploiement"]["modele_deploye"]}


def _reappro() -> Dict[str, Any]:
    """Réapprovisionnement à 3 mois."""
    from ml_engine.stock.reappro_model import train

    m = train()
    if m.get("error"):
        raise RuntimeError(m["error"])
    return {"auc": (m.get("hors_periode") or {}).get("auc"),
            "servi": m["decision_deploiement"]["modele_deploye"]}


def _echeancier() -> Dict[str, Any]:
    """L'échéancier n'expose pas de `train` : il évalue puis écrit son rapport."""
    import json as _json

    from ml_engine.forecasting.carnet_echeances import REPORTS as R_CARNET
    from ml_engine.forecasting.carnet_echeances import evaluer

    res = evaluer()
    R_CARNET.mkdir(parents=True, exist_ok=True)
    (R_CARNET / "cashflow_carnet_metrics.json").write_text(
        _json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")

    h1 = (res.get("horizons") or {}).get("h1") or {}
    return {"mape_h1": h1.get("mape_pct"), "servi": not h1.get("refuse", False)}


def _demande() -> Dict[str, Any]:
    from ml_engine.forecasting.demande_hybride import train
    m = train()
    return {"mape": m["methode_servie"]["mape_pct"], "servi": True}


def _demande_reference() -> Dict[str, Any]:
    """Demande par référence : rejoue le duel règle simple / modèle appris sur les 18 derniers mois, et…"""
    from ml_engine.forecasting.demande_reference import train
    m = train()
    return {"wape_h1": m["methode_servie"]["wape_h1_pct"],
            "methode": m["methode_servie"]["nom"], "servi": True}


def _recommandation() -> Dict[str, Any]:
    """Recommandation de produits : Wide & Deep mesuré contre LightGBM et références."""
    from ml_engine.deep.recommandation import train

    m = train(verbose=False)
    if m.get("error"):
        raise RuntimeError(m["error"])
    ev = m.get("evaluation") or {}
    return {"ndcg_at_10": (ev.get("methode_servie") or {}).get("ndcg_at_10"),
            "servi": bool((m.get("decision_deploiement") or {}).get("servi"))}


MODELES: Dict[str, Dict[str, Any]] = {
    "churn": {"libelle": "Décrochage client", "fn": _churn,
              "metrique": "auc", "sens": "haut"},
    "segmentation": {"libelle": "Typologie de clientèle", "fn": _segmentation,
                     "metrique": "silhouette", "sens": "haut"},
    "conversion_devis": {"libelle": "Conversion des devis",
                         "fn": _conversion_devis,
                         "metrique": "auc", "sens": "haut"},
    "marge_client": {"libelle": "Érosion de marge client",
                     "fn": _marge_client,
                     "metrique": "auc", "sens": "haut"},
    "ca_client_3m": {"libelle": "Chiffre d'affaires client à 3 mois",
                     "fn": lambda: _ca_client(3),
                     "metrique": "erreur_medianne_dt", "sens": "bas"},
    "ca_client_12m": {"libelle": "Chiffre d'affaires client à 12 mois",
                      "fn": lambda: _ca_client(12),
                      "metrique": "erreur_medianne_dt", "sens": "bas"},
    "credit": {"libelle": "Conditions de crédit", "fn": _credit,
               "metrique": "couverture_pct", "sens": "haut"},
    "flux_stock": {"libelle": "Position de stock réelle", "fn": _flux_stock,
                   "metrique": "valeur_dt", "sens": None},
    "fin_de_vie": {"libelle": "Fin de commercialisation à 6 mois",
                   "fn": _fin_de_vie, "metrique": "auc", "sens": "haut"},
    "reappro": {"libelle": "Besoin de réapprovisionnement à 3 mois",
                "fn": _reappro, "metrique": "auc", "sens": "haut"},
    "echeancier": {"libelle": "Échéancier de trésorerie", "fn": _echeancier,
                   "metrique": "mape_h1", "sens": "bas"},
    "demande": {"libelle": "Prévision de demande", "fn": _demande,
                "metrique": "mape", "sens": "bas"},
    "demande_reference": {"libelle": "Demande par référence (1 à 3 mois)",
                          "fn": _demande_reference, "metrique": "wape_h1", "sens": "bas"},
    "recommandation": {"libelle": "Recommandation de produits (deep learning)",
                       "fn": _recommandation, "metrique": "ndcg_at_10", "sens": "haut"},
}

SEUIL_DEGRADATION = 0.10


def _comparer(nom: str, avant: Optional[Dict[str, Any]],
              apres: Dict[str, Any]) -> Optional[str]:
    """La métrique du modèle s'est-elle dégradée après réentraînement ?"""
    spec = MODELES[nom]
    cle, sens = spec["metrique"], spec["sens"]
    if sens is None or not avant:
        return None
    v_avant, v_apres = avant.get(cle), apres.get(cle)
    if not isinstance(v_avant, (int, float)) or not isinstance(v_apres, (int, float)):
        return None
    if v_avant == 0:
        return None

    variation = (v_apres - v_avant) / abs(v_avant)
    degrade = variation < -SEUIL_DEGRADATION if sens == "haut" else variation > SEUIL_DEGRADATION
    if not degrade:
        return None
    return (f"{spec['libelle']} : {cle} passe de {v_avant} à {v_apres} "
            f"({variation:+.1%}). Les nouvelles données sont moins prévisibles "
            "que les précédentes — à surveiller au prochain cycle.")


def verifier() -> Dict[str, Any]:
    """Quels modèles ont appris sur des données périmées ?"""
    actuelle = empreinte_actuelle()
    if actuelle.get("erreur"):
        return {"erreur": actuelle["erreur"]}

    enregistrees = _empreintes_enregistrees()
    emp = actuelle["empreinte"]

    a_jour, perimes, jamais = [], [], []
    for nom in MODELES:
        e = enregistrees.get(nom)
        if not e:
            jamais.append(nom)
        elif e.get("empreinte") == emp:
            a_jour.append(nom)
        else:
            perimes.append(nom)

    return {
        "empreinte_actuelle": emp,
        "donnees": {k: v for k, v in actuelle.items() if k != "empreinte"},
        "a_jour": a_jour,
        "perimes": perimes,
        "jamais_entraines": jamais,
        "n_a_resynchroniser": len(perimes) + len(jamais),
    }


def synchroniser(forcer: bool = False) -> Dict[str, Any]:
    """Réentraîne ce qui doit l'être, et trace tout ce qui se passe."""
    etat = verifier()
    if etat.get("erreur"):
        return {"erreur": etat["erreur"]}

    emp = etat["empreinte_actuelle"]
    detail = etat["donnees"]
    enregistrees = _empreintes_enregistrees()

    cibles = (list(MODELES) if forcer
              else etat["perimes"] + etat["jamais_entraines"])

    resultats: List[Dict[str, Any]] = []
    for nom in cibles:
        spec = MODELES[nom]
        debut = time.time()
        try:
            apres = spec["fn"]()
            avant = (enregistrees.get(nom) or {}).get("resultat")
            alerte = _comparer(nom, avant, apres)

            _enregistrer(nom, emp, detail)
            d = _empreintes_enregistrees()
            d[nom]["resultat"] = apres
            json.dump(d, open(EMPREINTES, "w", encoding="utf-8"),
                      indent=2, ensure_ascii=False)

            resultats.append({
                "modele": nom, "libelle": spec["libelle"], "ok": True,
                "duree_s": round(time.time() - debut, 1),
                "resultat": apres,
                "servi_apres": bool(apres.get("servi", True)),
                "servi_avant": (None if not isinstance(avant, dict)
                                else bool(avant.get("servi", False))),
                "alerte_degradation": alerte,
            })
        except Exception as e:
            resultats.append({
                "modele": nom, "libelle": spec["libelle"], "ok": False,
                "duree_s": round(time.time() - debut, 1),
                "erreur": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[-600:],
            })

    echecs = [r for r in resultats if not r["ok"]]
    refuses = [r for r in resultats if r["ok"] and not r["servi_apres"]]

    regressions = [r for r in refuses if r.get("servi_avant") is True]
    refus_stables = [r for r in refuses if r.get("servi_avant") is not True]
    degradations = [r["alerte_degradation"] for r in resultats
                    if r.get("alerte_degradation")]

    rapport = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "empreinte": emp,
        "donnees": detail,
        "n_resynchronises": len(resultats),
        "resultats": resultats,
        "echecs": [f"{r['libelle']} — {r['erreur']}" for r in echecs],
        "modeles_refuses_apres_reentrainement": [r["libelle"] for r in refuses],
        "modeles_ayant_PERDU_le_service": [r["libelle"] for r in regressions],
        "modeles_refuses_de_longue_date": [r["libelle"] for r in refus_stables],
        "distinction": (
            "Un modèle refusé depuis l'origine et un modèle qui ÉTAIT servi et ne "
            "l'est plus appellent des réactions opposées : le premier est une "
            "conclusion conservée à dessein, le second une régression à "
            "investiguer. Seul le second fait basculer l'état en « attention »."),
        "degradations": degradations,
        "etat": ("echec" if echecs else
                 "attention" if (regressions or degradations) else
                 "ok" if resultats else "rien_a_faire"),
        "principe": (
            "Aucune défaillance n'est masquée. Un modèle qui n'atteint plus ses "
            "seuils après réentraînement est refusé par le registre et disparaît "
            "du tableau de bord : mieux vaut une absence qu'une réponse fausse."),
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    json.dump(rapport, open(REPORTS / "synchro.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    return rapport


def afficher(verifier_seulement: bool = False, forcer: bool = False) -> int:
    if verifier_seulement:
        e = verifier()
        if e.get("erreur"):
            print(f"\nErreur : {e['erreur']}\n")
            return 2
        print("\n" + "=" * 74)
        print("  ÉTAT DE SYNCHRONISATION")
        print("=" * 74)
        d = e["donnees"]
        print(f"\n  Données : {d['n_factures']:,} factures · {d['n_clients']} clients"
              .replace(",", " "))
        print(f"            {d['periode']}")
        print(f"  Empreinte : {e['empreinte_actuelle']}")
        print(f"\n  À jour              : {len(e['a_jour'])} modèle(s)")
        print(f"  Données périmées    : {len(e['perimes'])} modèle(s)")
        print(f"  Jamais entraînés    : {len(e['jamais_entraines'])} modèle(s)")
        if e["n_a_resynchroniser"]:
            noms = [MODELES[n]["libelle"] for n in e["perimes"] + e["jamais_entraines"]]
            print("\n  À resynchroniser : " + ", ".join(noms))
            print("\n  Lancer : python -m ml_engine.synchro")
        else:
            print("\n  Tous les modèles ont appris sur les données actuelles.")
        print("=" * 74 + "\n")
        return 1 if e["n_a_resynchroniser"] else 0

    r = synchroniser(forcer=forcer)
    if r.get("erreur"):
        print(f"\nErreur : {r['erreur']}\n")
        return 2

    print("\n" + "=" * 74)
    print(f"  SYNCHRONISATION — {datetime.now():%d/%m/%Y %H:%M}")
    print("=" * 74)

    if not r["resultats"]:
        print("\n  Les modèles ont déjà appris sur ces données. Rien à faire.")
        print("=" * 74 + "\n")
        return 0

    print(f"\n  {r['n_resynchronises']} modèle(s) réentraîné(s) :\n")
    for x in r["resultats"]:
        if x["ok"]:
            if x["servi_apres"]:
                etat = "servi"
            elif x.get("servi_avant") is True:
                etat = "SERVICE PERDU"
            else:
                etat = "refusé (comme avant)"
            print(f"    {x['libelle']:<38} {etat:<22} ({x['duree_s']} s)")
        else:
            print(f"    {x['libelle']:<38} ÉCHEC — {x['erreur'][:40]}")

    regressions = r.get("modeles_ayant_PERDU_le_service") or []
    stables = r.get("modeles_refuses_de_longue_date") or []

    if r["echecs"] or regressions or r["degradations"]:
        print("\n  " + "-" * 70)
        for e in r["echecs"]:
            print(f"    ÉCHEC : {e}")
        for m in regressions:
            print(f"    SERVICE PERDU : {m} était servi et ne l'est plus — "
                  "à investiguer")
        for d in r["degradations"]:
            for i in range(0, len(d), 66):
                print(f"    {'DÉGRADATION : ' if i == 0 else '              '}{d[i:i+66]}")
    else:
        print("\n  Aucune régression détectée.")

    if stables:
        print(f"\n  Refus confirmés (inchangés, attendus) : {', '.join(stables)}")
        print("    Ces modules ont été mesurés puis écartés parce qu'une règle "
              "d'une variable")
        print("    les égalait. Le réentraînement confirme ce verdict — c'est le "
              "résultat")
        print("    normal, pas un incident.")

    print("=" * 74 + "\n")
    return 2 if r["echecs"] else (1 if r["etat"] == "attention" else 0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Synchronisation modèles ↔ données.")
    ap.add_argument("--verifier", action="store_true",
                    help="signale les modèles périmés sans rien réentraîner")
    ap.add_argument("--forcer", action="store_true",
                    help=("réentraîne TOUT, même si les données n'ont pas changé. "
                          "Utile avant une soutenance ou après un changement de "
                          "version de bibliothèque"))
    args = ap.parse_args()
    if args.verifier and args.forcer:
        ap.error("--verifier et --forcer s'excluent : le premier ne réentraîne "
                 "rien, le second réentraîne tout")
    raise SystemExit(afficher(args.verifier, args.forcer))
