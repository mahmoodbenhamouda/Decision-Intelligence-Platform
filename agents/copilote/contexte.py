"""
agents/copilote/contexte.py
===========================
Le contexte donné au modèle de langage : les indicateurs PERTINENTS pour la
question, et eux seuls.

Un contexte qui contient tout noie la réponse : le copilote répétait les mêmes
chiffres quelle que soit la question. Chaque thème détecté apporte donc son
bloc (recouvrement, trésorerie, marge, stock…), les sorties des modèles
arrivent par la passerelle du registre, et les ratios sont CALCULÉS ICI : un
modèle de langage à qui l'on laisse faire une division se trompe.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.copilote import outils
from agents.copilote.outils import codes_perimetre, dt_montant, fmt


def _ratios_recouvrement(kpis: Dict[str, Any]) -> str:
    """Ratios de recouvrement PRÉ-CALCULÉS, à citer tels quels par le modèle.

    Le prompt interdit au LLM de calculer lui-même un pourcentage : livré à
    lui-même, il annonçait « 2 % du CA total » pour 30,4 M DT d'encours sur
    290,5 M DT de CA — la valeur exacte est 10,5 %, soit une sous-estimation
    d'un facteur cinq sur une phrase de risque. Les ratios qui comptent sont
    donc calculés ici, en Python, et fournis prêts à l'emploi.

    (Les 290,5 M cités ci-dessus sont le CA d'avant l'audit d'intégrité ; il
    est désormais de 274,7 M, avoirs déduits et doublons retirés. Le calcul
    ci-dessous lit `kpis` à l'exécution et suit donc la correction.)
    """
    expo = float(kpis.get("exposition_recente_dt") or 0)
    crit = float(kpis.get("exposition_recente_critique_dt") or 0)
    ca = float(kpis.get("ca_total_ttc") or 0)
    lignes = []
    if ca > 0 and expo > 0:
        lignes.append(f"  - Part de cette exposition dans le CA total : {expo / ca * 100:.1f} %")
    if expo > 0 and crit > 0:
        lignes.append(f"  - Part critique (>90j) dans l'exposition : {crit / expo * 100:.1f} %")
    if expo > 0:
        lignes.append(f"  - Si 30 % de l'exposition est recouvrée : {expo * 0.30:,.0f} DT"
                      .replace(",", " "))
    return ("\n".join(lignes) + "\n") if lignes else ""


def contexte_modeles(themes: List[str], kpis: Dict[str, Any],
                     filters: Optional[Dict[str, Any]] = None) -> List[str]:
    """Blocs de contexte issus des modèles, pour le LLM — toujours via la passerelle."""
    from ml_engine import passerelle as pw
    codes = set(codes_perimetre(filters))
    parts: List[str] = []

    def garder(code: Any) -> bool:
        return not codes or str(code) in codes

    if "modeles" in themes:
        lignes = []
        for c in pw.tableau_des_modeles():
            etat = "servi" if c.get("servi") else "retiré" if c.get("retire") else "refusé"
            lignes.append(f"  - {c.get('libelle')} [{c.get('nature')}, {etat}] : "
                          f"{pw.formater_metrique(c)}")
        parts.append("🔬 MODÈLES DE LA PLATEFORME (registre, métriques hors période) :\n"
                     + "\n".join(lignes))

    if "attrition" in themes:
        ch = pw.decrochage(kpis=kpis)
        top = [c for c in (ch.get("top") or []) if garder(c.get("code"))][:5]
        if ch.get("servi"):
            parts.append(
                "🔮 CLIENTS SUSCEPTIBLES DE PARTIR DANS LES 90 JOURS :\n"
                + ("\n".join(f"    · {c.get('nom')} — probabilité {float(c.get('probabilite_decrochage') or 0):.0%}, "
                             f"{dt_montant(c.get('enjeu_dt'))} en jeu" for c in top)
                   or "    · aucun client du périmètre parmi les plus exposés"))

    if "devis" in themes:
        cv = pw.conversion_devis()
        if cv.get("servi"):
            top = [d for d in (cv.get("top") or []) if garder(d.get("client"))][:5]
            noms = pw.noms_clients()
            parts.append(
                "📝 DEVIS À RELANCER :\n"
                f"  - Devis récents ouverts : {cv.get('n_devis', 0)}, espérance totale "
                f"{dt_montant(cv.get('esperance_totale_dt'))}\n"
                + "\n".join(f"    · {noms.get(str(d['client']), d['client'])} — {dt_montant(d['montant_ht_dt'])} HT, "
                             f"probabilité {float(d['probabilite']):.0%}, espérance {dt_montant(d['esperance_dt'])}"
                             for d in top))

    if "marge" in themes:
        mg = pw.marge_clients()
        if mg.get("servi"):
            top = [c for c in (mg.get("top") or []) if garder(c.get("client"))][:5]
            noms = pw.noms_clients()
            parts.append(
                "📉 CLIENTS DONT LA RENTABILITÉ VA BAISSER (3 MOIS) :\n"
                + "\n".join(f"    · {noms.get(str(c['client']), c['client'])} — marge actuelle "
                             f"{float(c['marge_actuelle_pct']):.1f} %, probabilité {float(c['probabilite']):.0%}, "
                             f"{dt_montant(c['marge_en_jeu_dt'])} de marge en jeu" for c in top))

    if "recommandation" in themes:
        if codes:
            blocs = []
            for code in sorted(codes):
                r = pw.recommandations(client=code)
                if r.get("produits"):
                    blocs.append(f"    · {r.get('nom')} : " + ", ".join(
                        f"{p['designation'][:40]} ({p['famille']})" for p in r["produits"][:5]))
            r0 = pw.recommandations(client=sorted(codes)[0])
        else:
            r0 = pw.recommandations()
            blocs = [f"    · {c['nom']} : " + ", ".join(p["designation"][:40] for p in c["produits"][:3])
                     + f" (ordre de grandeur {dt_montant(c['potentiel_top3_dt'])}/an)"
                     for c in (r0.get("top") or [])[:5]]
        if r0.get("servi"):
            parts.append(
                "🛒 PRODUITS À PROPOSER :\n" + ("\n".join(blocs) or "    · aucune"))
    return parts


def build_thematic_context(themes: List[str], kpis: Dict[str, Any]) -> str:
    """Construit le contexte KPI minimal et pertinent selon les thèmes détectés."""
    parts: List[str] = []

    if "recouvrement" in themes:
        top_risk = kpis.get("clients_relance") or kpis.get("clients_a_risque") or kpis.get("top_clients") or []
        top_client_name = ""
        if top_risk:
            c = top_risk[0]
            top_client_name = c.get("nom") or c.get("client") or ""
        parts.append(
            f"📌 RECOUVREMENT :\n"
            f"  - Exposition RÉCENTE en retard >60j ({kpis.get('exposition_recente_periode', '6 mois')}) : "
            f"{fmt(kpis.get('exposition_recente_dt'))} sur {kpis.get('exposition_recente_count', 0)} facture(s)\n"
            f"  - dont critique (>90j) : {fmt(kpis.get('exposition_recente_critique_dt'))}\n"
            f"{_ratios_recouvrement(kpis)}"
            f"  - DSO (délai encaissement moyen) : {kpis.get('dso_jours', 0):.0f} jours\n"
            f"  - Client prioritaire à relancer : {top_client_name or 'N/D'}\n"
            f"  - Repère historique (comportement de paiement, PAS un encours dû) : "
            f"{fmt(kpis.get('ca_retard_historique_ttc'))} de CA réglé avec >60j de retard sur tout l'historique"
        )

    if "change" in themes:
        # Le suivi du taux de change a été retiré avec la veille externe. Plutôt
        # que de renvoyer des « N/D », l'agent dit ce qu'il sait et ce qu'il ne
        # sait pas : les achats fournisseurs sont mesurés, leur part en devises
        # ne l'est pas — l'ERP n'expose aucune devise de règlement.
        parts.append(
            "💱 CHANGE :\n"
            f"  - Achats fournisseurs mesurés : {fmt(kpis.get('achats_total_ttc'))}\n"
            "  - Part réglée en devises : NON DISPONIBLE — l'export ERP ne porte "
            "aucune devise de règlement, et le suivi de taux externe a été retiré\n"
            "  - Conséquence : aucune exposition au change ne peut être chiffrée "
            "sans une donnée que l'entreprise devrait fournir"
        )

    if "tresorerie" in themes:
        cf = kpis.get("cash_forecast") or []
        cf_str = ", ".join(f"{p['period']} : {fmt(p['montant'])}" for p in cf[:3]) or "N/D"
        parts.append(
            f"💰 TRÉSORERIE :\n"
            f"  - DSO : {kpis.get('dso_jours', 0):.0f} jours\n"
            f"  - DPO : {kpis.get('dpo_jours', 0):.0f} jours\n"
            f"  - Cycle de conversion cash : {kpis.get('cash_conversion_cycle', 0):.0f} jours\n"
            f"  - Prévision cashflow : {cf_str}\n"
            f"  - Achats total TTC : {fmt(kpis.get('achats_total_ttc'))}\n"
            f"  - CA total TTC : {fmt(kpis.get('ca_total_ttc'))}"
        )

    if "marge" in themes:
        parts.append(
            f"📊 MARGE / RENTABILITÉ :\n"
            f"  - CA HT : {fmt(kpis.get('ca_total_ht'))}\n"
            f"  - Achats TTC : {fmt(kpis.get('achats_total_ttc'))}\n"
            f"  - Marge brute : {fmt(kpis.get('marge_brute'))}\n"
            f"  - Taux de marge : {kpis.get('taux_marge', 0):.1f}%\n"
            f"  - Note qualité marge : {kpis.get('marge_note', 'N/D')}"
        )

    if "prevision" in themes:
        fc = kpis.get("forecast_next") or []
        fc_str = "\n".join(
            f"    {p['period']} → {fmt(p['montant'])}" for p in fc
        ) or "  Données insuffisantes"
        monthly = kpis.get("monthly_sales") or []
        growth = kpis.get("yoy_growth")
        parts.append(
            f"🔮 PRÉVISION :\n"
            f"  - Croissance YoY : {growth:.1f}%" if growth else "  - Croissance YoY : N/D"
        )
        parts[-1] += f"\n  - CA mensuel (12 derniers mois) : {len(monthly)} points\n  - Projection CA :\n{fc_str}"

    if "fidelite" in themes:
        fideles = kpis.get("clients_fideles") or []
        fid_str = "\n".join(
            f"    {i+1}. {c.get('nom')} — {c.get('mois_actifs',0)} mois actifs, "
            f"{c.get('invoices',0)} factures, {fmt(c.get('revenue'))} CA "
            f"(depuis {c.get('premier','N/D')}, dernier achat {c.get('dernier','N/D')})"
            for i, c in enumerate(fideles[:6])
        ) or "  Aucun client récurrent (>=2 achats) sur ce périmètre."
        parts.append(
            f"🤝 CLIENTS FIDÈLES (récurrence = nb de mois d'achat distincts, "
            f"marqueur de fidélité) :\n{fid_str}"
        )

    if "attrition" in themes:
        dec = kpis.get("clients_decrochent") or []
        dec_str = "\n".join(
            f"    {i+1}. {c.get('nom')} — {fmt(c.get('ca_prev'))} → {fmt(c.get('ca_recent'))} sur 90j "
            f"(-{c.get('chute_pct',0):.0f}%), dernier achat {c.get('dernier','N/D')} ({c.get('jours_inactif',0)} j)"
            for i, c in enumerate(dec[:6])
        ) or "  Aucun décrochage marqué (clients établis stables)."
        parts.append(
            f"📉 CLIENTS QUI DÉCROCHENT (CA 90 derniers jours vs 90 précédents, "
            f"clients établis >=6 mois, chute >60%) :\n{dec_str}"
        )

    if "concentration" in themes:
        n80 = kpis.get("clients_pour_80pct") or 0
        ntot = kpis.get("nb_clients_ca") or kpis.get("nb_clients") or 0
        top5 = kpis.get("top_clients") or []
        top5_str = ", ".join(
            f"{c.get('nom') or c.get('client')} ({c.get('share',0):.0f}%)" for c in top5[:5]
        ) or "N/D"
        parts.append(
            f"🎯 CONCENTRATION CLIENTS :\n"
            f"  - {n80} clients font 80% du CA (sur {ntot} clients)\n"
            f"  - Part du Top 5 : {kpis.get('top_clients_revenue_share', 0):.0f}% du CA\n"
            f"  - HHI : {kpis.get('hhi_clients', 0):.0f}/10000\n"
            f"  - Principaux poids : {top5_str}"
        )

    if "approvisionnement" in themes:
        d = outils.demande_et_fournisseurs()
        top = (d.get("fournisseurs_top") or [{}])
        fc = d.get("demande_prevision") or []
        fc_str = ", ".join(f"{p['period']}≈{int(p['qte'])}" for p in fc) or "N/D"
        # Le libellé précédent — « pas de données de stock ERP » — poussait le
        # modèle à répondre « donnée indisponible » à toute question de stock,
        # y compris celles que le module de stock simulé sait traiter.
        parts.append(
            f"📦 DEMANDE & APPROVISIONNEMENT (analyse fournisseur ; le stock par référence "
            f"est traité par le module de stock simulé, cf. section STOCK) :\n"
            f"  - Dépendance fournisseur : {d.get('dependance_fournisseur', 'n/d')} "
            f"({top[0].get('fournisseur', 'N/D')} = {d.get('fournisseur_top1_pct', 0)}% des achats, "
            f"top 3 = {d.get('fournisseurs_top3_pct', 0)}%, HHI {d.get('fournisseurs_hhi', 0):.0f})\n"
            f"  - Prévision de demande (articles/mois, MAPE {d.get('demande_mape')}%) : {fc_str}"
        )

    # Factures importées par OCR : présentes dans TOUT contexte, car elles
    # modifient la lecture de n'importe quel indicateur si l'utilisateur vient
    # d'en déposer une. Le modèle doit savoir qu'elles existent ET qu'elles ne
    # sont pas comptées dans les totaux ERP, sinon il additionne les deux.
    imp = kpis.get("import_ocr") or {}
    if imp.get("n_factures"):
        recentes = imp["factures"][:3]
        parts.append(
            "📄 FACTURES IMPORTÉES PAR OCR (comptées À PART des totaux ERP ci-dessus, "
            "ne jamais les additionner aux montants ERP) :\n"
            f"  - {imp['n_factures']} facture(s) importée(s), "
            f"{imp['total_ttc_dt']:,.3f} DT TTC au total\n".replace(",", " ")
            + "\n".join(
                f"    · {f['numero']} — {f['client_name']} — "
                f"{float(f['ttc'] or 0):,.3f} DT".replace(",", " ")
                + (f" (lecture {f['confiance_ocr']:.0f} %)"
                   if f.get("confiance_ocr") else "")
                for f in recentes))

    if "risque_stock_client" in themes:
        # Croisement client × stock : la donnée existe (chaque ligne de stock
        # porte un client), elle n'était simplement jamais agrégée.
        cl = outils.stock_par_client(limite=5)
        if cl.get("error"):
            parts.append(f"🏥 STOCK PAR CLIENT : indisponible ({cl['error']}).")
        else:
            def _lig(c):
                nom = c["client"] if c["nom_resolu"] else f"{c['code']} (compte sans libellé ERP)"
                return (f"    · {nom} — {c['n_references']} références, "
                        f"{c['valeur_stock_dt']:,.0f} DT de stock, "
                        f"{c['n_a_risque']} à risque".replace(",", " "))
            sains = cl["clients_sans_risque"]
            parts.append(
                "🏥 STOCK PAR CLIENT (stock simulé, demande réelle) :\n"
                f"  - Clients analysés (≥ {cl['min_references']} références) : "
                f"{cl['n_clients_analyses']}\n"
                f"  - Clients SANS AUCUN risque (ni rupture, ni surstock, ni à commander) : "
                f"{cl['n_clients_sans_risque']}\n"
                + (f"  - Les {len(sains)} plus significatifs parmi eux, par valeur de stock :\n"
                   + "\n".join(_lig(c) for c in sains) + "\n" if sains else
                   "  - Aucun client n'est totalement exempt de risque.\n")
                + "  - Les 5 plus gros détenteurs de stock et leur état :\n"
                + "\n".join(_lig(c) for c in cl["top_par_valeur"]) + "\n"
                + "  - Les 5 clients les plus exposés :\n"
                + "\n".join(_lig(c) for c in cl["clients_les_plus_exposes"])
            )

    if "risque_stock" in themes:
        # Le modèle de risque de stock est RETIRÉ (cible dépendant de dates de
        # péremption simulées). Le contexte vient des flux réels et de la règle
        # de fin de commercialisation, via la passerelle du registre.
        try:
            ctx = outils.contexte_stock_reel(kpis)
        except Exception as e:
            ctx = {"flux": {}, "fin_de_vie": {}, "risque_stock": {"motif": str(e)}}
        flux, fdv, rs = ctx["flux"], ctx["fin_de_vie"], ctx["risque_stock"]
        lignes = [f"🧪 RISQUE DE STOCK (données RÉELLES reconstruites des factures ; "
                  f"le modèle de scoring est retiré : {rs.get('motif', 'non servi')}) :"]
        if flux.get("disponible"):
            lignes.append(f"  - Capital immobilisé : {dt_montant(flux.get('valeur_immobilisee_dt'))} sur "
                          f"{flux.get('n_references_accumulees', 0)} références (minorant)")
            lignes.append(f"  - Stock non écoulable avant péremption : {dt_montant(flux.get('perte_quasi_certaine_dt'))} "
                          f"sur {flux.get('n_obsoletes_certains', 0)} référence(s)")
            lignes.append("  - Ruptures d'approvisionnement : " + ("; ".join(
                f"{r['produit'][:38]} ({r['gravite']})" for r in (flux.get("ruptures") or [])[:5]) or "aucune"))
        if fdv.get("servi") and fdv.get("top"):
            lignes.append("  - Fin de commercialisation à 6 mois (" + str(fdv.get("nature")) + ") : " + "; ".join(
                f"{r['produit'][:38]} ({dt_montant(r['capital_expose_dt'])} exposés)" for r in fdv["top"][:5]))
        parts.append("\n".join(lignes))

    if "performance" in themes or not parts:
        top5 = kpis.get("top_clients") or []
        top5_str = "\n".join(
            f"    {i+1}. {c.get('nom') or c.get('client')} — {fmt(c.get('revenue'))} "
            f"({c.get('share', 0):.1f}% du CA)"
            for i, c in enumerate(top5[:5])
        ) or "  N/D"
        parts.append(
            f"📈 PERFORMANCE GLOBALE :\n"
            f"  - CA TTC : {fmt(kpis.get('ca_total_ttc'))}\n"
            f"  - Croissance YoY : {kpis.get('yoy_growth', 0):.1f}%\n"
            f"  - Nb clients actifs : {kpis.get('nb_clients', 0)}\n"
            f"  - Panier moyen : {fmt(kpis.get('panier_moyen'))}\n"
            f"  - Tendance : {kpis.get('tendance', 'N/D')}\n"
            f"  Top 5 clients :\n{top5_str}"
        )

    return "\n\n".join(parts)


def build_history_context(history: List[Dict[str, str]], max_turns: int = 8) -> str:
    """Formate les N derniers échanges de la conversation pour le contexte LLM."""
    if not history:
        return ""
    recent = history[-(max_turns * 2):]  # max_turns aller-retours
    lines = ["💬 HISTORIQUE DE CONVERSATION (contexte, ne pas répéter) :"]
    for msg in recent:
        role = msg.get("role", "user")
        text = (msg.get("text") or msg.get("content") or "").strip()
        if not text:
            continue
        prefix = "Utilisateur" if role == "user" else "Copilote"
        # Tronquer les réponses longues dans l'historique
        if len(text) > 300:
            text = text[:300] + "…"
        lines.append(f"  [{prefix}] : {text}")
    return "\n".join(lines)


def build_client_context(filters: Dict[str, Any], kpis: Dict[str, Any]) -> str:
    """Construit le contexte spécifique si un client est sélectionné."""
    clients = filters.get("selected_clients") or []
    if not clients:
        return ""

    top_clients = kpis.get("top_clients") or []
    client_names = [str(c) for c in clients[:5]]
    client_details = []
    for c in top_clients:
        c_id = str(c.get("client", ""))
        c_nom = c.get("nom") or c_id
        if c_id in client_names or c_nom in client_names:
            client_details.append(
                f"  • {c_nom} : CA={fmt(c.get('revenue'))}, "
                f"Factures={c.get('invoices', 0)}, "
                f"Part CA={c.get('share', 0):.1f}%, "
                f"Score risque={c.get('risk_score', 'N/D')}"
            )

    clients_at_risk = kpis.get("clients_a_risque") or []
    risk_details = []
    for r in clients_at_risk:
        r_id = str(r.get("client", ""))
        r_nom = r.get("nom") or r_id
        if r_id in client_names or r_nom in client_names:
            risk_details.append(
                f"  • {r_nom} : Montant à risque={fmt(r.get('montant_risque'))}, "
                f"Nb factures en retard={r.get('factures', 0)}"
            )

    scope_lines = [
        f"🎯 PÉRIMÈTRE CLIENT SÉLECTIONNÉ : {', '.join(client_names[:3])}"
        + (f" (+{len(clients)-3} autres)" if len(clients) > 3 else ""),
        "  ⚠️ Ta réponse doit se concentrer UNIQUEMENT sur ce(s) client(s).",
        "  Ne fais PAS de comparaisons avec d'autres clients non sélectionnés.",
    ]
    if client_details:
        scope_lines.append("  Données client(s) :")
        scope_lines.extend(client_details)
    if risk_details:
        scope_lines.append("  Risque client(s) :")
        scope_lines.extend(risk_details)

    return "\n".join(scope_lines)
