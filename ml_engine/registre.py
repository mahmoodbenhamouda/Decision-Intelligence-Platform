"""
ml_engine/registre.py
=====================
Registre des modèles — **point d'entrée unique** pour savoir ce qui est servi.

Le problème que ce fichier résout
---------------------------------
Un modèle refusé mais présent sur le disque est un piège. Rien n'empêche un
appelant de charger `credit_risk_model.joblib` et de servir ses probabilités,
alors que son rapport de métriques indique noir sur blanc qu'il ne généralise
pas. Le refus de déploiement n'existait que dans un JSON que personne n'était
obligé de lire.

Ici, la décision de déploiement devient **exécutable** : l'API et le tableau de
bord demandent au registre si un modèle est servi, et le registre répond en
lisant les métriques réellement mesurées. Un modèle dont les seuils ne sont pas
atteints est inaccessible, pas seulement déconseillé.

Principe
--------
Chaque modèle déclare où lit sa décision. Le registre ne recalcule rien et ne
juge rien : il rapporte ce que l'entraînement a mesuré. Si le rapport est absent,
le modèle est considéré **non déployé** — jamais l'inverse. Un doute se résout
toujours dans le sens du refus.

Lancement (état consolidé lisible) :
    python -m ml_engine.registre
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[1]

REPORTS_DIR = BASE / "reports"
MODELS_DIR = BASE / "models"


# ── Déclaration des modèles ─────────────────────────────────────────────────
# `chemin_decision` est la suite de clés menant au booléen de déploiement dans le
# rapport. On le déclare au lieu de le coder en dur pour que chaque modèle garde
# la structure de rapport qui lui convient.
# `nature` est la clé de lecture de tout ce registre. Un module peut être SERVI
# sans qu'aucun modèle n'ait été appris, et c'est un résultat, pas un pis-aller :
#
#   * modele_appris      — un modèle a été entraîné et a battu une référence
#                          triviale dans un protocole reproduisant l'usage ;
#   * regle_deterministe — une règle auditable, vérifiée hors période. Aucun
#                          apprentissage, parce que la grandeur visée est une
#                          donnée contractuelle qui se lit au lieu de se prédire ;
#   * methode_statistique— une statistique robuste validée en walk-forward, là où
#                          l'apprentissage a été essayé puis écarté faute de signal ;
#   * lecture_carnet     — la grandeur est déjà inscrite dans les données ; on la
#                          lit et l'on n'estime que la part manquante.
#   * modele_deep_learning — un réseau de neurones (PyTorch) entraîné et servi
#                          parce qu'il bat SIGNIFICATIVEMENT les références
#                          triviales ET les modèles non profonds plus simples.
#
# Confondre ces natures conduit à l'erreur inverse de celle qu'on croit éviter :
# présenter un module utile comme un échec parce qu'il ne contient pas de réseau.
MODELES: Dict[str, Dict[str, Any]] = {
    "churn": {
        "libelle": "Décrochage client (attrition à 90 jours)",
        "nature": "modele_appris",
        "rapport": "churn_metrics.json",
        "artefact": "churn_model.joblib",
        "chemin_decision": ["decision_deploiement", "modele_deploye"],
        "chemin_metrique": ["hors_periode", "auc"],
        "metrique_nom": "AUC hors période",
        "chemin_reference": ["hors_periode", "auc_meilleure_reference_triviale"],
        "sens": "haut",     # plus haut = mieux
    },
    "credit": {
        "libelle": "Conditions de crédit client",
        "nature": "regle_deterministe",
        "rapport": "credit_risk_metrics.json",
        "artefact": "credit_risk_model.joblib",
        # La décision se lit dans le bloc `production` : ce module sert une règle,
        # et le refus du modèle cold-start n'empêche pas de servir cette règle.
        "chemin_decision": ["production", "statut"],
        "valeur_servie": "servi",
        "chemin_metrique": ["production", "auc_hors_periode"],
        "metrique_nom": "AUC hors période (règle)",
        "chemin_reference": ["production", "reference_auc_hasard"],
        "sens": "haut",
    },
    "marge_client": {
        "libelle": "Érosion de marge client à 3 mois",
        "nature": "modele_appris",
        "rapport": "marge_client_metrics.json",
        "artefact": "marge_client.joblib",
        "chemin_decision": ["decision_deploiement", "modele_deploye"],
        "chemin_metrique": ["evaluation", "auc"],
        "metrique_nom": "AUC hors période",
        "chemin_reference": ["evaluation", "auc_meilleure_reference_triviale"],
        "sens": "haut",
    },
    "conversion_devis": {
        "libelle": "Conversion des devis (probabilité de signature)",
        "nature": "modele_appris",
        "rapport": "conversion_devis_metrics.json",
        "artefact": "conversion_devis.joblib",
        "chemin_decision": ["decision_deploiement", "modele_deploye"],
        "chemin_metrique": ["hors_periode", "auc"],
        "metrique_nom": "AUC hors période",
        "chemin_reference": ["hors_periode", "auc_meilleure_reference_triviale"],
        "sens": "haut",
    },
    "segmentation": {
        "libelle": "Typologie de clientèle (segmentation)",
        # Non supervisé : il n'existe aucune étiquette « type de client » à
        # prédire. La typologie est à découvrir, pas à reproduire — d'où
        # l'absence de protocole hors période, qui n'aurait pas de sens ici.
        "nature": "modele_non_supervise",
        "rapport": "segmentation_metrics.json",
        "artefact": "segmentation.joblib",
        "chemin_decision": ["servi"],
        "chemin_metrique": ["qualite", "silhouette"],
        "metrique_nom": "silhouette (séparation)",
        "chemin_reference": None,
        "sens": "haut",
    },
    "stock_risque": {
        "libelle": "Risque produit (péremption / rupture / surstock)",
        "nature": "modele_appris",
        # ══ RETIRÉ DU SERVICE — décision assumée, pas une panne ══
        #
        # Ce modèle atteint 0,8562 d'AUC hors période groupée par produit, et
        # aurait donc passé ses seuils. Il est retiré pour une raison qui ne
        # figure dans aucune métrique : **une partie de sa cible est simulée**.
        #
        # 11 576 de ses 18 071 cibles positives viennent de `risque_peremption`,
        # construit sur des `date_peremption` GÉNÉRÉES — l'ERP n'en porte aucune.
        # Ses variables de position proviennent elles aussi du module (s,S)
        # simulé. Une AUC honnête sur une cible inventée reste une AUC sur une
        # cible inventée.
        #
        # Ce qui le remplace, sans aucune simulation :
        #   * capital immobilisé et surstock -> flux_reels.py (achats − ventes) ;
        #   * stock non écoulable -> obsolescence par rotation, seuil déclaré ;
        #   * ruptures -> arrêt d'approvisionnement, arithmétique ;
        #   * fin de commercialisation -> fin_de_vie.py, cible observée.
        #
        # Le modèle et ses métriques sont conservés : ils documentent une démarche
        # CRISP-DM complète et trois fuites trouvées puis corrigées. C'est son
        # SERVICE qui cesse, pas son existence.
        "retire": True,
        "motif_retrait": (
            "retiré du service : 11 576 de ses 18 071 cibles positives reposent "
            "sur des dates de péremption simulées, et ses variables de position "
            "sur le module (s,S) généré. Remplacé par des mesures issues des "
            "factures réelles. Sa performance (AUC 0,8562) n'est pas en cause — "
            "seule l'origine de sa cible l'est."),
        "rapport": "stock_risk_metrics.json",
        "artefact": "stock_risk.joblib",
        # Ce rapport ne porte pas de booléen de déploiement : la décision est
        # déduite de la performance mesurée, cf. `_deduire_stock_risque`.
        "chemin_decision": None,
        "chemin_metrique": ["holdout", "auc"],
        "metrique_nom": "AUC hold-out groupé par produit",
        # La référence est le modèle LINÉAIRE sur les mêmes variables. Elle
        # répond à « la non-linéarité est-elle nécessaire ? » — ici oui, très
        # nettement, ce qui justifie un modèle d'ensemble plutôt qu'une règle.
        "chemin_reference": ["comparaison", "regression_logistique", "cv_auc"],
        "sens": "haut",
    },
    "fin_de_vie": {
        "libelle": "Fin de commercialisation à 6 mois",
        # Premier modèle du domaine stock dont TOUTES les entrées ET la cible
        # viennent des factures : positions reconstruites, mix de clientèle, prix.
        # Aucune quantité simulée, aucune date inventée.
        "nature": "modele_appris",
        "rapport": "fin_de_vie_metrics.json",
        "artefact": "fin_de_vie.joblib",
        "chemin_decision": ["decision_deploiement", "modele_deploye"],
        "chemin_metrique": ["hors_periode", "auc"],
        "metrique_nom": "AUC hors période",
        "chemin_reference": ["hors_periode", "auc_meilleure_reference_triviale"],
        "sens": "haut",
    },
    "reappro": {
        "libelle": "Besoin de réapprovisionnement à 3 mois",
        # Seul modèle du domaine stock dont TOUTES les variables viennent des
        # factures : la reconstruction des positions mensuelles a rendu possible
        # ce qui ne l'était pas quand les positions étaient simulées.
        "nature": "modele_appris",
        "rapport": "reappro_metrics.json",
        "artefact": "reappro_model.joblib",
        "chemin_decision": ["decision_deploiement", "modele_deploye"],
        "chemin_metrique": ["hors_periode", "auc"],
        "metrique_nom": "AUC hors période",
        "chemin_reference": ["hors_periode", "auc_meilleure_reference_triviale"],
        "sens": "haut",
    },
    "demande": {
        "libelle": "Demande mensuelle (volume d'articles)",
        "nature": "methode_statistique",
        "rapport": "demande_hybride_metrics.json",
        "artefact": None,       # aucun artefact à charger
        "chemin_decision": ["methode_servie", "statut"],
        "valeur_servie": "servi",
        "chemin_metrique": ["methode_servie", "mape_pct"],
        "metrique_nom": "MAPE walk-forward",
        "chemin_reference": ["evaluation", "mape_meilleure_reference_pct"],
        "sens": "bas",      # plus bas = mieux
    },
    "demande_reference": {
        "libelle": "Demande par référence (réactifs, 1 à 3 mois)",
        # Une méthode est TOUJOURS servie : la règle simple par défaut, le modèle
        # appris seulement s'il la bat de 2 points de WAPE avec un intervalle
        # entièrement positif. La nature dépend donc de la méthode que la mesure
        # a retenue ; elle est LUE dans le rapport, pas déclarée ici.
        "nature": "methode_statistique",
        "chemin_nature": ["methode_servie", "nature"],
        "rapport": "demande_reference_metrics.json",
        "artefact": None,
        "chemin_decision": ["methode_servie", "statut"],
        "valeur_servie": "servi",
        "chemin_metrique": ["methode_servie", "wape_h1_pct"],
        "metrique_nom": "WAPE walk-forward à 1 mois",
        "chemin_reference": ["regle_de_reference", "test", "wape_h1_pct"],
        "sens": "bas",      # plus bas = mieux
    },
    "recommandation": {
        "libelle": "Recommandation de produits (vente croisée à 6 mois)",
        # La nature dépend de la méthode que la mesure a retenue : Wide & Deep
        # s'il bat significativement les modèles plus simples, sinon le plus
        # simple d'entre eux. Elle est donc LUE dans le rapport, pas déclarée ici.
        "nature": "modele_deep_learning",
        "nature_selon_methode": {
            "wide_deep": "modele_deep_learning",
            "lightgbm": "modele_appris",
            "regression_logistique": "modele_appris",
            "popularite_12m": "regle_deterministe",
            "popularite_par_type": "regle_deterministe",
            "item_knn": "regle_deterministe",
        },
        "rapport": "recommandation_metrics.json",
        "artefact": None,       # recommandations précalculées : l'API n'exige pas PyTorch
        "chemin_decision": ["decision_deploiement", "servi"],
        "chemin_metrique": ["evaluation", "methode_servie", "ndcg_at_10"],
        "metrique_nom": "NDCG@10 walk-forward",
        "chemin_reference": ["evaluation", "meilleure_reference_triviale", "ndcg_at_10"],
        "sens": "haut",
    },
    "layoutlmv3": {
        "libelle": "Lecture de factures (LayoutLMv3 affiné)",
        "nature": "modele_deep_learning",
        "rapport": "layoutlmv3_metrics.json",
        # Le modèle est un DOSSIER ; on teste sa configuration, qui est le
        # fichier sans lequel `from_pretrained` échoue.
        "artefact": "layoutlmv3_factures/config.json",
        "chemin_decision": ["decision_deploiement", "modele_deploye"],
        "chemin_metrique": ["validation_croisee", "exactitude_globale_pct"],
        "metrique_nom": "exactitude par champ (validation croisée 5 plis)",
        "chemin_reference": ["validation_croisee", "regles_production_pct"],
        "sens": "haut",
        # Consommé HORS de la flotte : il lit des factures, il n'analyse pas la
        # gestion. Le test de câblage vérifie que ce fichier l'utilise vraiment,
        # au lieu d'exiger qu'un agent le cite.
        "hors_flotte": "ml_engine/ocr/layoutlm/extracteur.py",
    },
    "echeancier": {
        "libelle": "Échéancier de trésorerie à 1 mois",
        "nature": "lecture_carnet",
        "rapport": "cashflow_carnet_metrics.json",
        "artefact": None,
        "chemin_decision": None,    # décision portée par le gain mesuré, cf. ci-dessous
        "chemin_metrique": ["horizons", "h1", "mape_pct"],
        "metrique_nom": "MAPE h=1",
        "chemin_reference": None,
        "sens": "bas",
    },
}


def _lire(chemin: Path) -> Optional[Dict[str, Any]]:
    if not chemin.exists():
        return None
    try:
        return json.load(open(chemin, encoding="utf-8"))
    except Exception:
        return None


def _extraire(doc: Dict[str, Any], chemin: Optional[List[str]]) -> Any:
    """Suit une suite de clés, en renvoyant None dès qu'une étape manque."""
    if not chemin:
        return None
    cur: Any = doc
    for cle in chemin:
        if not isinstance(cur, dict) or cle not in cur:
            return None
        cur = cur[cle]
    return cur


