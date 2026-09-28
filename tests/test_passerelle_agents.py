"""
tests/test_passerelle_agents.py
===============================
Les modèles atteignent-ils réellement les agents — et seulement par le registre ?

Trois familles de garanties :

1. **Câblage** : chaque spécialiste consomme ses modèles et le déclare dans
   `modeles_utilises`. Un modèle correct mais débranché est invisible.
2. **Chemin unique** : aucun agent ni le copilote n'importe un module de modèle
   directement. C'est l'importation directe de `score_stock_risk` — un modèle
   RETIRÉ — qui avait fait fuiter un score non validé dans le copilote.
3. **Métriques** : accuracy toujours publiée avec la classe majoritaire, seuil
   choisi sur l'entraînement, métriques de classement correctes.

Les tests d'agents injectent des sorties de modèles FACTICES : ils ne dépendent
ni de l'entrepôt ni d'un entraînement.
"""

from __future__ import annotations

import glob
import os
import re
import sys

import numpy as np
import pandas as pd
import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from agents.fleet import nodes  # noqa: E402


# ── Sorties de modèles factices ─────────────────────────────────────────────
def _carte(module, servi=True, retire=False, nature="modele_appris", metrique=0.8):
    return {"module": module, "libelle": module.replace("_", " "), "nature": nature,
            "servi": servi, "retire": retire, "metrique_nom": "AUC hors période",
            "metrique": metrique,
            "classification": {"accuracy": 0.9, "balanced_accuracy": 0.7, "f1": 0.5,
                               "mcc": 0.45, "accuracy_classe_majoritaire": 0.88}}


def _modeles_factices(perimetre=()):
    return {
        "perimetre_client": list(perimetre),
        "decrochage": {"servi": True, "n_au_dessus_de_0_5": 12, "n_clients_scores": 800,
                       "enjeu_total_dt": 2_000_000,
                       "top": [{"code": "C9", "nom": "HOPITAL NORD", "probabilite_decrochage": 0.8,
                                "enjeu_dt": 500_000}],
                       "modele": _carte("churn")},
        "segmentation": {"servi": True, "par_client": {"C9": {"nom_segment": "Comptes stratégiques actifs"}},
                         "segments": [{"segment": 0, "nom": "Comptes stratégiques actifs",
                                       "part_menacee_pct": 10.3, "ca_menace_dt": 3_355_000}],
                         "modele": _carte("segmentation", nature="modele_non_supervise")},
        "conversion_devis": {"servi": True, "n_devis": 40, "esperance_totale_dt": 150_000,
                             "top": [{"client": "C7", "code": "C7", "nom": "CLINIQUE SUD",
                                      "montant_ht_dt": 120_000, "probabilite": 0.4,
                                      "esperance_dt": 48_000}],
                             "modele": _carte("conversion_devis")},
        "marge_client": {"servi": True, "seuil_marge_basse_pct": 25.5,
                         "top": [{"client": "C1", "code": "C1", "nom": "CHU SFAX",
                                  "marge_actuelle_pct": 24.0, "probabilite": 0.6,
                                  "marge_en_jeu_dt": 90_000}],
                         "modele": _carte("marge_client")},
        "recommandation": {"servi": True, "methode": "lightgbm", "horizon_mois": 6,
                           "top": [{"client": "C7", "nom": "CLINIQUE SUD", "potentiel_top3_dt": 30_000,
                                    "produits": [{"designation": "VIDAS TSH 60 tests"},
                                                 {"designation": "VIDAS FT4 60 tests"}]}],
                           "modele": {**_carte("recommandation"),
                                      "deep_learning": {"mesure": {"ndcg_at_10": 0.35}, "servi": False}}},
        "credit": {"servi": True, "scores": {"C001": {"score": 100, "avg_delay": 95,
                                                      "source": "regle_historique"}},
                   "modele": _carte("credit", nature="regle_deterministe", metrique=0.92)},
        "echeancier": {"servi": True, "montant_exigible_dt": 3_800_000, "part_deja_au_carnet": 0.99,
                       "modele": _carte("echeancier", nature="lecture_carnet", metrique=1.27)},
        "reappro": {"servi": False, "source": "regle_de_repli",
                    "modele": _carte("reappro", servi=False, metrique=0.93)},
        "fin_de_vie": {"servi": True, "nature": "regle_deterministe", "capital_expose_total_dt": 800_000,
                       "top": [{"produit": "ANALYSEUR X", "capital_expose_dt": 120_000}],
                       "modele": _carte("fin_de_vie", servi=False)},
        "risque_stock": {"servi": False, "retire": True,
                         "modele": _carte("stock_risque", servi=False, retire=True)},
        "demande_reference": {"servi": True, "methode": "mediane_12", "mois": ["2026-04", "2026-05", "2026-06"],
                              "references": [{"reference": "30427", "designation": "VIDAS CA 19-9 30 TESTS",
                                              "designations": ["VIDAS CA 19-9 30 TESTS"],
                                              "prevision": [40.0, 38.0, 42.0], "cumul_3_mois": 120.0,
                                              "borne_haute_3_mois": 150.0}],
                              "modele": _carte("demande_reference", nature="methode_statistique", metrique=38.3)},
        "derive": {"alertes": [], "decrochage_client": {"applicable": True, "psi_max": 0.08}},
        "tableau": [_carte("churn"), _carte("stock_risque", servi=False, retire=True),
                    _carte("reappro", servi=False),
                    {**_carte("recommandation"),
                     "deep_learning": {"mesure": {"ndcg_at_10": 0.35}, "servi": False,
                                       "duel_vs_lightgbm": {"ecart_moyen": 0.006,
                                                            "ecart_ic95": [-0.004, 0.016],
                                                            "significatif": False}}}],
    }


