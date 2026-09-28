"""
scripts/verif_reproductibilite.py
==================================
Exécute un entraînement DEUX FOIS et compare les rapports champ par champ.

Pourquoi ce script existe
-------------------------
`reports/METRICS_REPORT.md` affirmait « seeds fixées, backtests déterministes ».
C'était faux, et personne ne pouvait le savoir : rien ne le vérifiait. Deux
exécutions identiques du modèle de risque produit donnaient 0,8172 puis 0,8169
d'AUC, et la segmentation renommait des segments d'un lancement à l'autre.

Affirmer une propriété sans la mesurer est exactement ce que ce projet
s'interdit partout ailleurs — un modèle n'est déclaré déployé qu'après une mesure
hors période. La reproductibilité méritait le même traitement.

Comment il procède
------------------
Deux **processus distincts**, et non deux appels dans le même interpréteur. Un
même processus réutilise les bibliothèques déjà chargées, leurs pools de threads
et leurs caches : il masquerait précisément ce qu'on cherche à détecter.

Lecture du résultat
-------------------
Les écarts sont comparés à ce qui est en jeu, pas à zéro dans l'absolu. Un écart
de 0,0003 sur une AUC est sans conséquence ; le même écart devient grave si une
décision se joue à 0,003. Le script signale donc les champs instables ET la
distance de chacun à son seuil de décision quand celui-ci est connu.

    python scripts/verif_reproductibilite.py                  # tous les modules
    python scripts/verif_reproductibilite.py stock_risque     # un seul
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE = Path(__file__).resolve().parents[1]
REPORTS = BASE / "reports"

# Modules vérifiables. `seuils_critiques` documente ce qui se DÉCIDE à partir de
# ces chiffres : c'est la seule manière de juger si un écart est tolérable.
MODULES: Dict[str, Dict[str, Any]] = {
    "stock_risque": {
        "commande": ["-m", "ml_engine.models.stock_risk", "train"],
        "rapport": "stock_risk_metrics.json",
        "seuils_critiques": {
            "ecart_train_valid_auc": (0.10, "disqualification pour sur-apprentissage"),
            "cv_auc": (0.003, "écart typique entre deux candidats voisins"),
        },
    },
    "segmentation": {
        "commande": ["-m", "ml_engine.analytics.segmentation"],
        "rapport": "segmentation_metrics.json",
        "seuils_critiques": {
            "silhouette": (0.25, "seuil d'admissibilité"),
            "stabilite": (0.60, "seuil d'admissibilité"),
        },
    },
    "churn": {
        "commande": ["-m", "ml_engine.analytics.churn_model"],
        "rapport": "churn_metrics.json",
        "seuils_critiques": {
            "auc": (0.01, "écart de parcimonie entre candidats"),
        },
    },
    "reappro": {
        "commande": ["-m", "ml_engine.stock.reappro_model"],
        "rapport": "reappro_metrics.json",
        "seuils_critiques": {
            "auc": (0.02, "gain minimal exigé sur la référence triviale"),
        },
    },
}


def _aplatir(obj: Any, prefixe: str = "") -> Dict[str, float]:
    """Toutes les valeurs numériques du rapport, indexées par leur chemin."""
    out: Dict[str, float] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_aplatir(v, f"{prefixe}.{k}" if prefixe else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_aplatir(v, f"{prefixe}[{i}]"))
    elif isinstance(obj, bool):
        pass            # un booléen n'est pas une mesure
    elif isinstance(obj, (int, float)):
        out[prefixe] = float(obj)
    return out


def _executer(commande: List[str], rapport: str) -> Dict[str, float] | None:
    chemin = REPORTS / rapport
    r = subprocess.run([sys.executable, *commande], cwd=str(BASE),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        print(f"      [échec] code {r.returncode}")
        for ligne in (r.stderr or "").strip().splitlines()[-5:]:
            print(f"        {ligne}")
        return None
    if not chemin.exists():
        print(f"      [échec] rapport absent : {rapport}")
        return None
    try:
        return _aplatir(json.load(open(chemin, encoding="utf-8")))
    except Exception as e:
        print(f"      [échec] rapport illisible : {type(e).__name__}")
        return None


def _juger(champ: str, ecart: float,
           seuils: Dict[str, Tuple[float, str]]) -> str | None:
    """L'écart mesuré met-il en danger une décision connue ?"""
    for cle, (marge, motif) in seuils.items():
        if champ.endswith(cle) or f".{cle}" in champ:
            if ecart >= marge:
                return f"DÉPASSE la marge de {marge} — {motif}"
            if ecart >= marge * 0.10:
                return f"atteint 10 % de la marge de {marge} — {motif}"
            return None
    return None


