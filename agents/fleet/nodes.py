"""
Agents (nœuds) de la flotte.

Chaque agent est une fonction pure `node(state) -> partial_state`. Les
collecteurs remplissent `kpis` (interne) et `intel` (externe) ; les spécialistes
lisent ces données et ajoutent un `finding` ; le rédacteur synthétise le tout.
"""

from __future__ import annotations

from typing import Any, Dict, List


# ── Utilitaires ─────────────────────────────────────────────────────────────
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


# ── Collecteurs ─────────────────────────────────────────────────────────────
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


def veille_externe(state: Dict[str, Any]) -> Dict[str, Any]:
    """Agent Veille : récupère les signaux externes (cache de veille, sinon ERP)."""
    intel: Dict[str, Any] = {}
    try:
        from agents.veille_agent import load_market_intel
        intel = load_market_intel() or {}
    except Exception:
        intel = {}
    if not intel:
        intel = (state.get("kpis") or {}).get("market_intel") or {}
    n_news = len(intel.get("news") or [])
    fx = (intel.get("fx") or {}).get("eur_tnd")
    return {
        "intel": intel,
        "trace": [_log("📡 Veille externe", "ok" if intel else "vide",
                       f"{n_news} actualité(s), EUR/TND={fx or 'N/D'}")],
    }


# ── Agents spécialistes ─────────────────────────────────────────────────────
def _relevance_accuracy() -> Optional[float]:
    """Lit l'accuracy du modèle de pertinence (pour l'afficher dans le constat)."""
    try:
        import json
        from pathlib import Path
        p = Path(__file__).resolve().parents[2] / "reports" / "tender_relevance_metrics.json"
        return json.loads(p.read_text(encoding="utf-8")).get("accuracy")
    except Exception:
        return None


def agent_opportunites(state: Dict[str, Any]) -> Dict[str, Any]:
    """Scrape les appels d'offres, les classe par pertinence (modèle entraîné) et
    les matche aux clients existants (NLP sémantique)."""
    kpis = state.get("kpis") or {}

    # 1) SCRAPING réel (repli hors-ligne intégré)
    try:
        from agents.fleet.scraper import scrape_tenders
        items = scrape_tenders(max_items=25)
    except Exception:
        items = []

    # 2) CLASSIFICATION de pertinence (modèle entraîné, accuracy ~0.93)
    try:
        from ml_engine.nlp.tender_relevance import predict_relevance
        probs = predict_relevance([it["title"] for it in items]) if items else []
    except Exception:
        probs = [0.0] * len(items)

    # noms clients pour le matching sémantique
    noms_clients = [(c.get("nom") or c.get("client")) for c in (kpis.get("top_clients") or [])]
    noms_clients += [c.get("nom") for c in (kpis.get("clients_fideles") or [])]
    noms_clients = [c for c in noms_clients if c]
    try:
        from ml_engine.nlp.tender_matcher import match_candidates
    except Exception:
        match_candidates = None

    pertinents: List[Dict[str, Any]] = []
    for it, p in zip(items, probs):
        if p >= 0.5:
            cli, cs = (None, 0.0)
            if match_candidates and noms_clients:
                cli, cs = match_candidates(it["title"], noms_clients, threshold=0.0)
            pertinents.append({
                "title": it["title"], "score": round(float(p), 2),
                "client": cli if cs >= 0.35 else None, "client_score": round(float(cs), 2),
                "source": it.get("source"), "url": it.get("url"),
            })
    pertinents.sort(key=lambda x: x["score"], reverse=True)

    acc = _relevance_accuracy()
    acc_txt = f" (modèle pertinence, accuracy {acc:.2f})" if acc else ""
    n_scan, n_rel = len(items), len(pertinents)
    top = pertinents[:3]
    apercu = " ; ".join(f"« {o['title'][:55]}… » ({o['score']})" for o in top) or "aucun AO pertinent capté"
    finding = {
        "agent": "Opportunités",
        "categorie": "Développement",
        "severite": "moyenne" if n_rel else "faible",
        "titre": "Appels d'offres pertinents (scrapés + classés)",
        "montant_dt": 0,
        "constat": f"{n_scan} AO scannés → {n_rel} jugés pertinents{acc_txt}. Top : {apercu}.",
        "action": "Cibler d'abord les AO matchés à un client existant ; préparer un devis rapide.",
        "top_opportunites": top,
    }
    return {"findings": [finding],
            "trace": [_log("🎯 Agent Opportunités", "ok", f"{n_scan} scannés / {n_rel} pertinents")]}


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
        "montant_dt": round(float(expo or 0), 0),
        "constat": (f"{_fmt(expo)} d'exposition récente en retard >60j ({periode}), "
                    f"dont {_fmt(crit)} critique (>90j) sur {cnt} facture(s)."),
        "action": f"Relancer en priorité : {noms} (appel + relance écrite, échéancier si >90j).",
    }
    return {"findings": [finding], "trace": [_log("📋 Agent Recouvrement", "ok", f"{len(risque)} débiteurs récents")]}


