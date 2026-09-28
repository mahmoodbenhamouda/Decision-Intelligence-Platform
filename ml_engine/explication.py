"""
ml_engine/explication.py
========================
Pourquoi ce client, ce devis, ce produit — et pas un autre.

Un score sans justification ne se discute pas : un commercial à qui l'on dit
« ce client a 78 % de risque de partir » ne peut ni vérifier, ni agir. Ce module
transforme la décision d'un modèle en **trois phrases chiffrées en français**,
lisibles par quelqu'un qui n'a jamais entendu parler de régression logistique.

## Trois familles de modèles, trois techniques — jamais approximées sans le dire

1. **Modèles linéaires** (décrochage client, conversion des devis).
   Contribution = coefficient × valeur normalisée. Sur une régression
   logistique, cette décomposition est **EXACTE** : la somme des contributions
   et de l'ordonnée à l'origine reconstitue le logit, au flottant près. C'est
   vérifié par `tests/test_explication.py`, pas supposé.

2. **Modèles d'ensemble** (érosion de marge — gradient boosting).
   Décomposition **SHAP** (valeurs de Shapley, TreeExplainer) : la seule
   attribution qui garantisse que la somme des contributions égale l'écart à la
   prédiction moyenne. Approchée par nature, donc annoncée comme telle.

3. **Règles servies** (conditions de crédit, fin de commercialisation,
   réapprovisionnement). L'explication est la règle elle-même : la valeur
   observée, le seuil, et l'écart entre les deux. Aucune attribution à estimer.

## Ce que ce module refuse de faire

- **Inventer une phrase pour une variable inconnue.** Une variable sans libellé
  métier ressort sous un nom neutre plutôt qu'avec une explication plausible
  mais fausse.
- **Présenter une approximation comme une décomposition exacte.** Ce qui est
  exact et ce qui repose sur une hypothèse est écrit dans `docs/XAI.md`,
  documentation du projet — pas dans l'écran d'un utilisateur, qui n'a pas à
  lire la mécanique du modèle appliquée à son propre compte.
- **Afficher des poids qui ne totalisent pas 100 %.** Les poids publiés sont des
  PARTS de l'influence retenue, normalisées sur les raisons affichées.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence

__all__ = ["contributions_lineaires", "contributions_shap", "raisons_seuils",
           "phrase_variable"]


# ── Vocabulaire métier ──────────────────────────────────────────────────────
#
# Une fonction par variable : elle reçoit la valeur BRUTE et le sens de la
# contribution, et rend une phrase qu'un dirigeant lit sans traduction. Sans
# cette table, l'écran afficherait « tendance_freq = 2.0 », ce qui n'explique
# rien à personne.

def _dt(v: float) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.2f} M DT".replace(".", ",")
    if a >= 1e3:
        return f"{v / 1e3:.0f} K DT"
    return f"{v:.0f} DT"


def _jours(v: float) -> str:
    j = int(round(v))
    if j >= 730:
        return f"{j // 365} ans"
    if j >= 60:
        return f"{j // 30} mois"
    return f"{j} jour(s)"


def _pct(v: float) -> str:
    return f"{v:.1f} %".replace(".", ",")


#: variable → (phrase quand la contribution AGGRAVE, phrase quand elle PROTÈGE)
#: Les deux formulations existent parce qu'« il commande moins souvent qu'avant »
#: et « il commande plus souvent qu'avant » ne sont pas la même information.
PHRASES: Dict[str, Callable[[float, bool], str]] = {
    # ── Décrochage client ──
    "ca_6m": lambda v, m: (f"chiffre d'affaires de {_dt(v)} sur 6 mois, en retrait"
                           if m else f"chiffre d'affaires soutenu sur 6 mois ({_dt(v)})"),
    "ca_12m": lambda v, m: f"chiffre d'affaires de {_dt(v)} sur 12 mois",
    "freq_12m": lambda v, m: (f"seulement {v:.0f} commande(s) sur 12 mois"
                              if m else f"{v:.0f} commandes sur 12 mois, rythme régulier"),
    "recence_j": lambda v, m: (f"dernière commande il y a {_jours(v)}"
                               if m else f"a commandé récemment (il y a {_jours(v)})"),
    "intervalle_moyen_j": lambda v, m: f"commande en moyenne tous les {_jours(v)}",
    "tendance_ca": lambda v, m: ("son chiffre d'affaires baisse par rapport à l'an dernier"
                                 if m else "son chiffre d'affaires progresse"),
    "tendance_freq": lambda v, m: ("il commande moins souvent qu'avant"
                                   if m else "il commande plus souvent qu'avant"),
    "anciennete_j": lambda v, m: f"client depuis {_jours(v)}",
    "ratio_recence_intervalle": lambda v, m: (
        f"son silence dure {v:.1f} fois son intervalle habituel" if m
        else "son dernier achat est dans son rythme habituel"),

    # ── Conversion des devis ──
    "log_montant_ht": lambda v, m: f"devis de {_dt(math.expm1(v))} HT",
    "montant_ht": lambda v, m: f"devis de {_dt(v)} HT",
    "est_client": lambda v, m: ("prospect, jamais facturé" if v < 0.5
                                else "déjà client de la maison"),
    "anciennete_j_devis": lambda v, m: f"relation vieille de {_jours(v)}",
    "n_factures_12m": lambda v, m: f"{v:.0f} facture(s) sur les 12 derniers mois",
    "log_ca_12m": lambda v, m: f"chiffre d'affaires annuel de {_dt(math.expm1(v))}",
    "recence_facture_j": lambda v, m: f"dernière facture il y a {_jours(v)}",
    "panier_moyen": lambda v, m: f"panier moyen de {_dt(v)}",
    "marge_moyenne_pct": lambda v, m: f"marge habituelle de {_pct(v)}",
    "delai_median_accorde_j": lambda v, m: f"délai de paiement accordé : {_jours(v)}",
    "n_devis_12m": lambda v, m: f"{v:.0f} devis émis sur 12 mois",
    "taux_conversion_passe": lambda v, m: (
        f"il signe habituellement {_pct(v * 100 if v <= 1 else v)} de ses devis"),
    "log_montant_moyen_devis_passes": lambda v, m: (
        f"ses devis passés tournent autour de {_dt(math.expm1(v))}"),
    "ratio_montant_vs_habituel": lambda v, m: (
        f"devis {v:.1f} fois plus gros que ses devis habituels" if v >= 1
        else f"devis plus petit que d'habitude ({v:.1f} fois)"),
    "ratio_montant_panier": lambda v, m: f"devis équivalent à {v:.1f} paniers moyens",
    "ratio_montant_ca_12m": lambda v, m: (
        f"devis représentant {_pct(v * 100)} de son chiffre d'affaires annuel"),
    "n_devis_meme_mois": lambda v, m: f"{v:.0f} devis émis le même mois",
    "mois": lambda v, m: f"devis émis au mois {v:.0f}",
    "trimestre": lambda v, m: f"devis émis au trimestre {v:.0f}",
    "jour_semaine": lambda v, m: "jour d'émission dans la semaine",

    # ── Érosion de marge ──
    "marge_3m_pct": lambda v, m: (f"marge tombée à {_pct(v)} sur 3 mois" if m
                                  else f"marge tenue à {_pct(v)} sur 3 mois"),
    "marge_6m_pct": lambda v, m: f"marge de {_pct(v)} sur 6 mois",
    "marge_12m_pct": lambda v, m: f"marge de {_pct(v)} sur 12 mois",
    "tendance_marge": lambda v, m: ("sa marge se dégrade d'un trimestre à l'autre" if m
                                    else "sa marge se redresse"),
    "volatilite_marge": lambda v, m: (f"marge instable d'un mois à l'autre ({_pct(v)} d'écart)"
                                      if m else "marge stable d'un mois à l'autre"),
    "part_equipement_3m": lambda v, m: (
        f"{_pct(v)} d'équipement dans ses achats récents — moins margé que le réactif"
        if m else f"seulement {_pct(v)} d'équipement dans ses achats récents"),
    "anciennete_mois": lambda v, m: f"client depuis {v:.0f} mois",
    "mois_calendaire": lambda v, m: f"effet de saison (mois {v:.0f})",

    # ── Stock ──
    "mois_sans_vente": lambda v, m: f"aucune vente depuis {v:.0f} mois",
    "mois_couverture": lambda v, m: (f"{v:.0f} mois de stock devant soi" if m
                                     else f"couverture courte : {v:.0f} mois"),
    "n_clients_12m": lambda v, m: (f"plus que {v:.0f} client(s) acheteur(s)" if m
                                   else f"{v:.0f} clients acheteurs"),
    "stock_actuel": lambda v, m: f"{v:.0f} unité(s) en stock",
    "conso_mensuelle": lambda v, m: f"{v:.1f} unité(s) consommées par mois",
    "delai_reappro_j": lambda v, m: f"délai de réapprovisionnement de {_jours(v)}",

    # ── Crédit ──
    "avg_delay": lambda v, m: (f"règle en moyenne à {_jours(v)}" if m
                               else f"règle vite, en moyenne {_jours(v)}"),
    "exposure": lambda v, m: f"encours de {_dt(v)}",
    "n": lambda v, m: f"{v:.0f} facture(s) dans l'historique",
}

#: Noms lisibles de repli, quand aucune phrase n'est définie. Mieux vaut un nom
#: neutre qu'une explication inventée.
NOMS_NEUTRES: Dict[str, str] = {
    "log_montant_ht": "montant du devis",
    "log_ca_12m": "chiffre d'affaires annuel",
}


def phrase_variable(variable: str, valeur: float, aggrave: bool = True) -> str:
    """Phrase métier pour une variable, ou un nom neutre si elle est inconnue."""
    f = PHRASES.get(variable)
    if f is not None:
        try:
            return f(float(valeur), bool(aggrave))
        except Exception:
            pass
    nom = NOMS_NEUTRES.get(variable) or variable.replace("_", " ")
    try:
        return f"{nom} : {float(valeur):.2f}".rstrip("0").rstrip(",.")
    except Exception:
        return nom


# ── Fabrique commune des raisons ────────────────────────────────────────────
def _assembler(brutes: List[Dict[str, Any]], valeurs: Dict[str, float],
               n: int, garder_protecteur: bool,
               sens: Sequence[str] = ("aggrave", "protege")) -> List[Dict[str, Any]]:
    """Trie, normalise en parts de 100 %, et rédige les phrases.

    `brutes` : [{"variable", "contribution"}] — contribution signée, positive
    quand elle pousse vers l'issue signalée.

    `sens` nomme les deux directions. Elles ne veulent pas dire la même chose
    selon le modèle : ce qui « aggrave » un risque de départ « favorise » la
    signature d'un devis. Un seul vocabulaire pour les deux tromperait le
    lecteur.
    """
    aggravantes = sorted((b for b in brutes if b["contribution"] > 0),
                         key=lambda b: -b["contribution"])[:n]
    total = sum(b["contribution"] for b in aggravantes) or 1.0

    raisons = [{
        "variable": b["variable"],
        "valeur": round(float(valeurs.get(b["variable"], 0.0)), 4),
        "poids": round(float(b["contribution"]) / total, 3),
        "sens": sens[0],
        "explication": phrase_variable(b["variable"],
                                       valeurs.get(b["variable"], 0.0), True),
    } for b in aggravantes]

    if garder_protecteur:
        # UNE seule raison inverse : elle évite de présenter un client comme
        # uniformément mauvais, sans noyer le message principal.
        protectrices = sorted((b for b in brutes if b["contribution"] < 0),
                              key=lambda b: b["contribution"])
        if protectrices:
            b = protectrices[0]
            raisons.append({
                "variable": b["variable"],
                "valeur": round(float(valeurs.get(b["variable"], 0.0)), 4),
                # Pas de poids publié : les parts affichées totalisent 100 % des
                # facteurs qui POUSSENT dans le sens du signalement. Donner un
                # pourcentage au facteur inverse laisserait croire qu'il appartient
                # à la même somme, et un « 99 % » à côté de trois parts qui font
                # déjà 100 % ne veut plus rien dire.
                "poids": None,
                "sens": sens[1],
                "explication": phrase_variable(b["variable"],
                                               valeurs.get(b["variable"], 0.0), False),
            })
    return raisons


def contributions_lineaires(coefficients: Sequence[float],
                            moyennes: Sequence[float],
                            ecarts: Sequence[float],
                            valeurs: Sequence[float],
                            variables: Sequence[str],
                            n: int = 3,
                            garder_protecteur: bool = True,
                            sens: Sequence[str] = ("aggrave", "protege"),
                            ) -> List[Dict[str, Any]]:
    """Décomposition EXACTE d'un score linéaire normalisé.

    contribution_i = coefficient_i × (valeur_i − moyenne_i) / écart_i

    La somme de ces contributions, augmentée de l'ordonnée à l'origine, redonne
    le logit du modèle — propriété vérifiée par les tests.
    """
    brutes, vals = [], {}
    for i, var in enumerate(variables):
        try:
            ecart = float(ecarts[i]) or 1.0
            centre = (float(valeurs[i]) - float(moyennes[i])) / ecart
            brutes.append({"variable": var, "contribution": float(coefficients[i]) * centre})
            vals[var] = float(valeurs[i])
        except Exception:
            continue
    return _assembler(brutes, vals, n, garder_protecteur, sens)


def contributions_shap(valeurs_shap: Sequence[float],
                       valeurs: Sequence[float],
                       variables: Sequence[str],
                       n: int = 3,
                       garder_protecteur: bool = True,
                       sens: Sequence[str] = ("aggrave", "protege"),
                       ) -> List[Dict[str, Any]]:
    """Mise en forme de valeurs SHAP déjà calculées (une ligne)."""
    brutes = [{"variable": v, "contribution": float(x)}
              for v, x in zip(variables, valeurs_shap)]
    vals = {v: float(x) for v, x in zip(variables, valeurs)}
    return _assembler(brutes, vals, n, garder_protecteur, sens)


def raisons_seuils(valeurs: Dict[str, float],
                   regles: Sequence[Dict[str, Any]],
                   n: int = 3) -> List[Dict[str, Any]]:
    """Explication d'une RÈGLE : quels seuils sont franchis, et de combien.

    Chaque règle : {"variable", "seuil", "sens": "sup"|"inf", "poids"}.
    Le poids publié est la part de dépassement, pas une importance apprise —
    une règle n'apprend rien, et le prétendre serait faux.
    """
    franchies = []
    for r in regles:
        var, seuil = r["variable"], float(r["seuil"])
        v = valeurs.get(var)
        if v is None:
            continue
        v = float(v)
        depasse = (v >= seuil) if r.get("sens", "sup") == "sup" else (v <= seuil)
        if not depasse:
            continue
        ecart = abs(v - seuil) / (abs(seuil) or 1.0)
        franchies.append({
            "variable": var, "valeur": round(v, 4),
            "seuil": round(seuil, 4),
            "ecart_relatif": round(ecart, 3),
            # Le dépassement module le poids, il ne le renverse pas : un stock
            # vingt fois supérieur à son seuil ne doit pas passer devant « six
            # mois sans la moindre vente », qui est le vrai signal.
            "poids_brut": float(r.get("poids", 1.0)) * (1.0 + min(ecart, 1.0)),
            "explication": r.get("phrase") or phrase_variable(var, v, True),
        })
    franchies.sort(key=lambda x: -x["poids_brut"])
    franchies = franchies[:n]
    total = sum(f["poids_brut"] for f in franchies) or 1.0
    for f in franchies:
        f["poids"] = round(f.pop("poids_brut") / total, 3)
        f["sens"] = "aggrave"
    return franchies


def extraire_pipeline_lineaire(modele: Any) -> Optional[Dict[str, Any]]:
    """Récupère (coefficients, moyennes, écarts) d'un pipeline normalisé.

    Rend `None` plutôt qu'une approximation si le modèle n'est pas de cette
    forme : mieux vaut aucune explication qu'une explication d'un autre modèle.
    """
    try:
        etapes = dict(getattr(modele, "named_steps", {}) or {})
        lin = etapes.get("logisticregression") or etapes.get("logistic") \
            or (modele if hasattr(modele, "coef_") else None)
        sc = etapes.get("standardscaler")
        if lin is None or not hasattr(lin, "coef_"):
            return None
        coefs = list(lin.coef_[0])
        if sc is not None and hasattr(sc, "mean_"):
            return {"coefficients": coefs, "moyennes": list(sc.mean_),
                    "ecarts": list(sc.scale_)}
        n = len(coefs)
        return {"coefficients": coefs, "moyennes": [0.0] * n, "ecarts": [1.0] * n}
    except Exception:
        return None
