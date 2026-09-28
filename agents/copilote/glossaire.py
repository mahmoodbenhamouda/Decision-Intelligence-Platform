"""
agents/copilote/glossaire.py
============================
Glossaire financier : les définitions que le copilote cite telles quelles,
plutôt que de laisser un modèle de langage les reformuler.
"""

from __future__ import annotations

from typing import Dict, List

# ── Glossaire financier bilingue (FR/AR) utilisé dans le système-prompt ──────
FINANCIAL_GLOSSARY: Dict[str, str] = {
    "DSO": (
        "Days Sales Outstanding (Délai Moyen de Recouvrement) : nombre de jours "
        "moyen que met un client à payer ses factures après émission. "
        "Formule : (Créances clients / CA) × 365. Un DSO faible = encaissement rapide."
    ),
    "DPO": (
        "Days Payable Outstanding (Délai Moyen de Paiement Fournisseurs) : nombre "
        "de jours moyen pour payer les fournisseurs. Un DPO élevé améliore la "
        "trésorerie mais peut fragiliser la relation fournisseur."
    ),
    "BFR": (
        "Besoin en Fonds de Roulement : ressources nécessaires pour financer le "
        "cycle d'exploitation (stocks + créances - dettes fournisseurs). "
        "BFR = Créances + Stocks - Dettes fournisseurs."
    ),
    "FRNG": (
        "Fonds de Roulement Net Global : excédent des ressources permanentes sur "
        "les emplois stables. FRNG positif = sécurité financière à long terme."
    ),
    "TRÉ": (
        "Trésorerie nette : FRNG - BFR. Indique la position de liquidité immédiate."
    ),
    "VaR": (
        "Value at Risk (Valeur à Risque) : perte maximale estimée sur une position "
        "financière (ici le portefeuille de change) avec un niveau de confiance "
        "donné (ex : 95% sur 1 mois)."
    ),
    "EBITDA": (
        "Earnings Before Interest, Taxes, Depreciation and Amortization : bénéfice "
        "avant intérêts, impôts, dépréciations et amortissements. Mesure la "
        "performance opérationnelle brute."
    ),
    "DTA": (
        "Délai de Traitement des Avoirs : temps moyen entre l'émission d'un avoir "
        "(note de crédit) et son traitement effectif. Un DTA long crée des "
        "distorsions dans le solde des créances."
    ),
    "HHI": (
        "Indice Herfindahl-Hirschman : mesure la concentration d'un portefeuille. "
        "HHI > 0.25 = forte concentration (risque élevé si un client clé disparaît)."
    ),
    "FOREX / FX": (
        "Foreign Exchange (Marché des changes) : en Tunisie, les achats importés "
        "sont libellés en EUR ou USD mais facturés en Dinars Tunisiens (TND/DT). "
        "Une dépréciation du dinar augmente le coût d'achat et réduit la marge."
    ),
    "TND": (
        "Dinar Tunisien (DT) : monnaie nationale. Cours de référence : "
        "1 EUR ≈ 3.30 DT, 1 USD ≈ 3.10 DT (à vérifier sur les données temps réel)."
    ),
    "Ratio de liquidité": (
        "Actif court terme / Passif court terme. Un ratio > 1 indique que "
        "l'entreprise peut honorer ses dettes à court terme. "
        "< 1 = risque de cessation de paiements."
    ),
    "Couverture de change": (
        "Opération financière (forward, option) qui protège contre la variation "
        "du taux de change sur un flux futur en devises. Recommandée quand "
        "l'exposition dépasse 5% du CA annuel."
    ),
    "Aging des créances": (
        "Ventilation des créances clients par tranche d'ancienneté : 0-30j, 31-60j, "
        "61-90j, >90j. Permet d'identifier les factures critiques à recouvrer "
        "en priorité."
    ),
    "Marge brute": (
        "CA HT − Coût des achats. Exprimée en % du CA HT, elle mesure la "
        "rentabilité commerciale avant les frais fixes."
    ),
    "Taux de conversion devis": (
        "Ratio Devis acceptés / Devis émis. Un taux faible (<40%) peut indiquer "
        "un problème de prix ou de proposition commerciale."
    ),
    "Encours clients": (
        "Total des factures émises non encore encaissées à une date donnée. "
        "Synonyme de créances clients."
    ),
    "Recouvrement": (
        "Processus de relance et d'encaissement des factures impayées. "
        "Priorité : factures > 90 jours (risque d'irrecouvrabilité)."
    ),
    "Factoring / Affacturage": (
        "Cession des créances clients à un organisme financier (factor) qui avance "
        "les fonds immédiatement. Permet d'améliorer la trésorerie court terme "
        "en échange d'une commission."
    ),
    "Escompte commercial": (
        "Réduction accordée au client s'il paie avant l'échéance. "
        "Ex : 2% escompte si paiement sous 10 jours au lieu de 30."
    ),
    "Appel d'offres / AO": (
        "Procédure d'achat public (marchés publics tunisiens) par laquelle un "
        "organisme public (hôpital, ministère) sollicite des offres commerciales. "
        "Publié sur TUNEPS (www.tuneps.tn)."
    ),
    "TUNEPS": (
        "Système tunisien d'achats publics électroniques. Portail officiel des "
        "marchés publics tunisiens. Source principale des appels d'offres."
    ),
    "Pareto clients": (
        "Loi 80/20 appliquée aux clients : les 20% de clients les plus importants "
        "génèrent 80% du CA. Identifier ce groupe est prioritaire pour la fidélisation."
    ),
    "Cash conversion cycle": (
        "Cycle de conversion de trésorerie : DSO + DIO (jours de stock) - DPO. "
        "Mesure le délai entre le décaissement fournisseur et l'encaissement client."
    ),
}


def detect_glossary_terms(question: str) -> List[str]:
    """Retourne les termes du glossaire mentionnés dans la question."""
    q_lower = question.lower()
    terms = []
    for term in FINANCIAL_GLOSSARY:
        if term.lower() in q_lower:
            terms.append(term)
    return terms


def build_glossary_section(terms: List[str], question_themes: List[str]) -> str:
    """Construit la section glossaire à injecter dans le prompt."""
    # Termes explicitement demandés
    relevant = set(terms)
    # Termes liés aux thèmes détectés (automatique)
    theme_to_terms = {
        "change": ["TND"],
        "recouvrement": ["DSO", "Aging des créances", "Recouvrement", "Encours clients"],
        "tresorerie": ["BFR", "FRNG", "TRÉ", "Cash conversion cycle", "DPO"],
        "marge": ["Marge brute", "EBITDA", "Taux de conversion devis"],
    }
    for theme in question_themes:
        for t in theme_to_terms.get(theme, []):
            relevant.add(t)

    if not relevant:
        return ""

    lines = ["📚 GLOSSAIRE FINANCIER (à utiliser dans la réponse si pertinent) :"]
    for term in sorted(relevant):
        defn = FINANCIAL_GLOSSARY.get(term)
        if defn:
            lines.append(f"  • {term} : {defn}")
    return "\n".join(lines)
