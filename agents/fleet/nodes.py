"""Agents (nœuds) de la flotte."""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .delegation import (POSTE_COMMERCIAL, POSTE_LOGISTIQUE, POSTE_RECOUVREMENT,
                         domaine_designe, execution, execution_multi_signaux)

logger = logging.getLogger("fleet")

DECISION_DE_DIRECTION = None


def _pourquoi(lignes: List[Dict[str, Any]], cle_nom: str = "nom",
              n: int = 2) -> List[Dict[str, Any]]:
    """Reprend, pour les premières entités citées, les raisons produites par le modèle qui les a signalées."""
    sortie: List[Dict[str, Any]] = []
    for ligne in lignes[:n]:
        raisons = [r for r in (ligne.get("raisons") or [])
                   if r.get("sens") in (None, "aggrave", "favorise")][:3]
        if not raisons:
            continue
        sortie.append({
            "sujet": str(ligne.get(cle_nom) or ligne.get("code")
                         or ligne.get("client") or ligne.get("produit") or "").strip(),
            "raisons": [r.get("explication") for r in raisons if r.get("explication")],
        })
    return sortie


def _fmt(v: Any, suffix: str = "DT") -> str:
    if v is None:
        return "N/D"
    try:
        v = float(v)
    except Exception:
        return str(v)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f} M {suffix}"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f} K {suffix}"
    return f"{v:.0f} {suffix}"


N_CIBLES = 10


def _cible(nom: Any, montant: Any, motif: str, type_action: str, titre: str,
           code: Any = None) -> Dict[str, Any]:
    """Une ligne actionnable d'un constat : QUI, COMBIEN, POURQUOI, et la tâche exacte
    à confier. Le directeur confie une ligne, pas une carte entière."""
    return {"nom": str(nom or code or "").strip(), "code": str(code or "") or None,
            "montant_dt": round(float(montant or 0), 0), "motif": motif,
            "tache": {"type": type_action, "titre": titre[:200]}}