def _etat(perimetre=()):
    from tests.test_fleet import FAKE_KPIS
    etat = {"filters": {"selected_clients": list(perimetre)} if perimetre else {},
            "question": "", "findings": [], "trace": [], "kpis": dict(FAKE_KPIS)}
    etat["kpis"]["stock_flux_reel"] = {"disponible": True, "valeur_immobilisee_dt": 1_000_000,
                                       "perte_quasi_certaine_dt": 50_000,
                                       "n_references_accumulees": 900, "ruptures": [],
                                       "n_ruptures": 0, "n_ruptures_critiques": 0}
    etat["modeles"] = _modeles_factices(perimetre)
    return etat


# ── 1. Câblage : chaque spécialiste consomme ses modèles ────────────────────
def _modules(findings):
    return {u["module"] for f in findings for u in (f.get("modeles_utilises") or [])}


@pytest.mark.vitrine
def test_chaque_modele_du_registre_atteint_un_agent():
    """Chaque module du registre a un consommateur réel.

    Pour la flotte : cité par au moins un spécialiste. Le volet fiabilité n'est
    pas un spécialiste — il cite tous les modèles pour les surveiller, ce qui
    masquerait un modèle qu'aucun agent métier n'utilise ; il ne fait d'ailleurs
    plus partie des nœuds parcourus ici.

    Un modèle déclaré `hors_flotte` (la lecture de factures LayoutLMv3, consommée
    par la chaîne OCR) n'a pas à être cité par un agent : le test vérifie alors
    que le fichier déclaré consulte réellement son état au registre. Sans cette
    distinction, le test échouait dès l'ajout de LayoutLMv3 au registre.
    """
    from ml_engine.registre import MODELES

    etat = _etat()
    findings = []
    import ml_engine.analytics.demand_engine as de
    orig = de.compute_supply_demand
    de.compute_supply_demand = lambda: {"dependance_fournisseur": "critique"}
    try:
        for fn in (nodes.agent_recouvrement, nodes.agent_tresorerie, nodes.agent_risque,
                   nodes.agent_stock_approvisionnement, nodes.agent_commercial):
            findings += fn(etat).get("findings", [])
    finally:
        de.compute_supply_demand = orig

    hors_flotte = {k: v["hors_flotte"] for k, v in MODELES.items() if v.get("hors_flotte")}
    cites = _modules(findings)
    manquants = set(MODELES) - set(hors_flotte) - cites
    assert not manquants, f"module(s) du registre qu'aucun agent ne consomme : {manquants}"

    for nom, fichier in hors_flotte.items():
        chemin = os.path.join(RACINE, fichier)
        assert os.path.exists(chemin), f"{nom} : consommateur déclaré introuvable ({fichier})"
        source = open(chemin, encoding="utf-8").read()
        assert re.search(r"etat_modele\(\s*[\"']" + re.escape(nom) + r"[\"']", source), (
            f"{nom} : {fichier} ne consulte pas le registre — le modèle serait "
            "servi sans que son refus puisse l'arrêter")


