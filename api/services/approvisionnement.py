"""Le processus d'approvisionnement, et ce que l'ERP en enregistre vraiment.

Comptage pur : aucun modèle n'intervient, donc la règle de portée des filtres
ne s'applique pas. Les filtres de période s'appliquent en revanche normalement.

La RÉDACTION vit ici et non dans `ml_engine` : un module de calcul ne porte pas
de tables de phrases (garde-fou de `tests/test_explication.py`). Le moteur
renvoie des codes et des chiffres, cette couche les met en mots.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.services.serialisation import json_safe
from ml_engine.analytics import approvisionnement as ap

#: Les cinq étapes d'un processus d'achat, et l'état de ce que l'ERP en garde.
#:
#: Deux ne sont PAS couvertes. Les afficher quand même, avec leur raison, vaut
#: mieux que de les masquer : un directeur qui découvre en réunion qu'une étape
#: ne repose sur rien cesse de croire aux quatre autres.
ETAPES: Dict[str, Dict[str, str]] = {
    "sourcing": {
        "titre": "Recherche et repérage des fournisseurs",
        "ce_qu_on_voit": (
            "Qui fournit quoi, pour quel montant, depuis quel pays, et à quel "
            "point l'entreprise en dépend. Les références sans solution de "
            "repli sont listées."),
        "source": "vos factures d'achat et votre fichier fournisseurs",
    },
    "echantillons": {
        "titre": "Demande d'échantillons",
        "ce_qu_on_voit": "",
        "pourquoi_absent": (
            "Aucune demande d'échantillon n'est enregistrée nulle part : ni "
            "pièce, ni statut, ni date. Cette étape existe dans la réalité du métier, "
            "mais rien de ce qui est saisi ne permet de la mesurer, et la "
            "plateforme "
            "ne la crée pas non plus : elle concerne des fournisseurs qu'on "
            "n'a pas encore, là où la boucle de réassort porte sur des "
            "références déjà référencées."),
        "source": "aucune",
    },
    "commande_facturation": {
        "titre": "Commande et facturation",
        "ce_qu_on_voit": (
            "Les factures d'achat : montants, fréquence, et délai de paiement "
            "obtenu de chaque fournisseur."),
        "ce_qui_manque": (
            "Les BONS DE COMMANDE. Seules les factures sont saisies : "
            "impossible de mesurer le temps entre une commande et sa "
            "facturation, ni de repérer une commande restée sans suite."),
        "comble_par_la_plateforme": (
            "Une recommandation validée devient une commande enregistrée ici, "
            "avec sa date. Le bon de commande qui n'était consigné nulle part "
            "existe "
            "donc à partir du premier réassort décidé dans l'application."),
        "source": "vos factures d'achat",
    },
    "logistique": {
        "titre": "Planification de la logistique",
        "ce_qu_on_voit": (
            "Le rythme de réapprovisionnement de chaque référence, et celles "
            "dont le dernier achat remonte à plus longtemps que ce rythme."),
        "ce_qui_manque": (
            "Les DATES DE RÉCEPTION. Sans elles, aucun délai de livraison "
            "réel n'est calculable : ce qui est mesuré est l'écart entre deux "
            "factures d'achat, c'est-à-dire une fréquence, pas un délai."),
        "comble_par_la_plateforme": (
            "La saisie d'une réception pose la date qui manquait. L'écart "
            "entre la commande et la réception EST le délai de livraison "
            "réel : il devient mesurable dès la première réception saisie, et "
            "se précise à chaque tour de boucle."),
        "source": "lignes de factures d'achat",
    },
    "stock": {
        "titre": "Gestion du stock",
        "ce_qu_on_voit": (
            "La position reconstruite à partir des entrées et des sorties, la "
            "consommation mensuelle, et les ruptures à venir."),
        "ce_qui_manque": (
            "L'INVENTAIRE D'OUVERTURE. Aucun n'a été consigné : la position "
            "est reconstruite depuis 2019, ce qui rend négative celle des "
            "produits déjà en magasin avant cette date."),
        "source": "croisement des lignes d'achat et de vente",
    },
}

#: Ce que dit un indice de concentration, en clair.
def _lecture_hhi(hhi: float) -> str:
    if hhi >= 5000:
        return ("Concentration extrême : le marché d'achat se comporte comme "
                "un quasi-monopole.")
    if hhi >= 2500:
        return "Concentration forte : quelques fournisseurs portent l'essentiel."
    if hhi >= 1500:
        return "Concentration modérée."
    return "Achats répartis entre de nombreux fournisseurs."


#: Ce que la boucle doit avoir produit pour qu'une étape cesse d'être partielle.
#:
#: La couverture n'est pas un attribut figé du code : elle dépend de ce que
#: l'entreprise a réellement saisi. Tant qu'aucune commande n'a été passée,
#: l'étape « commande » reste partielle, et le dire est honnête. Dès qu'une
#: commande existe, elle devient mesurée — par la plateforme, pas par l'ERP.
COMBLEE_PAR = {
    "commande_facturation": "n_commandes",
    "logistique": "n_receptions",
}


def processus(filtres: Optional[Dict[str, Any]] = None,
              boucle: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Les cinq étapes, avec les chiffres pour trois et la raison pour deux.

    `boucle` porte ce que la plateforme a elle-même enregistré (commandes
    passées, réceptions saisies). Il fait évoluer la couverture de deux étapes :
    ce que l'ERP ne donne pas, l'application finit par le produire."""
    try:
        data = ap.analyser(filtres)
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}

    if not data.get("servi"):
        return data

    b = boucle or {}
    for e in data.get("etapes") or []:
        code = e.get("code")
        meta = ETAPES.get(code) or {}
        e.update({k: v for k, v in meta.items() if v})

        cle = COMBLEE_PAR.get(code)
        if cle and int(b.get(cle) or 0) > 0:
            e["couverte"] = True
            e["comblee_par_la_plateforme"] = True
            e["chiffres"] = {**(e.get("chiffres") or {}),
                             cle: int(b[cle])}
            e.pop("ce_qui_manque", None)
        elif cle:
            e["comblee_par_la_plateforme"] = False

    data["boucle"] = b

    f = data.get("fournisseurs") or {}
    if f.get("hhi") is not None:
        f["hhi_lecture"] = _lecture_hhi(float(f["hhi"]))
        f["hhi_methode"] = (
            "somme des carrés des parts de marché, en points. 10 000 = un "
            "fournisseur unique.")

    dep = f.get("dependance") or {}
    if dep.get("critique"):
        dep["consequence"] = (
            f"{dep['fournisseur']} porte {dep['part_pct']} % des achats. Une "
            "hausse de tarif, un changement de conditions ou une rupture chez "
            "lui se répercute presque intégralement, sans amortissement "
            "possible par un autre fournisseur.")
    return json_safe(data)
