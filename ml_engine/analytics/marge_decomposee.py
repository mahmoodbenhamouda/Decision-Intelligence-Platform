"""D'où vient la marge brute, et ce qu'elle ne dit pas.

La marge brute affichée au tableau de bord est un total : 76,7 M DT. Un total ne
se décide pas. Ce module le décompose sur les trois axes qui changent une
décision, et publie ce que le chiffre exclut.

  * PAR CATÉGORIE. Overlyne distribue du diagnostic in vitro. Les réactifs sont
    des consommables récurrents, l'équipement est l'automate qui les consomme.
    Les deux ne se vendent pas au même taux : agrégés, ils se masquent l'un
    l'autre.
  * PAR PRODUIT. Une référence porte la marge ou la détruit. Les deux listes
    sont publiées, celle des contributeurs et celle des pertes.
  * DANS LE TEMPS. Un taux de marge ne se juge pas sur un point mais sur sa
    pente.

Ce module ne PRÉDIT rien : il compte ce qui est facturé. La marge future est
l'affaire de `marge_client`. Aucun seuil appris, aucun modèle — donc aucune
règle de portée à appliquer au-delà des filtres eux-mêmes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Libellés des catégories ERP. Des étiquettes, pas des phrases : la rédaction
#: destinée au directeur appartient à la couche API (`api/services/marge.py`),
#: comme le veut le garde-fou de `tests/test_explication.py` — un module de
#: calcul ne doit pas porter de tables de phrases.
LIBELLES = {
    "reactif": "Réactifs",
    "equipement": "Équipement",
    "service": "Services",
    "autre": "Autre",
}

#: Au-delà de ce nombre de produits, une liste cesse d'être lisible : on la
#: traite, on ne la parcourt pas.
N_PRODUITS = 15


def _clauses(f: Optional[Dict[str, Any]], colonne_mois: str = "period") -> str:
    """Filtres du tableau de bord traduits pour les marts de marge."""
    f = f or {}
    w: List[str] = ["1=1"]
    if f.get("selected_years"):
        w.append("year IN (" + ",".join(str(int(y)) for y in f["selected_years"]) + ")")
    if f.get("selected_clients"):
        vals = ",".join("'" + str(c).replace("'", "''") + "'"
                        for c in f["selected_clients"])
        w.append(f"client IN ({vals})")
    if f.get("date_start") and colonne_mois:
        w.append(f"{colonne_mois} >= '{str(f['date_start'])[:7]}'")
    if f.get("date_end") and colonne_mois:
        w.append(f"{colonne_mois} <= '{str(f['date_end'])[:7]}'")
    return " AND ".join(w)


def _taux(ca: float, marge: float) -> Optional[float]:
    return round(marge / ca * 100, 1) if ca else None


def par_categorie(con, filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Marge par catégorie d'activité, avec son rôle économique."""
    lignes = con.execute(f"""
        SELECT categorie, sum(ca_ligne), sum(cout_revient), sum(marge),
               sum(n_lignes)
        FROM margin_category WHERE {_clauses(filtres)}
        GROUP BY categorie ORDER BY sum(ca_ligne) DESC NULLS LAST
    """).fetchall()

    total_ca = sum(float(r[1] or 0) for r in lignes)
    total_marge = sum(float(r[3] or 0) for r in lignes)
    return {
        "categories": [{
            "code": r[0],
            "nom": LIBELLES.get(r[0], r[0]),
            "ca_dt": round(float(r[1] or 0), 0),
            "cout_dt": round(float(r[2] or 0), 0),
            "marge_dt": round(float(r[3] or 0), 0),
            "taux_marge_pct": _taux(float(r[1] or 0), float(r[3] or 0)),
            "part_du_ca_pct": round(float(r[1] or 0) / total_ca * 100, 1) if total_ca else None,
            "part_de_la_marge_pct": (round(float(r[3] or 0) / total_marge * 100, 1)
                                     if total_marge else None),
            "n_lignes": int(r[4] or 0),
        } for r in lignes],
        "total_ca_dt": round(total_ca, 0),
        "total_marge_dt": round(total_marge, 0),
        "taux_ensemble_pct": _taux(total_ca, total_marge),
    }


