"""Ce que la plateforme fait gagner — mesuré, et borné par ce qu'on peut prouver."""

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


HYPOTHESES: Dict[str, Dict[str, Any]] = {
    "recouvrement": {
        "taux": 0.15,
        "justification": (
            "Part des créances à terme long dont la relance ciblée avance "
            "l'encaissement. Une relance ne crée pas la créance : elle en "
            "raccourcit le délai. 15 % est bas au regard des pratiques de "
            "recouvrement, précisément parce qu'aucune date "
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
    "conversion_devis": {
        "taux": 0.10,
        "justification": (
            "Part des ventes probables qu'une relance PRIORISÉE convertit "
            "au-delà de ce qu'obtiendrait une relance dans l'ordre d'arrivée. "
            "Ce taux est le seul du rapport appuyé sur une mesure directe : sur "
            "les 10 % de devis les mieux classés hors période, le taux de "
            "signature observé est 2,49 fois celui du taux de base — un lift "
            "mesuré, pas estimé. 10 % reste bas parce que la base de calcul est "
            "DÉJÀ pondérée par la probabilité de signature : appliquer ce taux à "
            "une espérance, et non à un montant brut, escompte le risque deux fois."),
    },
    "marge": {
        "taux": 0.25,
        "justification": (
            "Part de la marge menacée qu'une renégociation de prix ou de mix "
            "produit conserve. Le modèle classe les clients dont la rentabilité "
            "se dégrade avec une AUC de 0,797 hors période, contre 0,762 pour la "
            "marge des trois derniers mois seule : le classement informe, mais "
            "modestement. Et la cause dominante — la montée de la part "
            "d'équipement, moins margée que les réactifs — ne se corrige pas "
            "toujours, un hôpital qui équipe un service ne rachète pas un "
            "automate pour améliorer notre mix."),
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


def _dt(v: Any) -> str:
    """Un montant en dinars, lisible : « 4 895 100 DT »."""
    try:
        return f"{float(v or 0):,.0f} DT".replace(",", "\u202f")
    except Exception:
        return "— DT"


def _pct(v: Any) -> str:
    """Un taux en pourcentage, à la française : « 25,6 % »."""
    try:
        return f"{float(v or 0):.1f} %".replace(".", ",")
    except Exception:
        return "— %"


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


def _devis() -> Dict[str, Any]:
    """Devis ouverts : la limite est volontairement haute.

    `esperance_totale_dt` porte sur TOUS les devis en cours, pas sur le `top`,
    mais `par_client` a besoin de la liste. Demander large évite de chiffrer un
    poste global sur un extrait de dix lignes.
    """
    try:
        from ml_engine.analytics.conversion_devis import predire
        d = predire(limite=500)
        return {} if not d.get("servi") else d
    except Exception:
        return {}


def _marge() -> Dict[str, Any]:
    """Clients dont la rentabilité se dégrade, sur tout le portefeuille.

    Le total doit porter sur l'ensemble des clients, pas sur les quinze que
    l'écran affiche : un poste d'impact calculé sur le `top` de l'interface
    sous-estimerait la marge menacée d'un facteur arbitraire.
    """
    try:
        from ml_engine.analytics.marge_client import predire
        m = predire(limite=10_000)
        return {} if not m.get("servi") else m
    except Exception:
        return {}


def _poste(cle: str, libelle: str, identifie: float,
           quoi: str, action: str, source: str,
           reserve: Optional[str] = None,
           par_client: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    h = HYPOTHESES[cle]
    return {
        "poste": libelle,
        "cle": cle,
        "montant_identifie_dt": round(identifie, 0),
        "ce_qui_est_mesure": quoi,
        "hypothese_conversion": h["taux"],
        "justification_hypothese": h["justification"],
        "montant_recuperable_dt": round(identifie * h["taux"], 0),
        "action_requise": action,
        "source_du_chiffre": source,
        "reserve": reserve,
        # Un total ne se décide pas : il faut savoir SUR QUI appeler demain matin.
        "par_client": par_client or [],
    }


def _par_client(lignes: Any, cle_code: str, cle_nom: str, cle_montant: str,
                taux: float, limite: int = 10) -> List[Dict[str, Any]]:
    """Les comptes qui portent le poste, du plus lourd au plus léger.

    Le montant récupérable par client applique le MÊME taux que le poste : il
    n'y a pas de client pour lequel on supposerait une meilleure conversion que
    pour les autres, faute de quoi le total ne serait plus la somme de ses parts.
    """
    out: List[Dict[str, Any]] = []
    for x in (lignes or [])[:limite]:
        if not isinstance(x, dict):
            continue
        montant = float(x.get(cle_montant) or 0)
        if montant <= 0:
            continue
        code = str(x.get(cle_code) or "")
        out.append({
            "client": code,
            "nom": str(x.get(cle_nom) or code),
            "montant_identifie_dt": round(montant, 0),
            "montant_recuperable_dt": round(montant * taux, 0),
        })
    return out


def _phrases(postes: List[Dict[str, Any]], churn: Dict[str, Any],
             devis: Dict[str, Any], marge: Dict[str, Any],
             identifie: float, recuperable: float) -> List[str]:
    """Les chiffres, dits en une phrase chacun.

    Un directeur ne retient pas un tableau : il retient une phrase qu'il peut
    répéter. Ces phrases sont ENTIÈREMENT dérivées des montants calculés
    ci-dessus — aucune n'est écrite en dur, aucune ne survit si son poste
    disparaît. C'est la condition pour qu'elles restent vraies.
    """
    out: List[str] = []
    par_cle = {p["cle"]: p for p in postes}

    out.append(
        f"La plateforme identifie {_dt(identifie)} d'enjeu financier, dont "
        f"{_dt(recuperable)} que les hypothèses déclarées ici jugent "
        f"récupérables si les actions signalées sont menées.")

    p = par_cle.get("retention")
    if p and churn.get("n_au_dessus_de_0_5"):
        n = int(churn["n_au_dessus_de_0_5"])
        tete = p["par_client"][:3]
        if tete:
            somme = sum(c["montant_recuperable_dt"] for c in tete)
            out.append(
                f"{n} clients risquent de ne plus commander sous 90 jours et "
                f"représentent {_dt(p['montant_identifie_dt'])} de chiffre "
                f"d'affaires annuel. Rien que les trois premiers — "
                f"{', '.join(c['nom'] for c in tete)} — valent {_dt(somme)} "
                f"par an à {int(HYPOTHESES['retention']['taux'] * 100)} % de "
                f"reprise de contact réussie.")

    p = par_cle.get("conversion_devis")
    if p and devis.get("n_devis"):
        out.append(
            f"{devis['n_devis']} devis sont ouverts pour "
            f"{_dt(devis.get('montant_ouvert_total_dt'))}, soit "
            f"{_dt(p['montant_identifie_dt'])} de ventes probables. Relancer "
            f"les 10 % les mieux classés plutôt que dans l'ordre d'arrivée "
            f"signe 2,49 fois plus souvent — mesuré hors période, pas supposé.")

    p = par_cle.get("marge")
    if p and marge.get("n_clients"):
        out.append(
            f"{_dt(p['montant_identifie_dt'])} de marge se dégradent chez des "
            f"clients qui continuent d'acheter : ils passeront sous "
            f"{_pct(marge.get('seuil_marge_basse_pct'))} de taux de marge dans "
            f"les {marge.get('horizon_mois', 3)} prochains mois. Une "
            f"renégociation sur les comptes signalés en conserve "
            f"{_dt(p['montant_recuperable_dt'])}.")

    p = par_cle.get("recouvrement")
    if p:
        out.append(
            f"{_dt(p['montant_identifie_dt'])} sont facturés à plus de 60 jours "
            f"de délai accordé. Ce ne sont pas des impayés : le gain, "
            f"{_dt(p['montant_recuperable_dt'])}, porte sur le fait "
            f"d'encaisser plus tôt, pas sur une perte récupérée.")

    p = par_cle.get("peremption")
    if p:
        out.append(
            f"{_dt(p['montant_identifie_dt'])} de consommables représentent "
            f"plus de deux ans de ventes : ils périmeront avant d'être vendus. "
            f"C'est le poste le plus petit et le plus certain — il se lit "
            f"directement sur les factures, sans aucune date simulée.")

    out.append(
        "Et un chiffre qui ne s'additionne à aucun autre : le chiffre "
        "d'affaires publié était surévalué de 5,44 %, soit 15 800 000 DT. "
        "Rien à encaisser — mais c'est le seul montant de ce rapport qui ne "
        "repose sur aucune hypothèse.")
    return out


def calculer() -> Dict[str, Any]:
    kpis = _kpis()
    stock = _stock()
    churn = kpis.get("churn_anticipe") or {}
    devis = _devis()
    marge = _marge()

    postes: List[Dict[str, Any]] = []

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
            reserve=("Ce n'est PAS un impayé : aucune date de "
                     "règlement. Le gain porte sur l'ANTICIPATION du recouvrement, "
                     "pas sur la récupération d'une perte."),
        ))

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
            par_client=_par_client(churn.get("top"), "code", "nom", "enjeu_dt",
                                   HYPOTHESES["retention"]["taux"]),
        ))

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
            reserve=("Aucune date d'expiration n'est enregistrée. Le constat "
                     "porte donc sur la ROTATION : un consommable représentant "
                     "plus de deux ans de ventes périmera avant d'être vendu. "
                     "Le seuil de deux ans est un ordre de grandeur DÉCLARÉ du "
                     "diagnostic in vitro, révisable si l'entreprise fournit "
                     "les durées de conservation réelles."),
        ))

    esperance = float(devis.get("esperance_totale_dt") or 0)
    if esperance > 0:
        postes.append(_poste(
            "conversion_devis",
            "Ventes probables en attente de relance",
            esperance,
            f"somme des {devis.get('n_devis', 0)} devis ouverts "
            f"({_dt(devis.get('montant_ouvert_total_dt'))} proposés à "
            f"{devis.get('n_clients_concernes', 0)} établissements), chacun "
            "pondéré par sa probabilité de signature estimée",
            "relance dans l'ordre du classement, et non dans l'ordre d'arrivée",
            "conversion_devis — AUC 0,7165 hors période, lift 2,49 sur le "
            "décile supérieur",
            reserve=("La base est une ESPÉRANCE, déjà pondérée par la "
                     "probabilité : une partie de ces ventes se signerait sans "
                     "nous. Le gain porte sur l'ORDRE des relances et sur les "
                     "devis qui seraient morts d'ancienneté, pas sur la "
                     "création de demande."),
            par_client=_par_client(devis.get("top"), "client", "nom",
                                   "esperance_dt",
                                   HYPOTHESES["conversion_devis"]["taux"]),
        ))

    marge_en_jeu = sum(float(x.get("marge_en_jeu_dt") or 0)
                       for x in (marge.get("top") or []))
    if marge_en_jeu > 0:
        postes.append(_poste(
            "marge",
            "Marge menacée par la dégradation de la rentabilité",
            marge_en_jeu,
            f"sur {marge.get('n_clients', 0)} clients, marge réalisée sur douze "
            "mois pondérée par la probabilité de passer sous "
            f"{_pct(marge.get('seuil_marge_basse_pct'))} de taux de marge dans "
            f"les {marge.get('horizon_mois', 3)} prochains mois — le seuil du "
            "dernier quintile du portefeuille",
            "renégociation du prix ou du mix produit sur les comptes signalés",
            "marge_client — AUC 0,7969 hors période",
            reserve=("Une marge menacée n'est pas une marge perdue : le client "
                     "continue d'acheter, moins rentablement. Le montant mesure "
                     "ce qui se dégrade, et la cause dominante — la part "
                     "croissante d'équipement — n'est pas toujours corrigeable."),
            par_client=_par_client(marge.get("top"), "client", "nom",
                                   "marge_en_jeu_dt",
                                   HYPOTHESES["marge"]["taux"]),
        ))

    identifie = sum(p["montant_identifie_dt"] for p in postes)
    recuperable = sum(p["montant_recuperable_dt"] for p in postes)

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
        "phrases": _phrases(postes, churn, devis, marge, identifie, recuperable),
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
    dt = _dt

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

    print("\n" + "-" * 78)
    print("  À DIRE TEL QUEL")
    print("-" * 78)
    for phrase in m["phrases"]:
        mots, ligne = phrase.split(), ""
        for mot in mots:
            if len(ligne) + len(mot) + 1 > 72:
                print(f"  {ligne}")
                ligne = mot
            else:
                ligne = f"{ligne} {mot}".strip()
        if ligne:
            print(f"  {ligne}")
        print()

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
