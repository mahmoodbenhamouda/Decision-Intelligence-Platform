"""
ml_engine/synchro.py
=====================
Garder les modèles alignés sur les données — sans que personne y pense.

Le problème
-----------
Un nouvel export de l'ERP arrive. Les modèles, eux, ont appris sur l'ancien : ils
continuent de répondre, avec le même aplomb, sur une réalité qui a changé. Rien
ne casse, aucun message n'apparaît. C'est exactement ce qui rend cette
défaillance dangereuse — elle est **silencieuse**.

Le mécanisme
------------
Chaque modèle enregistre l'EMPREINTE des données sur lesquelles il a appris :
volumétrie, période couverte, total facturé. Avant de servir, on compare cette
empreinte à celle des données actuelles. Si elles diffèrent, le modèle est
périmé et doit être réentraîné.

Le principe est déjà utilisé dans le générateur de stock, qui se régénère quand
la signature de la demande change. On le généralise ici à tous les modèles.

Ce que ce module ne fait PAS, et c'est délibéré
------------------------------------------------
Il ne masque aucune défaillance. Si un réentraînement échoue, ou si le modèle
réentraîné n'atteint plus ses seuils, le registre le refusera et le module
disparaîtra du tableau de bord — c'est le comportement correct, même s'il est
moins flatteur qu'un affichage qui continue coûte que coûte.

**Un système qui dissimule ses pannes est pire qu'un système qui en a** : il fait
prendre de mauvaises décisions en silence. Tout ce qui se produit ici laisse donc
une trace dans `reports/synchro.json`, succès comme échecs.

Lancement :
    python -m ml_engine.synchro            # vérifie et réentraîne si nécessaire
    python -m ml_engine.synchro --verifier # signale sans rien réentraîner
    python -m ml_engine.synchro --forcer   # réentraîne tout, données inchangées
"""

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


# ── Empreinte des données ───────────────────────────────────────────────────
def empreinte_actuelle(con=None) -> Dict[str, Any]:
    """Signature de l'état des données, stable et sensible aux vrais changements.

    Les grandeurs retenues changent dès qu'une facture est ajoutée, corrigée ou
    supprimée, mais **pas** entre deux exécutions sur des données identiques.
    Un horodatage de fichier aurait déclenché un réentraînement à chaque copie du
    CSV, même sans modification du contenu.
    """
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


# ── Modèles suivis ──────────────────────────────────────────────────────────
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
    """Flux réels + régénération du volet simulé.

    La reconstruction de l'entrepôt supprime la table `stock_simule` : sans
    régénération, l'interface affiche « stock non généré » alors que les données
    réelles, elles, sont disponibles. Les deux volets doivent donc être
    reconstruits ensemble.

    Le volet simulé reste nécessaire pour ce que les factures ne portent pas :
    les dates de péremption n'existent nulle part dans l'export.
    """
    from ml_engine.stock.flux_reels import construire

    m = construire()
    if m.get("error"):
        raise RuntimeError(m["error"])

    # Le volet SIMULÉ n'est plus régénéré. Il l'était pour que l'interface ne
    # tombe pas en panne après reconstruction de l'entrepôt — mais rien ne le lit
    # plus : API, frontend, agents et rapport d'impact servent tous les flux réels,
    # et le modèle de risque produit qui en dépendait est retiré du service.
    #
    # Continuer à le régénérer entretiendrait un chemin mort susceptible d'être
    # rebranché par inadvertance.
    simule_ok = False

    # Les positions MENSUELLES se reconstruisent dans le même mouvement : elles
    # dérivent de `stock_flux_reel`, et un modèle appris dessus deviendrait muet
    # si sa table d'entrée n'était pas régénérée en même temps que sa source.
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
    """Fin de commercialisation à 6 mois.

    Ordonné après `flux_stock`, comme le réapprovisionnement : son panneau lit
    `stock_position_mensuelle`, que celui-ci vient de reconstruire.
    """
    from ml_engine.stock.fin_de_vie import train

    m = train()
    if m.get("error"):
        raise RuntimeError(m["error"])
    return {"auc": (m.get("hors_periode") or {}).get("auc"),
            "servi": m["decision_deploiement"]["modele_deploye"]}