def test_agent_commercial_produit_trois_constats_sources():
    out = nodes.agent_commercial(_etat())
    titres = [f["titre"] for f in out["findings"]]
    assert len(titres) == 3, titres
    for f in out["findings"]:
        assert f["modeles_utilises"], f["titre"]
        assert f["clients_concernes"], "l'arbitre a besoin des clients pour croiser"
    reco = next(f for f in out["findings"] if "Produits à proposer" in f["titre"])
    assert reco["modeles_utilises"][0]["module"] == "recommandation"


@pytest.mark.vitrine
def test_aucun_terme_technique_dans_les_textes_lus_par_un_dirigeant():
    """Constats, résumés et actions s'adressent à un directeur ou à un client.

    La trace technique (modèle, métrique, statut au registre) reste disponible
    dans `modeles_utilises` pour l'API et la soutenance, jamais dans le texte.
    """
    etat = _etat()
    import ml_engine.analytics.demand_engine as de
    orig = de.compute_supply_demand
    de.compute_supply_demand = lambda: {"dependance_fournisseur": "critique", "demande_mape": 15.7}
    try:
        findings = []
        for fn in (nodes.agent_recouvrement, nodes.agent_tresorerie, nodes.agent_risque,
                   nodes.agent_stock_approvisionnement, nodes.agent_commercial):
            findings += fn(etat).get("findings", [])
    finally:
        de.compute_supply_demand = orig
    interdits = re.compile(r"\b(AUC|MAPE|NDCG|accuracy|lightgbm|wide & deep|parcimonie|"
                           r"modèle|registre|probabilité calibrée)\b", re.IGNORECASE)
    for f in findings:
        for champ in ("titre", "resume", "constat", "action"):
            texte = str(f.get(champ) or "")
            assert not interdits.search(texte), f"{f['titre']} · {champ} : {texte}"


def test_agent_commercial_se_tait_sans_modeles():
    from tests.test_fleet import fake_state
    out = nodes.agent_commercial(fake_state())
    assert not out.get("findings")
    assert out["trace"][0]["status"] == "vide"


def test_risque_client_croise_segmentation_et_decrochage():
    out = nodes.agent_risque(_etat())
    anticipe = next(f for f in out["findings"] if "90 jours" in f["titre"])
    assert "Comptes stratégiques actifs" in anticipe["constat"]
    assert {"churn", "segmentation"} <= _modules([anticipe])
    assert any("Types de clients" in f["titre"] for f in out["findings"])


@pytest.mark.vitrine
def test_un_modele_refuse_ou_retire_n_est_jamais_presente_comme_servi():
    etat = _etat()
    findings = nodes.constat_stock(etat)["findings"]
    for u in (u for f in findings for u in f.get("modeles_utilises", [])):
        if u["module"] in ("stock_risque", "fin_de_vie"):
            assert u["statut"] != "servi", u


def test_volet_fiabilite_publie_accuracy_et_duel_deep_learning():
    f = nodes.fiabilite_modeles(_etat())["fiabilite"]
    assert f["categorie"] == "Qualité des modèles"
    assert "accuracy" in f["constat"]
    assert "Wide & Deep" in f["constat"] and "non significatif" in f["constat"]


def test_volet_fiabilite_ne_concurrence_pas_les_constats_metier():
    """Le volet fiabilité n'écrit JAMAIS dans `findings` : l'arbitre ne le voit pas.

    Et si un constat de cette catégorie arrivait tout de même par une autre voie,
    la garde de l'arbitre le classerait dernier, à enjeu nul.
    """
    etat = _etat()
    sortie = nodes.fiabilite_modeles(etat)
    assert "findings" not in sortie and sortie["fiabilite"]["categorie"] == "Qualité des modèles"

    egare = {**sortie["fiabilite"], "montant_dt": 0}
    findings = [egare] + nodes.agent_recouvrement(etat)["findings"]
    arb = nodes.arbitre({"findings": findings, "trace": []})["findings"][0]
    dernier = arb["classement"][-1]
    assert dernier["categorie"] == "Qualité des modèles"
    assert dernier["enjeu_court_terme_dt"] == 0


