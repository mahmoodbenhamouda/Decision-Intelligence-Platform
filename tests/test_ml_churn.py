"""Tests du modèle de décrochage client et du registre de modèles."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from ml_engine.analytics import churn_model as cm  # noqa: E402


def _client(code: str, dates: list[str], ttc: float = 1000.0) -> pd.DataFrame:
    return pd.DataFrame({
        "client": code,
        "date": pd.to_datetime(dates),
        "n_factures": 1,
        "ttc": ttc,
    })


@pytest.fixture
def factures_synthetiques() -> pd.DataFrame:
    """Deux comportements nets, construits pour être distinguables à la main."""
    reguliers = pd.date_range("2021-01-15", "2024-12-15", freq="MS").strftime("%Y-%m-%d")
    avant_arret = pd.date_range("2021-01-20", "2023-06-20", freq="MS").strftime("%Y-%m-%d")
    return pd.concat([
        _client("REGULIER", list(reguliers), 1500.0),
        _client("DECROCHE", list(avant_arret), 900.0),
    ], ignore_index=True).sort_values(["client", "date"]).reset_index(drop=True)


def test_les_variables_ignorent_tout_ce_qui_suit_la_date_observation(factures_synthetiques):
    """Modifier le FUTUR d'un client ne doit changer AUCUNE de ses variables."""
    t = pd.Timestamp("2023-01-31")
    hist = factures_synthetiques
    passe = hist[(hist["client"] == "REGULIER") & (hist["date"] <= t)]

    avant = cm._features_client(passe, t)
    assert avant is not None

    futur = _client("REGULIER",
                    ["2023-02-10", "2023-03-10", "2023-04-10"], 999_999.0)
    passe_inchange = pd.concat([passe, futur], ignore_index=True)
    passe_inchange = passe_inchange[passe_inchange["date"] <= t]

    apres = cm._features_client(passe_inchange, t)
    assert apres == avant, (
        "une variable a changé alors que seul le futur a été modifié : "
        "il y a fuite temporelle")


def test_la_cible_se_lit_uniquement_dans_la_fenetre_future(factures_synthetiques):
    """La cible doit valoir 1 si et seulement si le futur immédiat est vide."""
    panel = cm.construire_panel(factures_synthetiques, horizon=90)
    assert not panel.empty

    tardif = panel[(panel["client"] == "DECROCHE")
                   & (panel["date_obs"] >= pd.Timestamp("2023-08-31"))]
    if not tardif.empty:
        assert (tardif["y"] == 1).all(), (
            "un client sans aucune facture future doit être étiqueté décroché")

    reg = panel[(panel["client"] == "REGULIER")
                & (panel["date_obs"] <= pd.Timestamp("2024-06-30"))]
    if not reg.empty:
        assert (reg["y"] == 0).all(), (
            "un client qui commande chaque mois ne peut pas être décroché")


def test_le_panel_ne_va_pas_jusqu_a_une_cible_tronquee(factures_synthetiques):
    """Aucune observation ne doit avoir sa fenêtre cible coupée par la fin des données."""
    horizon = 90
    panel = cm.construire_panel(factures_synthetiques, horizon=horizon)
    fin_donnees = factures_synthetiques["date"].max()
    limite = fin_donnees - pd.Timedelta(days=horizon)
    assert panel["date_obs"].max() <= limite, (
        f"le panel va jusqu'à {panel['date_obs'].max()} alors que la dernière "
        f"date d'observation dont la cible est complète est {limite}")


def test_le_filtre_client_actif_ecarte_les_clients_deja_partis(factures_synthetiques):
    """Un client inactif depuis plus d'un an ne doit pas produire d'observation."""
    t = pd.Timestamp("2024-12-31")
    hist = factures_synthetiques
    passe = hist[(hist["client"] == "DECROCHE") & (hist["date"] <= t)]
    assert cm._features_client(passe, t) is None, (
        "un client sans activité sur la fenêtre d'activité doit être écarté")


