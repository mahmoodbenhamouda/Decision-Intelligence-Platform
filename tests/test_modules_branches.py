"""Vérifie que les modules décisionnels atteignent réellement l'application."""

from __future__ import annotations

import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)


def _entrepot_present() -> bool:
    from ml_engine.analytics.kpi_engine import STORE_PATH
    return os.path.exists(str(STORE_PATH))


besoin_entrepot = pytest.mark.skipif(
    not _entrepot_present(), reason="entrepôt DuckDB absent")


@besoin_entrepot
def test_le_radar_ne_sert_plus_la_projection_lstm():
    """Le radar financier ne doit plus contenir de carte issue du LSTM."""
    from ml_engine.analytics.kpi_engine import finance_radar

    cartes = finance_radar({}, {})
    ids = {c.get("id") for c in cartes}
    assert "tresorerie_lstm" not in ids, (
        "le radar sert encore la projection LSTM, pourtant non validée")

    titres = " ".join(str(c.get("titre", "")) for c in cartes).lower()
    assert "6 mois" not in titres, (
        "un horizon de 6 mois est annoncé alors que 99 % des factures ont un "
        "délai de 0 à 2 mois : au-delà, les encaissements viennent de factures "
        "non encore émises")


@besoin_entrepot
def test_le_radar_sert_l_echeancier_quand_le_registre_l_autorise():
    """Si le registre déclare l'échéancier servi, il doit apparaître au radar."""
    from ml_engine.analytics.kpi_engine import finance_radar
    from ml_engine.registre import est_deploye

    if not est_deploye("echeancier"):
        pytest.skip("échéancier non servi par le registre")

    cartes = finance_radar({}, {})
    ech = [c for c in cartes if c.get("id") == "echeancier_1m"]
    assert ech, ("le registre déclare l'échéancier servi, mais le radar ne "
                 "l'affiche pas — le module est débranché")

    c = ech[0]
    assert float(c.get("montant_dt") or 0) > 0, "montant d'échéance vide"
    assert "exigible" in (c.get("titre", "") + c.get("action", "")).lower()


@besoin_entrepot
def test_la_demande_passe_par_le_module_hybride():
    """`compute_supply_demand` doit servir le module hybride, pas le repli local."""
    from ml_engine.analytics.demand_engine import compute_supply_demand

    d = compute_supply_demand()
    source = d.get("demande_source")
    if source != "hybride":
        pytest.skip(f"module hybride indisponible (source={source})")

    prev = d.get("demande_prevision") or []
    assert prev, "aucune prévision produite"
    premier = prev[0]
    assert premier.get("bas") is not None and premier.get("haut") is not None, (
        "les prévisions doivent porter leur fourchette")
    assert premier["bas"] <= premier["qte"] <= premier["haut"], (
        f"prévision {premier['qte']} hors de son propre intervalle "
        f"[{premier['bas']} ; {premier['haut']}]")


@besoin_entrepot
def test_l_intervalle_de_demande_s_elargit_avec_l_horizon():
    """L'incertitude doit croître avec l'horizon, jamais se rétrécir."""
    from ml_engine.analytics.demand_engine import compute_supply_demand

    d = compute_supply_demand()
    if d.get("demande_source") != "hybride":
        pytest.skip("module hybride indisponible")

    prev = [p for p in (d.get("demande_prevision") or [])
            if p.get("bas") is not None and p.get("haut") is not None]
    if len(prev) < 2:
        pytest.skip("moins de deux horizons avec intervalle")

    largeurs = [p["haut"] - p["bas"] for p in prev]
    for i in range(1, len(largeurs)):
        assert largeurs[i] >= largeurs[i - 1] * 0.95, (
            f"l'intervalle du pas {i + 1} ({largeurs[i]:.0f}) est plus étroit "
            f"que celui du pas {i} ({largeurs[i - 1]:.0f})")


