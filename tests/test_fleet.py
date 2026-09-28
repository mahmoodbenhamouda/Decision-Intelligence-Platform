"""
tests/test_fleet.py
===================
Tests unitaires et d'intégration de la flotte multi-agents.

Principes :
- Données FACTICES injectées dans l'état (aucune dépendance réseau/entrepôt).
- Cas limites : état vide, KPIs manquants, agent qui lève une exception.
- Robustesse : AUCUN agent ne doit faire planter le briefing (décorateur
  `_safe_node`), et le briefing déterministe doit rester priorisé.

Exécution :
    python -m pytest tests/test_fleet.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agents.fleet import nodes
from agents.fleet.graph import run_briefing, _run_sequential


# ── État factice ────────────────────────────────────────────────────────────
FAKE_KPIS = {
    "ca_total_ttc": 1_500_000.0,
    "nb_clients": 42,
    "yoy_growth": 4.2,
    "exposition_recente_dt": 250_000.0,
    "exposition_recente_critique_dt": 90_000.0,
    "exposition_recente_count": 7,
    "exposition_recente_periode": "6 derniers mois",
    "clients_relance": [
        {"client": "C001", "nom": "CHU SFAX", "montant": 120_000},
        {"client": "C002", "nom": "CLINIQUE EL AMEN", "montant": 80_000},
    ],
    "clients_decrochent": [
        {"nom": "LABO PASTEUR", "ca_prev": 60_000, "ca_recent": 10_000},
    ],
    "dso_jours": 78.0,
    "dpo_jours": 45.0,
    "top_clients": [{"client": "C001", "nom": "CHU SFAX"}],
    "montant_risque_ttc": 11_220_000.0,
    # Chiffre d'affaires des 12 derniers mois : sert à convertir le cycle
    # d'encaissement (en jours) en besoin de financement (en dinars).
    "ttm_revenue": 36_500_000.0,
}


def fake_state():
    # Plus de clé `intel` : la veille externe a été retirée du projet, l'état ne
    # transporte que les données internes issues de l'entrepôt ERP.
    return {"filters": {}, "question": "", "findings": [], "trace": [],
            "kpis": dict(FAKE_KPIS)}


REQUIRED_FINDING_KEYS = {"agent", "categorie", "severite", "titre", "montant_dt",
                         "constat", "action"}


# ── Tests unitaires par agent ───────────────────────────────────────────────
@pytest.mark.parametrize("agent_fn", [
    nodes.agent_recouvrement, nodes.agent_tresorerie, nodes.agent_risque,
])
def test_agent_produit_un_constat_structure(agent_fn):
    out = agent_fn(fake_state())
    assert "findings" in out and len(out["findings"]) == 1
    f = out["findings"][0]
    assert REQUIRED_FINDING_KEYS.issubset(f.keys())
    assert f["severite"] in {"critique", "haute", "moyenne", "faible"}
    assert isinstance(f["montant_dt"], (int, float))
    assert out["trace"][0]["status"] in {"ok", "vide"}


def test_recouvrement_chiffre_et_source():
    """Chaque recommandation doit être CHIFFRÉE et actionnable (pas générique)."""
    f = nodes.agent_recouvrement(fake_state())["findings"][0]
    assert "250.0 K DT" in f["constat"] or "250" in f["constat"]
    assert "90" in f["constat"]              # montant critique
    assert "CHU SFAX" in f["action"]         # débiteur nommé → actionnable


def test_risque_client_detecte_le_decrochage():
    f = nodes.agent_risque(fake_state())["findings"][0]
    assert f["severite"] == "haute"
    assert "LABO PASTEUR" in f["action"]
    # perte estimée = ca_prev - ca_recent = 50 000
    assert f["montant_dt"] == 50_000


# ── Rapprochement trésorerie ↔ stock ────────────────────────────────────────
def test_tresorerie_convertit_le_cycle_en_dinars():
    """Le besoin de financement doit être annualisé sur les 12 DERNIERS mois.

    L'utiliser sur le chiffre d'affaires cumulé de tout l'historique donnerait un
    montant sans rapport avec l'exercice en cours — sept ans de facturation
    additionnés produiraient un besoin plusieurs fois supérieur à la réalité.
    """
    out = nodes.agent_tresorerie(fake_state())
    f = out["findings"][0]
    # (78 − 45) / 365 × 36 500 000 = 3 300 000
    attendu = (78.0 - 45.0) / 365.0 * 36_500_000.0
    assert abs(f["montant_dt"] - attendu) < 1_000, (
        f"besoin de financement = {f['montant_dt']}, attendu ≈ {attendu:.0f}")


def _etat_avec_flux_reels(immo: float = 1_200_000.0,
                          perte: float = 85_000.0) -> dict:
    """État de flotte portant des flux de stock RÉELS.

    La version précédente de ces tests injectait le stock en remplaçant le module
    `ml_engine.stock` par un faux — autrement dit en simulant le module SIMULÉ.
    L'agent Trésorerie ne le lit plus : un montant généré placé dans une phrase
    sur le besoin en fonds de roulement est indistinguable d'un montant mesuré
    pour le lecteur, et ce repli a été supprimé plutôt que rendu plus prudent.

    Le stock arrive désormais par `kpis["stock_flux_reel"]`, reconstruit des
    factures. L'intention des tests est inchangée ; seule leur source l'est.
    """
    etat = fake_state()
    etat.setdefault("kpis", {})["stock_flux_reel"] = {
        "disponible": True,
        "valeur_immobilisee_dt": immo,
        "perte_quasi_certaine_dt": perte,
        "n_references_accumulees": 1386,
        "n_references_plus_de_2_ans": 15,
    }
    return etat


def test_tresorerie_rapproche_le_stock_dormant():
    """Le stock immobilisé doit apparaître DANS le constat de trésorerie.

    C'est tout l'objet du rapprochement : sans lui, la flotte produisait deux
    constats séparés — un besoin de financement, un montant immobilisé — que le
    lecteur devait relier lui-même, alors que le second est une composante du
    premier.
    """
    f = nodes.agent_tresorerie(_etat_avec_flux_reels())["findings"][0]
    constat = f["constat"]

    assert "stock" in constat.lower(), "le stock immobilisé doit être mentionné"
    assert "1.20 M" in constat or "1 200" in constat.replace(" ", " "), \
        f"le montant immobilisé doit figurer : {constat}"
    # La péremption est une perte sèche, pas un décalage de trésorerie : la
    # distinction doit être faite, sinon les deux montants paraissent de même
    # nature alors que l'un est récupérable et l'autre non.
    assert "périmera" in constat or "perte sèche" in constat
    # La réserve doit voyager avec le chiffre. Elle a changé de NATURE avec sa
    # source : les quantités ne sont plus « estimées », elles sont reconstruites
    # des factures — mais le montant reste un MINORANT, le stock antérieur à
    # l'historique étant inconnu. Taire cela laisserait croire à un inventaire.
    assert "minorant" in constat.lower(), (
        f"le constat doit rappeler qu'il s'agit d'un minorant : {constat}")
    assert "trésorerie" in f["action"].lower()


def test_tresorerie_se_tait_sans_flux_reels():
    """Sans mesure réelle, la partie stock doit être ABSENTE — jamais estimée.

    Un repli existait : l'agent lisait le module (s,S) simulé quand les flux réels
    manquaient, et annonçait alors un surstock généré comme une part du besoin de
    financement. Ce test verrouille sa suppression — il échouerait si quelqu'un le
    rebranchait « juste pour que l'écran ne soit pas vide ».
    """
    etat = fake_state()
    etat.setdefault("kpis", {})["stock_flux_reel"] = {
        "disponible": False, "motif": "table absente"}

    f = nodes.agent_tresorerie(etat)["findings"][0]
    assert REQUIRED_FINDING_KEYS.issubset(f.keys())
    constat = f["constat"]

    assert "DSO" in constat, "le constat de cycle doit subsister"
    for interdit in ("stock", "dorment", "immobilis", "périmera"):
        assert interdit not in constat.lower(), (
            f"« {interdit} » apparaît alors qu'aucune mesure réelle n'existe : "
            "un repli simulé a probablement été réintroduit")


def test_volet_stock_ne_lit_plus_le_module_simule():
    """Le volet stock doit se taire sans flux réels, et non retomber sur le généré.

    Sa version précédente produisait un constat entier — stock valorisé, points de
    commande, pertes par péremption — dont aucune valeur n'était observée. Le
    préfixe `[SIMULATION]` rendait cela honnête et inexploitable : un briefing dont
    la moitié des chiffres sont générés n'est pas un briefing.
    """
    etat = fake_state()
    etat.setdefault("kpis", {})["stock_flux_reel"] = {
        "disponible": False, "motif": "table absente"}

    out = nodes.constat_stock(etat)
    assert not out.get("findings"), (
        "le volet stock produit un constat sans aucune mesure réelle")
    assert out["trace"][0]["status"] == "vide"

    # Et avec des flux réels, le constat doit être marqué comme NON simulé.
    out = nodes.constat_stock(_etat_avec_flux_reels())
    f = out["findings"][0]
    assert f["is_simulated"] is False, (
        "le drapeau `is_simulated` doit être présent et FAUX — le supprimer "
        "ferait disparaître une garantie au lieu de l'affirmer")
    assert "1.20 M" in f["constat"] or "1 200" in f["constat"].replace(" ", " ")


# ── Arbitre : hiérarchisation inter-domaines ────────────────────────────────
def test_arbitre_compare_sur_une_echelle_commune():
    """Les montants bruts ne sont pas comparables entre domaines.

    100 000 DT de créance en retard et 100 000 DT de marchandise périmée ne
    pèsent pas pareil : le premier est un décalage, le second une perte sèche.
    L'arbitre doit les pondérer avant de les classer, sinon il compare des
    grandeurs de natures différentes.
    """
    etat = {"findings": [
        {"agent": "Stock", "categorie": "Stock", "severite": "moyenne",
         "titre": "Surstock", "montant_dt": 1_000_000,
         "constat": "…", "action": "déstocker"},
        {"agent": "Recouvrement", "categorie": "Recouvrement", "severite": "haute",
         "titre": "Créances", "montant_dt": 1_000_000,
         "constat": "…", "action": "relancer"},
    ], "trace": []}

    f = nodes.arbitre(etat)["findings"][0]
    cl = {c["titre"]: c for c in f["classement"]}

    # Coefficients : recouvrement 0,15 contre stock 0,10 → à montant égal, la
    # créance passe devant.
    assert cl["Créances"]["rang"] < cl["Surstock"]["rang"], (
        "à montant brut égal, une créance récupérable doit primer sur du stock")
    assert cl["Créances"]["enjeu_court_terme_dt"] > cl["Surstock"]["enjeu_court_terme_dt"]
    assert cl["Créances"]["nature_economique"] != cl["Surstock"]["nature_economique"]


def test_arbitre_detecte_un_client_signale_par_deux_domaines():
    """Le croisement que seul l'arbitre peut faire.

    Un client qui doit de l'argent ET qui cesse de commander cumule deux risques
    dont la conjonction change la nature : la créance devient douteuse, puisque
    le levier commercial permettant de négocier disparaît avec la relation.

    Aucun agent ne peut le voir — le recouvrement ignore le décrochage, le
    risque client ignore les impayés.
    """
    etat = {"findings": [
        {"agent": "Recouvrement", "categorie": "Recouvrement", "severite": "haute",
         "titre": "Créances", "montant_dt": 500_000, "constat": "…", "action": "…",
         "clients_concernes": [{"nom": "UNOPS", "montant_dt": 300_000},
                               {"nom": "CHU SFAX", "montant_dt": 200_000}]},
        {"agent": "Risque client", "categorie": "Rétention", "severite": "haute",
         "titre": "Décrochage", "montant_dt": 400_000, "constat": "…", "action": "…",
         "clients_concernes": [{"nom": "UNOPS", "montant_dt": 400_000}]},
    ], "trace": []}

    f = nodes.arbitre(etat)["findings"][0]
    cumuls = f.get("clients_multi_signaux") or []

    assert cumuls, "aucun client multi-signaux détecté"
    assert cumuls[0]["client"].upper() == "UNOPS"
    assert len(cumuls[0]["domaines"]) == 2
    # CHU SFAX n'apparaît que dans un domaine : il ne doit pas être signalé.
    assert all(c["client"].upper() != "CHU SFAX" for c in cumuls)
    # Le cumul doit remonter dans le constat ET dans l'action.
    assert "UNOPS" in f["constat"] and "UNOPS" in f["action"]


def test_arbitre_ne_produit_aucun_score_global():
    """L'arbitre ordonne, il ne résume pas.

    Agréger créances, stock et décrochage en un score unique donnerait un
    indicateur que personne ne saurait interpréter ni actionner.
    """
    etat = {"findings": [
        {"agent": "Stock", "categorie": "Stock", "severite": "haute",
         "titre": "Surstock", "montant_dt": 900_000, "constat": "…", "action": "…"},
    ], "trace": []}
    f = nodes.arbitre(etat)["findings"][0]
    interdits = ("score_global", "sante_globale", "note_globale", "indice_global")
    assert not any(k in f for k in interdits), "un score global a été introduit"


def test_arbitre_classe_les_constats_sans_montant():
    """Une rupture d'approvisionnement n'a pas de montant, mais arrête la vente.

    Un constat sans montant ne doit pas être relégué en fin de liste : il reçoit
    le rang de sa sévérité déclarée.
    """
    etat = {"findings": [
        {"agent": "Approvisionnement", "categorie": "Approvisionnement",
         "severite": "critique", "titre": "Rupture fournisseur",
         "montant_dt": 0, "constat": "…", "action": "…"},
        {"agent": "Stock", "categorie": "Stock", "severite": "faible",
         "titre": "Surstock mineur", "montant_dt": 50_000,
         "constat": "…", "action": "…"},
    ], "trace": []}
    f = nodes.arbitre(etat)["findings"][0]
    premier = f["classement"][0]
    assert premier["titre"] == "Rupture fournisseur", (
        "un constat critique sans montant doit primer sur un constat faible chiffré")


def test_tresorerie_et_recouvrement_annoncent_la_meme_exposition():
    """Deux agents ne doivent jamais donner deux chiffres pour un même fait.

    Défaut constaté : l'agent Trésorerie utilisait `montant_risque_ttc`, qui
    additionne CINQ ANS de factures réglées avec retard — un comportement de
    paiement cumulé, pas un encours. Il annonçait 133,77 M DT là où l'agent
    Recouvrement annonçait 10,95 M DT pour la même réalité, soit 48 % du chiffre
    d'affaires total en prétendus impayés.

    Une contradiction entre deux agents sur un même fait ruine la crédibilité de
    tout le briefing, et un lecteur attentif la repère immédiatement.
    """
    etat = dict(fake_state())
    etat["kpis"] = {
        **FAKE_KPIS,
        "exposition_recente_dt": 10_950_000.0,
        # Valeur volontairement aberrante : si un agent la reprend, elle sautera
        # aux yeux dans le message d'échec.
        "montant_risque_ttc": 133_770_000.0,
        "exposition_recente_count": 2614,
    }

    tres = nodes.agent_tresorerie(etat)["findings"][0]["constat"]
    assert "133" not in tres.replace(" ", " ").replace(" ", ""), (
        f"l'agent Trésorerie reprend l'historique cumulé : {tres}")
    assert "10.95" in tres or "10,95" in tres or "10 950" in tres.replace(" ", " "), (
        f"l'exposition récente doit figurer : {tres}")


def test_tresorerie_ne_parle_pas_d_impayes():
    """L'ERP n'enregistre aucune date de règlement.

    Dire « créances dépassant l'échéance » laisserait croire à des impayés
    constatés, alors que seule la date d'échéance CONTRACTUELLE est connue. La
    nuance a été martelée dans toute l'interface ; elle doit tenir ici aussi.
    """
    etat = dict(fake_state())
    etat["kpis"] = {**FAKE_KPIS, "exposition_recente_dt": 5_000_000.0}
    c = nodes.agent_tresorerie(etat)["findings"][0]["constat"].lower()
    for mot in ("impayé", "impaye", "dépassent l'échéance", "en retard de paiement"):
        assert mot not in c, f"formulation trompeuse « {mot} » : {c}"


def test_arbitre_sur_liste_vide_ne_plante_pas():
    out = nodes.arbitre({"findings": [], "trace": []})
    assert isinstance(out, dict)
    assert not out.get("findings")


def test_agents_sur_etat_vide_ne_plantent_pas():
    """Cas limite : état totalement vide → constat dégradé mais pas d'exception."""
    empty = {"filters": {}, "findings": [], "trace": []}
    for fn in (nodes.agent_recouvrement, nodes.agent_tresorerie,
               nodes.agent_risque, nodes.redacteur):
        out = fn(dict(empty))
        assert isinstance(out, dict)
        assert "trace" in out


