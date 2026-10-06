"""Un écart en pourcentage ne se lit que si l'on sait contre quoi.

Le défaut corrigé ici : la carte annonçait « −66 % vs passé » sans dire sur
quels mois, sans montrer le montant de la base, et sans signaler que cette base
était un trimestre exceptionnel. Le chiffre était juste et la lecture fausse.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ml_engine.analytics import ca_client as cc


def _panel(horizon: int = 3) -> pd.DataFrame:
    try:
        return cc.construire_panel(horizon=horizon, pour_prediction=True)
    except Exception as e:  # pragma: no cover - entrepôt absent
        pytest.skip(f"panneau indisponible : {type(e).__name__}")


def test_les_fenetres_sont_calculees_depuis_la_derniere_donnee():
    """Jamais depuis l'horloge : les données s'arrêtent à l'export.

    Compter depuis aujourd'hui ferait vieillir la prévision chaque jour sans
    qu'aucune facture n'ait bougé."""
    panel = _panel()
    if panel.empty:
        pytest.skip("panneau vide")
    f = cc._fenetres(panel, 3)
    fin = pd.Timestamp(panel["mois"].max())
    assert f["derniere_donnee"] == fin.strftime("%Y-%m")
    assert f["passe_fin"] == fin.strftime("%Y-%m")


def test_les_deux_fenetres_ont_la_meme_longueur():
    """Comparer trois mois mesurés à quatre mois attendus fausserait l'écart."""
    panel = _panel()
    if panel.empty:
        pytest.skip("panneau vide")
    for horizon in (3, 12):
        f = cc._fenetres(panel, horizon)
        passe = (pd.Period(f["passe_fin"], "M") - pd.Period(f["passe_debut"], "M")).n
        futur = (pd.Period(f["futur_fin"], "M") - pd.Period(f["futur_debut"], "M")).n
        assert passe == futur == horizon - 1


def test_la_fenetre_future_commence_apres_la_derniere_donnee():
    panel = _panel()
    if panel.empty:
        pytest.skip("panneau vide")
    f = cc._fenetres(panel, 3)
    assert pd.Period(f["futur_debut"], "M") > pd.Period(f["passe_fin"], "M")


def test_la_lecture_nomme_les_deux_fenetres():
    panel = _panel()
    if panel.empty:
        pytest.skip("panneau vide")
    f = cc._fenetres(panel, 3)
    assert f["passe_debut"] in f["lecture"]
    assert f["futur_fin"] in f["lecture"]
    assert "mesuré" in f["lecture"] and "attendu" in f["lecture"]


def test_le_rythme_habituel_est_le_ca_12m_ramene_a_l_horizon():
    """C'est lui qui permet de dire si la base de comparaison est anormale.

    Sans ce repère, un client qui revient à la normale après un trimestre
    exceptionnel affiche un effondrement."""
    panel = _panel()
    if panel.empty:
        pytest.skip("panneau vide")
    horizon = 3
    dernier = panel.sort_values("mois").groupby("client", as_index=False).tail(1)
    attendu = dernier["ca_12m"] * horizon / 12.0
    assert (attendu >= 0).all()
    # Sur un client au rythme régulier, la fenêtre de comparaison et le rythme
    # habituel se ressemblent ; sur un client irrégulier, ils divergent. Les
    # deux cas doivent exister, sinon le signalement ne sert à rien.
    base = dernier[f"ca_{horizon}m"]
    ecart = ((base - attendu) / attendu.replace(0, pd.NA) * 100).dropna()
    assert (ecart.abs() < 25).any(), "aucun client régulier"
    assert (ecart.abs() >= 25).any(), "aucun client irrégulier"


def test_le_module_declare_quelle_mesure_il_utilise():
    """La courbe du tableau de bord affiche le CA TTC des en-têtes, le modèle
    travaille sur le montant signé des lignes : les deux diffèrent de quelques
    pour cent et ne se comparent pas directement. Il faut le dire."""
    source = (cc.__file__ or "")
    assert source
    import inspect
    texte = inspect.getsource(cc.predire)
    assert "mesure" in texte
    assert "TTC" in texte and "LIGNES" in texte