def etat_modele(nom: str) -> Dict[str, Any]:
    """État consolidé d'un modèle, tel que mesuré par son entraînement."""
    spec = MODELES.get(nom)
    if spec is None:
        return {"nom": nom, "connu": False,
                "deploye": False, "motif": "modèle inconnu du registre"}

    rapport = _lire(REPORTS_DIR / spec["rapport"])
    if rapport is None:
        # Absence de rapport → non déployé. Jamais l'inverse : un modèle dont on
        # ne sait rien ne doit pas être servi au prétexte que son fichier existe.
        return {
            "nom": nom, "connu": True, "libelle": spec["libelle"],
            "deploye": False,
            "motif": (f"rapport `{spec['rapport']}` absent — le modèle n'a pas été "
                      "évalué, donc il n'est pas servi"),
            "rapport_present": False,
        }

    # Un module RETIRÉ n'est pas servi, quelles que soient ses métriques. C'est la
    # seule décision du registre qui ne se déduit pas d'un chiffre : elle porte sur
    # l'ORIGINE de la cible, et aucune métrique ne peut la voir. La déclarer ici la
    # rend exécutoire au lieu de la laisser dans un document.
    if spec.get("retire"):
        return {
            "nom": nom, "connu": True, "libelle": spec["libelle"],
            "nature": spec.get("nature", "non precisee"),
            "deploye": False,
            "retire": True,
            "rapport_present": True,
            "metrique_nom": spec["metrique_nom"],
            "metrique": _extraire(rapport, spec["chemin_metrique"]),
            "reference_a_battre": _extraire(rapport, spec["chemin_reference"]),
            "gain": None,
            "version_rapport": rapport.get("version"),
            "motif": spec.get("motif_retrait", "retiré du service"),
        }

    artefact_ok = True
    if spec["artefact"]:
        artefact_ok = (MODELS_DIR / spec["artefact"]).exists()

    brut = _extraire(rapport, spec["chemin_decision"])
    if brut is None:
        # Pas de décision déclarée : le module porte la sienne autrement (cas de
        # l'échéancier, dont chaque horizon est accepté ou refusé séparément).
        if nom == "echeancier":
            deploye = _deduire_echeancier(rapport)
        elif nom == "stock_risque":
            deploye = _deduire_stock_risque(rapport)
        else:
            deploye = False
    elif "valeur_servie" in spec:
        # La décision est une chaîne de statut, pas un booléen.
        deploye = (str(brut) == spec["valeur_servie"])
    else:
        deploye = bool(brut)

    metrique = _extraire(rapport, spec["chemin_metrique"])
    reference = _extraire(rapport, spec["chemin_reference"])

    nature = spec.get("nature", "non precisee")
    if spec.get("chemin_nature"):
        nature = _extraire(rapport, spec["chemin_nature"]) or nature
    if spec.get("nature_selon_methode"):
        methode = _extraire(rapport, ["decision_deploiement", "methode_servie"])
        nature = spec["nature_selon_methode"].get(str(methode), nature)

    gain = None
    if isinstance(metrique, (int, float)) and isinstance(reference, (int, float)):
        gain = round((metrique - reference) if spec["sens"] == "haut"
                     else (reference - metrique), 4)

    # Le rapport peut avoir mesuré que l'écart à la référence n'est pas
    # distinguable de zéro (bootstrap apparié). Dans ce cas le signe du gain ne
    # porte pas d'information, et l'afficher comme un résultat serait trompeur.
    cmp_ = _extraire(rapport, ["evaluation",
                              "comparaison_socle_retenu_vs_meilleure_reference"])
    non_significatif = bool(isinstance(cmp_, dict)
                            and cmp_.get("significatif") is False)

    return {
        "nom": nom, "connu": True, "libelle": spec["libelle"],
        "nature": nature,
        "deploye": bool(deploye) and artefact_ok,
        "rapport_present": True,
        "artefact_present": artefact_ok,
        "metrique_nom": spec["metrique_nom"],
        "metrique": metrique,
        "reference_a_battre": reference,
        "gain": gain,
        "ecart_non_significatif": non_significatif,
        "version_rapport": rapport.get("version"),
        "motif": _motif(rapport, nom, bool(deploye), artefact_ok),
    }