def _reappro() -> Dict[str, Any]:
    """Réapprovisionnement à 3 mois.

    Ordonné APRÈS `flux_stock` dans `MODELES` : son panneau d'apprentissage lit
    `stock_position_mensuelle`, que la fonction précédente vient de reconstruire.
    Inverser les deux entraînerait le modèle sur les positions de la veille.
    """
    from ml_engine.stock.reappro_model import train

    m = train()
    if m.get("error"):
        raise RuntimeError(m["error"])
    return {"auc": (m.get("hors_periode") or {}).get("auc"),
            "servi": m["decision_deploiement"]["modele_deploye"]}


def _echeancier() -> Dict[str, Any]:
    """L'échéancier n'expose pas de `train` : il évalue puis écrit son rapport.

    On reproduit donc ici ce que fait son point d'entrée, plutôt que d'appeler
    un nom de fonction qui n'existe pas — l'erreur que la trace a révélée au
    premier passage.
    """
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
    """Demande par référence : rejoue le duel règle simple / modèle appris sur
    les 18 derniers mois, et sert le vainqueur selon la règle de déploiement."""
    from ml_engine.forecasting.demande_reference import train
    m = train()
    return {"wape_h1": m["methode_servie"]["wape_h1_pct"],
            "methode": m["methode_servie"]["nom"], "servi": True}


def _recommandation() -> Dict[str, Any]:
    """Recommandation de produits : Wide & Deep mesuré contre LightGBM et références.

    Ordonnée après `churn` et `segmentation` sans en dépendre ; elle lit
    `sales_lines`. Sans PyTorch, le deep learning n'est pas mesuré et le rapport
    le dit : la méthode servie reste celle que la mesure désigne.
    """
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
    "credit": {"libelle": "Conditions de crédit", "fn": _credit,
               "metrique": "couverture_pct", "sens": "haut"},
    "flux_stock": {"libelle": "Position de stock réelle", "fn": _flux_stock,
                   "metrique": "valeur_dt", "sens": None},
    # Ces deux-là doivent suivre `flux_stock` : ils apprennent sur la table que
    # celui-ci matérialise.
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

# Variation relative au-delà de laquelle une métrique est jugée dégradée. En
# deçà, l'écart relève du bruit de réentraînement : les découpages temporels se
# déplacent quand des données s'ajoutent, et les métriques bougent légèrement
# sans que le modèle ait empiré.
SEUIL_DEGRADATION = 0.10


def _comparer(nom: str, avant: Optional[Dict[str, Any]],
              apres: Dict[str, Any]) -> Optional[str]:
    """La métrique du modèle s'est-elle dégradée après réentraînement ?

    Cette comparaison est la raison d'être de la trace. Sans elle, un
    réentraînement automatique pourrait remplacer silencieusement un bon modèle
    par un moins bon — et personne ne le saurait jamais.
    """
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


# ── Synchronisation ─────────────────────────────────────────────────────────
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
                # Un modèle réentraîné qui n'atteint pas ses seuils n'est PAS
                # une réussite silencieuse : le registre le refusera, et le
                # tableau de bord cessera de l'afficher.
                "servi_apres": bool(apres.get("servi", True)),
                # ══ DEUX SITUATIONS QUE LE RAPPORT CONFONDAIT ══
                #
                # Un modèle REFUSÉ DEPUIS TOUJOURS et un modèle qui ÉTAIT SERVI
                # et ne l'est plus appellent des réactions opposées. Le premier
                # est une conclusion mesurée, conservée à dessein ; le second est
                # une régression à investiguer.
                #
                # La trace affichait « n'atteint PLUS ses seuils — retiré du
                # tableau de bord » dans les deux cas. Sur un modèle jamais
                # déployé, cette phrase décrit une panne qui n'a pas eu lieu, et
                # un lecteur du rapport en conclurait à une dégradation.
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

    # Seule une PERTE de service est une régression. Un modèle refusé depuis
    # l'origine reste refusé : c'est une conclusion, pas un incident, et l'état
    # global ne doit pas passer en « attention » pour cela.
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
        # Conservé sous ce nom pour ne pas casser les lecteurs existants, mais
        # scindé en deux listes : le total mélangeait une conclusion mesurée et
        # une régression.
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

    # `synchroniser(forcer=True)` existait depuis le début, mais n'était atteignable
    # que depuis du code Python : le CLI ne l'exposait pas. Un paramètre utile et
    # invisible revient à ne pas l'avoir — et il sert précisément à vérifier que la
    # trace dit la vérité quand rien n'a changé dans les données.
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

    # Les refus stables sont affichés À PART, et sans dramatisation : ce sont des
    # conclusions mesurées que le projet conserve volontairement, pas des pannes.
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
