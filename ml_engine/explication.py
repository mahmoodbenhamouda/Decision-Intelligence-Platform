"""Explicabilité des modèles : attribution locale, contrefactuel, fidélité.

PRINCIPE. Une explication se compose de trois éléments, produits séparément :

  1. le LIBELLÉ de la variable — traduction, jamais une affirmation ;
  2. le SENS — déduit du signe de la contribution, donc du coefficient APPRIS ;
  3. la POSITION de la valeur dans la distribution — centile, ou écart-type.

Les trois étaient auparavant fondus dans une phrase écrite à la main, où le sens
était supposé. Une contribution positive peut venir d'un coefficient positif avec
une valeur haute OU d'un coefficient négatif avec une valeur basse : la phrase
figée se trompait une fois sur deux. `tendance_freq = 2.0` (deux fois plus de
commandes qu'avant) s'affichait « il commande moins souvent qu'avant ».

Aucun libellé ne contient donc de verbe de direction, et un test le vérifie.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = ["contributions_lineaires", "contributions_shap", "raisons_seuils",
           "libelle_variable", "decrire_variable", "contrefactuel",
           "fidelite_suppression", "extraire_pipeline_lineaire",
           "VERBES_DE_DIRECTION"]


# ── Mise en forme des valeurs ────────────────────────────────────────────────

def _dt(v: float) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.2f} M DT".replace(".", ",")
    if a >= 1e3:
        return f"{v / 1e3:.0f} K DT"
    return f"{v:.0f} DT"


def _log_dt(v: float) -> str:
    return _dt(math.expm1(v))


def _jours(v: float) -> str:
    j = int(round(v))
    if j >= 730:
        return f"{j // 365} ans"
    if j >= 60:
        return f"{j // 30} mois"
    return f"{j} j"


def _mois(v: float) -> str:
    return f"{v:.0f} mois"


def _pct(v: float) -> str:
    return f"{v:.1f} %".replace(".", ",")


def _part(v: float) -> str:
    return _pct(v * 100.0) if abs(v) <= 1.0 else _pct(v)


def _ratio(v: float) -> str:
    return f"× {v:.2f}".replace(".", ",")


def _entier(v: float) -> str:
    return f"{v:.0f}"


def _decimal(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _mois_calendaire(v: float) -> str:
    noms = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
            "août", "septembre", "octobre", "novembre", "décembre"]
    i = int(round(v))
    return noms[i - 1] if 1 <= i <= 12 else f"mois {i}"


def _booleen(v: float) -> str:
    return "oui" if v >= 0.5 else "non"


# ── Libellés : des noms, pas des jugements ───────────────────────────────────
#
# Chaque entrée est (libellé, formateur). Le libellé nomme la grandeur mesurée et
# rien d'autre : ni « faible », ni « en retrait », ni « moins souvent ». Ces
# qualificatifs dépendent du coefficient appris et de la distribution, tous deux
# calculés plus bas.

LIBELLES: Dict[str, Tuple[str, Callable[[float], str]]] = {
    # Activité client
    "recence_j": ("jours depuis la dernière commande", _jours),
    "recence_facture_j": ("jours depuis la dernière facture", _jours),
    "anciennete_j": ("ancienneté de la relation", _jours),
    "anciennete_mois": ("ancienneté de la relation", _mois),
    "freq_3m": ("commandes sur 3 mois", _entier),
    "freq_6m": ("commandes sur 6 mois", _entier),
    "freq_12m": ("commandes sur 12 mois", _entier),
    "n_factures_12m": ("factures sur 12 mois", _entier),
    "intervalle_moyen_j": ("intervalle moyen entre commandes", _jours),
    "intervalle_ecart_type_j": ("irrégularité de l'intervalle", _jours),
    "ratio_recence_intervalle": ("silence rapporté au rythme habituel", _ratio),
    "panier_moyen": ("panier moyen", _dt),
    "est_client": ("déjà facturé", _booleen),

    # Chiffre d'affaires
    "ca_3m": ("chiffre d'affaires sur 3 mois", _dt),
    "ca_6m": ("chiffre d'affaires sur 6 mois", _dt),
    "ca_12m": ("chiffre d'affaires sur 12 mois", _dt),
    "log_ca_12m": ("chiffre d'affaires sur 12 mois", _log_dt),
    "tendance_ca": ("chiffre d'affaires récent sur chiffre d'affaires antérieur",
                    _ratio),
    "tendance_freq": ("commandes récentes sur commandes antérieures", _ratio),

    # Devis
    "log_montant_ht": ("montant du devis HT", _log_dt),
    "montant_ht": ("montant du devis HT", _dt),
    "log_montant_moyen_devis_passes": ("montant moyen de ses devis passés",
                                       _log_dt),
    "n_devis_12m": ("devis émis sur 12 mois", _entier),
    "n_devis_meme_mois": ("devis émis le même mois", _entier),
    "taux_conversion_passe": ("taux de signature passé", _part),
    "ratio_montant_vs_habituel": ("montant rapporté à ses devis habituels",
                                  _ratio),
    "ratio_montant_panier": ("montant rapporté à son panier moyen", _ratio),
    "ratio_montant_ca_12m": ("montant rapporté à son chiffre d'affaires annuel",
                             _part),
    "delai_median_accorde_j": ("délai de paiement accordé", _jours),
    "marge_moyenne_pct": ("marge habituelle", _pct),

    # Marge
    "marge_3m_pct": ("marge sur 3 mois", _pct),
    "marge_6m_pct": ("marge sur 6 mois", _pct),
    "marge_12m_pct": ("marge sur 12 mois", _pct),
    "tendance_marge": ("marge récente sur marge antérieure", _ratio),
    "volatilite_marge": ("variabilité de la marge", _pct),
    "part_equipement_3m": ("part d'équipement dans les achats récents", _pct),
    "part_reactif_3m": ("part de réactif dans les achats récents", _pct),
    "part_service_3m": ("part de service dans les achats récents", _pct),
    "variation_part_equipement": ("variation de la part d'équipement", _pct),
    "n_familles_3m": ("familles de produits achetées sur 3 mois", _entier),

    # Stock et fin de vie
    "conso_1m": ("consommation sur 1 mois", _decimal),
    "conso_3m": ("consommation sur 3 mois", _decimal),
    "conso_6m": ("consommation sur 6 mois", _decimal),
    "conso_12m": ("consommation sur 12 mois", _decimal),
    "conso_mensuelle": ("consommation mensuelle", _decimal),
    "tendance_conso": ("consommation récente sur consommation antérieure",
                       _ratio),
    "volatilite_conso": ("variabilité de la consommation", _decimal),
    "mois_actifs_12m": ("mois avec au moins une vente sur 12", _entier),
    "mois_depuis_derniere_vente": ("mois depuis la dernière vente", _mois),
    "mois_depuis_dernier_achat": ("mois depuis le dernier achat fournisseur",
                                  _mois),
    "mois_sans_vente": ("mois sans aucune vente", _mois),
    "mois_couverture": ("mois de stock devant soi", _mois),
    "stock_actuel": ("quantité en stock", _decimal),
    "delai_reappro_j": ("délai de réapprovisionnement", _jours),
    "log_valeur_stock": ("valeur du stock", _log_dt),
    "n_clients_12m": ("clients acheteurs sur 12 mois", _entier),
    "n_clients_3m": ("clients acheteurs sur 3 mois", _entier),
    "n_nouveaux_clients_6m": ("nouveaux clients sur 6 mois", _entier),
    "erosion_clients": ("clients récents sur clients antérieurs", _ratio),
    "concentration_hhi": ("concentration de la clientèle (HHI)", _decimal),
    "part_premier_client": ("part du premier client", _part),
    "prix_moyen_3m": ("prix de vente moyen sur 3 mois", _dt),
    "derive_prix": ("prix récent sur prix antérieur", _ratio),
    "volatilite_prix": ("variabilité du prix", _decimal),
    "marge_relative": ("marge relative du produit", _pct),

    # Encours client
    "avg_delay": ("délai de règlement moyen", _jours),
    "exposure": ("encours", _dt),
    "n": ("factures dans l'historique", _entier),

    # Saison
    "mois": ("mois d'émission", _mois_calendaire),
    "mois_calendaire": ("mois", _mois_calendaire),
    "trimestre": ("trimestre d'émission", _entier),
    "jour_semaine": ("jour d'émission dans la semaine", _entier),
}

# Un libellé qui contiendrait l'un de ces mots affirmerait une direction que le
# coefficient appris peut contredire. `tests/test_explication.py` échoue alors.
VERBES_DE_DIRECTION = (
    "faible", "fort", "élevé", "eleve", "bas", "haut", "retrait", "recul",
    "baisse", "hausse", "progresse", "dégrade", "degrade", "redresse",
    "instable", "stable", "irrégulier", "irregulier", "régulier", "regulier",
    "soutenu", "quasi nul", "seulement", "plus que", "moins souvent",
    "plus souvent", "inquiét", "inquiet", "rassur", "court", "long",
    "naturellement", "habituel " , "vite", "mauvais", "bon ",
)


def libelle_variable(variable: str) -> str:
    """Nom métier de la variable, ou son nom technique rendu lisible."""
    entree = LIBELLES.get(variable)
    if entree is not None:
        return entree[0]
    return variable.replace("_", " ")


def valeur_affichee(variable: str, valeur: float) -> str:
    """Valeur mise en forme avec son unité."""
    entree = LIBELLES.get(variable)
    formateur = entree[1] if entree is not None else _decimal
    try:
        return formateur(float(valeur))
    except Exception:
        return str(valeur)


# ── Position de la valeur dans la distribution ───────────────────────────────

def _centile(valeur: float, reference: Sequence[float]) -> Optional[int]:
    """Centile de `valeur` dans `reference`, ou None si la référence est vide."""
    try:
        ref = np.asarray(reference, dtype=float)
        ref = ref[np.isfinite(ref)]
        if ref.size < 20:
            return None
        return int(round(100.0 * float((ref <= float(valeur)).mean())))
    except Exception:
        return None


def _position(centile: Optional[int], ecart_type: Optional[float]) -> Optional[str]:
    """Position de la valeur, énoncée comme un fait calculé.

    Le centile est préféré : il se lit sans connaître la distribution. À défaut,
    seul le côté de la moyenne est énoncé ; la valeur en écarts-types reste dans
    le champ `ecart_type`, pour les rapports, et n'entre pas dans une phrase
    destinée à un commercial. Aucun adjectif n'est ajouté — « élevé » suppose un
    seuil que personne n'a déclaré.
    """
    if centile is not None:
        return f"{centile}ᵉ centile du parc"
    if ecart_type is None or not math.isfinite(ecart_type) or abs(ecart_type) < 0.1:
        return None
    return ("au-dessus de la moyenne du parc" if ecart_type > 0
            else "en dessous de la moyenne du parc")


def decrire_variable(variable: str, valeur: float,
                     centile: Optional[int] = None,
                     ecart_type: Optional[float] = None) -> str:
    """Phrase composée : libellé, valeur, position. Aucun gabarit figé."""
    morceaux = [f"{libelle_variable(variable)} : {valeur_affichee(variable, valeur)}"]
    pos = _position(centile, ecart_type)
    if pos:
        morceaux.append(pos)
    return " — ".join(morceaux)


# ── Attribution locale ───────────────────────────────────────────────────────

def _assembler(brutes: List[Dict[str, Any]], valeurs: Dict[str, float],
               n: int, garder_protecteur: bool,
               sens: Sequence[str] = ("aggrave", "protege"),
               reference: Optional[Dict[str, Sequence[float]]] = None,
               ) -> List[Dict[str, Any]]:
    """Trie par contribution, normalise en parts de 100 %, compose les phrases."""
    reference = reference or {}

    def enrichir(b: Dict[str, Any], poids: Optional[float],
                 sens_libelle: str) -> Dict[str, Any]:
        var = b["variable"]
        val = float(valeurs.get(var, 0.0))
        centile = _centile(val, reference[var]) if var in reference else None
        ecart = b.get("ecart_type")
        return {
            "variable": var,
            "libelle": libelle_variable(var),
            "valeur": round(val, 4),
            "valeur_affichee": valeur_affichee(var, val),
            "centile": centile,
            "ecart_type": (round(float(ecart), 2)
                           if ecart is not None and math.isfinite(ecart) else None),
            "position": _position(centile, ecart),
            "contribution": round(float(b["contribution"]), 4),
            "poids": poids,
            "sens": sens_libelle,
            "explication": decrire_variable(var, val, centile, ecart),
        }

    aggravantes = sorted((b for b in brutes if b["contribution"] > 0),
                         key=lambda b: -b["contribution"])[:n]
    total = sum(b["contribution"] for b in aggravantes) or 1.0
    raisons = [enrichir(b, round(float(b["contribution"]) / total, 3), sens[0])
               for b in aggravantes]

    if garder_protecteur:
        protectrices = sorted((b for b in brutes if b["contribution"] < 0),
                              key=lambda b: b["contribution"])
        if protectrices:
            raisons.append(enrichir(protectrices[0], None, sens[1]))
    return raisons


def contributions_lineaires(coefficients: Sequence[float],
                            moyennes: Sequence[float],
                            ecarts: Sequence[float],
                            valeurs: Sequence[float],
                            variables: Sequence[str],
                            n: int = 3,
                            garder_protecteur: bool = True,
                            sens: Sequence[str] = ("aggrave", "protege"),
                            reference: Optional[Dict[str, Sequence[float]]] = None,
                            ) -> List[Dict[str, Any]]:
    """Décomposition exacte d'un score linéaire : coefficient × valeur centrée.

    Pour un modèle linéaire, cette décomposition est identique aux valeurs de
    Shapley exactes φⱼ = βⱼ(xⱼ − E[xⱼ]) : la somme des contributions reconstitue
    l'écart de logit par rapport à l'observation moyenne.
    """
    brutes, vals = [], {}
    for i, var in enumerate(variables):
        try:
            ecart = float(ecarts[i]) or 1.0
            centre = (float(valeurs[i]) - float(moyennes[i])) / ecart
            brutes.append({"variable": var,
                           "contribution": float(coefficients[i]) * centre,
                           "ecart_type": centre})
            vals[var] = float(valeurs[i])
        except Exception:
            continue
    return _assembler(brutes, vals, n, garder_protecteur, sens, reference)


def contributions_shap(valeurs_shap: Sequence[float],
                       valeurs: Sequence[float],
                       variables: Sequence[str],
                       n: int = 3,
                       garder_protecteur: bool = True,
                       sens: Sequence[str] = ("aggrave", "protege"),
                       reference: Optional[Dict[str, Sequence[float]]] = None,
                       ) -> List[Dict[str, Any]]:
    """Mise en forme de valeurs SHAP déjà calculées, pour une observation."""
    brutes = [{"variable": v, "contribution": float(x)}
              for v, x in zip(variables, valeurs_shap)]
    vals = {v: float(x) for v, x in zip(variables, valeurs)}
    return _assembler(brutes, vals, n, garder_protecteur, sens, reference)


def raisons_seuils(valeurs: Dict[str, float],
                   regles: Sequence[Dict[str, Any]],
                   n: int = 3) -> List[Dict[str, Any]]:
    """Explication d'une RÈGLE : quels seuils sont franchis, et de combien."""
    franchies = []
    for r in regles:
        var, seuil = r["variable"], float(r["seuil"])
        v = valeurs.get(var)
        if v is None:
            continue
        v = float(v)
        if "phrase" in r:
            raise ValueError(
                f"règle « {var} » : une phrase écrite à la main recopie le seuil "
                "et se désynchronise au premier changement. Le libellé suffit.")
        sens_regle = r.get("sens", "sup")
        if not ((v >= seuil) if sens_regle == "sup" else (v <= seuil)):
            continue
        ecart = abs(v - seuil) / (abs(seuil) or 1.0)
        comparaison = "au-dessus de" if sens_regle == "sup" else "en dessous de"
        franchies.append({
            "variable": var,
            "libelle": libelle_variable(var),
            "valeur": round(v, 4),
            "valeur_affichee": valeur_affichee(var, v),
            "seuil": round(seuil, 4),
            "seuil_affiche": valeur_affichee(var, seuil),
            "ecart_relatif": round(ecart, 3),
            "_poids_brut": float(r.get("poids", 1.0)) * (1.0 + min(ecart, 1.0)),
            # Une règle n'a pas de distribution derrière elle : la position est le
            # seuil franchi, qui est déclaré, donc citable tel quel.
            "position": f"{comparaison} {valeur_affichee(var, seuil)}",
            "explication": (
                f"{libelle_variable(var)} : {valeur_affichee(var, v)} — "
                f"{comparaison} {valeur_affichee(var, seuil)}"),
        })
    franchies.sort(key=lambda x: -x["_poids_brut"])
    # Une variable peut franchir plusieurs seuils déclarés (90 jours ET 60 jours).
    # Seul le plus fort est retenu : afficher les deux dirait deux fois la même
    # chose et chasserait une autre raison de la liste.
    vues, uniques = set(), []
    for f in franchies:
        if f["variable"] in vues:
            continue
        vues.add(f["variable"])
        uniques.append(f)
    franchies = uniques[:n]
    total = sum(f["_poids_brut"] for f in franchies) or 1.0
    for f in franchies:
        f["poids"] = round(f.pop("_poids_brut") / total, 3)
        f["sens"] = "aggrave"
    return franchies