def test_modeles_mobilises_ne_citent_que_les_modeles_des_specialistes():
    """Tant que le volet fiabilité passait par l'arbitre, `modeles_mobilises`
    listait tous les modèles servis du registre — y compris la lecture de
    factures, qu'aucun agent n'utilise. Sur l'entrepôt réel, le briefing
    annonçait ainsi un modèle qu'il n'avait pas mobilisé."""
    etat = _etat()
    findings = nodes.agent_commercial(etat)["findings"] + nodes.agent_risque(etat)["findings"]
    arb = nodes.arbitre({"findings": findings, "trace": []})["findings"][0]
    attendus = {u.get("libelle") for f in findings for u in (f.get("modeles_utilises") or [])
                if u.get("statut") == "servi"}
    assert set(arb["modeles_mobilises"]) == attendus


def test_arbitre_liste_les_modeles_mobilises():
    etat = _etat()
    findings = nodes.agent_commercial(etat)["findings"] + nodes.agent_risque(etat)["findings"]
    arb = nodes.arbitre({"findings": findings, "trace": []})["findings"][0]
    assert len(arb["modeles_mobilises"]) >= 3


# ── 2. Confidentialité du périmètre client ──────────────────────────────────
def test_perimetre_client_masque_stock_fournisseurs_et_registre():
    etat = _etat(perimetre=("C7",))
    assert not nodes.agent_stock_approvisionnement(etat).get("findings")
    assert not nodes.constat_stock(etat).get("findings")
    assert not nodes.constat_approvisionnement(etat).get("findings")
    assert not nodes.fiabilite_modeles({**etat, "modeles": {**etat["modeles"], "tableau": []}}).get("fiabilite")
    tres = nodes.agent_tresorerie(etat)["findings"][0]["constat"]
    assert "stock" not in tres.lower(), "le stock de l'entreprise n'a pas à atteindre un client"


def test_collecte_modeles_filtre_les_autres_clients(monkeypatch):
    from ml_engine import passerelle as pw

    carte = _carte("x")
    monkeypatch.setattr(pw, "noms_clients", lambda: {"A": "CLIENT A", "B": "CLIENT B"})
    monkeypatch.setattr(pw, "carte_modele", lambda nom: carte)
    monkeypatch.setattr(pw, "segments_clients", lambda: {"servi": True, "modele": carte,
                        "par_client": {"A": {"nom_segment": "s"}, "B": {"nom_segment": "s"}}})
    monkeypatch.setattr(pw, "conditions_credit", lambda: {"servi": True, "modele": carte,
                        "scores": {"A": {}, "B": {}}})
    monkeypatch.setattr(pw, "recommandations", lambda client=None, n_clients=15: {
        "servi": True, "modele": carte, "nom": f"CLIENT {client}", "produits": [
            {"designation": "p", "montant_annuel_median_par_acheteur_dt": 10}]})
    kpis = {
        "churn_anticipe": {"servi": True, "top": [{"code": "A"}, {"code": "B"}]},
        "conversion_devis": {"servi": True, "top": [{"client": "A"}, {"client": "B"}]},
        "marge_client": {"servi": True, "top": [{"client": "B"}]},
    }
    out = nodes.collecte_modeles({"filters": {"selected_clients": ["A"]}, "kpis": kpis})
    m = out["modeles"]
    assert [c["code"] for c in m["decrochage"]["top"]] == ["A"]
    assert [c["code"] for c in m["conversion_devis"]["top"]] == ["A"]
    assert m["marge_client"]["top"] == []
    assert set(m["segmentation"]["par_client"]) == {"A"}
    assert set(m["credit"]["scores"]) == {"A"}
    assert "tableau" not in m and "fin_de_vie" not in m


# ── 3. Chemin unique vers les modèles ───────────────────────────────────────
_IMPORTS_INTERDITS = re.compile(
    r"from ml_engine\.(models|analytics\.(churn_model|conversion_devis|marge_client|"
    r"credit_risk_model|segmentation)|stock\.(reappro_model|fin_de_vie)|deep)\b|"
    r"score_stock_risk\s*\(")