def _deduire_echeancier(rapport: Dict[str, Any]) -> bool:
    """L'échéancier est servi si au moins un horizon affiche un gain réel.

    Son rapport ne porte pas de booléen unique : chaque horizon est jugé
    séparément, certains étant refusés pour raison structurelle (à h=3, moins de
    1 % des factures ont un délai suffisant). Un seul horizon utile suffit à
    rendre le module servable.
    """
    horizons = rapport.get("horizons") or {}
    for h in horizons.values():
        if not isinstance(h, dict) or h.get("refuse"):
            continue
        mape = h.get("mape_pct")
        # Le rapport nomme ce bloc `baselines_mape_pct`. On accepte les deux
        # graphies : une clé renommée en amont ne doit pas faire silencieusement
        # basculer un module servi vers « refusé ».
        refs = h.get("baselines_mape_pct") or h.get("baselines") or {}
        valeurs = [v for v in refs.values() if isinstance(v, (int, float))]
        if isinstance(mape, (int, float)) and valeurs and mape < min(valeurs):
            return True
    return False


def _deduire_stock_risque(rapport: Dict[str, Any]) -> bool:
    """Le modèle de risque produit est-il servable ?

    Trois conditions, dans l'esprit des autres modules :
      * une AUC hold-out décente dans l'absolu ;
      * un gain net sur le modèle LINÉAIRE construit sur les mêmes variables —
        sans quoi la complexité d'un ensemble ne se justifierait pas ;
      * pas d'effondrement entre validation croisée et hold-out, l'écart qui
        avait trahi la fuite temporelle du modèle de crédit.
    """
    hold = (rapport.get("holdout") or {}).get("auc")
    lin = ((rapport.get("comparaison") or {})
           .get("regression_logistique") or {}).get("cv_auc")
    retenu = rapport.get("modele_retenu")
    cv = ((rapport.get("comparaison") or {}).get(retenu) or {}).get("cv_auc")

    # Une AUC quasi parfaite sur un problème métier n'est pas une réussite :
    # c'est le symptôme d'une fuite. Le registre refuse donc par le HAUT aussi,
    # et non seulement par le bas — la première version de ce modèle affichait
    # 1,0000, et rien dans le code ne l'empêchait d'être servi.
    if isinstance(hold, (int, float)) and hold >= 0.99:
        return False
    if not isinstance(hold, (int, float)) or hold < 0.70:
        return False

    # Le chiffre lu doit être celui du protocole GROUPÉ par produit. Si l'audit
    # existe et désigne une autre mesure, on refuse plutôt que de décider sur un
    # nombre dont on ne sait pas d'où il vient.
    audit = rapport.get("audit_fuite") or {}
    if audit.get("applicable"):
        groupe = audit.get("auc_holdout_groupe_par_produit")
        if not isinstance(groupe, (int, float)) or abs(groupe - hold) > 1e-9:
            return False
    if isinstance(lin, (int, float)) and hold - lin < 0.02:
        return False
    if isinstance(cv, (int, float)) and cv - hold > 0.15:
        return False    # la performance s'effondre hors échantillon
    return True