# ── Robustesse : un agent en erreur ne casse pas le briefing ────────────────
def test_safe_node_capture_les_exceptions():
    @nodes._safe_node("Agent Test")
    def agent_qui_plante(state):
        raise RuntimeError("boom")

    out = agent_qui_plante({})
    assert out["trace"][0]["status"] == "erreur"
    assert "boom" in out["trace"][0]["detail"]


@pytest.mark.vitrine
def test_briefing_survit_a_un_agent_en_panne(monkeypatch):
    """Injection de panne : le volet fournisseurs lève une exception brute.

    Depuis la réunion de Stock et Approvisionnement en un seul agent, la panne
    d'un volet ne doit pas emporter l'autre : le constat de stock est livré, et
    la trace dit — sans le masquer — qu'une moitié a échoué.
    """
    def boom(state):
        raise RuntimeError("entrepôt indisponible")
    monkeypatch.setattr(nodes, "constat_approvisionnement", boom)

    out = nodes.agent_stock_approvisionnement(_etat_avec_flux_reels())
    assert [f["domaine"] for f in out.get("findings", [])] == ["Stock"], (
        "le constat de stock a été perdu avec la panne du volet fournisseurs")
    trace = out["trace"]
    assert len(trace) == 1 and trace[0]["status"] == "erreur"
    assert "fournisseurs" in trace[0]["detail"] and "entrepôt indisponible" in trace[0]["detail"]

    # Et une panne de la source de données (et non du code) reste absorbée.
    monkeypatch.undo()
    def source_hs():
        raise RuntimeError("entrepôt indisponible")
    monkeypatch.setattr("ml_engine.analytics.demand_engine.compute_supply_demand", source_hs)
    out = nodes.constat_approvisionnement(fake_state())
    assert isinstance(out, dict) and "trace" in out