_FICHIERS_AGENTS = ["agents/fleet/nodes.py"] + sorted(
    os.path.relpath(p, RACINE).replace(os.sep, "/")
    for p in glob.glob(os.path.join(RACINE, "agents", "copilote", "*.py")))


@pytest.mark.parametrize("fichier", _FICHIERS_AGENTS)
def test_aucun_agent_n_importe_un_modele_directement(fichier):
    code = open(os.path.join(RACINE, fichier), encoding="utf-8").read()
    # Les docstrings et commentaires peuvent NOMMER la fonction retirée.
    lignes = [l for l in code.splitlines()
              if l.strip() and not l.strip().startswith("#") and "`score_stock_risk`" not in l]
    fautives = [l.strip() for l in lignes if _IMPORTS_INTERDITS.search(l)]
    assert not fautives, (f"{fichier} contourne la passerelle du registre : {fautives}")


def test_copilote_stock_ne_touche_plus_au_modele_retire(monkeypatch):
    """Question de péremption : le modèle retiré ne doit pas être appelé."""
    import ml_engine.models.stock_risk as sr
    from agents.copilote import outils, repli

    def interdit(*a, **k):
        raise AssertionError("score_stock_risk appelé alors que le modèle est retiré")
    monkeypatch.setattr(sr, "score_stock_risk", interdit)
    monkeypatch.setattr(outils, "contexte_stock_reel", lambda kpis: {
        "risque_stock": {"motif": "retiré"},
        "flux": {"disponible": True, "perte_quasi_certaine_dt": 1000, "valeur_immobilisee_dt": 5000,
                 "n_obsoletes_certains": 1, "obsolescence": [], "ruptures": []},
        "fin_de_vie": {"servi": False}})
    txt = repli.reponse_deterministe("Quels réactifs risquent de périmer ?", {}, {})
    assert "factures" in txt and "modèle" not in txt.lower()


# ── 4. Métriques ────────────────────────────────────────────────────────────
def test_accuracy_toujours_accompagnee_de_la_classe_majoritaire():
    from ml_engine.metriques import metriques_classification

    rng = np.random.default_rng(0)
    y = (rng.random(2000) < 0.08).astype(int)
    p = np.clip(y * 0.3 + rng.random(2000) * 0.5, 0, 1)
    m = metriques_classification(y, p, y_train=y, p_train=p)
    assert m["accuracy_classe_majoritaire"] == pytest.approx(1 - y.mean(), abs=1e-4)
    for bloc in ("au_seuil_0_5", "au_seuil_optimise_train"):
        b = m[bloc]
        mc = b["matrice_confusion"]
        assert sum(mc.values()) == len(y)
        assert b["accuracy"] == pytest.approx((mc["vrais_positifs"] + mc["vrais_negatifs"]) / len(y), abs=1e-4)
    assert "classe majoritaire" in m["lecture"]


def test_un_classifieur_constant_a_une_balanced_accuracy_de_50():
    from ml_engine.metriques import metriques_decision

    y = np.array([0] * 90 + [1] * 10)
    m = metriques_decision(y, np.zeros(100))
    assert m["accuracy"] == 0.9
    assert m["balanced_accuracy"] == 0.5
    assert m["mcc"] == 0.0


def test_le_seuil_est_choisi_sur_l_entrainement_pas_sur_le_test():
    from ml_engine.metriques import metriques_classification

    y_tr = np.array([0, 0, 0, 1, 1]); p_tr = np.array([0.1, 0.2, 0.3, 0.35, 0.9])
    y_te = np.array([0, 1, 0, 1]); p_te = np.array([0.34, 0.36, 0.1, 0.8])
    m = metriques_classification(y_te, p_te, y_train=y_tr, p_train=p_tr)
    assert m["au_seuil_optimise_train"]["seuil"] <= 0.35
    assert m["au_seuil_optimise_train"]["seuil_choisi_sur"].startswith("entraînement")


def test_metriques_depuis_matrice_publiee():
    from ml_engine.metriques import metriques_depuis_matrice

    m = metriques_depuis_matrice([[48, 398], [11, 3273]])
    assert m["accuracy"] == pytest.approx((48 + 3273) / 3730, abs=1e-4)
    assert 0.5 < m["balanced_accuracy"] < 0.6


