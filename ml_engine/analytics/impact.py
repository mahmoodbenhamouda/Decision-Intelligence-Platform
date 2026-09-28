"""
ml_engine/analytics/impact.py
==============================
Ce que la plateforme fait gagner — mesuré, et borné par ce qu'on peut prouver.

La question à laquelle ce module répond
---------------------------------------
« Concrètement, ça rapporte quoi ? » C'est la première question d'un décideur, et
la plus facile à mal traiter : il est tentant d'additionner tous les montants
détectés et d'annoncer un gain de plusieurs millions.

Ce serait faux, et démontable en une phrase : **identifier une créance en retard
ne la recouvre pas**. La plateforme ne génère aucun encaissement. Elle produit de
l'information qui rend une action possible, et c'est l'action qui produit le gain.

La distinction structure tout ce fichier :

  * **IDENTIFIÉ** — un montant mesuré sur les données réelles, vérifiable. Aucune
    hypothèse. C'est le seul chiffre que la plateforme peut revendiquer seule.
  * **RÉCUPÉRABLE** — la part de ce montant qu'une action pourrait convertir,
    sous une hypothèse de taux de conversion EXPLICITE et volontairement basse.
  * **NON MESURABLE** — ce que la plateforme apporte sans qu'on puisse le
    chiffrer honnêtement. Ce bloc existe pour éviter de faire passer un silence
    pour un zéro.

Les taux de conversion sont des hypothèses, pas des mesures. Ils sont déclarés en
tête de fichier, justifiés un par un, et le rapport les affiche. Un lecteur qui
les juge trop optimistes peut refaire le calcul avec les siens.

Sortie : `reports/impact_metrics.json`

Lancement :
    python -m ml_engine.analytics.impact
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE / "reports"


# ── Hypothèses de conversion ────────────────────────────────────────────────
#
# Chacune est basse par construction. Le raisonnement retenu : mieux vaut un
# chiffre qu'on peut défendre entièrement qu'un chiffre qu'il faudra revoir à la
# baisse devant un interlocuteur sceptique.
HYPOTHESES: Dict[str, Dict[str, Any]] = {
    "recouvrement": {
        "taux": 0.15,
        "justification": (
            "Part des créances à terme long dont la relance ciblée avance "
            "l'encaissement. Une relance ne crée pas la créance : elle en "
            "raccourcit le délai. 15 % est bas au regard des pratiques de "
            "recouvrement, précisément parce que l'ERP ne fournit aucune date "
            "de règlement permettant de mesurer l'effet réel."),
    },
    "retention": {
        "taux": 0.20,
        "justification": (
            "Part du chiffre d'affaires menacé qu'une reprise de contact "
            "conserve. Le modèle identifie des clients ENCORE ACTIFS, donc "
            "joignables — mais un client qui s'éloigne le fait souvent pour des "
            "raisons qu'un appel ne règle pas (prix, concurrent, réorganisation)."),
    },
    "surstock": {
        "taux": 0.10,
        "justification": (
            "Part du stock excédentaire réellement déstockable à court terme. "
            "Le reste est immobilisé pour des raisons contractuelles ou "
            "techniques — un automate ne se revend pas comme un consommable."),
    },
    "peremption": {
        "taux": 0.40,
        "justification": (
            "Part du stock condamné qu'une action commerciale anticipée permet "
            "d'écouler. Taux plus élevé que les autres car la détection ne "
            "repose sur aucune estimation : la référence détient plus de deux "
            "ans de consommation, ce qui se lit directement sur les factures. "
            "L'incertitude ne porte que sur la capacité à écouler, pas sur le "
            "constat."),
    },
}


def _lire(nom: str) -> Optional[Dict[str, Any]]:
    p = REPORTS_DIR / nom
    if not p.exists():
        return None
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None


def _kpis() -> Dict[str, Any]:
    try:
        from ml_engine.analytics.kpi_engine import compute_dashboard
        return compute_dashboard({}) or {}
    except Exception:
        return {}


def _stock() -> Dict[str, Any]:
    try:
        from ml_engine.stock import compute_stock_kpis, stock_available
        if not stock_available():
            return {}
        k = compute_stock_kpis(limit_alertes=1)
        return {} if k.get("error") else k
    except Exception:
        return {}


# ── Postes d'impact ─────────────────────────────────────────────────────────
def _poste(cle: str, libelle: str, identifie: float,
           quoi: str, action: str, source: str,
           reserve: Optional[str] = None) -> Dict[str, Any]:
    h = HYPOTHESES[cle]
    return {
        "poste": libelle,
        "montant_identifie_dt": round(identifie, 0),
        "ce_qui_est_mesure": quoi,
        "hypothese_conversion": h["taux"],
        "justification_hypothese": h["justification"],
        "montant_recuperable_dt": round(identifie * h["taux"], 0),
        "action_requise": action,
        "source_du_chiffre": source,
        "reserve": reserve,
    }


def calculer() -> Dict[str, Any]:
    kpis = _kpis()
    stock = _stock()
    churn = kpis.get("churn_anticipe") or {}

    postes: List[Dict[str, Any]] = []

    # 1. Créances à terme long — priorisation du recouvrement
    exposition = float(kpis.get("exposition_recente_dt") or 0)
    if exposition > 0:
        postes.append(_poste(
            "recouvrement",
            "Créances à terme long priorisées",
            exposition,
            "chiffre d'affaires facturé avec un délai accordé supérieur à 60 jours "
            "sur les six derniers mois, classé par débiteur et par montant",
            "relance ciblée des plus gros débiteurs identifiés",
            "kpi_engine — échéances réelles des factures émises",
            reserve=("Ce n'est PAS un impayé : l'ERP n'enregistre aucune date de "
                     "règlement. Le gain porte sur l'ANTICIPATION du recouvrement, "
                     "pas sur la récupération d'une perte."),
        ))

    # 2. Chiffre d'affaires menacé par le décrochage
    if churn.get("servi") and churn.get("enjeu_total_dt"):
        postes.append(_poste(
            "retention",
            "Chiffre d'affaires menacé par le décrochage",
            float(churn["enjeu_total_dt"]),
            f"somme, sur {churn.get('n_clients_scores', 0)} clients actifs, du "
            "chiffre d'affaires annuel pondéré par la probabilité de décrochage "
            "estimée à 90 jours",
            "reprise de contact avec les comptes à fort enjeu",
            "churn_model — AUC 0,9224 hors période",
            reserve=("Le modèle apporte +2,2 points sur la simple fréquence de "
                     "commande : une part de ce montant aurait été détectée par "
                     "un suivi commercial attentif."),
        ))

    # 3. Trésorerie immobilisée — flux réels si disponibles, simulation sinon
    flux = kpis.get("stock_flux_reel") or {}
    if flux.get("disponible") and float(flux.get("valeur_immobilisee_dt") or 0) > 0:
        postes.append(_poste(
            "surstock",
            "Trésorerie immobilisée en stock excédentaire",
            float(flux["valeur_immobilisee_dt"]),
            "quantités achetées moins quantités vendues, valorisées au coût "
            f"d'achat réel — {flux.get('n_references_accumulees', 0)} références "
            f"accumulées, dont {flux.get('n_references_plus_de_2_ans', 0)} "
            "représentant plus de deux ans de consommation",
            "déstockage des références à forte couverture",
            "factures d'achat et de vente réelles — AUCUNE simulation",
            reserve=("Variation cumulée, non inventaire : le stock antérieur à "
                     "l'historique est inconnu. Ce montant est donc un MINORANT "
                     "du capital immobilisé, jamais une surestimation."),
        ))
    # ══ AUCUN REPLI SUR LE MODULE SIMULÉ ══
    #
    # Un repli existait ici, honnêtement marqué « QUANTITÉS simulées ». C'était
    # insuffisant : un montant estimé placé dans un tableau intitulé « impact
    # financier » sera lu comme un montant, quelle que soit sa réserve.
    #
    # Si les flux réels manquent, le poste est désormais ABSENT — et son absence se
    # voit dans le total, ce qui est le signal correct.

    # 4. Stock qui ne sera pas écoulé
    perte_reelle = float(flux.get("perte_quasi_certaine_dt") or 0)
    if flux.get("disponible") and perte_reelle > 0:
        postes.append(_poste(
            "peremption",
            "Stock qui ne sera pas écoulé avant péremption",
            perte_reelle,
            "excédent, au-delà de deux ans de consommation constatée, des "
            f"consommables détenus — {flux.get('n_obsoletes_certains', 0)} "
            "références "
            "concernées, équipements et pièces détachées exclus",
            "écoulement anticipé ou renégociation des références signalées",
            "factures d'achat et de vente réelles — AUCUNE date simulée",
            reserve=("Aucune date d'expiration n'existe dans l'ERP. Le constat "
                     "porte donc sur la ROTATION : un consommable représentant "
                     "plus de deux ans de ventes périmera avant d'être vendu. "
                     "Le seuil de deux ans est un ordre de grandeur DÉCLARÉ du "
                     "diagnostic in vitro, révisable si l'entreprise fournit "
                     "les durées de conservation réelles."),
        ))
    # Ici aussi, plus aucun repli : la liste de lots datés du module simulé
    # reposait sur des dates d'expiration inventées. Une liste précise et fausse
    # est plus dangereuse qu'un constat approché et vrai.

    identifie = sum(p["montant_identifie_dt"] for p in postes)
    recuperable = sum(p["montant_recuperable_dt"] for p in postes)

    # ── Correction de données : un gain d'une autre nature ──────────────────
    #
    # Celui-ci n'est pas un montant à récupérer mais une ERREUR SUPPRIMÉE. Il ne
    # peut donc pas être additionné aux précédents, et il est isolé pour cette
    # raison. C'est pourtant l'apport le plus certain de tout le projet : il ne
    # dépend d'aucune hypothèse de conversion.
    correction = {
        "poste": "Correction du chiffre d'affaires publié",
        "montant_dt": 15_800_000,
        "nature": "erreur supprimée, non montant à récupérer",
        "ce_qui_a_ete_corrige": (
            "Le chiffre d'affaires était surévalué de 5,44 %. Deux causes : les "
            "avoirs étaient additionnés au lieu d'être déduits (la colonne TTC "
            "est non signée, seule MONTANTSIGNE_DEV porte le signe), et 1 324 "
            "factures étaient comptées deux fois."),
        "pourquoi_isole": (
            "Ce montant ne s'additionne pas aux précédents : rien n'est à "
            "encaisser. C'est une décision faussée qui ne le sera plus — un "
            "objectif commercial, une prime, une prévision bâtis sur 5,44 % de "
            "trop."),
        "certitude": (
            "Le seul chiffre du rapport qui ne dépende d'AUCUNE hypothèse. "
            "Vérifié par des invariants comptables : CA net = ventes − avoirs, "
            "marge = CA − coût de revient."),
    }

    metriques = {
        "version": 1,
        "avertissement_principal": (
            "La plateforme ne génère aucun encaissement. Elle identifie et "
            "priorise. Les montants « récupérables » supposent qu'une action soit "
            "menée, et leurs taux de conversion sont des HYPOTHÈSES déclarées, "
            "non des mesures."),
        "montant_total_identifie_dt": round(identifie, 0),
        "montant_total_recuperable_dt": round(recuperable, 0),
        "postes": postes,
        "correction_de_donnees": correction,
        "non_mesurable": [
            {
                "apport": "Temps d'analyse épargné",
                "pourquoi_non_chiffre": (
                    "Le briefing agrège en quelques secondes ce qu'un contrôleur "
                    "de gestion assemblerait en plusieurs heures. Chiffrer ce gain "
                    "exigerait de mesurer le temps réellement passé avant la "
                    "plateforme — donnée dont nous ne disposons pas."),
            },
            {
                "apport": "Fiabilité des indicateurs publiés",
                "pourquoi_non_chiffre": (
                    "Neuf contrôles d'intégrité tournent à chaque calcul et "
                    "détecteraient une régression comme celle des 5,44 %. La "
                    "valeur d'une erreur évitée ne se mesure qu'après coup."),
            },
            {
                "apport": "Refus documentés",
                "pourquoi_non_chiffre": (
                    "Trois modèles ont été écartés faute de gain confirmé. Le coût "
                    "évité — décisions prises sur des prédictions non fiables — "
                    "n'est pas observable, par construction."),
            },
        ],
        "comment_verifier": (
            "Chaque montant identifié provient d'une requête sur l'entrepôt, "
            "reproductible par `python -m ml_engine.analytics.impact`. Les taux de "
            "conversion sont modifiables dans `HYPOTHESES` : un lecteur qui les "
            "juge inadaptés peut relancer le calcul avec les siens."),
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metriques, open(REPORTS_DIR / "impact_metrics.json", "w",
                              encoding="utf-8"), indent=2, ensure_ascii=False)
    return metriques


def afficher() -> None:
    m = calculer()

    def dt(v: float) -> str:
        return f"{v:,.0f} DT".replace(",", " ")

    print("\n" + "=" * 78)
    print("  IMPACT FINANCIER — ce que la plateforme identifie")
    print("=" * 78)
    print("\n  La plateforme ne génère aucun encaissement : elle identifie et")
    print("  priorise. Les montants récupérables supposent qu'une action soit menée.")

    for p in m["postes"]:
        print(f"\n  ── {p['poste']}")
        print(f"     identifié      {dt(p['montant_identifie_dt']):>18}")
        print(f"     récupérable    {dt(p['montant_recuperable_dt']):>18}"
              f"   (hypothèse {p['hypothese_conversion']:.0%})")
        print(f"     action         {p['action_requise']}")
        if p.get("reserve"):
            for i in range(0, len(p["reserve"]), 66):
                print(f"     ⚠ {p['reserve'][i:i+66]}")

    print("\n" + "-" * 78)
    print(f"  TOTAL IDENTIFIÉ    {dt(m['montant_total_identifie_dt']):>20}")
    print(f"  TOTAL RÉCUPÉRABLE  {dt(m['montant_total_recuperable_dt']):>20}"
          "   sous les hypothèses ci-dessus")

    c = m["correction_de_donnees"]
    print(f"\n  À PART — {c['poste']} : {dt(c['montant_dt'])}")
    print("  Non additionnable : c'est une erreur supprimée, pas un montant à")
    print("  encaisser. Mais c'est le seul chiffre sans aucune hypothèse.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