def verifier(nom: str, spec: Dict[str, Any]) -> bool:
    print(f"\n{'─' * 70}\n  {nom}\n{'─' * 70}")

    print("  exécution 1/2…")
    a = _executer(spec["commande"], spec["rapport"])
    if a is None:
        return False
    print("  exécution 2/2…")
    b = _executer(spec["commande"], spec["rapport"])
    if b is None:
        return False

    communs = sorted(set(a) & set(b))
    ecarts = [(c, abs(a[c] - b[c])) for c in communs if a[c] != b[c]]
    ecarts.sort(key=lambda t: -t[1])

    apparus = sorted(set(b) - set(a))
    disparus = sorted(set(a) - set(b))

    if not ecarts and not apparus and not disparus:
        print(f"  ✔ REPRODUCTIBLE — {len(communs)} valeurs numériques identiques")
        return True

    print(f"  ✘ {len(ecarts)} valeur(s) différente(s) sur {len(communs)}")
    if apparus or disparus:
        print(f"    champs apparus/disparus : {len(apparus)} / {len(disparus)}")

    critique = False
    for champ, e in ecarts[:15]:
        verdict = _juger(champ, e, spec.get("seuils_critiques") or {})
        marque = ""
        if verdict:
            marque = f"   <-- {verdict}"
            if "DÉPASSE" in verdict:
                critique = True
        print(f"    {champ:<58} Δ {e:.6f}{marque}")
    if len(ecarts) > 15:
        print(f"    … et {len(ecarts) - 15} autre(s)")

    if critique:
        print("\n  Au moins un écart dépasse une marge de décision : une "
              "conclusion de déploiement")
        print("  peut basculer d'une exécution à l'autre. À corriger avant "
              "toute présentation.")
    else:
        print("\n  Aucun écart n'atteint une marge de décision. L'instabilité "
              "est réelle mais")
        print("  sans conséquence sur les conclusions — à condition de le dire, "
              "et non de")
        print("  prétendre à un déterminisme parfait.")
    return not critique


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    demandes = sys.argv[1:] or list(MODULES)
    inconnus = [d for d in demandes if d not in MODULES]
    if inconnus:
        print(f"Module(s) inconnu(s) : {inconnus}")
        print(f"Disponibles : {', '.join(MODULES)}")
        return 2

    print("=" * 70)
    print("  REPRODUCTIBILITÉ — deux exécutions, deux processus, comparaison")
    print("=" * 70)

    from ml_engine.determinisme import etat
    e = etat()
    print(f"\n  threadpoolctl : {e['threadpoolctl']}")
    if not e["reproductible"]:
        print("  -> installez-le avant d'interpréter le résultat : "
              "pip install threadpoolctl")

    resultats = {n: verifier(n, MODULES[n]) for n in demandes}

    print("\n" + "=" * 70)
    ok = [n for n, v in resultats.items() if v]
    ko = [n for n, v in resultats.items() if not v]
    print(f"  {len(ok)}/{len(resultats)} module(s) sans écart critique")
    if ko:
        print(f"  à revoir : {', '.join(ko)}")
    print("=" * 70)
    return 0 if not ko else 1


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    sys.exit(main())
