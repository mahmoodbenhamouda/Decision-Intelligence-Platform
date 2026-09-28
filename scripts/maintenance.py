"""
scripts/maintenance.py
=======================
Une seule commande pour garder la plateforme à jour — et signaler ce qui cloche.

Le problème résolu
------------------
« Qui maintient tout ça quand vous partez ? » Personne dans l'équipe ne sait
enchaîner sept commandes Python dans le bon ordre. Sans réponse à cette question,
la plateforme cesse d'être fiable en quelques mois sans que personne ne s'en
aperçoive — c'est précisément ce qui rend la dérive dangereuse : elle est
silencieuse.

Ce que fait ce script
---------------------
Il enchaîne, dans l'ordre des dépendances : reconstruction de l'entrepôt,
contrôles d'intégrité, ré-entraînement des modèles, surveillance de dérive,
mesure d'impact. Puis il écrit un **rapport court**, lisible par quelqu'un qui
n'est pas développeur.

Principe de conception : **il ne signale que ce qui mérite attention**. Un rapport
qui dit « tout va bien » chaque jour n'est plus lu au bout d'une semaine, et la
première vraie alerte passe inaperçue.

Codes de sortie
---------------
    0  tout est à jour, rien à signaler
    1  attention requise (dérive, contrôle en échec, modèle refusé)
    2  échec technique — une étape n'a pas pu s'exécuter

Le code 1 est distinct du 2 délibérément : une dérive détectée n'est pas une
panne, c'est le système qui fait son travail.

Planification (Windows, hebdomadaire, lundi 6 h)
-------------------------------------------------
    schtasks /create /tn "Overlyne - maintenance" /tr ^
      "C:\\chemin\\.venv\\Scripts\\python.exe C:\\chemin\\scripts\\maintenance.py" ^
      /sc weekly /d MON /st 06:00

Lancement manuel :
    python scripts/maintenance.py
    python scripts/maintenance.py --verifier-seulement
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

REPORTS = RACINE / "reports"


class Etape:
    """Une étape de maintenance, isolée : son échec n'arrête pas les suivantes."""

    def __init__(self, cle: str, libelle: str, fn: Callable[[], Any],
                 critique: bool = False):
        self.cle = cle
        self.libelle = libelle
        self.fn = fn
        self.critique = critique

    def executer(self) -> Dict[str, Any]:
        debut = time.time()
        try:
            resultat = self.fn()
            return {"cle": self.cle, "libelle": self.libelle, "ok": True,
                    "duree_s": round(time.time() - debut, 1),
                    "resultat": resultat}
        except Exception as e:
            return {"cle": self.cle, "libelle": self.libelle, "ok": False,
                    "duree_s": round(time.time() - debut, 1),
                    "erreur": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-800:],
                    "critique": self.critique}


# ── Étapes ──────────────────────────────────────────────────────────────────
def _entrepot() -> Dict[str, Any]:
    from etl.construire import construire
    from ml_engine.analytics.kpi_engine import STORE_PATH
    r = construire(STORE_PATH)
    alertes = [c["controle"] for c in r["controles"] if c["statut"] == "alerte"]
    return {"entrepot": r["entrepot"], "duree_s": r["duree_s"],
            "volumes": r["volumes"], "alertes_qualite": alertes}


def _integrite() -> Dict[str, Any]:
    from ml_engine.analytics.data_quality import controler_integrite
    r = controler_integrite()
    erreurs = r.get("erreurs") or []
    alertes = r.get("alertes") or []
    return {
        "statut": r.get("statut"),
        "n_erreurs": len(erreurs),
        "n_alertes": len(alertes),
        # Les erreurs invalident un chiffre publié ; les alertes signalent une
        # anomalie sans le remettre en cause. La distinction est celle du module
        # d'intégrité, on ne la réinvente pas ici.
        "details": [e.get("message", "") for e in (erreurs + alertes)][:5],
        "resume": r.get("resume", ""),
    }


def _synchro() -> Dict[str, Any]:
    """Réentraîne UNIQUEMENT les modèles dont les données ont changé.

    Remplace le réentraînement systématique : inutile de refaire tourner six
    modèles quand l'export n'a pas bougé. La comparaison se fait par empreinte
    des données, pas par date de fichier — copier un CSV sans le modifier ne
    déclenche donc rien.
    """
    from ml_engine.synchro import synchroniser
    r = synchroniser()
    if r.get("erreur"):
        raise RuntimeError(r["erreur"])
    return {
        "n_resynchronises": r["n_resynchronises"],
        "echecs": r["echecs"],
        "refuses": r["modeles_refuses_apres_reentrainement"],
        "degradations": r["degradations"],
        "etat": r["etat"],
    }


def _derive() -> Dict[str, Any]:
    from ml_engine.derive import rapport
    r = rapport()
    return {"etat": r["etat"], "n_alertes": r["n_alertes"],
            "alertes": [a["alerte"] for a in r["alertes"]]}


def _impact() -> Dict[str, Any]:
    from ml_engine.analytics.impact import calculer
    m = calculer()
    return {"identifie_dt": m["montant_total_identifie_dt"],
            "recuperable_dt": m["montant_total_recuperable_dt"]}


def _encours() -> Dict[str, Any]:
    from ml_engine.analytics.encours import calculer
    m = calculer()
    if m.get("error"):
        raise RuntimeError(m["error"])
    return {"a_verifier_dt": m["a_verifier"]["montant_dt"],
            "n_clients": m["a_verifier"]["n_clients"]}