# ── Contrefactuel ────────────────────────────────────────────────────────────

def contrefactuel(coefficients: Sequence[float],
                  moyennes: Sequence[float],
                  ecarts: Sequence[float],
                  valeurs: Sequence[float],
                  variables: Sequence[str],
                  logit: float,
                  logit_cible: float,
                  actionnables: Dict[str, Dict[str, Any]],
                  ) -> Optional[Dict[str, Any]]:
    """Plus petit changement d'UNE variable actionnable ramenant le score au seuil.

    Sur un modèle linéaire la solution est en forme close : déplacer xⱼ de
    (cible − logit)·σⱼ/βⱼ suffit, les autres variables étant inchangées.

    `actionnables` déclare, par variable, la direction possible dans la réalité
    (`sens`: "baisse" ou "hausse") et les bornes observées (`min`, `max`) : un
    contrefactuel qui exigerait une valeur jamais vue n'est pas une action.
    """
    besoin = float(logit_cible) - float(logit)
    if besoin >= 0:
        return None

    candidats = []
    for i, var in enumerate(variables):
        regle = actionnables.get(var)
        if regle is None:
            continue
        try:
            beta = float(coefficients[i])
            sigma = float(ecarts[i]) or 1.0
            if abs(beta) < 1e-12:
                continue
            actuelle = float(valeurs[i])
            cible = actuelle + besoin * sigma / beta
        except Exception:
            continue

        if regle.get("sens") == "baisse" and cible >= actuelle:
            continue
        if regle.get("sens") == "hausse" and cible <= actuelle:
            continue
        borne_min, borne_max = regle.get("min"), regle.get("max")
        if borne_min is not None and cible < float(borne_min):
            continue
        if borne_max is not None and cible > float(borne_max):
            continue

        candidats.append({
            "variable": var,
            "libelle": libelle_variable(var),
            "valeur_actuelle": round(actuelle, 3),
            "valeur_actuelle_affichee": valeur_affichee(var, actuelle),
            "valeur_cible": round(cible, 3),
            "valeur_cible_affichee": valeur_affichee(var, cible),
            "effort_relatif": abs(cible - actuelle) / (abs(actuelle) or 1.0),
        })

    if not candidats:
        return None
    meilleur = min(candidats, key=lambda c: c["effort_relatif"])
    meilleur["effort_relatif"] = round(meilleur["effort_relatif"], 3)
    meilleur["phrase"] = (
        f"{meilleur['libelle']} à {meilleur['valeur_cible_affichee']} "
        f"(aujourd'hui {meilleur['valeur_actuelle_affichee']}) "
        "ramène le score sous le seuil")
    return meilleur


