"""Les règles SQL du tableau de bord valent-elles les modèles qu'elles doublent ?

Deux règles de `kpi_engine` répondent à une question déjà traitée par un modèle
mesuré, et personne ne les avait comparées :

  * `clients_decrochent` — `ca_90j < ca_90-180j × 0,4 AND mois_actifs >= 6` —
    face au modèle de décrochage (AUC hors période 0,9224) ;
  * `clients_fideles` — classement par nombre de mois actifs — face à la même
    cible, puisqu'une liste de fidélité sert à savoir qui ne partira pas.

Une règle qui gagne doit être servie, comme pour `fin_de_vie`. Une règle qui perd
doit être requalifiée : « baisse constatée », pas « risque ».

    python scripts/mesurer_regles_kpi.py

Écrit `reports/regles_vs_modeles.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

SORTIE = RACINE / "reports" / "regles_vs_modeles.json"

SEUIL_CHUTE = 0.40
MIN_MOIS_ACTIFS = 6


def _mesures(y, score):
    """AUC, et précision/rappel au point de fonctionnement d'une règle binaire."""
    import numpy as np
    from sklearn.metrics import roc_auc_score

    y = np.asarray(y, dtype=int)
    score = np.asarray(score, dtype=float)
    out = {"n": int(len(y)), "taux_de_base": round(float(y.mean()), 4)}
    try:
        out["auc"] = round(float(roc_auc_score(y, score)), 4)
    except Exception:
        out["auc"] = None

    # Une règle binaire n'a qu'un point : sa précision et son rappel s'y lisent.
    binaire = set(np.unique(score).tolist()) <= {0.0, 1.0}
    if binaire:
        signale = score > 0.5
        n_signale = int(signale.sum())
        out["n_signales"] = n_signale
        out["precision"] = (round(float(y[signale].mean()), 4)
                            if n_signale else None)
        out["rappel"] = (round(float(signale[y == 1].mean()), 4)
                         if (y == 1).any() else None)
    return out