def _motif(rapport: Dict[str, Any], nom: str,
           deploye: bool, artefact_ok: bool) -> str:
    """Motif affiché — il doit décrire CE QUI EST SERVI, pas ce qui a été écarté.

    Piège corrigé ici : pour le crédit, `decision_deploiement` parle du modèle
    cold-start refusé. L'afficher à côté d'un module servi produisait une
    contradiction apparente — « SERVI » suivi de « gain non confirmé ». Les blocs
    décrivant la production sont donc lus en premier.
    """
    # Ordre important. Un artefact absent PARCE QUE le modèle a été refusé n'est
    # pas une panne d'installation : c'est le comportement voulu, et afficher
    # « artefact absent » masquerait la vraie raison. On lit donc d'abord la
    # décision déclarée, et l'on ne parle du fichier que si aucune décision
    # explicite n'existe.
    decision = rapport.get("decision_deploiement")
    refus_declare = (isinstance(decision, dict)
                     and decision.get("modele_deploye") is False
                     and decision.get("motif"))
    if not artefact_ok:
        if refus_declare:
            return str(decision["motif"])
        return "artefact absent du dossier models/ — module non servi"

    if deploye:
        for bloc in ("production", "methode_servie"):
            d = rapport.get(bloc)
            if isinstance(d, dict):
                for cle in ("methode_servie", "nature", "motif"):
                    if d.get(cle):
                        return str(d[cle])

    for bloc in ("decision_deploiement", "decision_correcteur_appris"):
        d = rapport.get(bloc)
        if isinstance(d, dict) and d.get("motif"):
            return str(d["motif"])
    return "servi" if deploye else "non servi"