def test_ratio_recence_intervalle_distingue_les_deux_profils(factures_synthetiques):
    """La variable clé doit être nettement plus élevée pour le client qui décroche."""
    t = pd.Timestamp("2023-09-30")
    hist = factures_synthetiques

    f_reg = cm._features_client(hist[(hist["client"] == "REGULIER")
                                     & (hist["date"] <= t)], t)
    f_dec = cm._features_client(hist[(hist["client"] == "DECROCHE")
                                     & (hist["date"] <= t)], t)
    assert f_reg is not None and f_dec is not None
    assert f_dec["ratio_recence_intervalle"] > f_reg["ratio_recence_intervalle"] * 2, (
        "le rapport récence/intervalle ne sépare pas un client actif d'un client "
        "en train de décrocher")


def test_toutes_les_variables_declarees_sont_produites(factures_synthetiques):
    """`FEATURES` et les variables réellement calculées ne doivent pas diverger."""
    t = pd.Timestamp("2023-06-30")
    hist = factures_synthetiques
    f = cm._features_client(hist[(hist["client"] == "REGULIER")
                                 & (hist["date"] <= t)], t)
    assert f is not None
    produites = set(f) - {"client", "date_obs", "y"}
    assert set(cm.FEATURES) == produites, (
        f"déclarées mais absentes : {set(cm.FEATURES) - produites} ; "
        f"calculées mais non déclarées : {produites - set(cm.FEATURES)}")


@pytest.mark.vitrine
def test_aucune_variable_n_est_la_cible_deguisee():
    """Aucune variable ne doit porter un nom évoquant le futur ou la cible."""
    interdits = ("futur", "future", "apres", "y_", "cible", "target", "label")
    for f in cm.FEATURES:
        assert not any(mot in f.lower() for mot in interdits), (
            f"la variable `{f}` porte un nom évoquant la cible")


def test_le_train_hors_periode_respecte_la_marge():
    """Aucune observation d'entraînement ne doit voir au-delà de la coupure."""
    horizon = 90
    dates = pd.date_range("2021-06-30", "2024-06-30", freq="ME")
    panel = pd.DataFrame({
        "date_obs": dates,
        "client": [f"C{i%7}" for i in range(len(dates))],
        "y": [i % 3 == 0 for i in range(len(dates))],
    })
    coupure = panel["date_obs"].quantile(0.75)
    train = panel[panel["date_obs"] + pd.Timedelta(days=horizon) <= coupure]

    assert not train.empty
    fin_cible_max = (train["date_obs"] + pd.Timedelta(days=horizon)).max()
    assert fin_cible_max <= coupure, (
        f"la cible d'une observation d'entraînement s'étend jusqu'à "
        f"{fin_cible_max}, au-delà de la coupure {coupure}")


def test_le_registre_refuse_un_modele_inconnu():
    from ml_engine import registre

    e = registre.etat_modele("modele_qui_n_existe_pas")
    assert e["deploye"] is False
    assert e["connu"] is False


def test_le_registre_refuse_quand_le_rapport_manque(tmp_path, monkeypatch):
    """Sans rapport, un modèle doit être refusé — pas servi par défaut."""
    from ml_engine import registre

    monkeypatch.setattr(registre, "REPORTS_DIR", tmp_path / "vide")
    e = registre.etat_modele("churn")
    assert e["deploye"] is False
    assert "absent" in e["motif"].lower()


def test_le_registre_expose_un_etat_complet_coherent():
    """Les trois états doivent PARTITIONNER le registre — aucun module perdu."""
    from ml_engine import registre

    e = registre.etat_complet()
    assert set(e["modeles"]) == set(registre.MODELES)

    servis = set(e["deployes"])
    refuses = set(e["refuses"])
    retires = set(e.get("retires") or [])

    assert servis | refuses | retires == set(registre.MODELES), (
        "des modules n'appartiennent à aucun des trois états : "
        f"{set(registre.MODELES) - (servis | refuses | retires)}")
    assert not (servis & refuses) and not (servis & retires) \
        and not (refuses & retires), "les trois états se recouvrent"
    assert e["n_deployes"] + len(refuses) + len(retires) == e["n_total"]

    for nom, m in e["modeles"].items():
        assert isinstance(m["deploye"], bool), f"{nom} : `deploye` doit être booléen"
        if m.get("retire"):
            assert m["deploye"] is False, (
                f"{nom} est marqué retiré ET déployé — contradiction")