# ── Rédacteur : briefing priorisé et déterministe ───────────────────────────
def test_redacteur_deterministe_priorise_par_severite(monkeypatch):
    # `redacteur` appelle `load_dotenv()`, qui RECHARGE depuis le fichier .env
    # les clés que `delenv` vient de retirer de l'environnement. Sans le
    # neutraliser, ce test passait sur une machine sans .env et échouait sur une
    # machine qui en a un : il testait la branche LLM en croyant tester la
    # branche déterministe.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    st = fake_state()
    st["findings"] = [
        {"agent": "A", "categorie": "x", "severite": "faible", "titre": "Mineur",
         "montant_dt": 0, "constat": "c", "action": "a"},
        {"agent": "B", "categorie": "y", "severite": "critique", "titre": "Urgent",
         "montant_dt": 100, "constat": "c", "action": "a"},
    ]
    out = nodes.redacteur(st)
    b = out["briefing"]
    assert b.index("Urgent") < b.index("Mineur")   # critique avant faible
    assert "Briefing" in b



def test_redacteur_suit_l_ordre_de_l_arbitre(monkeypatch):
    """Quand l'arbitre a statué, le briefing suit SON classement, pas la
    sévérité déclarée par chaque agent — sinon le point 1 du briefing et la
    « priorité » annoncée par l'arbitre dans le même texte se contredisent."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    constats = [
        {"agent": "Stock & Approvisionnement", "categorie": "Approvisionnement",
         "severite": "critique", "titre": "Dépendance fournisseur", "montant_dt": 0,
         "constat": "c", "action": "a"},
        {"agent": "Recouvrement", "categorie": "Recouvrement", "severite": "moyenne",
         "titre": "Créances à relancer", "montant_dt": 20_000_000, "constat": "c", "action": "a"},
    ]
    synthese = nodes.arbitre({"findings": constats, "trace": []})["findings"][0]
    assert synthese["classement"][0]["titre"] == "Créances à relancer"
    st = fake_state()
    st["findings"] = constats + [synthese]
    b = nodes.redacteur(st)["briefing"]
    assert b.index("Créances à relancer") < b.index("Dépendance fournisseur")

# ── Intégration : run_briefing complet (collecteurs simulés) ────────────────
def test_run_briefing_integration(monkeypatch):
    """Briefing de bout en bout avec collecte interne simulée (pas d'entrepôt)."""
    monkeypatch.setattr(
        nodes, "collecte_interne",
        lambda s: {"kpis": dict(FAKE_KPIS), "trace": [nodes._log("collecte", "ok")]})
    # `load_dotenv` recharge depuis le fichier .env les clés que `delenv` retire :
    # sans le neutraliser, ce test emprunte la branche LLM.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    init = {"filters": {}, "question": "", "findings": [], "trace": []}
    result = _run_sequential(init)

    assert result.get("briefing"), "le briefing ne doit jamais être vide"
    agents_traces = [t["agent"] for t in result["trace"]]
    assert len(agents_traces) >= 6            # 1 collecteur + 5 spécialistes + rédacteur
    assert len(result["findings"]) >= 4       # au moins 4 constats de spécialistes
    assert agents_traces.count("✍️ Rédacteur") == 1
    assert "📦 Agent Stock & Approvisionnement" in agents_traces
    assert all(f.get("categorie") != "Qualité des modèles" for f in result["findings"])
    sev = {f["severite"] for f in result["findings"]}
    assert sev <= {"critique", "haute", "moyenne", "faible"}


def test_run_briefing_api_contract():
    """Le contrat de sortie de run_briefing est stable (consommé par l'API)."""
    out = run_briefing({}, question=None)
    assert set(out.keys()) == {"engine", "briefing", "findings", "trace", "fiabilite"}
    # Le volet fiabilité vit à part : jamais parmi les constats arbitrés.
    assert all(f.get("categorie") != "Qualité des modèles" for f in out["findings"])
    assert isinstance(out["findings"], list)
    assert isinstance(out["trace"], list)


# ── Structure de la flotte : 5 spécialistes + un volet fiabilité ────────────
def _etat_stock_appro(monkeypatch):
    monkeypatch.setattr("ml_engine.analytics.demand_engine.compute_supply_demand",
                        lambda: {"dependance_fournisseur": "critique",
                                 "fournisseurs_top": [{"fournisseur": "BIOMERIEUX"}],
                                 "fournisseur_top1_pct": 62.0})
    return _etat_avec_flux_reels()


def test_stock_et_approvisionnement_reunis_gardent_leurs_deux_constats(monkeypatch):
    """Réunir deux agents ne doit retirer aucun constat au classement.

    L'arbitre classe des constats, pas des agents : chaque volet garde sa
    catégorie (donc sa nature économique) et son domaine.
    """
    out = nodes.agent_stock_approvisionnement(_etat_stock_appro(monkeypatch))
    fs = out["findings"]
    assert [f["domaine"] for f in fs] == ["Stock", "Approvisionnement"]
    assert [f["categorie"] for f in fs] == ["Stock", "Approvisionnement"]
    assert {f["agent"] for f in fs} == {nodes.AGENT_STOCK_APPRO}
    for f in fs:
        assert "aucun modèle appris" in f["nature_analyse"], (
            "l'agent doit déclarer qu'il est déterministe et statistique")
        assert REQUIRED_FINDING_KEYS.issubset(f.keys())
    assert len(out["trace"]) == 1 and out["trace"][0]["status"] == "ok"

    # Les deux constats passent l'arbitrage avec leur nature économique propre.
    arb = nodes.arbitre({"findings": fs, "trace": []})["findings"][0]
    natures = {c["categorie"]: c["nature_economique"] for c in arb["classement"]}
    assert natures == {"Stock": "capital immobilisé", "Approvisionnement": "risque opérationnel"}


def test_stock_et_approvisionnement_hors_perimetre_client():
    etat = _etat_avec_flux_reels()
    etat["filters"] = {"selected_clients": ["C001"]}
    out = nodes.agent_stock_approvisionnement(etat)
    assert not out.get("findings")
    assert out["trace"][0]["status"] == "vide"


def test_le_domaine_appartient_au_constat_pas_a_l_agent():
    """Deux constats d'un MÊME agent mais de domaines différents doivent pouvoir
    déclencher l'alerte croisée — c'est ce qui rend les fusions d'agents sûres.
    Et un constat qui ne déclare pas de domaine retombe sur le nom de son agent.
    """
    commun = {"agent": "Agent fusionné", "severite": "haute", "constat": "…", "action": "…"}
    etat = {"findings": [
        {**commun, "domaine": "Recouvrement", "categorie": "Recouvrement",
         "titre": "Créances", "montant_dt": 100_000,
         "clients_concernes": [{"nom": "UNOPS", "montant_dt": 100_000}]},
        {**commun, "domaine": "Risque client", "categorie": "Rétention",
         "titre": "Décrochage", "montant_dt": 80_000,
         "clients_concernes": [{"nom": "UNOPS", "montant_dt": 80_000}]},
    ], "trace": []}
    cumuls = nodes.arbitre(etat)["findings"][0]["clients_multi_signaux"]
    assert cumuls and cumuls[0]["domaines"] == ["Recouvrement", "Risque client"]

    sans_domaine = [{k: v for k, v in f.items() if k != "domaine"} for f in etat["findings"]]
    cumuls = nodes.arbitre({"findings": sans_domaine, "trace": []})["findings"][0]["clients_multi_signaux"]
    assert not cumuls, "sans domaine déclaré, un seul agent = un seul domaine"


def test_reserve_de_fiabilite_atteint_le_briefing_sans_jargon(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    st = fake_state()
    st["findings"] = [{"agent": "A", "categorie": "x", "severite": "haute", "titre": "T",
                       "montant_dt": 10, "constat": "c", "action": "a"}]

    st["fiabilite"] = {"reentrainement_conseille": False}
    assert "Réserve" not in nodes.redacteur(st)["briefing"]

    st["fiabilite"] = {"reentrainement_conseille": True}
    out = nodes.redacteur(st)
    assert "Réserve" in out["briefing"]
    assert "réserve de fiabilité" in out["trace"][0]["detail"]
    import re
    reserve = nodes._reserve_fiabilite(st["fiabilite"])
    assert not re.search(r"\b(modèle|registre|AUC|PSI|dérive|algorithme)\b", reserve, re.I)



def test_volet_stock_chiffre_les_ruptures_avec_la_demande_par_reference():
    """La quantité à commander vient de la prévision servie : borne haute des
    trois prochains mois moins le stock encore positif — jamais négative."""
    etat = _etat_avec_flux_reels()
    etat["kpis"]["stock_flux_reel"]["ruptures"] = [
        {"produit": "Vidas CA 19-9 30 Tests", "position": 30.0},
        {"produit": "Produit sans prévision", "position": 0.0},
        {"produit": "VIDAS TSH", "position": 500.0},
    ]
    etat["kpis"]["stock_flux_reel"]["n_ruptures"] = 3
    carte = {"module": "demande_reference", "libelle": "Demande par référence", "servi": True,
             "nature": "methode_statistique", "metrique_nom": "WAPE", "metrique": 38.3}
    etat["modeles"] = {"demande_reference": {
        "servi": True, "modele": carte, "references": [
            {"designation": "VIDAS CA 19-9 30 TESTS", "designations": ["VIDAS CA 19-9 30 TESTS"],
             "cumul_3_mois": 120.0, "borne_haute_3_mois": 150.0},
            {"designation": "VIDAS TSH", "designations": ["VIDAS TSH"],
             "cumul_3_mois": 200.0, "borne_haute_3_mois": 260.0}]}}
    f = nodes.constat_stock(etat)["findings"][0]
    assert "Vidas CA 19-9 30 Tests 120 unités" in f["constat"]
    assert "Vidas CA 19-9 30 Tests 120" in f["action"], "150 − 30 = 120 à commander"
    quantites = f["action"].split("8 cas sur 10")[-1]
    assert "VIDAS TSH" in f["constat"] and "VIDAS TSH" not in quantites, (
        "un stock qui couvre déjà la borne ne donne ni quantité négative ni commande de 0")
    assert "Produit sans prévision" not in quantites
    assert any(u["module"] == "demande_reference" for u in f["modeles_utilises"])

# ── Topologie : jointure du rédacteur (LangGraph) et repli séquentiel ───────
def _graphe_instrumente(monkeypatch):
    """Remplace chaque nœud du graphe par une sonde qui journalise son passage."""
    from agents.fleet import graph as G
    journal = []

    def sonde(nom, sortie=None):
        def fn(state):
            journal.append((nom, [f.get("categorie") for f in state.get("findings") or []],
                            bool(state.get("fiabilite"))))
            return dict(sortie or {})
        return fn

    monkeypatch.setattr(G, "collecte_interne", sonde("collecte_interne", {"kpis": {}}))
    monkeypatch.setattr(G, "collecte_modeles", sonde("collecte_modeles", {"modeles": {}}))
    monkeypatch.setattr(G, "_COLLECTEURS", (G.collecte_interne, G.collecte_modeles))
    specialistes = {n: sonde(n, {"findings": [{"categorie": n}]}) for n in G._SPECIALISTES}
    monkeypatch.setattr(G, "_SPECIALISTES", specialistes)
    monkeypatch.setattr(G, "fiabilite_modeles",
                        sonde("fiabilite_modeles", {"fiabilite": {"categorie": "Qualité des modèles"}}))
    monkeypatch.setattr(G, "arbitre", sonde("arbitre"))
    monkeypatch.setattr(G, "redacteur", sonde("redacteur", {"briefing": "ok"}))
    return G, journal


def _verifier_journal(journal):
    noms = [n for n, _, _ in journal]
    assert noms.count("redacteur") == 1, f"le rédacteur s'est exécuté {noms.count('redacteur')} fois"
    assert noms.index("redacteur") > noms.index("arbitre")
    assert noms.index("redacteur") > noms.index("fiabilite_modeles")
    _, vus_par_arbitre, _ = next(j for j in journal if j[0] == "arbitre")
    assert "Qualité des modèles" not in vus_par_arbitre, "le volet fiabilité a atteint l'arbitre"
    assert len(vus_par_arbitre) == 5, vus_par_arbitre
    _, _, fiab_vue = next(j for j in journal if j[0] == "redacteur")
    assert fiab_vue, "le rédacteur n'a pas reçu le volet fiabilité"


def test_graphe_langgraph_joint_le_redacteur_une_seule_fois(monkeypatch):
    pytest.importorskip("langgraph")
    G, journal = _graphe_instrumente(monkeypatch)
    G.build_graph().invoke({"filters": {}, "question": "", "findings": [], "trace": []})
    _verifier_journal(journal)


def test_repli_sequentiel_suit_le_meme_ordre(monkeypatch):
    G, journal = _graphe_instrumente(monkeypatch)
    G._run_sequential({"filters": {}, "question": "", "findings": [], "trace": []})
    _verifier_journal(journal)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
