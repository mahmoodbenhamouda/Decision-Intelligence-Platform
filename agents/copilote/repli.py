"""Réponses DÉTERMINISTES, une par thème, quand aucun modèle de langage n'est disponible ou que sa…"""

from __future__ import annotations

from typing import Any, Dict, List

from agents.copilote import outils
from agents.copilote.glossaire import FINANCIAL_GLOSSARY, detect_glossary_terms
from agents.copilote.intention import detect_theme
from agents.copilote.outils import codes_perimetre, dt_montant, fmt


def reponse_deterministe(question: str, kpis: Dict[str, Any], filters: Dict[str, Any]) -> str:
    """Repli déterministe thématique — répond différemment selon le thème (sans LLM)."""
    themes = detect_theme(question)
    lines = []

    if "glossaire" in themes or any(
        kw in question.lower() for kw in ["c'est quoi", "définition", "signifie", "expliquer"]
    ):
        glossary_terms = detect_glossary_terms(question)
        if glossary_terms:
            lines.append("## 📚 Définitions financières\n")
            for term in glossary_terms:
                defn = FINANCIAL_GLOSSARY.get(term, "Terme non trouvé dans le glossaire.")
                lines.append(f"**{term}** : {defn}\n")
        else:
            lines.append("## 📚 Glossaire financier\n")
            lines.append("Je n'ai pas détecté de terme financier spécifique dans votre question. "
                         "Essayez par exemple : *DSO*, *BFR*, *marge brute*, *FOREX*, etc.\n")

    elif any(t in themes for t in ("modeles", "recommandation", "devis")):
        lines.extend(reponse_modeles(themes, kpis, filters))

    elif "recouvrement" in themes:
        top_risk = kpis.get("clients_relance") or kpis.get("clients_a_risque") or []
        periode = kpis.get("exposition_recente_periode", "6 derniers mois")
        expo = float(kpis.get("exposition_recente_dt") or 0)
        crit = float(kpis.get("exposition_recente_critique_dt") or 0)
        ca = float(kpis.get("ca_total_ttc") or 0)
        part = f", soit {expo / ca * 100:.1f} % du CA" if ca > 0 and expo > 0 else ""
        lines.append(f"**{fmt(expo)}** en retard de plus de 60 jours sur {periode}"
                     f"{part}, dont **{fmt(crit)}** au-delà de 90 jours "
                     f"({kpis.get('exposition_recente_count', 0)} factures).")
        lines.append("")
        for c in top_risk[:3]:
            lines.append(f"- 🔴 **{c.get('nom') or c.get('client')}** — {fmt(c.get('montant_risque'))} "
                         f"sur {c.get('factures', 0)} facture(s) → appel puis relance écrite")
        lines.append(f"- **DSO** (délai moyen d'encaissement) — {kpis.get('dso_jours', 0):.0f} jours")
        if top_risk:
            leader = top_risk[0]
            lines.append(f"\n**À faire :** relancer {leader.get('nom') or leader.get('client')} "
                         f"({fmt(leader.get('montant_risque'))}) sous 48 h ; échéancier si >90 jours.")
        else:
            lines.append("\n**À faire :** rien d'urgent — aucune créance de plus de 60 jours sur ce périmètre.")

    elif "change" in themes:
        mi = kpis.get("market_intel") or {}
        fx = mi.get("fx") or {}
        fxs = mi.get("fx_sensitivity") or {}
        impact = fxs.get("impact_per_1pct_dt")
        var = fx.get("eur_tnd_var_pct")
        lines.append(f"Une variation de 1 % du dinar déplace **{fmt(impact)}** sur vos achats importés"
                     + (f" ; l'EUR/TND a bougé de {var} % récemment." if var not in (None, "N/D") else "."))
        lines.append("")
        if fx:
            lines.append(f"- **Parités** — EUR/TND {fx.get('eur_tnd', 'N/D')}, "
                         f"USD/TND {fx.get('usd_tnd', 'N/D')}")
        if fxs:
            lines.append(f"- **Exposition annuelle** — {fmt(fxs.get('annual_fx_base_dt'))} d'achats en devises")
            lines.append(f"- 🟠 **VaR change** — {fmt(fxs.get('var_impact_dt'))} de perte estimée")
        else:
            lines.append("- Données de change non disponibles (veille non actualisée).")
        lines.append("\n**À faire :** couvrir à terme les achats importés si le dinar cède plus de 2 % sur un mois.")

    elif "tresorerie" in themes:
        cf = kpis.get("cash_forecast") or []
        cycle = kpis.get("cash_conversion_cycle", 0)
        lines.append(f"Votre cycle de conversion cash est de **{cycle:.0f} jours** "
                     f"(DSO {kpis.get('dso_jours', 0):.0f} j encaissés – "
                     f"DPO {kpis.get('dpo_jours', 0):.0f} j payés).")
        lines.append("")
        for p in cf[:3]:
            lines.append(f"- **{p['period']}** — {fmt(p['montant'])} d'encaissements attendus")
        if not cf:
            lines.append("- Prévision d'encaissement non disponible sur ce périmètre.")
        action = ("concentrer les relances sur le mois le plus creux ci-dessus."
                  if cf else "élargir la période pour obtenir une prévision.")
        lines.append(f"\n**À faire :** {action}")

    elif "marge" in themes:
        lines.append(f"Taux de marge de **{kpis.get('taux_marge', 0):.1f} %** pour "
                     f"{fmt(kpis.get('ca_total_ht'))} de CA HT, soit "
                     f"{fmt(kpis.get('marge_brute'))} de marge brute.")
        lines.append("")
        lines.append(f"- **Achats** — {fmt(kpis.get('achats_total_ttc'))} TTC")
        if kpis.get("marge_note"):
            lines.append(f"- 🟠 **Réserve** — {kpis['marge_note']}")
        lines.append("\n**À faire :** vérifier les familles sous la marge moyenne avant toute remise commerciale.")
        try:
            from ml_engine import passerelle as pw
            mg = pw.marge_clients()
            codes = set(codes_perimetre(filters))
            top = [c for c in (mg.get("top") or []) if not codes or str(c.get("client")) in codes][:3]
            if mg.get("servi") and top:
                noms = pw.noms_clients()
                lines.append("\n**Rentabilité en baisse dans les 3 mois** — "
                             + " ; ".join(f"{noms.get(str(c['client']), c['client'])} "
                                          f"({float(c['probabilite']):.0%}, {dt_montant(c['marge_en_jeu_dt'])} en jeu)"
                                          for c in top))
        except Exception:
            pass

    elif "prevision" in themes and "risque_stock" not in themes:
        fc = kpis.get("forecast_next") or []
        lines.append("## 🔮 Prévision de chiffre d'affaires\n")
        if fc:
            for p in fc:
                lines.append(f"- **{p['period']}** : {fmt(p['montant'])} (projection)")
            lines.append(f"\nBase : tendance sur {len(kpis.get('monthly_sales') or [])} mois d'historique.")
        else:
            lines.append("Historique insuffisant pour générer une prévision fiable.")

    elif "fidelite" in themes:
        fideles = kpis.get("clients_fideles") or []
        if fideles:
            leader = fideles[0]
            lines.append(f"**{leader.get('nom')}** est votre relation la plus régulière : "
                         f"{leader.get('mois_actifs', 0)} mois d'activité pour "
                         f"{fmt(leader.get('revenue'))} de CA.")
            lines.append("")
            for c in fideles[:4]:
                lines.append(f"- **{c.get('nom')}** — {c.get('mois_actifs', 0)} mois actifs, "
                             f"{c.get('invoices', 0)} factures, {fmt(c.get('revenue'))}")
            lines.append(f"\n**À faire :** sécuriser {leader.get('nom')} par un contrat-cadre, "
                         f"et cibler les prospects au profil comparable.")
        else:
            lines.append("Pas assez d'historique multi-mois sur ce périmètre pour identifier "
                         "des clients récurrents.")
            lines.append("\n**À faire :** élargir la période ou retirer les filtres client.")

    elif "opportunites" in themes:
        mi = kpis.get("market_intel") or {}
        news = mi.get("news") or []
        if news:
            lines.append(f"**{len(news)}** opportunité(s) détectée(s) par la veille.")
            lines.append("")
            for n in news[:4]:
                lines.append(f"- **[{n.get('type','?')}]** {n.get('title','')[:90]}"
                             + (f" → {n['reco']}" if n.get("reco") else ""))
            lines.append("\n**À faire :** qualifier les dossiers rattachés à un client connu en priorité.")
        else:
            lines.append("Aucun appel d'offres récent détecté.")
            lines.append("\n**À faire :** rafraîchir la veille depuis l'onglet Opportunités.")

    elif "risque_stock_client" in themes:
        cl = outils.stock_par_client(limite=5)
        if cl.get("error"):
            lines.append(f"Classement du stock par client indisponible : {cl['error']}")
            lines.append("\n**À faire :** `python -m ml_engine.stock.generator`.")
        else:
            def _nom(c):
                return c["client"] if c["nom_resolu"] else f"{c['code']} (sans libellé ERP)"

            def _dt(v):
                return f"{v:,.0f}".replace(",", " ")

            sains = cl["clients_sans_risque"]
            lines.append(
                f"**{cl['n_clients_sans_risque']} clients sur {cl['n_clients_analyses']}** "
                f"n'ont aucune référence à risque — ni rupture, ni surstock, ni à commander.")
            lines.append("")
            if sains:
                for c in sains:
                    lines.append(f"- 🟢 **{_nom(c)}** — {c['n_references']} références saines, "
                                 f"{_dt(c['valeur_stock_dt'])} DT de stock")
            else:
                lines.append("- Aucun client n'est totalement exempt de risque sur ce périmètre.")
            gros = cl["top_par_valeur"][0]
            lines.append(f"- 🔴 **{_nom(gros)}** — plus gros stock "
                         f"({_dt(gros['valeur_stock_dt'])} DT) mais {gros['n_a_risque']} "
                         f"références à risque")
            if sains:
                refs = [c["n_references"] for c in sains]
                etendue = (f"{min(refs)} à {max(refs)} références"
                           if min(refs) != max(refs) else f"{min(refs)} références")
                lines.append(f"\n**À faire :** ces comptes sains sont de petits portefeuilles "
                             f"({etendue}) — concentrer l'effort sur les gros comptes exposés.")
            else:
                lines.append("\n**À faire :** traiter en priorité les comptes les plus exposés.")
            lines.append("\n_Stock simulé, demande réelle (docs/STOCK_SIMULE.md)._")

    elif "palmares" in themes:
        tops = kpis.get("top_clients") or []
        share5 = kpis.get("top_clients_revenue_share")
        if tops:
            lines.append(f"**{tops[0].get('nom') or tops[0].get('client')}** est votre premier client avec "
                         f"{fmt(tops[0].get('revenue'))}"
                         + (f" ; vos 5 premiers pèsent **{share5:.0f} %** du CA." if share5 is not None else "."))
            lines.append("")
            for c in tops[:5]:
                lines.append(f"- **{c.get('nom') or c.get('client')}** — {fmt(c.get('revenue'))} "
                             f"({c.get('share', 0):.1f} % du CA, {c.get('invoices', 0)} factures)")
            lines.append("\n**À faire :** sécuriser les trois premiers comptes par un contrat-cadre.")
        else:
            lines.append("Aucun client sur ce périmètre.")

    elif "attrition" in themes:
        dec = kpis.get("clients_decrochent") or []
        if dec:
            leader = dec[0]
            perte = (leader.get("ca_prev") or 0) - (leader.get("ca_recent") or 0)
            lines.append(f"**{len(dec)}** client(s) établi(s) en fort décrochage ; le plus lourd est "
                         f"**{leader.get('nom')}**, {fmt(perte)} de CA perdu sur le trimestre.")
            lines.append("")
            for c in dec[:4]:
                lines.append(f"- 🔴 **{c.get('nom')}** — {fmt(c.get('ca_prev'))} → {fmt(c.get('ca_recent'))} "
                             f"sur 90 j (−{c.get('chute_pct', 0):.0f} %), inactif depuis "
                             f"{c.get('jours_inactif', 0)} j")
            lines.append(f"\n**À faire :** appeler {leader.get('nom')} cette semaine pour identifier la cause "
                         f"(prix, concurrence, satisfaction).")
        else:
            lines.append("Aucun décrochage marqué : les clients établis maintiennent leur niveau d'achat.")
            lines.append("\n**À faire :** rien sur ce périmètre.")
        try:
            from ml_engine import passerelle as pw
            ch = pw.decrochage(kpis=kpis)
            codes = set(codes_perimetre(filters))
            top = [c for c in (ch.get("top") or []) if not codes or str(c.get("code")) in codes][:3]
            if ch.get("servi") and top:
                lines.append("\n**Susceptibles de partir dans les 90 jours** — "
                             + " ; ".join(f"{c.get('nom')} ({float(c.get('probabilite_decrochage') or 0):.0%}, "
                                          f"{dt_montant(c.get('enjeu_dt'))} en jeu)" for c in top))
        except Exception:
            pass

    elif "concentration" in themes:
        n80 = kpis.get("clients_pour_80pct") or 0
        ntot = kpis.get("nb_clients_ca") or kpis.get("nb_clients") or 0
        share5 = kpis.get("top_clients_revenue_share")
        hhi = kpis.get("hhi_clients")
        top5 = kpis.get("top_clients") or []
        pct = (n80 / ntot * 100) if ntot else 0
        niveau = ("très concentré" if pct < 15 else
                  "concentré" if pct < 30 else "bien diversifié")
        lines.append(f"Portefeuille **{niveau}** : **{n80}** clients sur {ntot} réalisent 80 % du CA "
                     f"({pct:.0f} % du portefeuille).")
        lines.append("")
        if share5 is not None:
            lines.append(f"- **Top 5** — {share5:.0f} % du CA")
        if hhi is not None:
            lines.append(f"- **HHI** (indice de concentration) — {hhi:.0f}/10000, "
                         f"{'concentré' if hhi > 2500 else 'peu concentré'}")
        if top5:
            lines.append("- **Poids principaux** — " + ", ".join(
                f"{c.get('nom') or c.get('client')} {c.get('share', 0):.0f} %" for c in top5[:3]))
        lines.append("\n**À faire :** élargir la base clients pour réduire la dépendance aux premiers comptes.")

    elif "risque_stock" in themes:
        try:
            ctx = outils.contexte_stock_reel(kpis)
        except Exception as e:
            ctx = {"flux": {}, "fin_de_vie": {}, "risque_stock": {"motif": str(e)}}
        flux, fdv = ctx["flux"], ctx["fin_de_vie"]
        if not flux.get("disponible"):
            lines.append("Stock reconstruit indisponible : lancer `python -m ml_engine.stock.flux_reels`.")
        else:
            lines.append(f"**{dt_montant(flux.get('perte_quasi_certaine_dt'))}** de stock ne seront pas écoulés "
                         f"avant péremption, sur {flux.get('n_obsoletes_certains', 0)} référence(s) ; "
                         f"{dt_montant(flux.get('valeur_immobilisee_dt'))} immobilisés au total.")
            lines.append("")
            for o in [o for o in (flux.get("obsolescence") or [])
                      if o.get("gravite") == "perte_quasi_certaine"][:3]:
                lines.append(f"- 🔴 **{str(o.get('produit'))[:40]}** — {dt_montant(o.get('perte_probable_dt'))} "
                             "de perte quasi certaine (plus de deux ans de consommation en stock)")
            for r in (flux.get("ruptures") or [])[:3]:
                lines.append(f"- 🟠 **{r['produit'][:40]}** — encore vendu, approvisionnement "
                             f"interrompu ({r['gravite']})")
            if fdv.get("servi") and fdv.get("top"):
                t = fdv["top"][0]
                lines.append(f"- 🟡 **{t['produit'][:40]}** — fin de commercialisation probable, "
                             f"{dt_montant(t['capital_expose_dt'])} de capital exposé")
            lines.append("\n**À faire :** écouler ou renégocier le stock non écoulable, et commander "
                         "les références en rupture — ce ne sont pas les mêmes produits.")
            lines.append("\n_Chiffres calculés à partir de vos factures d'achat et de vente._")

    elif "approvisionnement" in themes:
        d = outils.demande_et_fournisseurs()
        top = (d.get("fournisseurs_top") or [{}])
        nom1 = top[0].get("fournisseur", "N/D")
        lines.append(f"Dépendance fournisseur **{d.get('dependance_fournisseur', 'n/d')}** : "
                     f"**{nom1}** représente **{d.get('fournisseur_top1_pct', 0)} %** de vos achats.")
        lines.append("")
        lines.append(f"- **Concentration** — top 3 à {d.get('fournisseurs_top3_pct', 0)} %, "
                     f"{d.get('fournisseurs_nb', 0)} fournisseurs, HHI {d.get('fournisseurs_hhi', 0):.0f}")
        fc = d.get("demande_prevision") or []
        if fc:
            lines.append(f"- **Demande prévue** (articles/mois, MAPE {d.get('demande_mape')} %) — "
                         + ", ".join(f"{p['period']} ≈ {int(p['qte'])}" for p in fc))
        lines.append(f"\n**À faire :** référencer une 2ᵉ source pour réduire la dépendance à {nom1}.")
        lines.append("\n_Analyse de la demande et du risque fournisseur : aucun relevé de "
                     "stock par référence n'est disponible._")

    else:
        lines.append(f"**{fmt(kpis.get('ca_total_ttc'))}** de CA TTC, croissance "
                     f"**{kpis.get('yoy_growth', 0):.1f} %** sur un an, "
                     f"{kpis.get('nb_clients', 0)} clients actifs.")
        lines.append("")
        lines.append(f"- **Encaissement** — DSO {kpis.get('dso_jours', 0):.0f} jours")
        crit = kpis.get("factures_delai_sup_90j", 0)
        lines.append(f"- {'🟠' if crit else '🟢'} **Délais accordés > 90 jours** — "
                     f"{crit} facture(s)")
        lines.append("\n**À faire :** " + (
            "revoir les conditions de paiement accordées sur ces factures."
            if crit else "aucune condition de paiement hors norme sur ce périmètre."))

    return "\n".join(lines)


