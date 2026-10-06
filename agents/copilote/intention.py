"""Ce que demande l'utilisateur : le mode (tableau de bord ou question), le périmètre (global ou…"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


THEME_KEYWORDS: Dict[str, List[str]] = {
    "recouvrement": [
        "recouvrement", "relance", "impayé", "retard", "créance", "facture",
        "aging", "délai", "encaissement", "dso", "60 j", "90 j", "critique",
        "client à risque", "encours",
    ],
    "change": [
        "change", "forex", "fx", "devise", "dinar", "eur", "usd", "tnd",
        "taux de change", "dépréciation", "couverture", "risque de change",
        "var", "sensibilité", "impact change",
    ],
    "tresorerie": [
        "trésorerie", "cash", "liquidité", "frng", "bfr", "flux", "cashflow",
        "encaissement", "décaissement", "solde", "paiement", "dpo",
        "cycle de conversion",
    ],
    "marge": [
        "marge", "rentabilité", "profit", "coût", "achat", "revient", "ebitda",
        "résultat", "bénéfice", "taux de marge", "marge brute", "marge commerciale",
    ],
    "prevision": [
        "prévision", "forecast", "projection", "projeté", "futur", "prochain",
        "anticiper", "tendance", "mois prochain", "trimestre",
    ],
    "glossaire": [
        "c'est quoi", "que veut dire", "définition", "expliquer", "signifie",
        "définir", "qu'est-ce que", "terme", "dso", "bfr", "frng", "var",
        "ebitda", "hhi", "dta", "factoring", "escompte",
    ],
    "fidelite": [
        "fidèle", "fidèles", "fidele", "fideles", "fidélité", "fidelite",
        "récurrent", "recurrent", "récurrents", "réguliers", "reguliers", "régulier",
        "meilleurs clients", "clients réguliers", "clients récurrents", "client fidèle",
        "loyal", "loyaux", "loyauté", "rétention", "retention", "clients historiques",
    ],
    "palmares": [
        "top 3", "top 5", "top 10", "top client", "top clients", "plus gros client",
        "plus gros clients", "principaux clients", "gros clients", "classement client",
        "classement des clients", "palmarès", "palmares", "clients les plus importants",
        "clients importants", "premiers clients", "liste des clients", "plus importants clients",
    ],
    "attrition": [
        "décroche", "decroche", "décrochent", "decrochent", "décrochage", "decrochage",
        "churn", "attrition", "perdre des clients", "perte de client", "clients perdus",
        "clients dormants", "dormant", "inactif", "inactifs", "ne commandent plus",
        "qui partent", "s'essouffl", "essouffl", "clients qui baissent", "perdent du terrain",
    ],
    "concentration": [
        "concentration", "concentré", "concentre", "dépendance", "dependance",
        "pareto", "80/20", "diversification", "diversifié", "diversifie",
        "poids des clients", "répartition du ca", "repartition du ca", "hhi",
        "trop dépendant", "dépendant de", "risque de dépendance",
    ],
    "approvisionnement": [
        "approvisionnement", "appro", "fournisseur", "fournisseurs", "dépendance fournisseur",
        "dependance fournisseur", "rupture", "rupture d'appro", "rupture de stock", "stock",
        "réappro", "reappro", "commande fournisseur", "biomérieux", "biomerieux",
        "prévision de demande", "prevision de demande", "demande d'articles", "volume d'articles",
        "achat", "achats", "sourcing", "chaîne d'approvisionnement",
    ],
    "performance": [
        "performance", "ca", "chiffre d'affaires", "vente", "croissance",
        "yoy", "mom", "hausse", "baisse", "évolution", "top client",
    ],
    "risque_stock": [
        "péremption", "peremption", "périmer", "perimer", "périmé", "perime",
        "date de péremption", "dlc", "expiration", "expirer", "lot expiré",
        "surstock", "sur-stock", "immobilisé", "immobilisation",
        "risque de stock", "risque stock", "score de risque", "days to stockout",
        "rupture de stock", "va manquer", "manquer de stock", "réappro urgent",
        "prévision de stock", "combien de jours de stock", "couverture de stock",
    ],
    "modeles": [
        "modèle", "modele", "modèles", "modeles", "accuracy", "exactitude",
        "auc", "fiabilité du modèle", "fiabilite du modele", "machine learning",
        "deep learning", "apprentissage profond", "réseau de neurones", "reseau de neurones",
        "data science", "registre des modèles", "quels modèles", "performance des modèles",
    ],
    "recommandation": [
        "recommand", "vente croisée", "vente croisee", "cross-sell", "cross sell",
        "quels produits proposer", "produits à proposer", "produits a proposer",
        "proposer à", "proposer a", "nouveaux produits pour", "opportunité produit",
        "opportunites produit", "que proposer",
    ],
    "devis": [
        "devis", "relance de devis", "relancer les devis", "taux de conversion",
        "signature", "signer", "pipeline commercial", "offres en cours",
    ],
    "risque_stock_client": [
        "client sans risque", "clients sans risque", "sans risque de stock",
        "sans risque sur le stock", "pas de risque de stock", "pas de risque sur le stock",
        "clients à risque de stock", "clients les plus exposés", "stock par client",
        "risque de stock par client", "quels clients ont du stock",
    ],
}

_MOTS_STOCK = ("stock", "rupture", "surstock", "péremption", "peremption",
               "périmer", "perimer", "périmé", "perime")
_MOTS_CLIENT = ("client", "hôpital", "hopital", "hôpitaux", "hopitaux",
                "laboratoire", "compte", "établissement", "etablissement")


def detect_theme(question: str) -> List[str]:
    """Retourne la liste des thèmes détectés dans la question (ordre priorité)."""
    q_lower = question.lower()
    themes = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            themes.append(theme)

    if any(m in q_lower for m in _MOTS_STOCK) and any(m in q_lower for m in _MOTS_CLIENT):
        if "risque_stock_client" not in themes:
            themes.insert(0, "risque_stock_client")

    return themes or ["performance"]


def has_internal_theme(question: str) -> bool:
    """Vrai si la question correspond à un thème 'données internes' (ERP/finance)."""
    q_lower = question.lower()
    return any(any(kw in q_lower for kw in kws) for kws in THEME_KEYWORDS.values())


def classer(filters: Dict[str, Any], question: str | None) -> Tuple[str, str]:
    """(mode, périmètre) : « qa » si une question est posée, sinon « dashboard » ; « client » si des…"""
    mode = "qa" if (question and str(question).strip()) else "dashboard"
    scope = "client" if filters.get("selected_clients") else "global"
    return mode, scope


def requete_documentaire(question: str) -> Tuple[bool, str]:
    """(forcée, requête) : le préfixe « doc: » ou « docs: » force la base documentaire et en est retiré…"""
    ql = question.strip().lower()
    force = ql.startswith("doc:") or ql.startswith("docs:")
    return force, (question.split(":", 1)[1].strip() if force else question)