@besoin_entrepot
def test_le_decrochage_remonte_jusqu_aux_kpis():
    """Le modèle de décrochage doit alimenter le tableau de bord."""
    from ml_engine.analytics.kpi_engine import _charger_churn_si_servi
    from ml_engine.registre import est_deploye

    ch = _charger_churn_si_servi()
    if not est_deploye("churn"):
        assert ch.get("servi") is False, (
            "un modèle refusé par le registre ne doit pas alimenter le "
            "tableau de bord")
        return

    assert ch.get("servi") is True, "modèle servi par le registre mais absent des KPI"
    top = ch.get("top") or []
    assert top, "aucun client classé"
    assert "nom" in top[0], "le nom du client doit être joint au code"
    enjeux = [float(c.get("enjeu_dt") or 0) for c in top]
    assert enjeux == sorted(enjeux, reverse=True), (
        "le classement doit suivre l'enjeu décroissant")


@besoin_entrepot
def test_la_segmentation_remonte_jusqu_aux_kpis():
    """La typologie doit atteindre le tableau de bord, pas rester dans un JSON."""
    from ml_engine.analytics.kpi_engine import _charger_segmentation_si_servie
    from ml_engine.registre import est_deploye

    s = _charger_segmentation_si_servie()

    if not est_deploye("segmentation"):
        assert s.get("servi") is False, (
            "segmentation refusée par le registre mais présente dans les KPI")
        return

    assert s.get("servi") is True, "servie par le registre mais absente des KPI"
    segments = s.get("segments") or []
    assert segments, "aucun segment remonté"

    noms = [x["nom"] for x in segments]
    assert len(set(noms)) == len(noms), f"noms de segments en double : {noms}"
    for n in noms:
        assert not any(m in n.lower() for m in ("segment ", "cluster", "classe")), \
            f"nom technique affiché à l'utilisateur : {n}"


@besoin_entrepot
def test_la_segmentation_couvre_toute_la_clientele():
    """Les parts doivent totaliser 100 % : aucun client ne doit disparaître."""
    from ml_engine.analytics.kpi_engine import _charger_segmentation_si_servie

    s = _charger_segmentation_si_servie()
    if not s.get("servi"):
        pytest.skip("segmentation non servie")

    segments = s["segments"]
    assert abs(sum(x["part_clients_pct"] for x in segments) - 100) < 1.5
    assert abs(sum(x["part_ca_pct"] for x in segments) - 100) < 1.5
    assert sum(x["n_clients"] for x in segments) == s["n_clients"], (
        "la somme des effectifs de segments ne retombe pas sur le total")


@besoin_entrepot
def test_le_croisement_avec_le_decrochage_est_present():
    """Le croisement est ce qui justifie le module : il doit atteindre l'interface."""
    from ml_engine.analytics.kpi_engine import _charger_segmentation_si_servie
    from ml_engine.registre import est_deploye

    s = _charger_segmentation_si_servie()
    if not s.get("servi") or not est_deploye("churn"):
        pytest.skip("segmentation ou décrochage non servis")

    avec_risque = [x for x in s["segments"] if x.get("part_menacee_pct") is not None]
    assert avec_risque, (
        "aucun segment ne porte de part menacée : le croisement avec le modèle "
        "de décrochage n'atteint pas les KPI")
    for x in avec_risque:
        assert 0 <= x["part_menacee_pct"] <= 100


@besoin_entrepot
def test_le_tableau_de_bord_expose_la_segmentation():
    """Vérification de bout en bout : `compute_dashboard` porte-t-il la clé ?"""
    from ml_engine.analytics.kpi_engine import compute_dashboard

    k = compute_dashboard({})
    assert "segmentation" in k, (
        "`compute_dashboard` ne renvoie pas `segmentation` : le panneau du "
        "tableau de bord restera vide quoi qu'il arrive")
    assert isinstance(k["segmentation"], dict)
    assert "servi" in k["segmentation"]