def _registre() -> Dict[str, Any]:
    from ml_engine.registre import etat_complet
    e = etat_complet()
    return {"servis": e["n_deployes"], "total": e["n_total"],
            "refuses": e["refuses"]}


ETAPES_COMPLETES: List[Etape] = [
    Etape("entrepot", "Reconstruction de l'entrepôt", _entrepot, critique=True),
    Etape("integrite", "Contrôles d'intégrité comptable", _integrite, critique=True),
    Etape("synchro", "Modèles ↔ données (réentraînement si besoin)", _synchro),
    Etape("derive", "Surveillance de dérive", _derive),
    Etape("encours", "Encours contractuel", _encours),
    Etape("impact", "Mesure d'impact", _impact),
    Etape("registre", "État du registre des modèles", _registre),
]

# Vérification seule : aucun ré-entraînement, aucune écriture lourde. Utile pour
# un contrôle quotidien, là où le ré-entraînement reste hebdomadaire.
ETAPES_VERIFICATION: List[Etape] = [
    Etape("integrite", "Contrôles d'intégrité comptable", _integrite, critique=True),
    Etape("derive", "Surveillance de dérive", _derive),
    Etape("encours", "Encours contractuel", _encours),
    Etape("registre", "État du registre des modèles", _registre),
]


# ── Synthèse ────────────────────────────────────────────────────────────────
def analyser(resultats: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ne retient QUE ce qui appelle une action.

    Un rapport qui énumère tout ce qui va bien n'est plus lu au bout d'une
    semaine, et la première vraie alerte y passe inaperçue.
    """
    alertes: List[str] = []
    pannes: List[str] = []

    for r in resultats:
        if not r["ok"]:
            (pannes if r.get("critique") else alertes).append(
                f"{r['libelle']} n'a pas pu s'exécuter — {r['erreur']}")
            continue

        res = r["resultat"] or {}

        if r["cle"] == "integrite":
            if res.get("n_erreurs"):
                pannes.append(
                    f"{res['n_erreurs']} contrôle(s) d'intégrité en ERREUR : "
                    + " ; ".join(res["details"][:2])
                    + ". Les chiffres publiés sont peut-être faux.")
            elif res.get("n_alertes"):
                alertes.append(
                    f"{res['n_alertes']} anomalie(s) d'intégrité signalée(s) : "
                    + " ; ".join(res["details"][:2]))

        if r["cle"] == "derive" and res.get("n_alertes"):
            for a in res["alertes"]:
                alertes.append(f"Dérive — {a}")

        if r["cle"] == "synchro":
            for e in res.get("echecs") or []:
                pannes.append(f"Réentraînement impossible — {e}")
            for m in res.get("refuses") or []:
                alertes.append(
                    f"« {m} » n'atteint plus ses seuils après réentraînement : "
                    "le module a été retiré du tableau de bord. Mieux vaut une "
                    "absence qu'une réponse fausse, mais cela mérite un examen.")
            for d in res.get("degradations") or []:
                alertes.append(f"Dégradation — {d}")

        if r["cle"] == "registre" and res.get("refuses"):
            alertes.append(
                "Modules non servis : " + ", ".join(res["refuses"]))

    return {
        "n_alertes": len(alertes), "n_pannes": len(pannes),
        "alertes": alertes, "pannes": pannes,
        "etat": "panne" if pannes else ("attention" if alertes else "ok"),
    }


def ecrire_rapport(resultats: List[Dict[str, Any]], synthese: Dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    chemin = REPORTS / "maintenance.json"
    json.dump({
        "date": datetime.now().isoformat(timespec="seconds"),
        "synthese": synthese,
        "etapes": [{k: v for k, v in r.items() if k != "trace"} for r in resultats],
    }, open(chemin, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return chemin


def main() -> int:
    ap = argparse.ArgumentParser(description="Maintenance de la plateforme.")
    ap.add_argument("--verifier-seulement", action="store_true",
                    help="contrôles et surveillance, sans ré-entraînement")
    args = ap.parse_args()

    etapes = ETAPES_VERIFICATION if args.verifier_seulement else ETAPES_COMPLETES
    mode = "VÉRIFICATION" if args.verifier_seulement else "MAINTENANCE COMPLÈTE"

    print("\n" + "=" * 74)
    print(f"  {mode} — {datetime.now():%d/%m/%Y %H:%M}")
    print("=" * 74 + "\n")

    resultats = []
    for i, e in enumerate(etapes, 1):
        print(f"  [{i}/{len(etapes)}] {e.libelle}…", end=" ", flush=True)
        r = e.executer()
        resultats.append(r)
        print(f"ok ({r['duree_s']} s)" if r["ok"] else f"ÉCHEC — {r['erreur'][:60]}")

    synthese = analyser(resultats)
    chemin = ecrire_rapport(resultats, synthese)

    print("\n" + "-" * 74)
    if synthese["etat"] == "ok":
        print("  Tout est à jour. Rien ne demande votre attention.")
    else:
        if synthese["pannes"]:
            print("  PANNES — la plateforme peut afficher des chiffres périmés :")
            for p in synthese["pannes"]:
                print(f"    • {p}")
        if synthese["alertes"]:
            print("\n  À VÉRIFIER :")
            for a in synthese["alertes"]:
                for j in range(0, len(a), 68):
                    print(f"    {'• ' if j == 0 else '  '}{a[j:j+68]}")

    print(f"\n  Détail : {chemin}")
    print("=" * 74 + "\n")

    return 2 if synthese["pannes"] else (1 if synthese["alertes"] else 0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