def produits(con, filtres: Optional[Dict[str, Any]] = None,
             limite: int = N_PRODUITS) -> Dict[str, Any]:
    """Les produits qui portent la marge, et ceux qui la détruisent.

    Les deux listes sont tirées du MÊME agrégat, filtré sur la MÊME période que
    les totaux : un produit ne peut pas figurer dans les deux, et la somme des
    deux ne dépasse jamais la marge totale affichée.
    """
    where = _clauses(filtres)
    agrege = con.execute(f"""
        SELECT reference, any_value(designation), any_value(categorie),
               sum(ca_ligne), sum(cout_revient), sum(marge),
               count(DISTINCT client)
        FROM margin_product WHERE {where}
        GROUP BY reference
    """).fetchall()

    def ligne(r) -> Dict[str, Any]:
        ca, marge = float(r[3] or 0), float(r[5] or 0)
        return {
            "reference": r[0],
            "designation": (r[1] or r[0])[:60],
            "categorie": LIBELLES.get(r[2], r[2]),
            "ca_dt": round(ca, 0),
            "cout_dt": round(float(r[4] or 0), 0),
            "marge_dt": round(marge, 0),
            "taux_marge_pct": _taux(ca, marge),
            "n_clients": int(r[6] or 0),
        }

    tous = [ligne(r) for r in agrege]
    porteurs = sorted((p for p in tous if p["marge_dt"] > 0),
                      key=lambda p: -p["marge_dt"])[:limite]
    pertes = sorted((p for p in tous if p["marge_dt"] < 0),
                    key=lambda p: p["marge_dt"])[:limite]

    marge_totale = sum(p["marge_dt"] for p in tous) or 1.0
    for p in porteurs:
        p["part_de_la_marge_pct"] = round(p["marge_dt"] / marge_totale * 100, 1)

    return {
        "porteurs": porteurs,
        "pertes": pertes,
        "n_references": len(tous),
        "perte_totale_dt": round(sum(p["marge_dt"] for p in pertes), 0),
        "lecture_des_pertes": (
            "Un produit vendu sous son coût de revient n'est pas forcément une "
            "erreur : un automate placé à perte installe le parc qui consommera "
            "des réactifs pendant des années. Ce qui se décide ici, c'est si le "
            "parc a effectivement suivi."),
    }