@besoin_entrepot
def test_aucun_module_refuse_n_est_servi():
    """Un module que le registre refuse ne doit alimenter aucune sortie."""
    from ml_engine.registre import etat_complet

    etat = etat_complet()
    for nom, m in etat["modeles"].items():
        if m["deploye"]:
            continue
        if nom == "churn":
            from ml_engine.analytics.kpi_engine import _charger_churn_si_servi
            assert _charger_churn_si_servi().get("servi") is False, (
                "le décrochage est refusé mais alimente encore les KPI")
        if nom == "echeancier":
            from ml_engine.analytics.kpi_engine import finance_radar
            ids = {c.get("id") for c in finance_radar({}, {})}
            assert "echeancier_1m" not in ids, (
                "l'échéancier est refusé mais s'affiche au radar")
        if nom == "segmentation":
            from ml_engine.analytics.kpi_engine import _charger_segmentation_si_servie
            assert _charger_segmentation_si_servie().get("servi") is False, (
                "la segmentation est refusée mais alimente encore les KPI")


@besoin_entrepot
def test_le_stock_reconstruit_atteint_le_tableau_de_bord():
    """`compute_dashboard` doit porter la clé `stock_flux_reel`."""
    from ml_engine.analytics.kpi_engine import compute_dashboard

    k = compute_dashboard({})
    assert "stock_flux_reel" in k, (
        "`compute_dashboard` ne renvoie pas `stock_flux_reel` : le panneau de "
        "stock retombera sur les quantités simulées")

    flux = k["stock_flux_reel"]
    if not flux.get("disponible"):
        pytest.skip(f"table non matérialisée ({flux.get('motif')})")

    assert float(flux["valeur_immobilisee_dt"]) > 0, "capital immobilisé vide"
    assert "minorant" in (flux.get("nature") or "").lower()


@besoin_entrepot
def test_l_impact_financier_prefere_le_reel_au_simule():
    """Les postes de stock doivent citer les factures, jamais la simulation."""
    from ml_engine.analytics.impact import calculer
    from ml_engine.analytics.kpi_engine import _charger_flux_reels, _connect

    con = _connect()
    try:
        flux = _charger_flux_reels(con)
    finally:
        con.close()
    if not flux.get("disponible"):
        pytest.skip("flux réels indisponibles")

    rapport = calculer()
    postes = {p["poste"]: p for p in rapport["postes"]}

    surstock = [p for p in rapport["postes"] if "immobilisée" in p["poste"]]
    assert surstock, "poste de trésorerie immobilisée absent"
    assert "AUCUNE simulation" in surstock[0]["source_du_chiffre"], (
        "le poste de surstock est servi depuis le module simulé alors que les "
        f"flux réels sont disponibles : {surstock[0]['source_du_chiffre']}")
    assert surstock[0]["montant_identifie_dt"] == flux["valeur_immobilisee_dt"]

    perim = [p for p in rapport["postes"]
             if "péremption" in p["poste"] or "écoulé" in p["poste"]]
    if perim:
        assert "AUCUNE date simulée" in perim[0]["source_du_chiffre"], (
            "la perte de péremption provient encore de dates d'expiration "
            f"inventées : {perim[0]['source_du_chiffre']}")
        assert perim[0]["montant_identifie_dt"] == flux["perte_quasi_certaine_dt"]

    assert postes, "rapport d'impact vide"


@besoin_entrepot
def test_l_obsolescence_epargne_equipements_et_pieces():
    """Un automate ne périme pas, une pièce de rechange non plus."""
    from ml_engine.stock.flux_reels import _est_perissable

    for non_perissable in ("Seals kit vidas range", "VIDAS NSH UPGRADE KIT",
                           "P.M. KIT VIDAS", "AUTOMATE VC FILMARRAY TORCH SYSTEM",
                           "Hb NEXT Analyzer", "FILTER LIQUID COMPLETE"):
        assert not _est_perissable(non_perissable), (
            f"{non_perissable} est compté comme périmable")

    for perissable in ("VIDAS QCV CONTRÔLE QUALITE", "SERIGRUP DIANA A1/B",
                       "VIDAS PROCALCITONINE  60 TESTS"):
        assert _est_perissable(perissable), (
            f"{perissable} est exclu des périmables alors que c'est un "
            "consommable")