# ── Fidélité des explications ────────────────────────────────────────────────

def fidelite_suppression(predire: Callable[[np.ndarray], np.ndarray],
                         X: np.ndarray,
                         attributions: np.ndarray,
                         remplacement: Sequence[float],
                         k_max: int = 5,
                         graine: int = 42) -> Dict[str, Any]:
    """Courbe de suppression : l'explication désigne-t-elle ce qui porte le score ?

    On remplace les k variables les plus attribuées par leur valeur de référence
    et on mesure la chute du score moyen. Une explication fidèle fait chuter plus
    vite qu'un choix aléatoire de k variables. Le rapport des aires est publié :
    il remplace l'unique corrélation de Spearman, qui ne disait rien des raisons.
    """
    X = np.asarray(X, dtype=float)
    attributions = np.asarray(attributions, dtype=float)
    remplacement = np.asarray(remplacement, dtype=float)
    n, p = X.shape
    k_max = int(min(k_max, p))
    rng = np.random.default_rng(graine)

    depart = float(np.mean(predire(X)))
    ordre = np.argsort(-attributions, axis=1)
    hasard = np.argsort(rng.random((n, p)), axis=1)

    def chute(indices: np.ndarray, k: int) -> float:
        Xk = X.copy()
        lignes = np.arange(n)[:, None]
        cibles = indices[:, :k]
        Xk[lignes, cibles] = remplacement[cibles]
        return depart - float(np.mean(predire(Xk)))

    guidee = [chute(ordre, k) for k in range(1, k_max + 1)]
    aleatoire = [chute(hasard, k) for k in range(1, k_max + 1)]
    aire_g, aire_a = float(np.sum(guidee)), float(np.sum(aleatoire))

    # Le rapport des aires n'est publié que si l'aire aléatoire est franchement
    # positive : remplacer des variables au hasard fait monter le score aussi
    # souvent qu'il le fait baisser, donc cette aire avoisine zéro et un rapport
    # y serait instable. L'écart, lui, se lit toujours.
    rapport = (round(aire_g / aire_a, 3)
               if aire_a > max(1e-9, 0.01 * abs(aire_g)) else None)

    return {
        "protocole": (
            f"les k variables les plus attribuées sont remplacées par leur "
            f"valeur de référence, k de 1 à {k_max}, sur {n} observations ; "
            "comparaison avec k variables tirées au hasard"),
        "score_moyen_de_depart": round(depart, 4),
        "chute_guidee_par_les_attributions": [round(v, 4) for v in guidee],
        "chute_par_choix_aleatoire": [round(v, 4) for v in aleatoire],
        "aire_guidee": round(aire_g, 4),
        "aire_aleatoire": round(aire_a, 4),
        "ecart_des_aires": round(aire_g - aire_a, 4),
        "rapport_des_aires": rapport,
        "lecture": (
            "Un écart positif signifie que les variables désignées par "
            "l'explication portent davantage le score qu'un choix au hasard. "
            "Un écart nul signifierait que l'explication ne désigne rien de "
            "particulier, quelle que soit la qualité du modèle."),
    }