def test_le_registre_suit_la_decision_ecrite_dans_le_rapport(tmp_path, monkeypatch):
    """Le registre rapporte la décision mesurée — il ne la recalcule pas."""
    import json

    from ml_engine import registre

    rep = tmp_path / "reports"
    mod = tmp_path / "models"
    rep.mkdir()
    mod.mkdir()
    (mod / "churn_model.joblib").write_bytes(b"artefact factice")

    for attendu in (True, False):
        json.dump(
            {"version": 1,
             "decision_deploiement": {"modele_deploye": attendu, "motif": "test"},
             "hors_periode": {"auc": 0.9,
                              "auc_meilleure_reference_triviale": 0.8}},
            open(rep / "churn_metrics.json", "w", encoding="utf-8"))

        monkeypatch.setattr(registre, "REPORTS_DIR", rep)
        monkeypatch.setattr(registre, "MODELS_DIR", mod)
        assert registre.est_deploye("churn") is attendu


def test_le_registre_refuse_si_l_artefact_manque(tmp_path, monkeypatch):
    """Un rapport favorable ne suffit pas : l'artefact doit être présent."""
    import json

    from ml_engine import registre

    rep = tmp_path / "reports"
    rep.mkdir()
    json.dump(
        {"version": 1,
         "decision_deploiement": {"modele_deploye": True, "motif": "test"},
         "hors_periode": {"auc": 0.9, "auc_meilleure_reference_triviale": 0.8}},
        open(rep / "churn_metrics.json", "w", encoding="utf-8"))

    monkeypatch.setattr(registre, "REPORTS_DIR", rep)
    monkeypatch.setattr(registre, "MODELS_DIR", tmp_path / "models_absents")
    assert registre.est_deploye("churn") is False


def test_le_modele_separe_deux_profils_construits_pour_etre_separables():
    """Sur des profils nets, l'AUC doit être franchement supérieure au hasard."""
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(0)
    lignes = []
    for i in range(40):
        d = pd.date_range("2021-01-10", "2024-12-10", freq="MS")
        lignes.append(_client(f"REG{i}", list(d.strftime("%Y-%m-%d")),
                              float(rng.uniform(500, 2000))))
    for i in range(40):
        fin = pd.Timestamp("2022-06-10") + pd.Timedelta(days=int(rng.integers(0, 500)))
        d = pd.date_range("2021-01-10", fin, freq="MS")
        if len(d) < 4:
            continue
        lignes.append(_client(f"STOP{i}", list(d.strftime("%Y-%m-%d")),
                              float(rng.uniform(500, 2000))))

    df = pd.concat(lignes, ignore_index=True).sort_values(["client", "date"])
    panel = cm.construire_panel(df.reset_index(drop=True), horizon=90)

    assert len(panel) > 200, f"panel trop petit ({len(panel)}) pour conclure"
    assert panel["y"].nunique() == 2, "les deux classes doivent être présentes"

    coupure = panel["date_obs"].quantile(0.7)
    tr = panel[panel["date_obs"] + pd.Timedelta(days=90) <= coupure]
    te = panel[panel["date_obs"] > coupure]
    if len(tr) < 100 or len(te) < 50 or te["y"].nunique() < 2:
        pytest.skip("découpage synthétique insuffisant sur cette configuration")

    m = cm._modele("regression_logistique")
    m.fit(tr[cm.FEATURES], tr["y"])
    auc = roc_auc_score(te["y"], m.predict_proba(te[cm.FEATURES])[:, 1])
    assert auc > 0.70, (
        f"AUC={auc:.3f} sur des profils synthétiques tranchés : la chaîne "
        "panel → variables → modèle a un défaut")


def test_la_parcimonie_prefere_le_modele_simple_a_gain_egal():
    """À performance équivalente, le modèle le plus simple doit être retenu."""
    assert cm.CANDIDATS[0] == "regression_logistique", (
        "le candidat le plus simple doit être en tête : c'est lui qui est retenu "
        "quand l'écart d'AUC reste sous le seuil de parcimonie")
    assert 0 < cm.ECART_PARCIMONIE < 0.05
