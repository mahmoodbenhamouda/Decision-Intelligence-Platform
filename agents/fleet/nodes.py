"""
Agents (nœuds) de la flotte.

Chaque agent est une fonction pure `node(state) -> partial_state`. Deux
collecteurs préparent l'état : `collecte_interne` calcule les indicateurs de
l'entrepôt ERP (`kpis`), puis `collecte_modeles` interroge TOUS les modèles du
projet par la passerelle `ml_engine.passerelle` (`modeles`). Les CINQ
spécialistes croisent indicateurs et prédictions et ajoutent des `findings` ;
chaque constat tiré d'un modèle déclare `modeles_utilises` — nature, statut au
registre et fiabilité mesurée (AUC/MAPE/NDCG hors période, accuracy).

Le volet fiabilité (`fiabilite_modeles`) n'est pas un spécialiste : il audite
les modèles et écrit dans `fiabilite`, jamais dans `findings`. L'arbitre
hiérarchise les constats métier, le rédacteur synthétise et ajoute la réserve
de fiabilité quand il y en a une.

Aucun agent n'importe un module de modèle : ils passent tous par la passerelle,
qui consulte le registre. Un modèle refusé ou retiré ne peut donc pas atteindre
un briefing par une importation oubliée.

Périmètre : entièrement interne à l'ERP. La veille externe (appels d'offres,
taux de change) a été retirée du projet.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("fleet")


# ── Utilitaires ─────────────────────────────────────────────────────────────
def _pourquoi(lignes: List[Dict[str, Any]], cle_nom: str = "nom",
              n: int = 2) -> List[Dict[str, Any]]:
    """Reprend, pour les premières entités citées, les raisons produites par le
    modèle qui les a signalées.

    Le briefing dit QUOI faire ; sans cette reprise, il ne dit jamais POURQUOI
    ce client-là plutôt qu'un autre — et un directeur qui ne peut pas
    contredire un classement finit par ne plus le lire.
    """
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


def _log(agent: str, status: str, detail: str = "") -> Dict[str, Any]:
    return {"agent": agent, "status": status, "detail": detail}


def _safe_node(label: str) -> Callable:
    """Décorateur de robustesse : AUCUN agent ne doit faire planter le briefing.

    Si le nœud lève une exception, on renvoie une mise à jour d'état minimale
    (trace `erreur` + constat dégradé) au lieu de propager l'erreur — le
    rédacteur peut ainsi toujours produire un briefing avec les agents valides.
    """
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


# ── Collecteurs ─────────────────────────────────────────────────────────────
@_safe_node("🗄️ Collecte interne (ERP)")
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
    return {"kpis": kpis, "trace": [_log("🗄️ Collecte interne (ERP)", status, detail)]}


def _perimetre(state: Dict[str, Any]) -> List[str]:
    """Codes clients imposés par le périmètre (compte client : forcé côté serveur)."""
    return [str(c) for c in ((state.get("filters") or {}).get("selected_clients") or [])]


def _nom(noms: Dict[str, str], code: Any) -> str:
    return str(noms.get(str(code), code) or code)


@_safe_node("🧠 Collecte modèles (registre)")
def collecte_modeles(state: Dict[str, Any]) -> Dict[str, Any]:
    """Interroge chaque modèle du projet par la passerelle — une seule fois par briefing.

    Les sorties déjà calculées par le tableau de bord (décrochage, conversion,
    marge, réapprovisionnement) sont reprises des `kpis` au lieu d'être
    recalculées. Chaque sortie embarque la carte du modèle : les spécialistes n'ont
    plus à savoir où lire une métrique ni si le modèle est servi.

    Confidentialité : sur un périmètre client (compte client), seules les sorties
    portant sur SES codes sont conservées, et les modules internes à l'entreprise
    (stock, fournisseurs, qualité des modèles) ne sont pas collectés. Sans ce
    filtrage, la liste des clients qui décrochent — calculée sur tout le
    portefeuille — aurait atteint le briefing d'un client.
    """
    from ml_engine import passerelle as pw

    kpis = state.get("kpis") or {}
    perimetre = set(_perimetre(state))
    noms = pw.noms_clients()
    m: Dict[str, Any] = {"perimetre_client": sorted(perimetre)}

    def _depuis_kpis(cle: str, nom_modele: str, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        v = kpis.get(cle)
        if isinstance(v, dict) and "servi" in v:
            return {**v, "modele": pw.carte_modele(nom_modele)}
        return fn()

    def _nommer(liste: List[Dict[str, Any]], cle: str = "client") -> List[Dict[str, Any]]:
        out = []
        for e in liste or []:
            code = str(e.get(cle) or e.get("code") or "")
            if perimetre and code not in perimetre:
                continue
            out.append({**e, "code": code, "nom": e.get("nom") or _nom(noms, code)})
        return out

    dec = _depuis_kpis("churn_anticipe", "churn", lambda: pw.decrochage(kpis=kpis))
    if dec.get("top"):
        dec = {**dec, "top": _nommer(dec["top"], "code")}
    m["decrochage"] = dec

    seg = pw.segments_clients()
    if perimetre and seg.get("par_client"):
        seg = {**seg, "par_client": {c: v for c, v in seg["par_client"].items() if c in perimetre}}
    m["segmentation"] = seg

    conv = _depuis_kpis("conversion_devis", "conversion_devis", pw.conversion_devis)
    if conv.get("top"):
        conv = {**conv, "top": _nommer(conv["top"])}
    m["conversion_devis"] = conv

    marge = _depuis_kpis("marge_client", "marge_client", pw.marge_clients)
    if marge.get("top"):
        marge = {**marge, "top": _nommer(marge["top"])}
    m["marge_client"] = marge

    credit = pw.conditions_credit()
    if credit.get("scores"):
        credit = {**credit, "scores": {c: v for c, v in credit["scores"].items()
                                       if not perimetre or c in perimetre}}
    m["credit"] = credit

    if perimetre:
        recos = []
        for code in sorted(perimetre):
            r = pw.recommandations(client=code)
            if r.get("produits"):
                recos.append({"client": code, "nom": r.get("nom") or _nom(noms, code),
                              "produits": r["produits"][:3],
                              "potentiel_top3_dt": round(sum(
                                  float(p_.get("montant_annuel_median_par_acheteur_dt") or 0)
                                  for p_ in r["produits"][:3]), 0)})
        base = pw.recommandations(client=next(iter(sorted(perimetre))))
        m["recommandation"] = {**{k: v for k, v in base.items()
                                  if k not in ("produits", "client", "nom")},
                               "top": recos}
    else:
        m["recommandation"] = pw.recommandations()
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
            "trace": [_log("🧠 Collecte modèles (registre)", "ok",
                           f"{servis} module(s) servi(s) interrogé(s) par la passerelle"
                           + (" · périmètre client" if perimetre else ""))]}


def _modeles(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.get("modeles") or {}


def _usage(sortie: Dict[str, Any], role: str) -> Dict[str, Any]:
    from ml_engine.passerelle import trace_modele
    return trace_modele(sortie.get("modele") or {}, role)


# ── Agents spécialistes ────────────────────────────────────────────────────────────────────────


@_safe_node("📋 Agent Recouvrement")
def agent_recouvrement(state: Dict[str, Any]) -> Dict[str, Any]:
    kpis = state.get("kpis") or {}
    risque = kpis.get("clients_relance") or kpis.get("clients_a_risque") or []
    top = risque[:3]
    expo = kpis.get("exposition_recente_dt")
    crit = kpis.get("exposition_recente_critique_dt")
    cnt = kpis.get("exposition_recente_count", 0)
    periode = kpis.get("exposition_recente_periode", "6 derniers mois")
    noms = ", ".join((c.get("nom") or c.get("client")) for c in top) or "vos principaux débiteurs"
    finding = {
        "agent": "Recouvrement",
        "categorie": "Recouvrement",
        "severite": "haute" if float(crit or 0) > 0 else "moyenne",
        "titre": "Créances à relancer en priorité",
        "resume": f"{_fmt(expo)} à plus de 60 jours, dont {_fmt(crit)} à plus de 90 jours",
        "montant_dt": round(float(expo or 0), 0),
        "constat": (f"{_fmt(expo)} d'exposition récente en retard >60j ({periode}), "
                    f"dont {_fmt(crit)} critique (>90j) sur {cnt} facture(s)."),
        "action": f"Relancer en priorité : {noms} (appel + relance écrite, échéancier si >90j).",
        # Liste STRUCTURÉE des clients concernés. Elle permet à l'arbitre de
        # détecter qu'un même client apparaît dans plusieurs domaines — ce
        # qu'aucun agent ne peut voir, chacun restant dans son périmètre.
        "clients_concernes": [
            {"nom": (c.get("nom") or c.get("client") or "").strip(),
             "montant_dt": float(c.get("montant_risque") or c.get("montant") or 0)}
            for c in top if (c.get("nom") or c.get("client"))
        ],
    }

    # ── Conditions de crédit (règle servie par le registre) ────────────────
    #
    # La règle ne prédit pas un impayé : elle dit si le délai HABITUEL du client
    # dépasse 60 jours. Pour un débiteur à relancer, c'est l'argument qui décide
    # du ton : un client structurellement à 90 jours n'est pas en défaut, il
    # applique ses conditions — la relance porte alors sur l'échéancier, pas sur
    # un litige.
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
            finding["constat"] += " Conditions de crédit : " + " ; ".join(details) + "."
        finding["modeles_utilises"] = [_usage(credit, "conditions de crédit des débiteurs")]
    return {"findings": [finding], "trace": [_log("📋 Agent Recouvrement", "ok", f"{len(risque)} débiteurs récents")]}


@_safe_node("💰 Agent Trésorerie")
def agent_tresorerie(state: Dict[str, Any]) -> Dict[str, Any]:
    """Cycle d'encaissement, et ce que le stock y immobilise.

    Le volet CHANGE a été retiré avec la veille externe : il reposait sur un taux
    EUR/TND récupéré en ligne, donc sur une source dont la qualité ne pouvait pas
    être auditée comme l'est celle de l'ERP.

    En revanche cet agent CONSULTE le stock, et c'est délibéré. Les cinq
    spécialistes s'exécutent en parallèle sans se parler : le volet stock de
    l'agent Stock & Approvisionnement annonce un montant immobilisé, celui-ci un
    besoin de financement, et personne ne rapprochait les deux — alors que du
    stock dormant EST de la trésorerie gelée.
    Le rapprochement est fait ici parce que c'est la trésorerie qui en subit
    l'effet, pas le magasin.
    """
    kpis = state.get("kpis") or {}
    dso = float(kpis.get("dso_jours") or 0)
    dpo = float(kpis.get("dpo_jours") or 0)
    # `exposition_recente_dt` et NON `montant_risque_ttc`. Le second additionne
    # cinq ans d'historique de factures réglées avec retard : c'est un
    # comportement de paiement cumulé, pas un encours. L'annoncer comme
    # « créances dépassant l'échéance » donnait 133,77 M DT — 48 % du chiffre
    # d'affaires total — et contredisait l'agent Recouvrement, qui annonce
    # 10,95 M DT pour la même réalité. Deux agents qui se contredisent sur un
    # même fait ruinent la crédibilité de l'ensemble.
    expo = float(kpis.get("exposition_recente_dt") or 0)
    ttm = float(kpis.get("ttm_revenue") or 0)
    jours_cycle = dso - dpo

    # Besoin de financement du cycle, en dinars. On l'annualise sur le chiffre
    # d'affaires des douze derniers mois (`ttm_revenue`) et non sur le CA total
    # de l'historique : sept ans de facturation cumulés donneraient un besoin
    # sans rapport avec l'exercice en cours.
    bfr = (jours_cycle / 365.0) * ttm if ttm > 0 else 0.0

    # ── Ce que le stock immobilise ──────────────────────────────────────────
    #
    # Priorité aux FLUX RÉELS quand ils sont disponibles : ils sont reconstruits
    # des factures d'achat et de vente, alors que le module (s,S) repose sur des
    # quantités simulées. Un directeur n'engage pas un déstockage sur une
    # estimation ; l'origine du chiffre change donc la nature du constat.
    immo, perte, stock_lu, origine = 0.0, 0.0, False, ""
    flux = ((state.get("kpis") or {}).get("stock_flux_reel") or {}) if not _perimetre(state) else {}
    if flux.get("disponible") and float(flux.get("valeur_immobilisee_dt") or 0) > 0:
        immo = float(flux["valeur_immobilisee_dt"])
        stock_lu = True
        origine = "reel"

    # La perte par obsolescence est désormais MESURÉE, non simulée : un
    # consommable dont le stock dépasse deux ans de consommation périmera, quelle
    # que soit sa date d'expiration — que l'ERP ne fournit pas.
    if flux.get("disponible"):
        perte = float(flux.get("perte_quasi_certaine_dt") or 0)

    # Aucun repli sur le module simulé. Il en existait un : si les flux réels
    # manquaient, l'agent Trésorerie lisait le stock (s,S) généré et annonçait un
    # surstock estimé comme une part du besoin de financement. Un chiffre inventé
    # présenté dans une phrase sur le besoin en fonds de roulement est pire qu'une
    # absence — le lecteur n'a aucun moyen de distinguer les deux.
    #
    # Si `stock_flux_reel` est indisponible, la partie stock de ce constat est
    # simplement omise, et la trace le dit.

    constat = (f"DSO {dso:.0f} j contre DPO {dpo:.0f} j : le cycle exige de "
               f"financer {jours_cycle:.0f} j de chiffre d'affaires")
    if bfr > 0:
        constat += f", soit environ {_fmt(bfr)}"
    # Formulation exacte : ces factures ont été ÉMISES avec un délai dépassant
    # 60 jours. L'ERP n'enregistre aucune date de règlement — parler de créances
    # « dépassant l'échéance » laisserait croire à des impayés constatés.
    constat += (f". {_fmt(expo)} facturés à plus de 60 jours de délai sur les "
                "six derniers mois.")

    action = ("Aligner les relances sur les creux d'encaissement ; renégocier les "
              "délais fournisseurs tant que le DSO dépasse le DPO.")

    if stock_lu and immo > 0:
        # Part du besoin de financement gelée en stock dormant. C'est le chiffre
        # qui transforme deux constats juxtaposés en une seule décision.
        part = (immo / bfr * 100) if bfr > 0 else None
        constat += (f" Sur ce besoin, {_fmt(immo)} dorment en stock excédentaire"
                    + (f", soit {part:.0f} % du financement mobilisé" if part and part <= 300 else "")
                    + ".")
        if perte > 0:
            # Une seule formulation possible désormais : l'origine est toujours
            # réelle. La variante « simulée » a disparu avec son repli.
            constat += (f" S'y ajoute {_fmt(perte)} de marchandise dont le stock "
                        "dépasse deux ans de consommation : elle périmera avant "
                        "d'être vendue — une perte sèche, pas un décalage.")
        constat += (
            " Ce montant est reconstruit des factures d'achat et de vente : "
            "quantités entrées moins quantités sorties. C'est un minorant, le "
            "stock antérieur à l'historique étant inconnu.")
        action = ("Déstocker les références excédentaires libérerait de la "
                  "trésorerie sans emprunter ni relancer un client. "
                  + action[0].lower() + action[1:])

    # ── Échéancier à un mois (lecture du carnet, servi par le registre) ─────
    ech = _modeles(state).get("echeancier") or {}
    usages: List[Dict[str, Any]] = []
    if ech.get("servi") and ech.get("montant_exigible_dt"):
        constat += (f" L'échéancier annonce {_fmt(ech['montant_exigible_dt'])} de "
                    "créances exigibles le mois prochain, dont "
                    f"{float(ech.get('part_deja_au_carnet') or 0):.0%} déjà inscrits "
                    "sur des factures émises.")
        usages.append(_usage(ech, "créances exigibles à un mois"))

    # Le stock dormant pèse-t-il lourd dans le besoin de financement ?
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
    }
    if usages:
        finding["modeles_utilises"] = usages
    detail = f"cycle {jours_cycle:.0f} j"
    if stock_lu:
        detail += f" · {immo/1e3:.0f} K DT en stock dormant"
    return {"findings": [finding], "trace": [_log("💰 Agent Trésorerie", "ok", detail)]}


@_safe_node("📉 Agent Risque client")
def agent_risque(state: Dict[str, Any]) -> Dict[str, Any]:
    """Deux constats distincts : le décrochage CONSTATÉ et le décrochage ANTICIPÉ.

    Le premier se lit dans les chiffres passés — le client est déjà parti, et la
    marge de manœuvre est faible. Le second vient du modèle de décrochage, sur des
    clients ENCORE ACTIFS : c'est là qu'une relance change quelque chose. Les
    présenter séparément évite de laisser croire qu'une même action répond aux deux.
    """
    kpis = state.get("kpis") or {}
    findings: List[Dict[str, Any]] = []

    # ── Constaté ────────────────────────────────────────────────────────────
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
                                for c in top), 0),
        "constat": (f"{len(dec)} client(s) établi(s) en fort décrochage "
                    "(CA des 90 derniers jours en chute de plus de 60 %)."
                    if dec else "Aucun décrochage marqué détecté."),
        "action": (f"Recontacter d'urgence : {noms} — comprendre la cause avant de "
                   "perdre définitivement le compte."
                   if dec else "Maintenir le suivi commercial habituel."),
    })

    # ── Anticipé (modèle) ───────────────────────────────────────────────────
    modeles = _modeles(state)
    ch = modeles.get("decrochage") or kpis.get("churn_anticipe") or {}
    seg = modeles.get("segmentation") or {}
    segment_de = {c: v.get("nom_segment") for c, v in (seg.get("par_client") or {}).items()}
    if ch.get("servi") and ch.get("top"):
        cibles = ch["top"][:3]
        # Nom d'établissement, jamais le code : un briefing qui écrit
        # « CE000229 » oblige son lecteur à ouvrir l'ERP pour savoir qui appeler.
        # Et « risque élevé » se comprend sans traduction, contrairement à « p=0,91 ».
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
                (f"Probabilité de décrochage dans les 90 prochains jours : {libelles}."
                 if modeles.get("perimetre_client") else
                 f"{ch.get('n_au_dessus_de_0_5', 0)} client(s) actif(s) sur "
                 f"{ch.get('n_clients_scores', 0)} présentent une probabilité de "
                 "décrochage supérieure à 50 % dans les 90 prochains jours. "
                 f"Priorités par enjeu : {libelles}.")),
            "action": ("Relancer en priorité les comptes à fort enjeu : ils sont "
                       "encore actifs, donc récupérables — contrairement à ceux "
                       "déjà en décrochage constaté."),
            "pourquoi": _pourquoi(cibles),
            "clients_concernes": [
                {"nom": str(c.get("nom") or c.get("code") or "").strip(),
                 "montant_dt": float(c.get("enjeu_dt") or 0)}
                for c in cibles if (c.get("nom") or c.get("code"))
            ],
            **({"modeles_utilises": [_usage(ch, "probabilité de décrochage à 90 jours")]
                + ([_usage(seg, "segment de chaque client")] if segment_de else [])}
               if ch.get("modele") else {}),
        })

    # ── Quel TYPE de clientèle perdons-nous ? (segmentation × décrochage) ──
    #
    # La liste nominative oriente les appels ; ce constat oriente une politique.
    # Il n'existe que parce que deux modèles se répondent : la segmentation dit
    # QUI sont les clients, le décrochage LESQUELS partent.
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
                f"Le segment « {pire.get('nom')} » porte le plus fort chiffre d'affaires "
                f"menacé : {_fmt(pire.get('ca_menace_dt'))}, soit "
                f"{float(pire.get('part_menacee_pct') or 0):.1f} % de son CA. "
                f"Le taux de menace le plus élevé est celui du segment "
                f"« {plus_expose.get('nom')} » ({float(plus_expose.get('part_menacee_pct') or 0):.1f} %)."),
            "action": (f"Suivre la RÉGULARITÉ des commandes du segment « {pire.get('nom')} », "
                       "pas seulement son volume : c'est le rythme qui se dérègle "
                       "avant que le chiffre d'affaires ne chute."),
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


# ── Agent Stock & Approvisionnement (un agent, deux volets) ─────────────────
#
# Ces deux volets étaient deux agents. Ils sont réunis parce qu'ils répondent à
# la même décision — commander ce qui manque, écouler ce qui dort — et parce
# qu'aucun des deux ne sert de modèle appris : le registre a refusé le
# réapprovisionnement et la fin de commercialisation, retiré le risque stock,
# et la demande est une médiane mobile dont le correcteur appris n'apportait
# rien. Alignés à côté de l'agent Commercial et de ses trois modèles servis,
# ils laissaient croire à une symétrie qui n'existe pas.
#
# L'agent est donc DÉTERMINISTE ET STATISTIQUE, et le déclare dans chaque
# constat (`nature_analyse`) :
#   * volet stock        : capital immobilisé, ruptures, stock non écoulable —
#                          arithmétique sur les factures d'achat et de vente ;
#   * volet fournisseurs : dépendance fournisseur (part des achats) et volume
#                          attendu (médiane mobile validée en walk-forward).
#
# Chaque volet garde son constat, sa catégorie et son DOMAINE : l'arbitre
# classe des constats, pas des agents, donc la fusion ne retire rien au
# classement. Et chaque volet reste isolé : une panne de l'un n'emporte pas
# l'autre.
AGENT_STOCK_APPRO = "Stock & Approvisionnement"
NATURE_STOCK_APPRO = ("déterministe et statistique : arithmétique sur les factures "
                      "et médiane mobile, aucun modèle appris servi")


@_safe_node("📦 Volet fournisseurs")
def constat_approvisionnement(state: Dict[str, Any]) -> Dict[str, Any]:
    """Volet fournisseurs de l'agent Stock & Approvisionnement : dépendance
    fournisseur (part des achats) et volume attendu (médiane mobile).

    Aucun modèle appris : le réapprovisionnement a été refusé par le registre,
    et la demande est une méthode statistique validée en walk-forward."""
    if _perimetre(state):
        # Achats et fournisseurs de l'entreprise : hors du périmètre d'un client
        # (la route `/api/supply` est d'ailleurs réservée au directeur).
        return {"trace": [_log("📦 Volet fournisseurs", "vide",
                               "hors périmètre client — données fournisseurs internes")]}
    try:
        from ml_engine.analytics.demand_engine import compute_supply_demand
        d = compute_supply_demand()
    except Exception:
        d = {}
    dep = d.get("dependance_fournisseur") or "n/d"
    top = (d.get("fournisseurs_top") or [{}])[0]
    top1_name, top1_pct = top.get("fournisseur", "N/D"), d.get("fournisseur_top1_pct", 0)
    mape = d.get("demande_mape")
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
        "constat": (f"Dépendance fournisseur {dep} : {top1_name} représente {top1_pct} % des "
                    f"achats (trois premiers fournisseurs : {d.get('fournisseurs_top3_pct', 0)} %). "
                    f"Volumes attendus sur les trois prochains mois : {fc_txt}."),
        "action": ("Sécuriser une 2e source d'approvisionnement pour réduire la dépendance ; "
                   "caler les commandes sur la prévision et anticiper les pics saisonniers."),
    }

    modeles = _modeles(state)
    usages: List[Dict[str, Any]] = []
    if modeles:
        from ml_engine.passerelle import carte_modele
        usages.append(_usage({"modele": carte_modele("demande")},
                             "prévision de demande à 3 mois"))
    reappro = modeles.get("reappro") or {}
    if reappro.get("servi") and reappro.get("top"):
        top_r = reappro["top"][:3]
        finding["constat"] += (" Commandes à prévoir sur trois mois : budget "
                               f"{_fmt(reappro.get('budget_total_dt'))}, en tête "
                               + ", ".join(r["produit"][:28] for r in top_r) + ".")
        usages.append(_usage(reappro, "références à réapprovisionner au trimestre"))
    elif reappro.get("modele"):
        # Le modèle a été mesuré puis REFUSÉ : ses probabilités ne sont jamais
        # utilisées. Le constat reste en langage métier ; la trace technique vit
        # dans `modeles_utilises`, que l'interface n'affiche pas.
        usages.append(_usage(reappro, "écarté — repli sur la détection de rupture"))
    if usages:
        finding["modeles_utilises"] = usages
    return {"findings": [finding],
            "trace": [_log("📦 Volet fournisseurs", "ok", f"dépendance {dep}")]}


@_safe_node("📦 Volet stock")
def constat_stock(state: Dict[str, Any]) -> Dict[str, Any]:
    """Volet stock : immobilisations, ruptures et stock non écoulable — sur données RÉELLES.

    Réécrit intégralement. La version précédente lisait le module (s,S) SIMULÉ :
    elle annonçait un stock valorisé, des points de commande et des pertes par
    péremption dont **aucune valeur n'était observée**. Le constat le signalait
    par un préfixe `[SIMULATION]`, ce qui était honnête et inutilisable — un
    directeur ne déstocke pas sur une estimation, et un briefing dont la moitié
    des chiffres sont générés n'est pas un briefing.

    Tout ce qui est annoncé ici vient désormais des factures :

      * capital immobilisé  = quantités achetées − vendues, au coût d'achat réel ;
      * ruptures            = référence encore vendue, approvisionnement arrêté ;
      * stock non écoulable = plus de deux ans de consommation constatée.

    Le module simulé n'est plus lu, même en repli : servir une estimation quand la
    mesure manque reviendrait à remettre du généré dans le briefing par la porte
    de derrière. Si les flux réels sont indisponibles, le volet se tait.
    """
    if _perimetre(state):
        return {"trace": [_log("📦 Volet stock", "vide",
                               "hors périmètre client — stock interne de l'entreprise")]}
    flux = (state.get("kpis") or {}).get("stock_flux_reel") or {}
    if not flux.get("disponible"):
        return {"trace": [_log("📦 Volet stock", "vide",
                               f"flux réels indisponibles — "
                               f"{flux.get('motif', 'table absente')}"[:80])]}

    immo = float(flux.get("valeur_immobilisee_dt") or 0)
    perte = float(flux.get("perte_quasi_certaine_dt") or 0)
    n_dormantes = int(flux.get("n_references_plus_de_2_ans") or 0)
    n_refs = int(flux.get("n_references_accumulees") or 0)
    ruptures = flux.get("ruptures") or []
    n_crit = int(flux.get("n_ruptures_critiques") or 0)
    budget = float(flux.get("budget_commandes_dt") or 0)
    n_obsoletes = int(flux.get("n_obsoletes_certains") or 0)

    # Les ruptures sont déjà triées par gravité puis par consommation : les trois
    # premières sont celles qui coûtent le plus vite.
    noms = ", ".join(r["produit"][:28] for r in ruptures[:3]) or "aucune"

    severite = ("haute" if n_crit > 0
                else "moyenne" if ruptures or perte > 0
                else "faible")

    # Séparateur de milliers appliqué au NOMBRE seul : un `.replace(",", " ")`
    # sur la phrase entière effaçait aussi sa ponctuation.
    def _n(v: float) -> str:
        return f"{v:,.0f}".replace(",", " ")

    # `ruptures` est tronquée à 25 lignes pour l'affichage ; le compte vient de
    # `n_ruptures`. Annoncer « 25 ruptures dont 277 critiques » se contredisait.
    n_ruptures = int(flux.get("n_ruptures") or len(ruptures))
    constat = (
        f"{n_refs} références en position positive, {_n(immo)} DT immobilisés "
        "au coût d'achat réel"
        + (f", dont {n_dormantes} référence(s) représentant plus de deux ans de "
           "consommation" if n_dormantes else "")
        + ". "
    )

    if ruptures:
        constat += (f"{n_ruptures} référence(s) encore vendues dont "
                    f"l'approvisionnement s'est interrompu, dont {n_crit} sous un "
                    f"mois de couverture. ")
    if perte > 0:
        constat += (f"{_n(perte)} DT de stock ne seront pas écoulés avant "
                    f"péremption sur {n_obsoletes} référence(s).")

    # Les deux actions portent sur des situations OPPOSÉES : on commande ce qui
    # manque, on écoule ce qui dort. Les formuler séparément évite au rédacteur de
    # proposer d'écouler un produit en rupture.
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
            constat += (" Références qui vont cesser de se vendre dans les six mois : "
                        + f"{_fmt(fdv.get('capital_expose_total_dt'))} de stock concerné, en tête "
                        + ", ".join(f"{r['produit'][:28]} ({_fmt(r['capital_expose_dt'])})"
                                    for r in cibles) + ". ")
            action += (" Arrêter de réapprovisionner les références en fin de vie : "
                       + ", ".join(r["produit"][:28] for r in cibles) + ".")
            usages.append(_usage(fdv, "références en fin de commercialisation"))
    rs = _modeles(state).get("risque_stock") or {}
    if rs.get("modele") and not rs.get("servi"):
        usages.append(_usage(rs, "NON utilisé — cible dépendant de dates simulées"))

    # ── Combien commander : la demande attendue, référence par référence ────
    #
    # La quantité suggérée par la détection de rupture est un repère : trois
    # mois de consommation moyenne. La prévision par référence la remplace pour
    # les ruptures en tête de liste, par une quantité qui couvre les trois
    # prochains mois dans 8 cas sur 10 (borne haute calibrée sur la
    # validation), moins le stock encore positif. La prévision vient de la
    # méthode que le registre sert — règle simple ou modèle appris.
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
            constat += (" Demande attendue sur les trois prochains mois : "
                        + ", ".join(f"{p_[:28]} {_n(q)} unités" for p_, q, _ in chiffres) + ". ")
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
        # Conservé et mis à FALSE plutôt que supprimé : le rédacteur et les tests
        # lisent ce drapeau, et le retirer ferait disparaître silencieusement une
        # garantie au lieu de l'affirmer.
        "is_simulated": False,
        "origine_des_chiffres": ("factures d'achat et de vente — aucune "
                                 "simulation, aucune date inventée"),
        "reserve": ("Variation cumulée et non inventaire : le stock antérieur à "
                    "l'historique est inconnu, donc ce montant est un MINORANT."),
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
    """Commander ce qui manque, écouler ce qui dort : un agent, deux volets.

    Renvoie les constats des deux volets tels quels (catégorie et domaine
    conservés) et UNE ligne de trace pour le nœud. Les volets sont appelés
    par leur nom au moment de l'exécution : un test peut en remplacer un pour
    vérifier que l'autre survit à sa panne.
    """
    label = "📦 Agent Stock & Approvisionnement"
    if _perimetre(state):
        return {"trace": [_log(label, "vide",
                               "hors périmètre client — stock et fournisseurs internes")]}
    findings: List[Dict[str, Any]] = []
    statuts: List[str] = []
    details: List[str] = []
    for volet, fn in (("stock", constat_stock), ("fournisseurs", constat_approvisionnement)):
        try:
            out = fn(state) or {}
        except Exception as e:      # un volet en panne n'emporte pas l'autre
            logger.exception("Volet %s en erreur", volet)
            out = {"trace": [_log(volet, "erreur", f"{type(e).__name__}: {e}")]}
        findings += out.get("findings") or []
        for t in out.get("trace") or []:
            statuts.append(str(t.get("status")))
            details.append(f"{volet} : {t.get('detail') or t.get('status')}")
    # Une erreur n'est jamais masquée par le succès de l'autre volet : le
    # constat survivant est livré, mais la trace dit qu'il manque une moitié.
    statut = "erreur" if "erreur" in statuts else "ok" if "ok" in statuts else "vide"
    retour: Dict[str, Any] = {"trace": [_log(label, statut, " · ".join(details))]}
    if findings:
        retour["findings"] = findings
    return retour


@_safe_node("🤝 Agent Commercial")
def agent_commercial(state: Dict[str, Any]) -> Dict[str, Any]:
    """Cycle commercial : devis à relancer, marges qui s'érodent, vente croisée.

    Trois modèles, trois décisions distinctes — et donc trois constats :

      * **conversion des devis** (régression logistique, AUC hors période) :
        quels devis ouverts relancer, classés par espérance de chiffre
        d'affaires = probabilité × montant ;
      * **érosion de marge** (gradient boosting) : quels clients voient leur
        marge passer sous le seuil bas dans les 3 mois, classés par marge en jeu ;
      * **recommandation de produits** (Wide & Deep mesuré contre LightGBM et
        des références triviales) : quels produits proposer à quel client.

    Chaque constat publie `clients_concernes` : l'arbitre peut ainsi repérer un
    client à relancer pour un devis ALORS qu'il décroche, ou dont la marge
    s'érode ALORS qu'il doit de l'argent.
    """
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
                f"{conv.get('n_devis', 0)} devis récents encore ouverts représentent "
                f"{_fmt(conv.get('esperance_totale_dt'))} de ventes probables. En tête : "
                + " ; ".join(f"{d['nom']} — {_fmt(d['montant_ht_dt'])} HT, signature "
                             f"probable à {float(d['probabilite']):.0%}"
                             for d in top) + "."),
            "action": ("Relancer d'abord les devis qui rapportent le plus s'ils sont signés, "
                       "plutôt que dans l'ordre d'arrivée."),
            "pourquoi": _pourquoi(top),
            "clients_concernes": [{"nom": d["nom"], "montant_dt": float(d.get("esperance_dt") or 0)}
                                  for d in top],
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
                f"{len(marge['top'])} clients risquent de devenir moins rentables dans les "
                f"trois mois, pour {_fmt(en_jeu)} de marge. En tête : "
                + " ; ".join(f"{c['nom']} — marge actuelle {float(c['marge_actuelle_pct']):.1f} %, "
                             f"risque {float(c['probabilite']):.0%}" for c in top) + "."),
            "action": ("Revoir les conditions tarifaires et le mix de ces comptes AVANT "
                       "la prochaine négociation : la baisse n'est pas encore jouée."),
            "pourquoi": _pourquoi(top),
            "clients_concernes": [{"nom": c["nom"], "montant_dt": float(c.get("marge_en_jeu_dt") or 0)}
                                  for c in top],
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
                f"Produits jamais achetés que ces clients sont les plus susceptibles "
                f"d'adopter dans les {reco.get('horizon_mois', 6)} mois. "
                + " ; ".join(f"{c['nom']} : " + ", ".join(p["designation"][:30]
                                                         for p in c["produits"][:2])
                             for c in top)
                + f". Ordre de grandeur observé : {_fmt(potentiel)} par an, d'après la "
                  "dépense médiane des clients qui achètent déjà ces produits."),
            "action": ("Présenter ces produits lors de la prochaine visite : ce sont des "
                       "adoptions probables, pas des commandes acquises."),
            "clients_concernes": [{"nom": c["nom"], "montant_dt": float(c.get("potentiel_top3_dt") or 0)}
                                  for c in top],
            "modeles_utilises": [_usage(reco, "classement des produits par client")],
        })

    detail = f"{len(findings)} constat(s) issus de {len(findings)} modèle(s)"
    return {"findings": findings, "trace": [_log("🤝 Agent Commercial",
                                                 "ok" if findings else "vide", detail)]}


@_safe_node("🔬 Volet fiabilité des modèles")
def fiabilite_modeles(state: Dict[str, Any]) -> Dict[str, Any]:
    """Volet fiabilité : surveille les modèles eux-mêmes — ce qui est servi, avec
    quelle fiabilité, ce qui dérive et ce qui a été refusé.

    Pourquoi ce n'est plus un agent du parallèle
    --------------------------------------------
    C'était le septième « spécialiste ». Il n'en était pas un : il ne lit aucune
    donnée de l'entreprise, il lit le registre, et son constat ne propose aucune
    action de gestion — l'arbitre devait d'ailleurs le neutraliser en forçant
    son enjeu à zéro. Pire, en citant TOUS les modèles pour les surveiller, il
    faisait figurer dans `modeles_mobilises` des modèles qu'aucun spécialiste
    n'avait utilisés (la lecture de factures LayoutLMv3, par exemple).

    Il écrit donc dans sa propre clé d'état, `fiabilite`, et jamais dans
    `findings` : l'arbitre ne le voit plus, et le rédacteur le reçoit par une
    jointure pour qualifier le briefing — une réserve, sans jargon, quand une
    dérive est détectée.

    Un briefing qui s'appuie sur six modèles doit dire si ces modèles méritent
    encore la confiance qu'on leur accorde. Cet agent lit le registre, les
    métriques de classification (AUC, accuracy, balanced accuracy, MCC) et la
    surveillance de dérive (PSI). Il ne produit aucun montant : son constat
    qualifie les autres.

    Réservé au périmètre direction : les motifs de refus décrivent la
    méthodologie interne, comme la route `/api/models/metrics`.
    """
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
    delais = derive.get("delais_de_paiement") or {}
    reco = next((c for c in tableau if c.get("module") == "recommandation"), {})
    dl = reco.get("deep_learning") or {}
    duel = dl.get("duel_vs_lightgbm") or {}

    constat = (f"{len(servis)} module(s) servi(s) sur {len(tableau)}, dont {len(appris)} "
               "modèle(s) appris : " + " ; ".join(lignes) + ". ")
    if refuses:
        constat += ("Mesurés puis refusés (une règle plus simple fait aussi bien) : "
                    + ", ".join(c["libelle"] for c in refuses) + ". ")
    if retires:
        constat += ("Retirés (cible dépendant de données simulées) : "
                    + ", ".join(c["libelle"] for c in retires) + ". ")
    if dl.get("mesure"):
        constat += (f"Deep learning : Wide & Deep NDCG@10 {dl['mesure'].get('ndcg_at_10'):.3f}"
                    + (f", écart {duel.get('ecart_moyen'):+.3f} face à LightGBM (IC95 "
                       f"{duel.get('ecart_ic95')}, {'significatif' if duel.get('significatif') else 'non significatif'})"
                       if duel else "")
                    + (" — servi." if dl.get("servi") else " — challenger, réévalué à chaque réentraînement. "))
    if dec.get("applicable"):
        constat += (f"Dérive : PSI max {float(dec.get('psi_max') or 0):.3f} sur les variables du "
                    "décrochage")
        if delais.get("applicable"):
            constat += (f", part des factures à délai ≤ 2 mois "
                        f"{float(delais.get('part_sous_2_mois_reference') or 0):.1%} → "
                        f"{float(delais.get('part_sous_2_mois_recent') or 0):.1%}")
        constat += "."

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


# ── Arbitre (hiérarchisation transversale) ──────────────────────────────────
#
# Nature économique de chaque catégorie de constat. C'est ce qui permet de
# comparer des montants qui n'ont pas le même sens :
#
#   * une créance en retard est un DÉCALAGE — l'argent viendra, plus tard ;
#   * une péremption est une PERTE SÈCHE — l'argent ne viendra jamais ;
#   * un client qui décroche est un REVENU MENACÉ — probabiliste, et récurrent ;
#   * du stock dormant est du CAPITAL GELÉ — récupérable, mais lentement.
#
# Le coefficient traduit la part du montant qui est réellement en jeu à court
# terme. Il reprend les hypothèses déclarées dans `ml_engine/analytics/impact.py`
# — les deux doivent dire la même chose, sinon le tableau de bord et le briefing
# hiérarchiseraient différemment les mêmes faits.
_NATURE_ECONOMIQUE = {
    "Trésorerie":       (0.15, "décalage de trésorerie", "l'encaissement est différé, pas perdu"),
    "Recouvrement":     (0.15, "décalage de trésorerie", "l'encaissement est différé, pas perdu"),
    "Rétention":        (0.20, "revenu récurrent menacé", "un client perdu ne revient pas seul"),
    "Stock":            (0.10, "capital immobilisé", "récupérable, mais au rythme des ventes"),
    "Approvisionnement": (0.05, "risque opérationnel", "pas de montant direct, mais une rupture arrête la vente"),
    "Commercial":       (0.10, "revenu à capter", "une probabilité de signature ou d'adoption, pas un chiffre acquis"),
    "Rentabilité":      (0.20, "marge menacée", "une marge perdue ne se rattrape pas sur le volume"),
    # Le volet fiabilité ne passe plus par l'arbitre (clé d'état `fiabilite`).
    # L'entrée reste : un constat de cette catégorie, s'il en arrivait un par
    # une autre voie, ne doit jamais concurrencer les constats métier.
    "Qualité des modèles": (0.0, "fiabilité des décisions", "ne se chiffre pas : qualifie les autres constats"),
}
_DEFAUT_NATURE = (0.10, "à qualifier", "nature économique non déclarée")


@_safe_node("⚖️ Arbitre")
def arbitre(state: Dict[str, Any]) -> Dict[str, Any]:
    """Hiérarchise les constats de TOUS les agents sur une échelle commune.

    Le problème résolu ici
    ----------------------
    Chaque spécialiste déclare la sévérité de son propre constat, selon ses
    propres critères. Un « haute » de l'agent Stock et un « haute » de l'agent
    Recouvrement ne mesurent donc pas la même chose, et le rédacteur les triait
    à égalité — l'ordre entre eux était arbitraire.

    Or ce sont précisément ces arbitrages inter-domaines qu'un dirigeant doit
    faire : relancer un débiteur ou déstocker ? La question ne se pose à aucun
    agent pris isolément.

    Comment l'arbitrage est rendu comparable
    ----------------------------------------
    Les montants bruts ne sont PAS additionnables : 100 000 DT de créance en
    retard et 100 000 DT de marchandise périmée ne pèsent pas pareil, le premier
    étant récupérable et le second perdu. Chaque montant est donc pondéré par un
    coefficient de récupérabilité propre à sa nature économique, ce qui donne un
    **enjeu à court terme** — grandeur homogène, donc comparable.

    Ce que l'arbitre ne fait PAS
    ----------------------------
    Il ne produit aucun score global de santé. Agréger créances, stock et
    décrochage en un chiffre unique donnerait un indicateur que personne ne
    saurait interpréter ni actionner. Il ordonne, il ne résume pas.
    """
    findings = state.get("findings") or []
    if not findings:
        return {"trace": [_log("⚖️ Arbitre", "vide", "aucun constat à arbitrer")]}

    classes: List[Dict[str, Any]] = []
    for f in findings:
        montant = float(f.get("montant_dt") or 0)
        coef, nature, explication = _NATURE_ECONOMIQUE.get(
            str(f.get("categorie") or ""), _DEFAUT_NATURE)
        enjeu = montant * coef

        # Un constat sans montant n'est pas sans importance : une rupture
        # d'approvisionnement arrête la vente. On lui attribue le rang de sa
        # sévérité déclarée plutôt que de le reléguer en fin de liste.
        if montant <= 0:
            enjeu = {"critique": 5e5, "haute": 2e5,
                     "moyenne": 5e4, "faible": 1e4}.get(f.get("severite"), 1e4)

        if f.get("categorie") == "Qualité des modèles":
            enjeu = 0.0      # qualifie les autres constats, ne les concurrence pas
        classes.append({
            **f,
            "nature_economique": nature,
            "coefficient_recuperabilite": coef,
            "enjeu_court_terme_dt": round(enjeu, 0),
            "pourquoi_ce_rang": explication,
        })

    classes.sort(key=lambda c: -c["enjeu_court_terme_dt"])
    for i, c in enumerate(classes, 1):
        c["rang"] = i

    # ── Clients signalés par PLUSIEURS agents ───────────────────────────────
    #
    # Le croisement que seul l'arbitre peut faire. Un client qui doit de l'argent
    # ET qui cesse de commander cumule deux risques dont la conjonction change la
    # nature : la créance devient douteuse, puisque le levier commercial qui
    # aurait permis de négocier un échéancier disparaît avec la relation.
    #
    # Aucun agent ne peut le voir : le recouvrement ignore le décrochage, le
    # risque client ignore les impayés. Chacun signale son client dans sa liste,
    # et personne ne rapproche les deux.
    par_client: Dict[str, List[Dict[str, Any]]] = {}
    for c in classes:
        for cl in (c.get("clients_concernes") or []):
            nom = str(cl.get("nom") or "").strip()
            if len(nom) < 3:
                continue
            par_client.setdefault(nom.upper(), []).append({
                # Le domaine est une propriété du CONSTAT, pas de l'agent qui
                # l'émet. Tant qu'il était déduit du nom de l'agent, réunir deux
                # agents fusionnait leurs domaines et faisait taire l'alerte
                # croisée pour un client présent dans les deux. Un constat qui
                # ne déclare rien retombe sur le nom de son agent : le
                # comportement des agents existants est inchangé.
                "domaine": c.get("domaine") or c.get("agent"),
                "titre": c.get("titre"),
                "montant_dt": float(cl.get("montant_dt") or 0),
                "nom_affiche": nom,
            })

    cumuls = []
    for _, occurrences in par_client.items():
        domaines = {o["domaine"] for o in occurrences}
        if len(domaines) < 2:
            continue
        cumuls.append({
            "client": occurrences[0]["nom_affiche"],
            "domaines": sorted(domaines),
            "signaux": occurrences,
            "montant_cumule_dt": round(sum(o["montant_dt"] for o in occurrences), 0),
        })
    cumuls.sort(key=lambda x: -x["montant_cumule_dt"])

    total = sum(c["enjeu_court_terme_dt"] for c in classes)
    tete = classes[0]

    # Concentration : les deux premières actions couvrent-elles l'essentiel ?
    # Si oui, le message est « faites ces deux choses » ; sinon le risque est
    # dispersé et aucune action isolée ne change la situation.
    part_top2 = (sum(c["enjeu_court_terme_dt"] for c in classes[:2]) / total
                 if total else 0.0)

    synthese = {
        "agent": "Arbitre",
        "categorie": "Pilotage",
        "severite": tete.get("severite", "moyenne"),
        "titre": "Hiérarchie des actions, tous domaines confondus",
        "montant_dt": round(total, 0),
        "constat": (
            f"{len(classes)} constats arbitrés sur une échelle commune. "
            f"Priorité : {tete.get('titre')} ({tete.get('agent')}), "
            f"{_fmt(tete['enjeu_court_terme_dt'])} d'enjeu à court terme. "
            + (f"Les deux premières actions concentrent {part_top2:.0%} de "
               "l'enjeu total : les traiter suffit à changer la situation."
               if part_top2 >= 0.6 else
               f"L'enjeu est dispersé — les deux premières actions ne couvrent "
               f"que {part_top2:.0%} du total, aucune ne suffit à elle seule.")
            + (f" ALERTE CROISÉE : {len(cumuls)} client(s) signalé(s) par "
               "plusieurs domaines à la fois, dont "
               + ", ".join(f"{c['client']} ({' + '.join(c['domaines'])})"
                           for c in cumuls[:3]) + "."
               if cumuls else "")),
        "action": (
            (f"Traiter EN PREMIER {cumuls[0]['client']} : ce compte cumule "
             f"{' et '.join(cumuls[0]['domaines'])}. Une créance sur un client "
             "qui s'éloigne devient douteuse — le levier commercial qui "
             "permettrait de négocier disparaît avec la relation. Puis : "
             if cumuls else "Traiter dans l'ordre : ")
            + " puis ".join(f"{c['titre'].lower()}" for c in classes[:3])
            + "."),
        "classement": classes,
        "clients_multi_signaux": cumuls,
        # Tous les modèles mobilisés par les spécialistes, dédoublonnés : le
        # lecteur voit d'un coup d'œil sur quelle science repose le briefing.
        "modeles_mobilises": sorted({(u.get("libelle") or u.get("module") or "")
                                     for c in classes for u in (c.get("modeles_utilises") or [])
                                     if u.get("statut") == "servi"} - {""}),
        "pourquoi_les_cumuls_comptent": (
            "Un client présent dans plusieurs constats cumule des risques dont "
            "la conjonction change la nature. Aucun agent ne peut le détecter : "
            "le recouvrement ignore le décrochage, le risque client ignore les "
            "impayés. Ce croisement n'existe qu'après le fan-in."),
        "methode": (
            "Les montants bruts ne sont pas comparables : une créance en retard "
            "est un décalage, une péremption une perte sèche. Chacun est pondéré "
            "par la part réellement en jeu à court terme."),
    }

    return {"findings": [synthese],
            "trace": [_log("⚖️ Arbitre", "ok",
                           f"{len(classes)} constats · priorité « "
                           f"{tete.get('titre')} »")]}


# ── Rédacteur (synthèse) ────────────────────────────────────────────────────
_SEV_ORDER = {"critique": 0, "haute": 1, "moyenne": 2, "faible": 3}
_SEV_ICON = {"critique": "🔴", "haute": "🟠", "moyenne": "🟡", "faible": "🟢"}


def _reserve_fiabilite(fiabilite: Optional[Dict[str, Any]]) -> str:
    """Ce que le volet fiabilité doit faire savoir au lecteur — sans jargon.

    Rien quand tout va bien : le détail technique (métriques, refus, dérive)
    reste dans l'API et le rapport. Une phrase quand une dérive est détectée :
    c'est le seul cas où la fiabilité change la façon de lire les constats.
    """
    if not fiabilite or not fiabilite.get("reentrainement_conseille"):
        return ""
    return ("Réserve : une partie de ces analyses s'appuie sur des comportements "
            "clients qui s'écartent récemment de l'historique ; elles seront "
            "confirmées à la prochaine mise à jour des données.")


def _ordre_de_lecture(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordre dans lequel le briefing présente les constats.

    L'ordre de l'ARBITRE quand il a statué : les constats classés par enjeu à
    court terme, puis sa synthèse. Le briefing triait auparavant par sévérité
    déclarée — l'échelle que l'arbitre a précisément été créé pour remplacer,
    un « haute » de l'agent Stock et un « haute » du Recouvrement ne mesurant
    pas la même chose. Sur l'entrepôt réel, le point 1 du briefing était ainsi
    la dépendance fournisseur (7e enjeu), pendant que le paragraphe de
    l'arbitre, dans le même texte, annonçait les créances comme priorité. Et
    entre sévérités égales, l'ordre dépendait de l'ordre d'arrivée des agents.

    Sans arbitrage (arbitre en panne, appel isolé), repli sur la sévérité.
    Le constat de fiabilité s'adresse à l'équipe technique : jamais listé.
    """
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
            # Le mot « chiffrées » suffisait à faire fabriquer des nombres au
            # modèle : taux de remise, volumes à transférer, objectifs de
            # recouvrement — aucun ne figurait dans les constats. Un briefing
            # contenant un seul chiffre inventé perd toute valeur, puisque le
            # lecteur ne peut plus distinguer le mesuré de l'imaginé.
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