# ── Extraction des coefficients du modèle SERVI ──────────────────────────────

def _lineaire_et_scaler(modele: Any) -> Optional[Tuple[Any, Any]]:
    """Retrouve (modèle linéaire, scaler) dans un pipeline, ou None."""
    etapes = dict(getattr(modele, "named_steps", {}) or {})
    lin = (etapes.get("logisticregression") or etapes.get("logistic")
           or etapes.get("linearregression")
           or (modele if hasattr(modele, "coef_") else None))
    if lin is None or not hasattr(lin, "coef_"):
        return None
    return lin, etapes.get("standardscaler")


def _normalise(lin: Any, scaler: Any) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(coefficients, moyennes, écarts-types) du modèle linéaire normalisé."""
    coefs = np.asarray(lin.coef_[0], dtype=float)
    if scaler is not None and hasattr(scaler, "mean_"):
        echelles = np.asarray(scaler.scale_, dtype=float)
        echelles = np.where(echelles == 0, 1.0, echelles)
        return coefs, np.asarray(scaler.mean_, dtype=float), echelles
    return coefs, np.zeros_like(coefs), np.ones_like(coefs)


def extraire_pipeline_lineaire(modele: Any) -> Optional[Dict[str, Any]]:
    """Coefficients du modèle SERVI, y compris sous un calibrateur.

    Un `CalibratedClassifierCV` contient K estimateurs ajustés, un par pli, et
    sert la moyenne de leurs sorties. La moyenne de leurs fonctions linéaires est
    elle-même linéaire : on l'extrait, au lieu de réentraîner un modèle de
    substitution sur tout le panel — un substitut explique un autre modèle que
    celui qui décide, et voit la période de test.
    """
    try:
        calibres = getattr(modele, "calibrated_classifiers_", None)
        if calibres:
            internes = []
            for c in calibres:
                base = (getattr(c, "estimator", None)
                        or getattr(c, "base_estimator", None))
                trouve = _lineaire_et_scaler(base) if base is not None else None
                if trouve is None:
                    return None
                internes.append(_normalise(*trouve))
            if not internes:
                return None

            # Chaque pli applique βk(x − μk)/σk. La moyenne de ces K fonctions est
            # linéaire et s'écrit exactement β*(x − μ*)/σ* avec :
            #     pente*  = moyenne_k(βk/σk)        (échelle des données brutes)
            #     σ*      = moyenne_k(σk)           (pour lire la position en σ)
            #     β*      = pente* · σ*
            #     μ*      = moyenne_k(βk·μk/σk) / pente*
            pentes = np.mean([c / e for c, _, e in internes], axis=0)
            decalages = np.mean([c * m / e for c, m, e in internes], axis=0)
            echelles = np.mean([e for _, _, e in internes], axis=0)
            sans_effet = np.abs(pentes) < 1e-12
            centres = np.divide(decalages, pentes,
                                out=np.zeros_like(pentes), where=~sans_effet)
            return {
                "coefficients": list(pentes * echelles),
                "moyennes": list(centres),
                "ecarts": list(echelles),
                "origine": (f"modèle servi — moyenne des {len(internes)} "
                            "estimateurs du calibrateur"),
            }

        trouve = _lineaire_et_scaler(modele)
        if trouve is None:
            return None
        coefs, centres, echelles = _normalise(*trouve)
        return {"coefficients": list(coefs), "moyennes": list(centres),
                "ecarts": list(echelles), "origine": "modèle servi"}
    except Exception:
        return None