def est_deploye(nom: str) -> bool:
    """Question posée par l'API avant de servir une prédiction."""
    return bool(etat_modele(nom)["deploye"])


def etat_complet() -> Dict[str, Any]:
    """État de tous les modèles, pour le tableau de bord et le rapport."""
    etats = {nom: etat_modele(nom) for nom in MODELES}
    deployes = [n for n, e in etats.items() if e["deploye"]]
    par_nature: Dict[str, List[str]] = {}
    for n, e in etats.items():
        if e["deploye"]:
            par_nature.setdefault(e.get("nature", "non precisee"), []).append(n)
    return {
        "modeles": etats,
        "n_total": len(etats),
        "n_deployes": len(deployes),
        "deployes": deployes,
        "refuses": [n for n, e in etats.items()
                    if not e["deploye"] and not e.get("retire")],
        "retires": [n for n, e in etats.items() if e.get("retire")],
        "servis_par_nature": par_nature,
        "n_modeles_appris": len(par_nature.get("modele_appris", [])),
        "n_modeles_non_supervises": len(par_nature.get("modele_non_supervise", [])),
        "n_modeles_deep_learning": len(par_nature.get("modele_deep_learning", [])),
        "principe": (
            "Un module n'est servi que si sa performance a été mesurée dans un "
            "protocole reproduisant l'usage — hors période pour les modèles, "
            "walk-forward pour les séries. En l'absence de rapport, il est "
            "refusé : un doute se résout toujours dans le sens du refus."),
        "lecture_des_natures": (
            "Être servi sans apprentissage n'est pas un pis-aller. Les conditions "
            "de crédit sont une clause contractuelle : elle se lit, elle ne se "
            "prédit pas. La demande mensuelle n'a pas de signal exploitable dans "
            "son résidu, ce qui a été mesuré puis assumé. Dans les deux cas, "
            "servir une règle ou une statistique robuste est la réponse juste, "
            "et un modèle appris n'aurait ajouté que de l'opacité."),
    }