def agent_tresorerie(state: Dict[str, Any]) -> Dict[str, Any]:
    kpis = state.get("kpis") or {}
    intel = state.get("intel") or {}
    fxs = (kpis.get("market_intel") or {}).get("fx_sensitivity") or kpis.get("fx_sensitivity") or {}
    fx = intel.get("fx") or (kpis.get("market_intel") or {}).get("fx") or {}
    var = fx.get("eur_tnd_var_pct")
    impact = fxs.get("var_impact_dt") or fxs.get("impact_per_1pct_dt")
    finding = {
        "agent": "Trésorerie / Change",
        "categorie": "Trésorerie",
        "severite": "moyenne",
        "titre": "Trésorerie & exposition au change",
        "montant_dt": round(float(impact or 0), 0),
        "constat": (f"DSO {kpis.get('dso_jours', 0):.0f}j / DPO {kpis.get('dpo_jours', 0):.0f}j ; "
                    f"variation EUR/TND {var if var is not None else 'N/D'}%, "
                    f"impact estimé {_fmt(impact)} sur les achats importés."),
        "action": "Aligner les relances sur les creux d'encaissement ; envisager une couverture si le dinar se déprécie.",
    }
    return {"findings": [finding], "trace": [_log("💰 Agent Trésorerie/Change", "ok")]}


def agent_risque(state: Dict[str, Any]) -> Dict[str, Any]:
    kpis = state.get("kpis") or {}
    dec = kpis.get("clients_decrochent") or []
    top = dec[:3]
    noms = ", ".join(c.get("nom") for c in top) or "aucun"
    finding = {
        "agent": "Risque client",
        "categorie": "Rétention",
        "severite": "haute" if dec else "faible",
        "titre": "Clients qui décrochent",
        "montant_dt": round(sum(float(c.get("ca_prev") or 0) - float(c.get("ca_recent") or 0) for c in top), 0),
        "constat": (f"{len(dec)} client(s) établi(s) en fort décrochage (CA 90j en chute >60%)."
                    if dec else "Aucun décrochage marqué détecté."),
        "action": (f"Recontacter d'urgence : {noms} (comprendre la cause avant de perdre le compte)."
                   if dec else "Maintenir le suivi commercial habituel."),
    }
    return {"findings": [finding], "trace": [_log("📉 Agent Risque client", "ok", f"{len(dec)} en décrochage")]}


def agent_approvisionnement(state: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse la demande (prévision + MAPE) et le risque de dépendance fournisseur."""
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
    fc_txt = ", ".join(f"{p['period']}: {int(p['qte'])}" for p in fc) or "N/D"
    sev = "haute" if dep in ("critique", "élevée") else "moyenne"
    finding = {
        "agent": "Approvisionnement",
        "categorie": "Approvisionnement",
        "severite": sev,
        "titre": "Demande prévisionnelle & dépendance fournisseur",
        "montant_dt": 0,
        "constat": (f"Dépendance fournisseur {dep} : {top1_name} = {top1_pct}% des achats "
                    f"(top 3 = {d.get('fournisseurs_top3_pct', 0)}%). "
                    f"Prévision demande 3 mois en articles (MAPE {mape}%) : {fc_txt}."),
        "action": ("Sécuriser une 2e source d'approvisionnement pour réduire la dépendance ; "
                   "caler les commandes sur la prévision et anticiper les pics saisonniers."),
    }
    return {"findings": [finding],
            "trace": [_log("📦 Agent Approvisionnement", "ok", f"dépendance {dep}, MAPE {mape}%")]}


# ── Rédacteur (synthèse) ────────────────────────────────────────────────────
_SEV_ORDER = {"critique": 0, "haute": 1, "moyenne": 2, "faible": 3}
_SEV_ICON = {"critique": "🔴", "haute": "🟠", "moyenne": "🟡", "faible": "🟢"}


def _deterministic_briefing(findings: List[Dict[str, Any]], kpis: Dict[str, Any]) -> str:
    findings = sorted(findings, key=lambda f: _SEV_ORDER.get(f.get("severite"), 4))
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
    return "\n".join(lines)


def redacteur(state: Dict[str, Any]) -> Dict[str, Any]:
    """Agent Rédacteur : synthétise les constats des agents en un briefing (LLM sinon déterministe)."""
    findings = state.get("findings") or []
    kpis = state.get("kpis") or {}
    question = state.get("question") or ""

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
                for f in findings
            )
            prompt = (
                "Tu es le rédacteur d'une cellule d'intelligence financière. À partir des constats "
                "des agents ci-dessous, rédige un briefing exécutif en français, concis et priorisé "
                "(Markdown, titres, puces), qui met en avant les 3 actions les plus urgentes et chiffrées. "
                "Ne fais pas de remplissage.\n\n"
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
                                "trace": [_log("✍️ Rédacteur", "ok", "briefing LLM")]}
                except Exception:
                    continue
        except Exception:
            pass

    return {"briefing": _deterministic_briefing(findings, kpis),
            "trace": [_log("✍️ Rédacteur", "ok", "briefing déterministe")]}