def tendance(con, filtres: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Taux de marge mois par mois, sur tout l'historique du périmètre.

    La période choisie restreint les totaux, pas la courbe : une pente ne se lit
    pas sur douze points isolés."""
    f = dict(filtres or {})
    f.pop("date_start", None)
    f.pop("date_end", None)
    f.pop("selected_years", None)
    lignes = con.execute(f"""
        SELECT period, sum(ca_ligne), sum(marge)
        FROM margin_category WHERE {_clauses(f)}
        GROUP BY period ORDER BY period
    """).fetchall()
    return [{
        "period": r[0],
        "ca_dt": round(float(r[1] or 0), 0),
        "marge_dt": round(float(r[2] or 0), 0),
        "taux_marge_pct": _taux(float(r[1] or 0), float(r[2] or 0)),
    } for r in lignes]


def completude(con, periode: Dict[str, Any],
               filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """L'année en cours n'est pas une année : il y manque des mois.

    L'entrepôt s'arrête à la dernière facture exportée. Afficher « marge de
    l'année en cours » sur quatre mois écoulés laisse croire à un effondrement
    alors qu'il ne manque que du temps. On publie donc trois choses : combien de
    mois sont réellement couverts, ce que la même fenêtre valait l'an dernier,
    et une PROJECTION de fin d'année clairement nommée comme telle.

    La projection repose sur une règle simple et vérifiable : la part de l'année
    déjà réalisée, mesurée sur l'exercice précédent. Si janvier-avril pesait 34 %
    de la marge de l'an dernier, les quatre mois de cette année en représentent
    vraisemblablement une part comparable. C'est une saisonnalité constatée, pas
    un modèle appris — et c'est annoncé.
    """
    if periode.get("code") != "annee" or not periode.get("fin"):
        return {}

    fin = str(periode["fin"])
    annee = int(fin[:4])
    dernier_mois = fin[:7]
    n_mois = int(fin[5:7])

    # Les bornes de dates injectées par `analyser` délimitent l'année en cours :
    # les garder écraserait la comparaison avec l'exercice précédent. On repart
    # des filtres de l'utilisateur, et c'est `selected_years` qui porte l'année.
    propre = {k: v for k, v in (filtres or {}).items()
              if k not in ("date_start", "date_end", "selected_years")}

    base = _clauses({**propre, "selected_years": [annee]})
    courant = con.execute(
        f"SELECT sum(ca_ligne), sum(marge) FROM margin_category WHERE {base}"
    ).fetchone() or (0, 0)

    prec = annee - 1
    base_prec = _clauses({**propre, "selected_years": [prec]})
    ref = con.execute(f"""
        SELECT sum(ca_ligne) FILTER (WHERE period <= '{prec}-{n_mois:02d}'),
               sum(marge)    FILTER (WHERE period <= '{prec}-{n_mois:02d}'),
               sum(ca_ligne), sum(marge)
        FROM margin_category WHERE {base_prec}
    """).fetchone() or (0, 0, 0, 0)

    marge_courante = float(courant[1] or 0)
    marge_prec_partielle = float(ref[1] or 0)
    marge_prec_totale = float(ref[3] or 0)

    part = (marge_prec_partielle / marge_prec_totale
            if marge_prec_totale else None)
    projection = (round(marge_courante / part, 0)
                  if part and part > 0.05 else None)

    evolution = (round((marge_courante - marge_prec_partielle)
                       / marge_prec_partielle * 100, 1)
                 if marge_prec_partielle else None)

    return {
        "annee": annee,
        "mois_couverts": n_mois,
        "mois_dans_l_annee": 12,
        "dernier_mois": dernier_mois,
        "incomplete": n_mois < 12,
        "marge_realisee_dt": round(marge_courante, 0),
        "ca_realise_dt": round(float(courant[0] or 0), 0),
        "comparaison": {
            "annee": prec,
            "marge_meme_periode_dt": round(marge_prec_partielle, 0),
            "marge_annee_complete_dt": round(marge_prec_totale, 0),
            "part_de_l_annee_pct": round(part * 100, 1) if part else None,
            "evolution_pct": evolution,
        },
        "projection_fin_d_annee_dt": projection,
        "projection_methode": (
            f"marge réalisée sur {n_mois} mois, divisée par la part que ces "
            f"mêmes {n_mois} mois représentaient dans la marge de {prec} "
            f"({round(part * 100, 1) if part else '—'} %). Saisonnalité "
            "CONSTATÉE sur un seul exercice, pas un modèle appris."
            if projection else
            "projection impossible : l'exercice précédent ne couvre pas la "
            "même fenêtre."),
        "projection_limite": (
            "Une projection n'est pas une mesure. Elle suppose que la fin "
            "d'année ressemblera à celle de l'an dernier : ni gros marché "
            "gagné, ni perdu, ni rupture d'approvisionnement."),
    }


def ce_que_le_chiffre_ne_dit_pas(con) -> Dict[str, Any]:
    """Les limites du chiffre, en données et non en avertissement vague.

    Publier le total sans ses exclusions, c'est le présenter comme exhaustif
    alors qu'il ne l'est pas."""
    try:
        q = con.execute("""
            SELECT lignes_exclues, lignes_facturees, lignes_retour, ca_retour,
                   ca_exclu, lignes_offertes, cout_offert
            FROM margin_quality
        """).fetchone()
    except Exception:
        return {}
    if not q:
        return {}

    exclues, facturees = int(q[0] or 0), int(q[1] or 0)
    return {
        "nature": "marge BRUTE",
        "ce_qui_est_deduit": (
            "le coût de revient des produits vendus, tel qu'il figure sur chaque "
            "ligne de facture"),
        "ce_qui_n_est_pas_deduit": (
            "ni salaires, ni loyers, ni transport, ni frais financiers. La marge "
            "brute n'est pas un résultat : c'est ce qui reste pour les payer."),
        "lignes_ecartees": exclues,
        "lignes_ecartees_pct": (round(exclues / facturees * 100, 2)
                                if facturees else None),
        "lignes_ecartees_motif": (
            "coût de revient supérieur à 5 fois le prix de vente — erreur de "
            "saisie, par exemple un panel vendu 28 300 DT dont le coût est "
            "déclaré à 665 450 DT"),
        "ca_ecarte_dt": round(float(q[4] or 0), 0),
        "lignes_offertes": int(q[5] or 0),
        "cout_offert_dt": round(float(q[6] or 0), 0),
        "lignes_offertes_motif": (
            "lignes facturées à zéro mais portant un coût : échantillons, "
            "remplacements sous garantie, gestes commerciaux. Leur coût est "
            "supporté sans recette, et il ne figure dans aucun taux de marge."),
        "lignes_retour": int(q[2] or 0),
        "ca_retour_dt": round(float(q[3] or 0), 0),
        "lignes_retour_motif": (
            "retours clients, déduits du chiffre d'affaires comme de la marge"),
    }


def analyser(filtres: Optional[Dict[str, Any]] = None,
             limite: int = N_PRODUITS) -> Dict[str, Any]:
    """Décomposition complète de la marge brute sur le périmètre filtré.

    La période de référence est celle du tableau de bord (12 derniers mois par
    défaut) : sans ça, la décomposition porterait sur tout l'historique alors
    que le total affiché juste au-dessus porte sur douze mois."""
    from ml_engine.analytics.kpi_engine import _connect, periode_reference

    con = _connect()
    try:
        periode = periode_reference(con, filtres or {})
        portee_filtres = dict(filtres or {})
        if periode.get("debut"):
            portee_filtres["date_start"] = periode["debut"]
            portee_filtres["date_end"] = periode["fin"]
        filtres = portee_filtres

        cat = par_categorie(con, filtres)
        if not cat["categories"]:
            return {"servi": False, "periode_reference": periode,
                    "motif": ("aucune ligne de vente avec un coût de revient "
                              "exploitable sur ce périmètre")}
        return {
            "servi": True,
            "nature": "comptage",
            "periode_reference": periode,
            "completude": completude(con, periode, portee_filtres),
            "par_categorie": cat,
            "produits": produits(con, filtres, limite),
            "tendance": tendance(con, filtres),
            "limites": ce_que_le_chiffre_ne_dit_pas(con),
            "waterfall": [
                {"etape": "Chiffre d'affaires des lignes",
                 "valeur_dt": cat["total_ca_dt"], "genre": "depart"},
                {"etape": "Coût de revient",
                 "valeur_dt": -round(cat["total_ca_dt"] - cat["total_marge_dt"], 0),
                 "genre": "negatif"},
                {"etape": "Marge brute",
                 "valeur_dt": cat["total_marge_dt"], "genre": "total"},
            ],
        }
    finally:
        con.close()