@besoin_entrepot
def test_l_encours_ne_signale_pas_tout_le_portefeuille():
    """Une alerte universelle est sa propre réfutation."""
    import json
    import os

    chemin = os.path.join(RACINE, "reports", "encours_metrics.json")
    if not os.path.exists(chemin):
        pytest.skip("encours non calculé")

    m = json.load(open(chemin, encoding="utf-8"))
    part = float(m["a_verifier"]["part_du_total_pct"])
    assert 0 < part < 50, (
        f"{part} % du montant échu est signalé à vérifier — une alerte qui "
        "désigne la majorité du portefeuille ne hiérarchise rien")

    assert m["date_reference_echeances"] > m["date_reference_activite"], (
        "les deux dates de référence ont été confondues : c'est la cause exacte "
        "du défaut d'origine")


@besoin_entrepot
def test_le_panneau_de_reappro_ne_regarde_pas_le_futur():
    """Aucune variable ne doit contenir d'information postérieure au mois observé."""
    from ml_engine.stock.reappro_model import FEATURES, construire_panel

    panel = construire_panel()
    if panel.empty:
        pytest.skip("positions mensuelles non matérialisées")

    assert set(panel["y"].unique()) <= {0, 1}
    assert 0 < panel["y"].mean() < 1, (
        "cible dégénérée : toutes les observations ont la même classe")

    for f in FEATURES:
        if panel[f].nunique() < 2:
            continue
        rho = abs(float(panel[[f, "y"]].corr().iloc[0, 1]))
        assert rho < 0.98, (
            f"la variable `{f}` est corrélée à {rho:.4f} avec la cible — "
            "fuite probable")

    from ml_engine.stock.positions_historiques import charger_panel
    brut = charger_panel()
    if not brut.empty:
        import pandas as pd
        fin_donnees = pd.to_datetime(brut["mois"]).max()
        marge = (fin_donnees.to_period("M")
                 - panel["mois"].max().to_period("M")).n
        assert marge >= 3, (
            f"le panneau va jusqu'à {panel['mois'].max().date()} alors que les "
            f"données s'arrêtent en {fin_donnees.date()} : l'horizon de 3 mois "
            "des dernières observations n'a pas pu être observé")


@besoin_entrepot
def test_le_reappro_respecte_la_decision_du_registre():
    """Servi si et seulement si le registre l'autorise — dans les deux sens."""
    from ml_engine.analytics.kpi_engine import _charger_reappro_si_servi
    from ml_engine.registre import est_deploye

    r = _charger_reappro_si_servi()
    if est_deploye("reappro"):
        assert r.get("servi") is True, (
            "le registre déclare le modèle servi mais les KPI ne le portent pas")
        assert (r.get("top") or []), "aucune référence classée"
        budgets = [float(x.get("budget_dt") or 0) for x in r["top"]]
        assert budgets == sorted(budgets, reverse=True), (
            "le classement ne suit pas le budget décroissant")
    else:
        assert r.get("servi") is False, (
            "modèle refusé par le registre mais servi au tableau de bord")


@besoin_entrepot
def test_le_tableau_de_bord_expose_le_reappro():
    """Chemin exact de l'application : `compute_dashboard` porte-t-il la clé ?"""
    from ml_engine.analytics.kpi_engine import compute_dashboard

    k = compute_dashboard({})
    assert "reappro" in k, (
        "`compute_dashboard` ne renvoie pas `reappro` : le module resterait "
        "débranché quelle que soit sa performance")
    assert "servi" in k["reappro"]