def test_tout_rapport_de_classifieur_publie_l_accuracy():
    """Chaque classifieur du registre expose une accuracy au tableau des modèles."""
    from ml_engine import passerelle as pw

    cartes = {c["module"]: c for c in pw.tableau_des_modeles()}
    for nom in ("churn", "conversion_devis", "marge_client", "reappro", "credit",
                "fin_de_vie", "stock_risque"):
        if nom not in cartes or cartes[nom].get("metrique") is None:
            pytest.skip("rapports absents — modèles non entraînés")
        assert (cartes[nom].get("classification") or {}).get("accuracy") is not None, nom


# ── 5. Recommandation : métriques de classement ─────────────────────────────
def test_ndcg_et_rappel_sur_un_cas_calcule_a_la_main():
    from ml_engine.deep.recommandation import metriques_classement

    ex = pd.DataFrame({"client": ["a"] * 4 + ["b"] * 3,
                       "reference": ["p1", "p2", "p3", "p4", "p1", "p2", "p3"],
                       "y": [0, 1, 0, 1, 0, 0, 0]})
    score = np.array([4, 3, 2, 1, 3, 2, 1], dtype=float)
    resume, par_client = metriques_classement(ex, score, k=2)
    assert resume["n_clients_evalues"] == 1          # « b » n'adopte rien
    ligne = par_client.iloc[0]
    assert ligne["rappel"] == 0.5 and ligne["hit"] == 1.0
    idcg = 1 + 1 / np.log2(3)
    assert ligne["ndcg"] == pytest.approx((1 / np.log2(3)) / idcg)


def test_comparaison_ndcg_detecte_un_ecart_reel_et_rejette_le_bruit():
    from ml_engine.deep.recommandation import comparer_ndcg

    rng = np.random.default_rng(1)
    a = rng.random(800)
    assert comparer_ndcg(a + 0.1, a)["significatif"] is True
    assert comparer_ndcg(a, a[::-1].copy())["significatif"] is False


def test_le_registre_lit_la_nature_de_la_methode_de_recommandation(tmp_path, monkeypatch):
    import json
    from ml_engine import registre

    rapport = {"decision_deploiement": {"servi": True, "methode_servie": "wide_deep"},
               "evaluation": {"methode_servie": {"ndcg_at_10": 0.35},
                              "meilleure_reference_triviale": {"ndcg_at_10": 0.29}}}
    (tmp_path / "recommandation_metrics.json").write_text(json.dumps(rapport), encoding="utf-8")
    monkeypatch.setattr(registre, "REPORTS_DIR", tmp_path)
    e = registre.etat_modele("recommandation")
    assert e["deploye"] and e["nature"] == "modele_deep_learning"
    rapport["decision_deploiement"]["methode_servie"] = "lightgbm"
    (tmp_path / "recommandation_metrics.json").write_text(json.dumps(rapport), encoding="utf-8")
    assert registre.etat_modele("recommandation")["nature"] == "modele_appris"


def test_les_exemples_d_entrainement_ne_voient_pas_la_fenetre_cible():
    """Aucune variable ne doit changer si l'on modifie le FUTUR d'un client."""
    from ml_engine.deep.recommandation import VARIABLES, construire_exemples

    dates = pd.date_range("2022-01-01", "2024-06-30", freq="15D")
    lignes = []
    for i, d in enumerate(dates):
        for j, c in enumerate(("A", "B", "C")):
            # chaque client achète sa propre gamme de 4 références : il reste des
            # produits jamais achetés, donc des candidats à recommander
            lignes.append({"client": c, "reference": f"R{4 * j + i % 4}", "designation": "x",
                           "famille": "REACTIF", "date": d, "montant": 100.0,
                           "type_etab": "LABORATOIRE"})
    df = pd.DataFrame(lignes)
    coupure = pd.Timestamp("2023-12-31")
    base = construire_exemples(df, coupure)
    assert not base.empty
    futur_modifie = df.copy()
    masque = futur_modifie["date"] > coupure
    futur_modifie.loc[masque, "reference"] = "R_NOUVEAU"
    autre = construire_exemples(futur_modifie, coupure)
    pd.testing.assert_frame_equal(
        base[VARIABLES].reset_index(drop=True), autre[VARIABLES].reset_index(drop=True))