def mesurer() -> dict:
    import numpy as np

    from ml_engine.analytics import churn_model as cm

    rapport = {
        "question": ("les règles du tableau de bord battent-elles les modèles "
                     "qui répondent à la même question ?"),
        "cible_commune": (f"aucune commande dans les {cm.HORIZON_JOURS} jours "
                          "suivant l'observation — la cible du modèle de "
                          "décrochage, inchangée"),
    }

    # `construire_panel` attend les factures : le module ne les charge pas lui-même,
    # pour qu'un test puisse lui en fournir de synthétiques.
    factures = cm.charger_factures()
    if factures is None or factures.empty:
        return {**rapport, "applicable": False, "motif": "aucune facture chargée"}

    panel = cm.construire_panel(factures)
    if panel is None or panel.empty:
        return {**rapport, "applicable": False, "motif": "panneau de churn vide"}

    # Même coupure que le modèle, pour que la comparaison porte sur les mêmes
    # observations : mesurer une règle sur l'ensemble du panel et un modèle sur
    # son seul test ne comparerait rien.
    hp = cm.evaluer_hors_periode(panel)
    if not hp.get("applicable", True) and hp.get("motif"):
        return {**rapport, "applicable": False, "motif": hp["motif"]}

    import pandas as pd

    coupure = hp.get("coupure")
    if not coupure:
        return {**rapport, "applicable": False,
                "motif": "le modèle n'a pas publié de coupure hors période"}
    te = panel[panel["date_obs"] > pd.Timestamp(coupure)]
    if te.empty:
        return {**rapport, "applicable": False, "motif": "test vide"}

    y = te["y"].to_numpy(dtype=int)

    # ── Règle « clients_decrochent », reproduite sur le panel du modèle ───────
    #
    # `ca_prev` est reconstitué par `ca_6m − ca_3m` : le panel de churn n'a pas la
    # fenêtre 90-180 jours en colonne, mais la différence des deux cumuls la donne
    # exactement. La condition `mois_actifs >= 6` n'est pas reproduite : le filtre
    # de client actif du panel l'impose déjà, et c'est déclaré ici plutôt que
    # silencieusement omis.
    ca_recent = te["ca_3m"].to_numpy(dtype=float)
    ca_prev = (te["ca_6m"].to_numpy(dtype=float) - ca_recent)
    regle = ((ca_prev > 0) & (ca_recent < ca_prev * SEUIL_CHUTE)).astype(float)

    # ── Règle « clients_fideles » : classement par récurrence ────────────────
    # Moins de commandes = plus de risque, donc le score est l'opposé.
    fidelite = -te["freq_12m"].to_numpy(dtype=float)

    resultats = {
        "regle_clients_decrochent": {
            "definition": (f"ca_90j < ca_90-180j × {SEUIL_CHUTE} "
                           f"(et mois_actifs >= {MIN_MOIS_ACTIFS}, déjà imposé "
                           "par le filtre de client actif du panel)"),
            "seuils_jamais_mesures_avant_aujourdhui": [SEUIL_CHUTE,
                                                       MIN_MOIS_ACTIFS],
            **_mesures(y, regle),
        },
        "regle_clients_fideles": {
            "definition": "classement par récurrence (freq_12m), signe inversé",
            "note": ("c'est exactement la référence triviale "
                     "« inverse_frequence_12m » que le modèle de décrochage "
                     "devait déjà battre : le projet l'avait donc mesurée sans "
                     "le dire"),
            **_mesures(y, fidelite),
        },
        "modele_churn": {
            "definition": (f"{hp.get('modele_retenu', 'modèle servi')} "
                           "hors période, mêmes observations de test"),
            "auc": (round(float(hp["auc"]), 4) if hp.get("auc") is not None
                    else None),
            "auc_meilleure_reference_triviale":
                (round(float(hp["auc_meilleure_reference_triviale"]), 4)
                 if hp.get("auc_meilleure_reference_triviale") is not None
                 else None),
            "meilleure_reference_triviale":
                hp.get("meilleure_reference_triviale"),
        },
    }

    auc_modele = resultats["modele_churn"]["auc"] or 0.0
    verdicts = {}
    for cle in ("regle_clients_decrochent", "regle_clients_fideles"):
        auc_regle = resultats[cle]["auc"] or 0.0
        ecart = round(auc_regle - auc_modele, 4)
        verdicts[cle] = {
            "ecart_auc_vs_modele": ecart,
            "verdict": ("la règle gagne — elle doit être servie, comme pour "
                        "fin_de_vie" if ecart > 0 else
                        "la règle perd — elle doit être requalifiée en constat, "
                        "pas en risque"),
        }

    return {**rapport, "applicable": True, "coupure": str(coupure),
            "n_test": int(len(te)), "resultats": resultats,
            "verdicts": verdicts,
            "pourquoi_ce_script": (
                "Deux réponses concurrentes à une même question circulaient dans "
                "le même objet `kpis`, l'une mesurée et l'autre pas. Les règles "
                "n'apparaissent sur aucun graphique mais le copilote les lit : "
                "elles atteignaient l'utilisateur sans étiquette.")}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    rapport = mesurer()
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    json.dump(rapport, open(SORTIE, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    print("=" * 78)
    print("  LES RÈGLES DU TABLEAU DE BORD CONTRE LES MODÈLES")
    print("=" * 78)
    if not rapport.get("applicable"):
        print(f"\n  Inapplicable : {rapport.get('motif')}")
        print("=" * 78)
        return 1

    r = rapport["resultats"]
    print(f"\n  Cible   : {rapport['cible_commune']}")
    print(f"  Coupure : {rapport['coupure']} — {rapport['n_test']} observations\n")
    print(f"  {'Prédicteur':<34} {'AUC':>8} {'précision':>11} {'rappel':>8}")
    print("  " + "-" * 64)
    for cle, libelle in (("modele_churn", "modèle de décrochage"),
                         ("regle_clients_decrochent", "règle clients_decrochent"),
                         ("regle_clients_fideles", "règle clients_fideles")):
        b = r[cle]
        pr = b.get("precision")
        ra = b.get("rappel")
        print(f"  {libelle:<34} {b.get('auc') or 0:>8.4f} "
              f"{(f'{pr:.4f}' if pr is not None else '—'):>11} "
              f"{(f'{ra:.4f}' if ra is not None else '—'):>8}")

    print()
    for cle, v in rapport["verdicts"].items():
        print(f"  {cle} : {v['ecart_auc_vs_modele']:+.4f} → {v['verdict']}")
    print(f"\n  → {SORTIE}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