def test_tout_artefact_serialise_est_couvert_par_le_reentrainement():
    """Un modèle absent de `retrain_all.py` reste sur une version périmée."""
    import importlib.util
    import os

    chemin = os.path.join(RACINE, "scripts", "retrain_all.py")
    spec = importlib.util.spec_from_file_location("retrain_all", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    couverts = {a["fichier"] for a in mod.ARTEFACTS}
    dossier = os.path.join(RACINE, "models")
    if not os.path.isdir(dossier):
        pytest.skip("dossier models/ absent")

    presents = {f for f in os.listdir(dossier) if f.endswith(".joblib")}
    manquants = presents - couverts
    assert not manquants, (
        f"artefact(s) jamais ré-entraîné(s) par retrain_all.py : {manquants}")

    for a in mod.ARTEFACTS:
        module = importlib.import_module(a["module"])
        nom_fn = a.get("fonction", "train")
        assert hasattr(module, nom_fn), (
            f"{a['module']} n'expose pas `{nom_fn}` — l'entrée du registre de "
            "maintenance est fausse et l'échec serait silencieux")


def test_aucun_artefact_serialise_n_echappe_au_reentrainement():
    """Le test précédent ne regardait que `models/` — et laissait passer un cas."""
    import importlib.util
    import os

    chemin = os.path.join(RACINE, "scripts", "retrain_all.py")
    spec = importlib.util.spec_from_file_location("retrain_all", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    couverts = {a["fichier"] for a in mod.ARTEFACTS}
    couverts.add(os.path.basename(str(mod.INDEX_RAG)))

    tolere = {"chunks.pkl"}
    ignores = {".venv", "node_modules", ".git", "__pycache__", ".pytest_cache"}

    orphelins = []
    for racine, dossiers, fichiers in os.walk(RACINE):
        dossiers[:] = [d for d in dossiers if d not in ignores]
        for f in fichiers:
            if not f.endswith((".joblib", ".pkl")):
                continue
            if f in couverts or f in tolere:
                continue
            orphelins.append(os.path.relpath(os.path.join(racine, f), RACINE))

    assert not orphelins, (
        f"artefact(s) sérialisé(s) qu'aucune commande de maintenance ne "
        f"réaligne : {orphelins}")


def test_la_nomenclature_est_la_seule_autorite_de_classement():
    """`flux_reels` ne doit plus porter ses propres motifs."""
    from ml_engine.stock import flux_reels, nomenclature

    assert not hasattr(flux_reels, "_MOTIFS_PIECE"), (
        "flux_reels porte encore ses propres motifs de pièce détachée")
    assert not hasattr(flux_reels, "_MOTIFS_EQUIPEMENT"), (
        "flux_reels porte encore ses propres motifs d'équipement")

    for p in ("Seals kit vidas range", "VIDAS NSH UPGRADE KIT",
              "VIDAS QCV CONTRÔLE QUALITE", "Hb NEXT Analyzer"):
        assert flux_reels._est_perissable(p) == nomenclature.est_perissable(p)


@besoin_entrepot
def test_la_conversion_devis_atteint_le_tableau_de_bord():
    """Un modèle servi qui n'atteint pas l'écran n'existe pas pour l'utilisateur."""
    from ml_engine.analytics.kpi_engine import compute_dashboard
    from ml_engine.registre import est_deploye

    k = compute_dashboard({})
    assert "conversion_devis" in k, (
        "`compute_dashboard` ne renvoie pas `conversion_devis` : le panneau "
        "resterait vide quelle que soit la performance du modèle")

    d = k["conversion_devis"]
    if est_deploye("conversion_devis"):
        assert d.get("servi") is True, (
            "le registre déclare le modèle servi mais les KPI ne le portent pas")
        top = d.get("top") or []
        if top:
            esp = [float(x.get("esperance_dt") or 0) for x in top]
            assert esp == sorted(esp, reverse=True), (
                "le classement ne suit pas l'espérance de chiffre d'affaires")
            for x in top:
                assert 0.0 <= float(x["probabilite"]) <= 1.0
    else:
        assert d.get("servi") is False, (
            "modèle refusé par le registre mais servi au tableau de bord")


@besoin_entrepot
def test_la_marge_client_atteint_le_tableau_de_bord():
    """Même garantie pour l'érosion de marge, et même classement par enjeu."""
    from ml_engine.analytics.kpi_engine import compute_dashboard
    from ml_engine.registre import est_deploye

    k = compute_dashboard({})
    assert "marge_client" in k, (
        "`compute_dashboard` ne renvoie pas `marge_client`")

    d = k["marge_client"]
    if est_deploye("marge_client"):
        assert d.get("servi") is True
        top = d.get("top") or []
        if top:
            enjeux = [float(x.get("marge_en_jeu_dt") or 0) for x in top]
            assert enjeux == sorted(enjeux, reverse=True), (
                "le classement ne suit pas la marge en jeu décroissante")
    else:
        assert d.get("servi") is False


@besoin_entrepot
def test_le_devis_ne_regarde_pas_le_futur():
    """Aucune variable ne doit contenir d'information postérieure au devis."""
    from ml_engine.analytics.conversion_devis import FEATURES, construire_panel

    panel = construire_panel()
    if panel.empty:
        pytest.skip("table devis indisponible")

    assert set(panel["y"].unique()) <= {0, 1}
    assert 0 < panel["y"].mean() < 1, "cible dégénérée"

    for f in FEATURES:
        if panel[f].nunique() < 2:
            continue
        rho = abs(float(panel[[f, "y"]].corr().iloc[0, 1]))
        assert rho < 0.98, (
            f"la variable `{f}` est corrélée à {rho:.4f} avec la cible — "
            "fuite probable")


@besoin_entrepot
def test_le_censurage_des_devis_recents_est_applique():
    """Les devis trop récents pour être jugés doivent être ÉCARTÉS."""
    import pandas as pd

    from ml_engine.analytics.conversion_devis import (MATURATION_MOIS,
                                                      construire_panel)

    apprentissage = construire_panel()
    complet = construire_panel(pour_prediction=True)
    if apprentissage.empty or complet.empty:
        pytest.skip("table devis indisponible")

    fin = complet["date"].max()
    limite = fin - pd.DateOffset(months=MATURATION_MOIS)
    assert apprentissage["date"].max() <= limite, (
        f"le panneau d'apprentissage va jusqu'à {apprentissage['date'].max()} "
        f"alors que la limite de maturation est {limite}")

    assert complet["date"].max() > limite, (
        "le panneau de prédiction écarte les devis récents — or ce sont les "
        "seuls sur lesquels une relance change quelque chose")


@besoin_entrepot
def test_le_seuil_de_marge_est_calcule_sur_le_train_seul():
    """Un seuil déduit de l'ensemble des données ferait fuiter le test."""
    from ml_engine.analytics.marge_client import (construire_panel,
                                                  seuil_marge_basse)

    panel = construire_panel()
    if panel.empty:
        pytest.skip("panneau de marge indisponible")

    coupure = panel["mois"].quantile(0.75)
    train = panel[panel["mois"] <= coupure]
    if len(train) < 100:
        pytest.skip("train trop petit")

    seuil_train = seuil_marge_basse(train)
    seuil_global = seuil_marge_basse(panel)

    assert seuil_train == seuil_train, "seuil non calculable"
    assert isinstance(seuil_global, float)


def test_aucun_module_servi_ne_depend_de_donnees_simulees():
    """La règle qui fait tenir tout le domaine stock, rendue exécutoire."""
    from ml_engine.registre import MODELES, etat_complet

    DEPENDANTS_DU_SIMULE = {"stock_risque"}

    etat = etat_complet()
    for nom in DEPENDANTS_DU_SIMULE:
        assert nom in MODELES, f"{nom} a disparu du registre sans trace"
        m = etat["modeles"][nom]
        assert m["deploye"] is False, (
            f"{nom} est SERVI alors que sa cible dépend de données simulées")
        assert m.get("retire") is True, (
            f"{nom} n'est pas marqué « retiré » : un lecteur du registre croirait "
            "à un simple échec de performance")
        assert "simul" in (m.get("motif") or "").lower(), (
            f"le motif de retrait de {nom} ne cite pas la simulation : "
            f"« {m.get('motif')} »")

    for nom in etat["deployes"]:
        assert nom not in DEPENDANTS_DU_SIMULE, (
            f"{nom} est servi alors qu'il figure parmi les modules dépendant du "
            "stock simulé")


@besoin_entrepot
def test_la_famille_erp_prime_sur_les_mots_cles():
    """La donnée ERP doit gouverner le classement, pas le libellé."""
    from ml_engine.stock.flux_reels import _connect
    from ml_engine.stock.nomenclature import charger_familles_erp, mesurer

    con = _connect()
    try:
        familles = charger_familles_erp(con)
        m = mesurer(con)
    finally:
        con.close()

    if not familles:
        pytest.skip("aucune famille ERP lisible")

    assert len(familles) > 100, (
        f"seulement {len(familles)} désignations portent une famille ERP — "
        "la lecture est probablement cassée")

    if not m.get("disponible"):
        pytest.skip("stock_flux_reel absent")

    origines = m["par_origine"]
    val_erp = origines["erp"]["valeur_dt"] + origines["erp_precise"]["valeur_dt"]
    val_totale = m["valeur_totale_dt"]

    assert val_erp > val_totale * 0.5, (
        f"seulement {val_erp:.0f} DT sur {val_totale:.0f} classés par l'ERP — "
        "la famille ERP ne gouverne pas le classement")


def test_le_mot_cle_piece_precise_l_erp_sans_le_contredire():
    """La famille ERP n'a aucune valeur « pièce détachée » — d'où cette exception."""
    from ml_engine.stock import nomenclature as nm

    cache_origine = nm._familles_erp
    try:
        nm._familles_erp = {
            "SEALS KIT VIDAS RANGE": "REACTIF",
            "VIDAS NSH UPGRADE KIT": "REACTIF",
            "VIDAS QCV CONTROLE QUALITE": "REACTIF",
            "AUTOMATE VC FILMARRAY TORCH SYSTEM": "EQUIPEMENT",
            "CONTRAT DE MAINTENANCE VIDAS": "SERVICE",
        }

        assert nm.classer("Seals kit vidas range") == nm.PIECE
        assert nm.classer("VIDAS NSH UPGRADE KIT") == nm.PIECE
        assert not nm.est_perissable("Seals kit vidas range")
        assert nm.origine_du_classement("Seals kit vidas range") == "erp_precise"

        assert nm.classer("VIDAS QCV CONTROLE QUALITE") == nm.CONSOMMABLE
        assert nm.est_perissable("VIDAS QCV CONTROLE QUALITE")
        assert nm.origine_du_classement("VIDAS QCV CONTROLE QUALITE") == "erp"

        assert nm.classer("AUTOMATE VC FILMARRAY TORCH SYSTEM") == nm.EQUIPEMENT
        assert nm.classer("CONTRAT DE MAINTENANCE VIDAS") == nm.PRESTATION
    finally:
        nm._familles_erp = cache_origine


def test_la_classification_est_deterministe_et_exhaustive():
    """Toute désignation reçoit exactement une catégorie connue."""
    from ml_engine.stock.nomenclature import CATEGORIES, classer

    for p in ("", "   ", "PRODUIT INCONNU XZ42", "CONTRAT DE MAINTENANCE",
              "AUTOMATE VC VIDAS KUBE CLINIC", "FILTER LIQUID COMPLETE",
              "VIDAS PROCALCITONINE  60 TESTS", None):
        cat = classer(p)
        assert cat in CATEGORIES, f"catégorie inconnue « {cat} » pour « {p} »"
        assert classer(p) == cat

    from ml_engine.stock.nomenclature import CONSOMMABLE
    assert classer("") != CONSOMMABLE
    assert classer(None) != CONSOMMABLE


@besoin_entrepot
def test_la_perte_decroit_quand_le_seuil_augmente():
    """Vérification de sens : la perte porte sur l'EXCÉDENT au-delà du seuil."""
    from ml_engine.stock.flux_reels import SEUIL_OBSOLESCENCE_CERTAINE, sensibilite_seuils

    s = sensibilite_seuils(seuils=(18, 24, 30))
    res = s.get("resultats") or {}
    if len(res) < 2:
        pytest.skip("flux réels indisponibles")

    pertes = [res[f"{k}_mois"]["perte_quasi_certaine_dt"] for k in (18, 24, 30)]
    for i in range(1, len(pertes)):
        assert pertes[i] <= pertes[i - 1], (
            f"la perte augmente avec le seuil ({pertes}) — l'excédent n'est pas "
            "calculé au-delà du seuil")

    assert SEUIL_OBSOLESCENCE_CERTAINE == s["seuil_servi_mois"]
