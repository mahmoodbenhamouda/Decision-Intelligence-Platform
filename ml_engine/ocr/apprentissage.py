"""
ml_engine/ocr/apprentissage.py
==============================
Boucle d'apprentissage, partie 1 : MESURER le modèle en production.

La validation croisée mesure le modèle sur 89 factures annotées une fois pour
toutes. En production, chaque facture validée par un utilisateur est une
nouvelle mesure, gratuite : un champ laissé tel quel était juste, un champ
corrigé était faux (ou vide).

    exactitude(champ) = 1 − corrigés / champs à renseigner

« À renseigner » = le champ a une valeur lue OU une valeur validée. Un champ
vide des deux côtés (pas de timbre sur la facture) ne compte ni pour ni contre.

Biais à connaître, et affiché avec le chiffre : « validée telle quelle » veut
dire que l'utilisateur n'a rien modifié, pas qu'il a tout vérifié. Une
validation distraite gonfle l'exactitude. C'est pourquoi on ne mesure que sur
les factures RELUES (écran de validation), jamais sur les imports sans relecture.

Partie 2 (réentraîner) : `evaluation_ocr/preparation/6_integrer_production.py`.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .importer import CHAMPS_VALIDABLES, _assurer_schema, _connect, _valeur

# Champs mesurés : ceux que LayoutLMv3 extrait (le matricule et la devise non).
CHAMPS_MESURES = ["numero", "date_facture", "fournisseur", "client", "montant_ht",
                  "montant_tva", "timbre_fiscal", "montant_ttc", "net_a_payer"]
RELUES = ("corrigee", "validee_telle_quelle")


def mesure_production(depuis: Optional[str] = None) -> Dict[str, Any]:
    """Exactitude par champ et par moteur, sur les factures relues."""
    con = _connect()
    try:
        _assurer_schema(con)
        conds, args = [f"statut_validation IN {RELUES}", "lecture_origine IS NOT NULL"], []
        if depuis:
            conds.append("importe_le >= ?"); args.append(depuis)
        rows = con.execute(f"""SELECT coalesce(moteur, 'inconnu'), lecture_origine, corrections,
                                      coalesce(fournisseur_lu, fournisseur), coalesce(client_lu, client_name),
                                      numero, date, ht, tva, timbre_fiscal, ttc, net_a_payer
                               FROM factures_importees WHERE {' AND '.join(conds)}""", args).fetchall()
    finally:
        con.close()

    par_moteur: Dict[str, Dict[str, Any]] = {}
    for moteur, lu_json, corr_json, four, cli, num, d, ht, tva, tim, ttc, net in rows:
        lu = json.loads(lu_json) if lu_json else {}
        corr = json.loads(corr_json) if corr_json else {}
        valide = {"numero": num, "date_facture": d.isoformat() if d else None, "fournisseur": four,
                  "client": cli, "montant_ht": ht, "montant_tva": tva, "timbre_fiscal": tim,
                  "montant_ttc": ttc, "net_a_payer": net}
        if lu.get("client") is None and lu.get("tiers"):
            lu["client"] = lu["tiers"]                    # lectures « règles seules »
        m = par_moteur.setdefault(moteur, {"n_factures": 0, "n_sans_correction": 0,
                                           "champs": {c: {"n": 0, "corriges": 0} for c in CHAMPS_MESURES}})
        m["n_factures"] += 1
        erreurs = 0
        for c in CHAMPS_MESURES:
            t = CHAMPS_VALIDABLES[c]
            a, b = _valeur(t, lu.get(c)), _valeur(t, valide.get(c))
            if a is None and b is None:
                continue
            m["champs"][c]["n"] += 1
            if c in corr:
                m["champs"][c]["corriges"] += 1
                erreurs += 1
        m["n_sans_correction"] += erreurs == 0

    for m in par_moteur.values():
        for c, v in m["champs"].items():
            v["exactitude_pct"] = round(100 * (1 - v["corriges"] / v["n"]), 1) if v["n"] else None
        tot_n = sum(v["n"] for v in m["champs"].values())
        tot_c = sum(v["corriges"] for v in m["champs"].values())
        m["exactitude_globale_pct"] = round(100 * (1 - tot_c / tot_n), 1) if tot_n else None
        m["factures_sans_correction_pct"] = round(100 * m["n_sans_correction"] / m["n_factures"], 1)
    n = sum(m["n_factures"] for m in par_moteur.values())
    return {
        "n_factures_relues": n,
        "par_moteur": par_moteur,
        "suffisant": n >= 30,
        "note": ("Mesuré sur les factures relues à l'écran de validation : un champ corrigé "
                 "compte comme une erreur du modèle. « Validée telle quelle » signifie « non "
                 "modifiée », pas forcément « vérifiée » : l'exactitude peut être surestimée. "
                 + ("" if n >= 30 else f"Seulement {n} facture(s) : chiffres encore très instables.")),
    }