def afficher() -> None:
    e = etat_complet()
    print("\n" + "=" * 78)
    print("  REGISTRE DES MODÈLES")
    print("=" * 78)
    _NATURES = {
        "modele_appris": "modèle appris (supervisé)",
        "modele_non_supervise": "modèle non supervisé (aucune étiquette à prédire)",
        "regle_deterministe": "règle déterministe, sans apprentissage",
        "methode_statistique": "statistique robuste, sans apprentissage",
        "lecture_carnet": "lecture du carnet, estimation du reste",
        "modele_deep_learning": "réseau de neurones (deep learning, PyTorch)",
    }
    for nom, m in e["modeles"].items():
        etat = ("SERVI " if m["deploye"]
                else "RETIRÉ" if m.get("retire") else "REFUSÉ")
        nature = _NATURES.get(m.get("nature", ""), m.get("nature", ""))
        print(f"\n  [{etat}] {m.get('libelle', nom)}")
        print(f"           nature : {nature}")
        if m.get("metrique") is not None:
            val = m["metrique"]
            fmt = f"{val:.4f}" if isinstance(val, float) and val <= 1 else f"{val}"
            ligne = f"      {m['metrique_nom']} = {fmt}"
            ref = m.get("reference_a_battre")
            if ref is not None:
                rfmt = f"{ref:.4f}" if isinstance(ref, float) and ref <= 1 else f"{ref}"
                ligne += f"  (référence {rfmt}"
                gain = m.get("gain")
                if gain is not None:
                    # Un écart mesuré non distinguable de zéro ne doit pas
                    # s'afficher comme un gain négatif : ce serait présenter du
                    # bruit d'échantillonnage comme un désavantage établi.
                    if m.get("ecart_non_significatif"):
                        ligne += ", écart non significatif"
                    else:
                        ligne += f", gain {gain:+.4f}"
                ligne += ")"
            print(ligne)
        motif = m.get("motif", "")
        if motif:
            for i in range(0, len(motif), 70):
                print(f"      {motif[i:i+70]}")
    print("\n" + "-" * 78)
    print(f"  {e['n_deployes']} module(s) servi(s) sur {e['n_total']} : "
          + (", ".join(e["deployes"]) if e["deployes"] else "aucun"))
    print(f"  dont {e['n_modeles_appris']} modèle(s) supervisé(s) et "
          f"{e['n_modeles_non_supervises']} non supervisé(s) et "
          f"{e['n_modeles_deep_learning']} deep learning ; les autres servent "
          "une règle ou une statistique")
    if e["refuses"]:
        print(f"  refusé(s) : {', '.join(e['refuses'])}")
    if e.get("retires"):
        print(f"  retiré(s) : {', '.join(e['retires'])} — décision portant sur "
              "l'ORIGINE de la cible,")
        print("              pas sur la performance. Aucune métrique ne peut la voir.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