def _devis_par_client(devis: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Un client qui a plusieurs devis ouverts = UNE ligne, UNE tâche : deux
    commerciaux ne doivent pas appeler le même établissement le même jour."""
    groupes: Dict[str, List[Dict[str, Any]]] = {}
    for d in devis:
        groupes.setdefault(str(d.get("client") or d.get("code") or d.get("nom")), []).append(d)
    lignes = []
    for code, ds in groupes.items():
        nom = ds[0].get("nom") or code
        esperance = sum(float(d.get("esperance_dt") or 0) for d in ds)
        pieces = ", ".join(str(d.get("piece_no") or "") for d in ds)
        if len(ds) == 1:
            d = ds[0]
            motif = (f"devis {d.get('piece_no', '')} de {_fmt(d.get('montant_ht_dt'))} HT, "
                     f"signature probable à {float(d.get('probabilite') or 0):.0%}")
            titre = f"Relancer {nom} sur le devis {pieces} ({_fmt(d.get('montant_ht_dt'))} HT)"
        else:
            total_ht = sum(float(d.get("montant_ht_dt") or 0) for d in ds)
            motif = f"{len(ds)} devis ouverts ({pieces}), {_fmt(total_ht)} HT au total"
            titre = f"Relancer {nom} sur ses {len(ds)} devis ouverts ({_fmt(total_ht)} HT)"
        lignes.append(_cible(nom, esperance, motif, "relance_devis", titre, code=code))
    return sorted(lignes, key=lambda x: -x["montant_dt"])


def _log(agent: str, status: str, detail: str = "") -> Dict[str, Any]:
    return {"agent": agent, "status": status, "detail": detail}


def _safe_node(label: str) -> Callable:
    """Décorateur de robustesse : AUCUN agent ne doit faire planter le briefing."""
    def deco(fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
            try:
                return fn(state)
            except Exception as e:  # pragma: no cover - filet de sécurité
                logger.exception("Nœud %s en erreur", label)
                return {"trace": [_log(label, "erreur", f"{type(e).__name__}: {e}")]}
        return wrapper
    return deco


@_safe_node("🗄️ Collecte interne (facturation)")
def collecte_interne(state: Dict[str, Any]) -> Dict[str, Any]:
    """Agent Données : calcule les KPIs internes depuis l'entrepôt DuckDB."""
    filters = state.get("filters") or {}
    kpis: Dict[str, Any] = {}
    try:
        from ml_engine.analytics.kpi_engine import compute_dashboard
        kpis = compute_dashboard(filters) or {}
        detail = f"{len(kpis)} indicateurs calculés"
        status = "ok"
    except Exception as e:  # pragma: no cover
        detail = f"erreur: {e}"
        status = "erreur"
    return {"kpis": kpis, "trace": [_log("🗄️ Collecte interne (facturation)", status, detail)]}


def _portee(state: Dict[str, Any]) -> Dict[str, Any]:
    """Règle de portée des filtres sur les modèles (voir ml_engine.portee)."""
    from ml_engine import portee as po
    return po.portee(state.get("filters") or {})


def _perimetre(state: Dict[str, Any]) -> List[str]:
    """Codes clients retenus par le filtre client ou fidélité (vide = tout le portefeuille)."""
    return list(_portee(state).get("clients") or [])


def _analyses_globales(state: Dict[str, Any]) -> bool:
    """Stock, fournisseurs, échéancier : seulement sans aucun filtre de périmètre."""
    from ml_engine import portee as po
    return _portee(state)["mode"] == po.GLOBAL


def _nom(noms: Dict[str, str], code: Any) -> str:
    return str(noms.get(str(code), code) or code)


@_safe_node("🧠 Collecte modèles (registre)")
def collecte_modeles(state: Dict[str, Any]) -> Dict[str, Any]:
    """Interroge chaque modèle du projet par la passerelle — une seule fois par briefing.

    La règle de portée des filtres décide de ce qui est interrogé : rien de
    prédictif sous un filtre de période ou de facture ; les modèles par client,
    restreints, sous un filtre client ou fidélité ; tout, sans filtre."""
    from ml_engine import passerelle as pw
    from ml_engine import portee as po

    p = _portee(state)
    label = "🧠 Collecte modèles (registre)"
    if p["mode"] == po.MASQUE:
        return {"modeles": {"perimetre_client": [], "portee": p,
                            "derive": pw.derive(), "tableau": pw.tableau_des_modeles()},
                "trace": [_log(label, "vide", "prévisions masquées : " + p["motif"][:80])]}

    kpis = state.get("kpis") or {}
    clients = p["clients"]
    perimetre = set(clients or [])
    noms = pw.noms_clients()
    m: Dict[str, Any] = {"perimetre_client": sorted(perimetre), "portee": p}

    def _depuis_kpis(cle: str, nom_modele: str, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        v = kpis.get(cle)
        if isinstance(v, dict) and "servi" in v and not v.get("masque"):
            return {**v, "modele": pw.carte_modele(nom_modele)}
        return fn()

    def _nommer(liste: List[Dict[str, Any]], cle: str = "client") -> List[Dict[str, Any]]:
        out = []
        for e in liste or []:
            code = str(e.get(cle) or e.get("code") or "")
            if clients is not None and code not in perimetre:
                continue
            out.append({**e, "code": code, "nom": e.get("nom") or _nom(noms, code)})
        return out

    def _nommer_sortie(d: Dict[str, Any], cle: str = "client") -> Dict[str, Any]:
        return {**d, "top": _nommer(d["top"], cle)} if d.get("top") else d

    m["decrochage"] = _nommer_sortie(_depuis_kpis(
        "churn_anticipe", "churn", lambda: pw.decrochage(kpis=kpis, clients=clients)), "code")
    m["conversion_devis"] = _nommer_sortie(_depuis_kpis(
        "conversion_devis", "conversion_devis", lambda: pw.conversion_devis(clients=clients)))
    m["marge_client"] = _nommer_sortie(_depuis_kpis(
        "marge_client", "marge_client", lambda: pw.marge_clients(clients=clients)))
    m["recommandation"] = _nommer_sortie(pw.recommandations(clients=clients))
    m["ca_client_3m"] = _nommer_sortie(pw.ca_client(horizon=3, limite=15, clients=clients))
    m["ca_client_12m"] = pw.ca_client(horizon=12, limite=15, clients=clients)

    seg = pw.segments_clients()
    if clients is not None and seg.get("par_client"):
        seg = {**seg, "par_client": {c: v for c, v in seg["par_client"].items() if c in perimetre}}
    m["segmentation"] = seg

    credit = pw.conditions_credit()
    if credit.get("scores"):
        credit = {**credit, "scores": {c: v for c, v in credit["scores"].items()
                                       if clients is None or c in perimetre}}
    m["credit"] = credit

    if p["mode"] == po.GLOBAL:
        reappro_kpis = kpis.get("reappro")
        m["reappro"] = ({**reappro_kpis, "modele": pw.carte_modele("reappro"), "source": "modele"}
                        if isinstance(reappro_kpis, dict) and reappro_kpis.get("servi")
                        else pw.reapprovisionnement())
        m["fin_de_vie"] = pw.fin_de_vie()
        m["risque_stock"] = pw.risque_stock()
        m["demande_reference"] = pw.demande_par_reference()
        m["echeancier"] = pw.echeancier_1_mois()
        m["derive"] = pw.derive()
        m["tableau"] = pw.tableau_des_modeles()

    servis = sum(1 for v in m.values()
                 if isinstance(v, dict) and (v.get("modele") or {}).get("servi"))
    return {"modeles": m,
            "trace": [_log(label, "ok",
                           f"{servis} module(s) servi(s) interrogé(s) par la passerelle"
                           + (f" · {len(perimetre)} client(s) filtré(s)" if clients is not None else ""))]}


def _modeles(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.get("modeles") or {}


def _usage(sortie: Dict[str, Any], role: str) -> Dict[str, Any]:
    from ml_engine.passerelle import trace_modele
    return trace_modele(sortie.get("modele") or {}, role)


@_safe_node("📋 Agent Recouvrement")
def agent_recouvrement(state: Dict[str, Any]) -> Dict[str, Any]:
    kpis = state.get("kpis") or {}
    risque = kpis.get("clients_relance") or kpis.get("clients_a_risque") or []
    top = risque[:3]
    cibles = risque[:N_CIBLES]
    expo = kpis.get("exposition_recente_dt")
    crit = kpis.get("exposition_recente_critique_dt")
    noms = ", ".join((c.get("nom") or c.get("client")) for c in top) or "vos principaux débiteurs"
    finding = {
        "agent": "Recouvrement",
        "categorie": "Recouvrement",
        "severite": "haute" if float(crit or 0) > 0 else "moyenne",
        "titre": "Créances à relancer en priorité",
        "resume": f"{_fmt(expo)} à plus de 60 jours, dont {_fmt(crit)} à plus de 90 jours",
        "montant_dt": round(float(expo or 0), 0),
        "constat": (f"{_fmt(expo)} de factures en retard de plus de 60 jours, "
                    f"dont {_fmt(crit)} au-delà de 90 jours."),
        "action": f"Relancer en priorité : {noms} (appel + relance écrite, échéancier si >90j).",
        "execution": execution(POSTE_RECOUVREMENT, "appel"),
        "clients_concernes": [
            _cible(c.get("nom") or c.get("client"), c.get("montant_risque"),
                   f"{_fmt(c.get('montant_risque'))} sur {int(c.get('factures') or 0)} facture(s) à plus de 60 j",
                   "appel",
                   f"Appeler {(c.get('nom') or c.get('client') or '').strip()} : "
                   f"{_fmt(c.get('montant_risque'))} de factures à plus de 60 jours",
                   code=c.get("client"))
            for c in cibles if (c.get("nom") or c.get("client"))
        ],
    }

    credit = _modeles(state).get("credit") or {}
    if credit.get("servi") and credit.get("scores"):
        details = []
        for c in top:
            sc = credit["scores"].get(str(c.get("client") or ""))
            if not sc:
                continue
            nom = (c.get("nom") or c.get("client") or "").strip()
            if sc.get("source") == "regle_historique":
                details.append(f"{nom} — délai habituel {float(sc.get('avg_delay') or 0):.0f} j"
                               + (" (conditions longues, pas un défaut)"
                                  if float(sc.get("score") or 0) >= 50 else ""))
            else:
                details.append(f"{nom} — historique trop court, taux de base appliqué")
        if details:
            pass  # credit details kept in modeles_utilises, not in constat
        finding["modeles_utilises"] = [_usage(credit, "conditions de crédit des débiteurs")]
    return {"findings": [finding], "trace": [_log("📋 Agent Recouvrement", "ok", f"{len(risque)} débiteurs récents")]}


@_safe_node("💰 Agent Trésorerie")
def agent_tresorerie(state: Dict[str, Any]) -> Dict[str, Any]:
    """Cycle d'encaissement, et ce que le stock y immobilise."""
    kpis = state.get("kpis") or {}
    dso = float(kpis.get("dso_jours") or 0)
    dpo = float(kpis.get("dpo_jours") or 0)
    expo = float(kpis.get("exposition_recente_dt") or 0)
    ttm = float(kpis.get("ttm_revenue") or 0)
    jours_cycle = dso - dpo

    bfr = (jours_cycle / 365.0) * ttm if ttm > 0 else 0.0

    immo, perte, stock_lu, origine = 0.0, 0.0, False, ""
    flux = ((state.get("kpis") or {}).get("stock_flux_reel") or {}) if _analyses_globales(state) else {}
    if flux.get("disponible") and float(flux.get("valeur_immobilisee_dt") or 0) > 0:
        immo = float(flux["valeur_immobilisee_dt"])
        stock_lu = True
        origine = "reel"

    if flux.get("disponible"):
        perte = float(flux.get("perte_quasi_certaine_dt") or 0)


    constat = (f"DSO {dso:.0f} j, DPO {dpo:.0f} j : {jours_cycle:.0f} jours de CA à financer"
               + (f" ({_fmt(bfr)})" if bfr > 0 else "")
               + f". {_fmt(expo)} de factures dépassent 60 jours.")

    action = ("Aligner les relances sur les creux d'encaissement ; renégocier les "
              "délais fournisseurs tant que le DSO dépasse le DPO.")

    if stock_lu and immo > 0:
        constat += f" {_fmt(immo)} dorment en stock excédentaire."
        action = ("Déstocker les références excédentaires libérerait de la "
                  "trésorerie sans emprunter ni relancer un client. " + action)

    ech = _modeles(state).get("echeancier") or {}
    usages: List[Dict[str, Any]] = []
    if ech.get("servi") and ech.get("montant_exigible_dt"):
        constat += f" {_fmt(ech['montant_exigible_dt'])} de créances exigibles le mois prochain."
        usages.append(_usage(ech, "créances exigibles à un mois"))

    stock_pesant = bool(bfr > 0 and immo > 0.25 * bfr)
    finding = {
        "agent": "Trésorerie",
        "categorie": "Trésorerie",
        "severite": "haute" if (jours_cycle > 0 and stock_pesant) or dso > dpo else "moyenne",
        "titre": "Trésorerie : encaissements et stock dormant",
        "resume": (f"{_fmt(ech.get('montant_exigible_dt'))} à encaisser le mois prochain"
                   if ech.get("servi") and ech.get("montant_exigible_dt")
                   else f"{jours_cycle:.0f} jours de chiffre d'affaires à financer"),
        "montant_dt": round(bfr if bfr > 0 else expo, 0),
        "constat": constat,
        "action": action,
        "execution": DECISION_DE_DIRECTION,
    }
    if usages:
        finding["modeles_utilises"] = usages
    detail = f"cycle {jours_cycle:.0f} j"
    if stock_lu:
        detail += f" · {immo/1e3:.0f} K DT en stock dormant"
    return {"findings": [finding], "trace": [_log("💰 Agent Trésorerie", "ok", detail)]}


@_safe_node("📉 Agent Risque client")
def agent_risque(state: Dict[str, Any]) -> Dict[str, Any]:
    """Deux constats distincts : le décrochage CONSTATÉ et le décrochage ANTICIPÉ."""
    kpis = state.get("kpis") or {}
    findings: List[Dict[str, Any]] = []

    dec = kpis.get("clients_decrochent") or []
    top = dec[:3]
    noms = ", ".join(c.get("nom") for c in top if c.get("nom")) or "aucun"
    findings.append({
        "agent": "Risque client",
        "categorie": "Rétention",
        "severite": "haute" if dec else "faible",
        "titre": "Clients qui ont déjà fortement réduit leurs achats",
        "resume": (f"{len(dec)} client(s) en forte baisse" if dec else "Aucune baisse marquée"),
        "montant_dt": round(sum(float(c.get("ca_prev") or 0) - float(c.get("ca_recent") or 0)
                                for c in dec), 0),
        "constat": (f"{len(dec)} client(s) ont réduit leurs achats de plus de 60 % sur les 90 derniers jours."
                    if dec else "Aucun décrochage marqué détecté."),
        "action": (f"Recontacter d'urgence : {noms} — comprendre la cause avant de "
                   "perdre définitivement le compte."
                   if dec else "Maintenir le suivi commercial habituel."),
        "execution": execution(POSTE_COMMERCIAL, "appel"),
        "clients_concernes": [
            _cible(c.get("nom"), float(c.get("ca_prev") or 0) - float(c.get("ca_recent") or 0),
                   f"achats en baisse de {float(c.get('chute_pct') or 0):.0f} %, "
                   f"inactif depuis {int(c.get('jours_inactif') or 0)} j",
                   "appel",
                   f"Appeler {c.get('nom')} : comprendre la baisse de "
                   f"{float(c.get('chute_pct') or 0):.0f} % de ses achats",
                   code=c.get("code"))
            for c in dec[:N_CIBLES] if c.get("nom")
        ],
    })

    modeles = _modeles(state)
    ch = modeles.get("decrochage") or kpis.get("churn_anticipe") or {}
    seg = modeles.get("segmentation") or {}
    segment_de = {c: v.get("nom_segment") for c, v in (seg.get("par_client") or {}).items()}
    if ch.get("servi") and ch.get("top"):
        cibles = ch["top"][:3]
        def _mot(p: float) -> str:
            return ("très élevé" if p >= 0.7 else "élevé" if p >= 0.5
                    else "modéré" if p >= 0.3 else "faible")

        libelles = " ; ".join(
            f"{c.get('nom') or c.get('code')} "
            f"(risque {_mot(float(c.get('probabilite_decrochage') or 0))}, "
            f"{float(c.get('enjeu_dt') or 0)/1e3:.0f} K DT en jeu"
            + (f", segment « {segment_de[str(c.get('code'))]} »"
               if segment_de.get(str(c.get("code"))) else "")
            + ")"
            for c in cibles)
        findings.append({
            "agent": "Risque client",
            "categorie": "Rétention",
            "severite": ("haute" if (ch.get("n_au_dessus_de_0_5", 0) >= 10
                                     if not modeles.get("perimetre_client")
                                     else any(float(c.get("probabilite_decrochage") or 0) >= 0.5
                                              for c in cibles)) else "moyenne"),
            "titre": "Clients susceptibles de partir dans les 90 jours",
            "resume": (f"{cibles[0].get('nom') or cibles[0].get('code')} en tête · "
                       f"{_fmt(sum(float(c.get('enjeu_dt') or 0) for c in cibles))} en jeu"),
            "montant_dt": round(float(ch.get("enjeu_total_dt") or 0)
                                if not modeles.get("perimetre_client")
                                else sum(float(c.get("enjeu_dt") or 0) for c in cibles), 0),
            "constat": (
                (f"Risque de départ dans les 90 jours : {libelles}."
                 if modeles.get("perimetre_client") else
                 f"{ch.get('n_au_dessus_de_0_5', 0)} client(s) risquent de partir dans les 90 jours. "
                 f"En tête : {libelles}.")),
            "action": ("Relancer en priorité les comptes à fort enjeu : ils sont "
                       "encore actifs, donc récupérables — contrairement à ceux "
                       "déjà en décrochage constaté."),
            "pourquoi": _pourquoi(cibles),
            "execution": execution(POSTE_COMMERCIAL, "appel"),
            "clients_concernes": [
                _cible(c.get("nom") or c.get("code"), c.get("enjeu_dt"),
                       f"risque de départ {_mot(float(c.get('probabilite_decrochage') or 0))}",
                       "appel",
                       f"Appeler {str(c.get('nom') or c.get('code')).strip()} pour le retenir : "
                       f"{_fmt(c.get('enjeu_dt'))} de chiffre d'affaires en jeu",
                       code=c.get("code"))
                for c in ch["top"][:N_CIBLES] if (c.get("nom") or c.get("code"))
            ],
            **({"modeles_utilises": [_usage(ch, "probabilité de décrochage à 90 jours")]
                + ([_usage(seg, "segment de chaque client")] if segment_de else [])}
               if ch.get("modele") else {}),
        })

    segs = [s_ for s_ in (seg.get("segments") or []) if s_.get("part_menacee_pct") is not None]
    if seg.get("servi") and segs and not modeles.get("perimetre_client"):
        pire = max(segs, key=lambda s_: float(s_.get("ca_menace_dt") or 0))
        plus_expose = max(segs, key=lambda s_: float(s_.get("part_menacee_pct") or 0))
        findings.append({
            "agent": "Risque client",
            "categorie": "Rétention",
            "severite": "haute" if float(pire.get("part_menacee_pct") or 0) >= 5 else "moyenne",
            "titre": "Types de clients les plus exposés au départ",
            "resume": f"« {pire.get('nom')} » : {_fmt(pire.get('ca_menace_dt'))} menacés",
            "montant_dt": round(float(pire.get("ca_menace_dt") or 0), 0),
            "constat": (
                f"Le segment « {pire.get('nom')} » concentre {_fmt(pire.get('ca_menace_dt'))} de CA menacé "
                f"({float(pire.get('part_menacee_pct') or 0):.1f} %). "
                f"Le segment « {plus_expose.get('nom')} » a le taux de menace le plus élevé "
                f"({float(plus_expose.get('part_menacee_pct') or 0):.1f} %)."),
            "action": (f"Suivre la RÉGULARITÉ des commandes du segment « {pire.get('nom')} », "
                       "pas seulement son volume : c'est le rythme qui se dérègle "
                       "avant que le chiffre d'affaires ne chute."),
            "execution": DECISION_DE_DIRECTION,
            "modeles_utilises": [_usage(seg, "typologie de clientèle (KMeans)"),
                                 _usage(ch, "part du CA menacée par segment")],
        })

    detail = f"{len(dec)} constaté(s)"
    if ch.get("servi"):
        detail += (f" · {len(ch.get('top') or [])} score(s) du périmètre"
                   if modeles.get("perimetre_client")
                   else f" · {ch.get('n_au_dessus_de_0_5', 0)} anticipé(s)")
    return {"findings": findings,
            "trace": [_log("📉 Agent Risque client", "ok", detail)]}


AGENT_STOCK_APPRO = "Stock & Approvisionnement"
NATURE_STOCK_APPRO = ("déterministe et statistique : arithmétique sur les factures "
                      "et médiane mobile, aucun modèle appris servi")


@_safe_node("📦 Volet fournisseurs")
def constat_approvisionnement(state: Dict[str, Any]) -> Dict[str, Any]:
    """Volet fournisseurs de l'agent Stock & Approvisionnement : dépendance fournisseur (part des…"""
    if not _analyses_globales(state):
        return {"trace": [_log("📦 Volet fournisseurs", "vide",
                               "analyse globale — masquée sous un filtre")]}
    try:
        from ml_engine.analytics.demand_engine import compute_supply_demand
        d = compute_supply_demand()
    except Exception:
        d = {}
    dep = d.get("dependance_fournisseur") or "n/d"
    top = (d.get("fournisseurs_top") or [{}])[0]
    top1_name, top1_pct = top.get("fournisseur", "N/D"), d.get("fournisseur_top1_pct", 0)
    fc = d.get("demande_prevision") or []
    fc_txt = ", ".join(f"{p['period']} : {int(p['qte']):,} articles".replace(",", " ")
                       for p in fc) or "non disponible"
    sev = "haute" if dep in ("critique", "élevée") else "moyenne"
    finding = {
        "agent": AGENT_STOCK_APPRO,
        "domaine": "Approvisionnement",
        "nature_analyse": NATURE_STOCK_APPRO,
        "categorie": "Approvisionnement",
        "severite": sev,
        "titre": "Dépendance à un fournisseur",
        "resume": f"{top1_name} représente {top1_pct} % de vos achats",
        "montant_dt": 0,
        "constat": (f"Dépendance {dep} : {top1_name} représente {top1_pct} % des achats. "
                    f"Volumes attendus à 3 mois : {fc_txt}."),
        "action": ("Sécuriser une 2e source d'approvisionnement pour réduire la dépendance ; "
                   "caler les commandes sur la prévision et anticiper les pics saisonniers."),
        "execution": DECISION_DE_DIRECTION,
    }

    modeles = _modeles(state)
    usages: List[Dict[str, Any]] = []
    if modeles:
        from ml_engine.passerelle import carte_modele
        usages.append(_usage({"modele": carte_modele("demande")},
                             "prévision de demande à 3 mois"))
    reappro = modeles.get("reappro") or {}
    if reappro.get("servi") and reappro.get("top"):
        finding["constat"] += (f" Budget commandes 3 mois : {_fmt(reappro.get('budget_total_dt'))}.")
        usages.append(_usage(reappro, "références à réapprovisionner au trimestre"))
    elif reappro.get("modele"):
        usages.append(_usage(reappro, "écarté — repli sur la détection de rupture"))
    if usages:
        finding["modeles_utilises"] = usages
    return {"findings": [finding],
            "trace": [_log("📦 Volet fournisseurs", "ok", f"dépendance {dep}")]}


@_safe_node("📦 Volet stock")
def constat_stock(state: Dict[str, Any]) -> Dict[str, Any]:
    """Volet stock : immobilisations, ruptures et stock non écoulable — sur données RÉELLES."""
    if not _analyses_globales(state):
        return {"trace": [_log("📦 Volet stock", "vide",
                               "analyse globale — masquée sous un filtre")]}
    flux = (state.get("kpis") or {}).get("stock_flux_reel") or {}
    if not flux.get("disponible"):
        return {"trace": [_log("📦 Volet stock", "vide",
                               f"flux réels indisponibles — "
                               f"{flux.get('motif', 'table absente')}"[:80])]}

    immo = float(flux.get("valeur_immobilisee_dt") or 0)
    perte = float(flux.get("perte_quasi_certaine_dt") or 0)
    n_dormantes = int(flux.get("n_references_plus_de_2_ans") or 0)
    ruptures = flux.get("ruptures") or []
    n_crit = int(flux.get("n_ruptures_critiques") or 0)
    budget = float(flux.get("budget_commandes_dt") or 0)

    noms = ", ".join(r["produit"][:28] for r in ruptures[:3]) or "aucune"

    severite = ("haute" if n_crit > 0
                else "moyenne" if ruptures or perte > 0
                else "faible")

    def _n(v: float) -> str:
        return f"{v:,.0f}".replace(",", " ")

    n_ruptures = int(flux.get("n_ruptures") or len(ruptures))
    constat = f"{_n(immo)} DT immobilisés en stock"
    if n_dormantes:
        constat += f", dont {n_dormantes} référence(s) dormante(s)"
    constat += "."
    if ruptures:
        constat += f" {n_ruptures} rupture(s) dont {n_crit} critique(s)."
    if perte > 0:
        constat += f" {_n(perte)} DT de stock périmé."

    action = ""
    if ruptures:
        action = (f"Commander en priorité : {noms}"
                  + (f" (budget estimé {_n(budget)} DT pour l'ensemble des "
                     f"{n_ruptures} ruptures)" if budget else "") + ". ")
    if perte > 0:
        action += (f"Séparément, écouler ou renégocier les {_n(perte)} DT de "
                   "stock non écoulable — ce sont d'autres références.")
    if not action:
        action = "Aucune action de réapprovisionnement urgente."

    usages: List[Dict[str, Any]] = []
    fdv = _modeles(state).get("fin_de_vie") or {}
    pourquoi_stock: List[Dict[str, Any]] = []
    if fdv.get("servi") and fdv.get("top"):
        cibles = [r for r in fdv["top"] if float(r.get("capital_expose_dt") or 0) > 0][:3]
        if cibles:
            pourquoi_stock = _pourquoi(cibles, cle_nom="produit")
            constat += f" {_fmt(fdv.get('capital_expose_total_dt'))} en fin de vie."
            action += (" Arrêter de réapprovisionner les références en fin de vie : "
                       + ", ".join(r["produit"][:28] for r in cibles) + ".")
            usages.append(_usage(fdv, "références en fin de commercialisation"))
    rs = _modeles(state).get("risque_stock") or {}
    if rs.get("modele") and not rs.get("servi"):
        usages.append(_usage(rs, "NON utilisé — cible dépendant de dates simulées"))

    dem = _modeles(state).get("demande_reference") or {}
    if dem.get("modele"):
        chiffres: List[Tuple[str, float, float]] = []
        if dem.get("servi") and ruptures:
            par_libelle: Dict[str, Dict[str, Any]] = {}
            for ref in dem.get("references") or []:
                for lib in (ref.get("designations") or [ref.get("designation")]):
                    par_libelle[str(lib or "").strip().upper()] = ref
            for r in ruptures[:3]:
                prev = par_libelle.get(str(r.get("produit") or "").strip().upper())
                if not prev:
                    continue
                reste = max(float(r.get("position") or 0), 0.0)
                chiffres.append((str(r["produit"]),
                                 float(prev.get("cumul_3_mois") or 0),
                                 max(float(prev.get("borne_haute_3_mois") or 0) - reste, 0.0)))
        if chiffres:
            pass  # demand details kept in modeles_utilises
            a_commander = [(p_, c) for p_, _, c in chiffres if c >= 1]
            if a_commander:
                action += (" Quantités qui couvrent ces trois mois dans 8 cas sur 10 : "
                           + ", ".join(f"{p_[:28]} {_n(c)}" for p_, c in a_commander) + ".")
            usages.append(_usage(dem, "quantités à commander pour trois mois, par référence"))
        else:
            usages.append(_usage(dem, "consultée — aucune rupture en tête de liste à chiffrer"
                                 if dem.get("servi") else "indisponible — repère de consommation conservé"))

    finding = {
        "agent": AGENT_STOCK_APPRO,
        "domaine": "Stock",
        "nature_analyse": NATURE_STOCK_APPRO,
        "categorie": "Stock",
        "severite": severite,
        "titre": "Stock : ruptures et argent immobilisé",
        "resume": (f"{n_crit} produit(s) en rupture, {_fmt(immo)} immobilisés"
                   if n_crit else f"{_fmt(immo)} immobilisés en stock"),
        "montant_dt": round(immo, 0),
        "constat": constat.strip(),
        "action": action.strip(),
        "execution": execution(POSTE_LOGISTIQUE, "commande" if ruptures else "autre"),
        "is_simulated": False,
        "origine_des_chiffres": ("factures d'achat et de vente — aucune "
                                 "simulation, aucune date inventée"),
        "produits_concernes": [
            # Montant 0 : le budget d'achat n'est pas une part de l'argent
            # immobilisé que chiffre la carte ; il est donné dans le motif.
            _cible(r.get("produit"), 0,
                   f"{_n(float(r.get('quantite_suggeree') or 0))} unités, budget "
                   f"{_fmt(float(r.get('quantite_suggeree') or 0) * float(r.get('cout_unitaire_dt') or 0))}"
                   + (" — rupture imminente" if r.get("gravite") in ("rupture_probable", "critique") else ""),
                   "commande",
                   f"Commander {_n(float(r.get('quantite_suggeree') or 0))} × {str(r.get('produit'))[:60]}")
            for r in sorted(ruptures, key=lambda r: -float(r.get("quantite_suggeree") or 0)
                            * float(r.get("cout_unitaire_dt") or 0))[:N_CIBLES]
            if r.get("produit")
        ],
    }
    if pourquoi_stock:
        finding["pourquoi"] = pourquoi_stock
    if usages:
        finding["modeles_utilises"] = usages
    return {"findings": [finding],
            "trace": [_log("📦 Volet stock", "ok",
                           f"{_n(immo)} DT immobilisés, {n_ruptures} "
                           f"rupture(s) dont {n_crit} critique(s)")]}


@_safe_node("📦 Agent Stock & Approvisionnement")
def agent_stock_approvisionnement(state: Dict[str, Any]) -> Dict[str, Any]:
    """Commander ce qui manque, écouler ce qui dort : un agent, deux volets."""
    label = "📦 Agent Stock & Approvisionnement"
    if not _analyses_globales(state):
        return {"trace": [_log(label, "vide",
                               "analyse globale — masquée sous un filtre")]}
    findings: List[Dict[str, Any]] = []
    statuts: List[str] = []
    details: List[str] = []
    for volet, fn in (("stock", constat_stock), ("fournisseurs", constat_approvisionnement)):
        try:
            out = fn(state) or {}
        except Exception as e:
            logger.exception("Volet %s en erreur", volet)
            out = {"trace": [_log(volet, "erreur", f"{type(e).__name__}: {e}")]}
        findings += out.get("findings") or []
        for t in out.get("trace") or []:
            statuts.append(str(t.get("status")))
            details.append(f"{volet} : {t.get('detail') or t.get('status')}")
    statut = "erreur" if "erreur" in statuts else "ok" if "ok" in statuts else "vide"
    retour: Dict[str, Any] = {"trace": [_log(label, statut, " · ".join(details))]}
    if findings:
        retour["findings"] = findings
    return retour


@_safe_node("🤝 Agent Commercial")
def agent_commercial(state: Dict[str, Any]) -> Dict[str, Any]:
    """Cycle commercial : devis à relancer, marges qui s'érodent, vente croisée."""
    modeles = _modeles(state)
    if not modeles:
        return {"trace": [_log("🤝 Agent Commercial", "vide", "aucun modèle collecté")]}
    findings: List[Dict[str, Any]] = []

    conv = modeles.get("conversion_devis") or {}
    if conv.get("servi") and conv.get("top"):
        top = conv["top"][:3]
        findings.append({
            "agent": "Commercial",
            "categorie": "Commercial",
            "severite": "haute" if float(top[0].get("esperance_dt") or 0) >= 100_000 else "moyenne",
            "titre": "Devis à relancer en priorité",
            "resume": (f"{conv.get('n_devis', 0)} devis ouverts · "
                       f"{_fmt(conv.get('esperance_totale_dt'))} de ventes probables"),
            "montant_dt": round(float(conv.get("esperance_totale_dt") or 0), 0),
            "constat": (
                f"{conv.get('n_devis', 0)} devis ouverts pour {_fmt(conv.get('esperance_totale_dt'))} "
                f"de ventes probables. En tête : "
                + ", ".join(f"{d['nom']} ({_fmt(d['montant_ht_dt'])})" for d in top) + "."),
            "action": ("Relancer d'abord les devis qui rapportent le plus s'ils sont signés, "
                       "plutôt que dans l'ordre d'arrivée."),
            "execution": execution(POSTE_COMMERCIAL, "relance_devis"),
            "pourquoi": _pourquoi(top),
            "clients_concernes": _devis_par_client(conv["top"])[:N_CIBLES],
            "modeles_utilises": [_usage(conv, "probabilité de signature de chaque devis")],
        })

    marge = modeles.get("marge_client") or {}
    if marge.get("servi") and marge.get("top"):
        top = marge["top"][:3]
        en_jeu = sum(float(c.get("marge_en_jeu_dt") or 0) for c in marge["top"])
        findings.append({
            "agent": "Commercial",
            "categorie": "Rentabilité",
            "severite": "haute" if en_jeu >= 200_000 else "moyenne",
            "titre": "Clients dont la rentabilité va baisser",
            "resume": f"{len(marge['top'])} clients · {_fmt(en_jeu)} de marge menacée",
            "montant_dt": round(en_jeu, 0),
            "constat": (
                f"{len(marge['top'])} clients risquent de perdre en rentabilité ({_fmt(en_jeu)} de marge menacée). "
                f"En tête : " + ", ".join(f"{c['nom']}" for c in top) + "."),
            "action": ("Revoir les conditions tarifaires et le mix de ces comptes AVANT "
                       "la prochaine négociation : la baisse n'est pas encore jouée."),
            "execution": execution(POSTE_COMMERCIAL, "visite"),
            "pourquoi": _pourquoi(top),
            "clients_concernes": [
                _cible(c["nom"], c.get("marge_en_jeu_dt"),
                       f"marge actuelle {float(c.get('marge_actuelle_pct') or 0):.1f} % "
                       f"(12 mois : {float(c.get('marge_12m_pct') or 0):.1f} %)",
                       "visite",
                       f"Revoir les prix de {c['nom']} : {_fmt(c.get('marge_en_jeu_dt'))} de marge menacée",
                       code=c.get("client") or c.get("code"))
                for c in marge["top"][:N_CIBLES]],
            "modeles_utilises": [_usage(marge, "probabilité d'érosion de marge")],
        })

    reco = modeles.get("recommandation") or {}
    if reco.get("servi") and reco.get("top"):
        top = reco["top"][:3]
        potentiel = sum(float(c.get("potentiel_top3_dt") or 0) for c in reco["top"][:10])
        findings.append({
            "agent": "Commercial",
            "categorie": "Commercial",
            "severite": "moyenne",
            "titre": "Produits à proposer à vos clients",
            "resume": f"{len(reco['top'])} clients · {_fmt(potentiel)} de potentiel annuel",
            "montant_dt": round(potentiel, 0),
            "constat": (
                f"{len(reco['top'])} clients pourraient adopter de nouveaux produits "
                f"({_fmt(potentiel)} de potentiel annuel). "
                f"En tête : " + ", ".join(f"{c['nom']}" for c in top) + "."),
            "action": ("Présenter ces produits lors de la prochaine visite : ce sont des "
                       "adoptions probables, pas des commandes acquises."),
            "execution": execution(POSTE_COMMERCIAL, "visite"),
            "clients_concernes": [
                _cible(c["nom"], c.get("potentiel_top3_dt"),
                       "à proposer : " + ", ".join(p["designation"][:28] for p in c["produits"][:2]),
                       "visite",
                       f"Proposer à {c['nom']} : "
                       + ", ".join(p["designation"][:28] for p in c["produits"][:2]),
                       code=c.get("client") or c.get("code"))
                for c in reco["top"][:N_CIBLES]],
            "modeles_utilises": [_usage(reco, "classement des produits par client")],
        })

    # ── Chiffre d'affaires attendu par client ────────────────────────────────
    #
    # Le top clients du tableau de bord est un DÉCOMPTE du passé. Ce constat est
    # la seule vue prospective du portefeuille : il dit qui achètera, pas qui a
    # acheté. L'horizon 3 mois porte le constat (c'est celui qui est actionnable
    # sur un trimestre commercial) ; l'horizon 12 mois est cité en appui parce
    # qu'il alimente déjà les mouvements du top 10 sur le radar.
    ca3 = modeles.get("ca_client_3m") or {}
    ca12 = modeles.get("ca_client_12m") or {}
    if ca3.get("servi") and ca3.get("top"):
        top_ca = ca3["top"][:3]
        baisse = [c for c in (ca3.get("top") or [])
                  if float(c.get("ecart_vs_passe_dt") or 0) < 0]
        usages = [_usage(ca3, "chiffre d'affaires attendu par client à 3 mois")]
        if ca12.get("servi"):
            usages.append(_usage(ca12, "classement attendu à 12 mois"))
        findings.append({
            "agent": "Commercial",
            "categorie": "Portefeuille",
            "severite": "haute" if baisse else "moyenne",
            "titre": "Chiffre d'affaires attendu par client (3 mois)",
            "resume": (f"{_fmt(ca3.get('ca_attendu_total_dt'))} attendus sur "
                       f"{ca3.get('n_clients', 0)} clients"),
            # Ce qui est EN JEU, c'est la baisse attendue (ce que la visite peut
            # sauver), pas tout le chiffre d'affaires attendu : sinon la carte
            # annonce un montant que ses lignes ne peuvent jamais additionner.
            "montant_dt": round(sum(abs(float(c.get("ecart_vs_passe_dt") or 0)) for c in baisse)
                                if baisse else float(ca3.get("ca_attendu_total_dt") or 0), 0),
            "constat": (
                f"{_fmt(ca3.get('ca_attendu_total_dt'))} attendus sur 3 mois. "
                f"En tête : " + ", ".join(
                    f"{c.get('nom') or c.get('client')} ({_fmt(c.get('ca_attendu_dt'))})"
                    for c in top_ca) + "."
                + (f" {len(baisse)} en baisse par rapport au trimestre passé." if baisse else "")),
            "action": (
                "Passer voir en priorité les comptes qui devraient commander "
                "moins que le trimestre écoulé : la baisse n'est pas encore faite."
                if baisse else
                "Sécuriser les commandes attendues des comptes en tête avant "
                "la fin du trimestre."),
            "execution": execution(POSTE_COMMERCIAL, "visite"),
            "pourquoi": _pourquoi(top_ca, "nom"),
            "clients_concernes": [
                _cible(c.get("nom") or c.get("client"), abs(float(c.get("ecart_vs_passe_dt") or 0)),
                       f"attendu {_fmt(c.get('ca_attendu_dt'))} contre {_fmt(c.get('ca_passe_dt'))} "
                       "le trimestre passé",
                       "visite",
                       f"Passer voir {c.get('nom') or c.get('client')} : commandes attendues en baisse de "
                       f"{_fmt(abs(float(c.get('ecart_vs_passe_dt') or 0)))}",
                       code=c.get("client"))
                for c in sorted(baisse, key=lambda x: float(x.get("ecart_vs_passe_dt") or 0))[:N_CIBLES]]
            or [
                _cible(c.get("nom") or c.get("client"), c.get("ca_attendu_dt"),
                       f"{_fmt(c.get('ca_attendu_dt'))} de commandes attendues sur 3 mois",
                       "visite",
                       f"Sécuriser les commandes de {c.get('nom') or c.get('client')} : "
                       f"{_fmt(c.get('ca_attendu_dt'))} attendus sur 3 mois",
                       code=c.get("client"))
                for c in (ca3.get("top") or [])[:N_CIBLES]],
            "modeles_utilises": usages,
        })
    elif (ca3.get("modele") or ca12.get("modele")) and findings:
        # Refusé par le registre : l'usage est tout de même tracé, sinon le refus
        # serait indiscernable d'un oubli de branchement.
        findings[-1].setdefault("modeles_utilises", []).extend(
            _usage(c, "écarté — aucune attente de chiffre d'affaires publiée")
            for c in (ca3, ca12) if c.get("modele"))

    detail = f"{len(findings)} constat(s) issus de {len(findings)} modèle(s)"
    return {"findings": findings, "trace": [_log("🤝 Agent Commercial",
                                                 "ok" if findings else "vide", detail)]}


@_safe_node("🔬 Volet fiabilité des modèles")
def fiabilite_modeles(state: Dict[str, Any]) -> Dict[str, Any]:
    """Volet fiabilité : surveille les modèles eux-mêmes — ce qui est servi, avec quelle fiabilité, ce…"""
    modeles = _modeles(state)
    tableau = modeles.get("tableau") or []
    if not tableau:
        return {"trace": [_log("🔬 Volet fiabilité des modèles", "vide",
                               "registre non collecté (périmètre client ou erreur)")]}

    servis = [c for c in tableau if c.get("servi")]
    appris = [c for c in servis if c.get("nature") in ("modele_appris", "modele_non_supervise",
                                                       "modele_deep_learning")]
    refuses = [c for c in tableau if not c.get("servi") and not c.get("retire")]
    retires = [c for c in tableau if c.get("retire")]

    lignes = []
    for c in appris:
        cl = c.get("classification") or {}
        m = c.get("metrique")
        txt = f"{c['libelle']} — {c.get('metrique_nom')} {m:.3f}" if isinstance(m, float) else c["libelle"]
        if cl.get("accuracy") is not None:
            txt += f", accuracy {cl['accuracy']:.1%}, balanced {cl['balanced_accuracy']:.1%}"
        lignes.append(txt)

    derive = modeles.get("derive") or {}
    alertes = derive.get("alertes") or []
    dec = derive.get("decrochage_client") or {}
    reco = next((c for c in tableau if c.get("module") == "recommandation"), {})
    dl = reco.get("deep_learning") or {}

    constat = (f"{len(servis)} module(s) actif(s) sur {len(tableau)}, "
               f"dont {len(appris)} entraîné(s).")
    if refuses:
        constat += f" {len(refuses)} écarté(s) au profit d'une règle plus simple."
    if retires:
        constat += f" {len(retires)} retiré(s)."
    if dec.get("applicable") and dec.get("reentrainement_conseille"):
        constat += " Une mise à jour est recommandée."

    a_reentrainer = bool(alertes) or bool(dec.get("reentrainement_conseille"))
    fiabilite = {
        "agent": "Volet fiabilité",
        "categorie": "Qualité des modèles",
        "severite": "haute" if a_reentrainer else "faible",
        "reentrainement_conseille": a_reentrainer,
        "n_servis": len(servis),
        "n_refuses": len(refuses),
        "n_retires": len(retires),
        "titre": "Fiabilité des modèles du registre",
        "montant_dt": 0,
        "constat": constat.strip(),
        "action": ("Réentraîner les modèles en dérive : python -m ml_engine.synchro."
                   if a_reentrainer else
                   "Aucun réentraînement requis : les modèles servis restent dans leur "
                   "domaine de validité."),
        "modeles_utilises": [
            {"module": c.get("module"), "libelle": c.get("libelle"), "nature": c.get("nature"),
             "statut": "servi" if c.get("servi") else "retiré" if c.get("retire") else "refusé",
             "role": "surveillance", "fiabilite": _fiabilite(c)} for c in tableau],
    }
    return {"fiabilite": fiabilite,
            "trace": [_log("🔬 Volet fiabilité des modèles", "ok",
                           f"{len(servis)} servis · {len(refuses)} refusés · "
                           f"{len(alertes)} alerte(s) de dérive")]}


def _fiabilite(carte: Dict[str, Any]) -> str:
    from ml_engine.passerelle import formater_metrique
    return formater_metrique(carte)


_NATURE_ECONOMIQUE = {
    "Trésorerie":       (0.15, "décalage de trésorerie", "l'encaissement est différé, pas perdu"),
    "Recouvrement":     (0.15, "décalage de trésorerie", "l'encaissement est différé, pas perdu"),
    "Rétention":        (0.20, "revenu récurrent menacé", "un client perdu ne revient pas seul"),
    "Stock":            (0.10, "capital immobilisé", "récupérable, mais au rythme des ventes"),
    "Approvisionnement": (0.05, "risque opérationnel", "pas de montant direct, mais une rupture arrête la vente"),
    "Commercial":       (0.10, "revenu à capter", "une probabilité de signature ou d'adoption, pas un chiffre acquis"),
    "Rentabilité":      (0.20, "marge menacée", "une marge perdue ne se rattrape pas sur le volume"),
    "Qualité des modèles": (0.0, "fiabilité des décisions", "ne se chiffre pas : qualifie les autres constats"),
}
_DEFAUT_NATURE = (0.10, "à qualifier", "nature économique non déclarée")


@_safe_node("⚖️ Arbitre")
def arbitre(state: Dict[str, Any]) -> Dict[str, Any]:
    """Hiérarchise les constats de TOUS les agents sur une échelle commune."""
    findings = state.get("findings") or []
    if not findings:
        return {"trace": [_log("⚖️ Arbitre", "vide", "aucun constat à arbitrer")]}

    classes: List[Dict[str, Any]] = []
    for f in findings:
        montant = float(f.get("montant_dt") or 0)
        coef, nature, explication = _NATURE_ECONOMIQUE.get(
            str(f.get("categorie") or ""), _DEFAUT_NATURE)
        enjeu = montant * coef

        if montant <= 0:
            enjeu = {"critique": 5e5, "haute": 2e5,
                     "moyenne": 5e4, "faible": 1e4}.get(f.get("severite"), 1e4)

        if f.get("categorie") == "Qualité des modèles":
            enjeu = 0.0
        # Les lignes d'une carte sont pondérées comme la carte : leur somme ne
        # dépasse jamais l'« en jeu » affiché (elle l'égale si toutes y figurent).
        lignes = {}
        for cle in ("clients_concernes", "produits_concernes"):
            if f.get(cle):
                lignes[cle] = [{**x, "enjeu_dt": round(float(x.get("montant_dt") or 0) * coef, 0)}
                               if montant > 0 else x for x in f[cle]]
        classes.append({
            **f,
            **lignes,
            "nature_economique": nature,
            "coefficient_recuperabilite": coef,
            "enjeu_court_terme_dt": round(enjeu, 0),
            "pourquoi_ce_rang": explication,
        })

    classes.sort(key=lambda c: -c["enjeu_court_terme_dt"])
    for i, c in enumerate(classes, 1):
        c["rang"] = i

    par_client: Dict[str, List[Dict[str, Any]]] = {}
    for c in classes:
        for cl in (c.get("clients_concernes") or []):
            nom = str(cl.get("nom") or "").strip()
            if len(nom) < 3:
                continue
            par_client.setdefault(nom.upper(), []).append({
                "domaine": c.get("domaine") or c.get("agent"),
                "categorie": c.get("categorie"),
                "titre": c.get("titre"),
                "montant_dt": float(cl.get("montant_dt") or 0),
                "nom_affiche": nom,
            })

    cumuls = []
    for _, occurrences in par_client.items():
        domaines = {o["domaine"] for o in occurrences}
        if len(domaines) < 2:
            continue
        designe = domaine_designe(sorted(domaines))
        categorie = next((o.get("categorie") for o in occurrences
                          if o["domaine"] == designe), None)
        cumuls.append({
            "client": occurrences[0]["nom_affiche"],
            "domaines": sorted(domaines),
            "signaux": occurrences,
            "montant_cumule_dt": round(sum(o["montant_dt"] for o in occurrences), 0),
            "categorie": categorie,
            "execution": execution_multi_signaux(sorted(domaines)),
        })
    cumuls.sort(key=lambda x: -x["montant_cumule_dt"])

    total = sum(c["enjeu_court_terme_dt"] for c in classes)
    tete = classes[0]

    synthese = {
        "agent": "Arbitre",
        "categorie": "Pilotage",
        "severite": tete.get("severite", "moyenne"),
        "titre": "Hiérarchie des actions, tous domaines confondus",
        "montant_dt": round(total, 0),
        "constat": (
            f"Priorité n°1 : {tete.get('titre')} ({_fmt(tete['enjeu_court_terme_dt'])} d'enjeu)."
            + (" Alerte croisée : " + ", ".join(c['client'] for c in cumuls[:3]) + "."
               if cumuls else "")),
        "action": (
            (f"Traiter en premier {cumuls[0]['client']} (signalé dans {' et '.join(cumuls[0]['domaines'])}). "
             if cumuls else "")
            + "Ordre : " + ", ".join(f"{c['titre'].lower()}" for c in classes[:3]) + "."),
        "classement": classes,
        "clients_multi_signaux": cumuls,
        "modeles_mobilises": sorted({(u.get("libelle") or u.get("module") or "")
                                     for c in classes for u in (c.get("modeles_utilises") or [])
                                     if u.get("statut") == "servi"} - {""}),
        "pourquoi_les_cumuls_comptent": (
            "Un client signalé par plusieurs domaines cumule des risques "
            "qu'aucun domaine seul ne voit."),
        "methode": "Chaque montant est pondéré par sa part réellement en jeu à court terme.",
    }

    return {"findings": [synthese],
            "trace": [_log("⚖️ Arbitre", "ok",
                           f"{len(classes)} constats · priorité « "
                           f"{tete.get('titre')} »")]}


_SEV_ORDER = {"critique": 0, "haute": 1, "moyenne": 2, "faible": 3}
_SEV_ICON = {"critique": "🔴", "haute": "🟠", "moyenne": "🟡", "faible": "🟢"}


def _reserve_fiabilite(fiabilite: Optional[Dict[str, Any]]) -> str:
    """Ce que le volet fiabilité doit faire savoir au lecteur — sans jargon."""
    if not fiabilite or not fiabilite.get("reentrainement_conseille"):
        return ""
    return ("Réserve : une partie de ces analyses s'appuie sur des comportements "
            "clients qui s'écartent récemment de l'historique ; elles seront "
            "confirmées à la prochaine mise à jour des données.")


def _ordre_de_lecture(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordre dans lequel le briefing présente les constats."""
    metier = [f for f in findings if f.get("categorie") != "Qualité des modèles"]
    synthese = next((f for f in metier if f.get("classement")), None)
    if synthese:
        classes = [c for c in synthese["classement"]
                   if c.get("categorie") != "Qualité des modèles"]
        return classes + [synthese]
    return sorted(metier, key=lambda f: _SEV_ORDER.get(f.get("severite"), 4))


def _deterministic_briefing(findings: List[Dict[str, Any]], kpis: Dict[str, Any],
                            reserve: str = "") -> str:
    findings = _ordre_de_lecture(findings)
    lines = ["# 🧭 Briefing décisionnel — flotte d'agents\n"]
    ca = kpis.get("ca_total_ttc")
    if ca is not None:
        lines.append(f"**Contexte** : CA {_fmt(ca)} · {kpis.get('nb_clients', 0)} clients · "
                     f"croissance {kpis.get('yoy_growth', 0):.1f}%\n")
    lines.append("## Priorités du moment\n")
    for i, f in enumerate(findings, 1):
        icon = _SEV_ICON.get(f.get("severite"), "•")
        montant = f.get("montant_dt")
        montant_txt = f" — {_fmt(montant)}" if montant else ""
        lines.append(f"**{i}. {icon} {f.get('titre')}** ({f.get('agent')}){montant_txt}")
        lines.append(f"   {f.get('constat')}")
        lines.append(f"   → _{f.get('action')}_\n")
    if reserve:
        lines.append(f"_{reserve}_")
    return "\n".join(lines)


@_safe_node("✍️ Rédacteur")
def redacteur(state: Dict[str, Any]) -> Dict[str, Any]:
    """Agent Rédacteur : synthétise les constats des agents en un briefing (LLM sinon déterministe)."""
    findings = state.get("findings") or []
    kpis = state.get("kpis") or {}
    question = state.get("question") or ""
    reserve = _reserve_fiabilite(state.get("fiabilite"))

    import os
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:
        pass
    if os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        try:
            from config.settings import get_llm
            bloc = "\n".join(
                f"- [{f.get('severite')}] {f.get('titre')} ({f.get('agent')}) : "
                f"{f.get('constat')} → {f.get('action')}"
                for f in _ordre_de_lecture(findings)
            )
            if reserve:
                bloc += f"\n- [réserve] Fiabilité des analyses : {reserve}"
            prompt = (
                "Tu es le rédacteur d'une cellule d'intelligence financière. À partir des "
                "constats ci-dessous, rédige un briefing exécutif en français, concis et "
                "priorisé (Markdown, titres, puces), mettant en avant les 3 priorités.\n\n"
                "RÈGLES ABSOLUES :\n"
                "1. N'écris AUCUN chiffre qui ne figure pas mot pour mot dans les constats. "
                "Pas de pourcentage de remise, pas d'objectif de récupération, pas de volume "
                "à transférer, pas de délai en jours : rien que tu aurais calculé ou supposé.\n"
                "2. Ne recommande pas d'écouler, brader ou vendre un produit en RUPTURE : une "
                "rupture est un manque de stock, l'inverse d'un excédent. Seul le surstock "
                "s'écoule.\n"
                "3. N'invente aucun levier commercial absent des constats (remises, "
                "consignation, ventes flash, appels d'offres).\n"
                "4. Reprends l'action proposée par chaque agent ; tu peux la reformuler, "
                "jamais la remplacer par une idée à toi.\n"
                "5. Si un constat signale que des données sont estimées ou simulées, "
                "conserve cette réserve.\n"
                "6. N'invente NI calendrier, NI répartition de responsabilités, NI "
                "échéance. « Semaine 1 », « équipe recouvrement », « sous 30 jours » "
                "n'existent pas dans les constats : tu ne connais ni l'organisation "
                "de cette entreprise ni ses capacités.\n"
                "7. Si un client est signalé par PLUSIEURS domaines à la fois, "
                "place-le en tête et dis pourquoi le cumul aggrave sa situation.\n"
                "8. Le lecteur est un dirigeant ou un client, pas un ingénieur : n'emploie "
                "aucun terme technique (modèle, algorithme, AUC, accuracy, probabilité "
                "calibrée, registre).\n\n"
                f"{('QUESTION DE L’UTILISATEUR : ' + question) if question else ''}\n\n"
                f"CONSTATS DES AGENTS :\n{bloc}\n\nBRIEFING :"
            )
            for _m in (None, "openai/gpt-oss-20b", "gemma2-9b-it"):
                try:
                    llm = get_llm(model=_m) if _m else get_llm()
                    res = llm.invoke(prompt)
                    txt = getattr(res, "content", str(res))
                    if txt and "[Mode mock" not in txt:
                        return {"briefing": txt.strip(),
                                "trace": [_log("✍️ Rédacteur", "ok", "briefing LLM"
                                               + (" · réserve de fiabilité" if reserve else ""))]}
                except Exception:
                    continue
        except Exception:
            pass

    return {"briefing": _deterministic_briefing(findings, kpis, reserve),
            "trace": [_log("✍️ Rédacteur", "ok", "briefing déterministe"
                           + (" · réserve de fiabilité" if reserve else ""))]}