def reponse_modeles(themes: List[str], kpis: Dict[str, Any],
                    filters: Dict[str, Any]) -> List[str]:
    """Repli déterministe des thèmes servis par les modèles (passerelle)."""
    from ml_engine import passerelle as pw
    codes = set(codes_perimetre(filters))
    lines: List[str] = []
    if "modeles" in themes:
        tab = pw.tableau_des_modeles()
        servis = [c for c in tab if c.get("servi")]
        lines.append(f"**{len(servis)} modules servis sur {len(tab)}**, chacun validé hors période "
                     "avant d'être utilisé :")
        lines.append("")
        for c in tab:
            icone = "🟢" if c.get("servi") else "⚪"
            etat = "servi" if c.get("servi") else "retiré" if c.get("retire") else "refusé"
            lines.append(f"- {icone} **{c.get('libelle')}** ({etat}) — {pw.formater_metrique(c)}")
        lines.append("\n_L'accuracy est comparée à la classe majoritaire : sur une cible rare, "
                     "la balanced accuracy mesure mieux la détection des cas positifs._")
    elif "recommandation" in themes:
        r = (pw.recommandations(client=sorted(codes)[0]) if codes else pw.recommandations())
        if not r.get("servi"):
            lines.append(f"Recommandations indisponibles : {r.get('motif')}.")
        elif codes:
            lines.append(f"Produits que **{r.get('nom')}** n'a jamais achetés et qu'il est le plus "
                         f"susceptible d'adopter dans les {r.get('horizon_mois', 6)} mois :")
            lines.append("")
            for p in (r.get("produits") or [])[:5]:
                lines.append(f"- **{p['designation'][:45]}** ({p['famille']}) — adopté par "
                             f"{p['adoption_meme_type_pct']:.0f} % des établissements du même type")
        else:
            lines.append("Meilleures opportunités de vente croisée (produits jamais achetés par ces clients) :")
            lines.append("")
            for c in (r.get("top") or [])[:5]:
                lines.append(f"- **{c['nom']}** — " + ", ".join(p["designation"][:35] for p in c["produits"][:3])
                             + f" (ordre de grandeur {dt_montant(c['potentiel_top3_dt'])}/an)")
    elif "devis" in themes:
        cv = pw.conversion_devis()
        if not cv.get("servi"):
            lines.append(f"Scoring des devis indisponible : {cv.get('motif')}.")
        else:
            noms = pw.noms_clients()
            top = [d for d in (cv.get("top") or []) if not codes or str(d.get("client")) in codes][:5]
            lines.append(f"**{cv.get('n_devis', 0)} devis ouverts** représentent "
                         f"**{dt_montant(cv.get('esperance_totale_dt'))}** de ventes probables.")
            lines.append("")
            for d in top:
                lines.append(f"- **{noms.get(str(d['client']), d['client'])}** — {dt_montant(d['montant_ht_dt'])} HT, "
                             f"signature probable à {float(d['probabilite']):.0%}")
            lines.append("\n**À faire :** relancer d'abord les devis qui rapportent le plus s'ils sont signés.")
    return lines
