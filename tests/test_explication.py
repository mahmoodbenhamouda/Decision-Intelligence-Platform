"""L'explicabilité tient ses promesses — ou elle ne vaut rien."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from ml_engine.explication import (LIBELLES, VERBES_DE_DIRECTION,  # noqa: E402
                                   contrefactuel, contributions_lineaires,
                                   contributions_shap, decrire_variable,
                                   extraire_pipeline_lineaire,
                                   fidelite_suppression, libelle_variable,
                                   raisons_seuils)

VARIABLES = ["recence_j", "freq_12m", "ca_12m", "tendance_ca"]


# ── La décomposition est exacte ──────────────────────────────────────────────

@pytest.mark.vitrine
def test_la_somme_des_contributions_reconstitue_le_score_du_modele():
    """La promesse « décomposition exacte » est tenue au flottant près."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    rng = np.random.RandomState(0)
    X = rng.normal(size=(400, len(VARIABLES)))
    y = (X[:, 0] * 1.4 - X[:, 1] * 0.9 + rng.normal(scale=0.3, size=400) > 0).astype(int)

    modele = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(X, y)
    lin = extraire_pipeline_lineaire(modele)
    assert lin is not None

    ligne = X[7]
    contributions = [
        float(lin["coefficients"][i]) * (float(ligne[i]) - float(lin["moyennes"][i]))
        / (float(lin["ecarts"][i]) or 1.0)
        for i in range(len(VARIABLES))]
    intercept = float(modele.named_steps["logisticregression"].intercept_[0])

    p = float(modele.predict_proba([ligne])[0, 1])
    logit_modele = np.log(p / (1 - p))
    assert abs(intercept + sum(contributions) - logit_modele) < 1e-9


@pytest.mark.vitrine
def test_les_coefficients_viennent_du_modele_servi_pas_dun_substitut():
    """Un calibrateur contient K estimateurs : leur moyenne est extraite telle
    quelle, au lieu de réentraîner un modèle qui expliquerait autre chose."""
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(0)
    n, p = 500, 5
    X = rng.normal(size=(n, p)) * rng.uniform(1, 40, p) + rng.uniform(-5, 5, p)
    y = (X @ rng.normal(size=p) / 20 + rng.normal(size=n) > 0).astype(int)
    groupes = rng.integers(0, 50, n)

    cal = CalibratedClassifierCV(
        make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
        method="isotonic",
        cv=list(GroupKFold(n_splits=5).split(X, y, groupes))).fit(X, y)

    lin = extraire_pipeline_lineaire(cal)
    assert lin is not None
    assert "modèle servi" in lin["origine"]

    internes = []
    for c in cal.calibrated_classifiers_:
        est = getattr(c, "estimator", None) or getattr(c, "base_estimator", None)
        internes.append(est.decision_function(X))
    attendu = np.mean(internes, axis=0)

    reconstruit = (((X - np.asarray(lin["moyennes"])) / np.asarray(lin["ecarts"]))
                   @ np.asarray(lin["coefficients"]))
    ecart = (reconstruit - reconstruit.mean()) - (attendu - attendu.mean())
    assert np.abs(ecart).max() < 1e-9, (
        "la moyenne des K fonctions linéaires n'est pas reproduite exactement")


def test_un_modele_non_lineaire_ne_produit_aucune_explication_lineaire():
    """Mieux vaut aucune explication qu'une explication d'un autre modèle."""
    from sklearn.ensemble import RandomForestClassifier

    rng = np.random.RandomState(1)
    X = rng.normal(size=(60, 4))
    y = (X[:, 0] > 0).astype(int)
    assert extraire_pipeline_lineaire(
        RandomForestClassifier(n_estimators=5).fit(X, y)) is None


# ── Les parts affichées ──────────────────────────────────────────────────────

def test_les_parts_affichees_totalisent_cent_pour_cent():
    raisons = contributions_lineaires(
        coefficients=[2.0, 1.0, 0.5, -3.0],
        moyennes=[0, 0, 0, 0], ecarts=[1, 1, 1, 1],
        valeurs=[1.0, 1.0, 1.0, 1.0], variables=VARIABLES)
    poussent = [r for r in raisons if r["poids"] is not None]
    assert len(poussent) == 3
    assert abs(sum(r["poids"] for r in poussent) - 1.0) < 1e-6


def test_le_facteur_en_sens_inverse_ne_recoit_aucune_part():
    """Un « 99 % » à côté de trois parts qui font déjà 100 % ne veut rien dire."""
    raisons = contributions_lineaires(
        coefficients=[1.0, 0.5, 0.2, -9.0],
        moyennes=[0] * 4, ecarts=[1] * 4, valeurs=[1.0] * 4, variables=VARIABLES)
    inverses = [r for r in raisons if r["sens"] == "protege"]
    assert len(inverses) == 1
    assert inverses[0]["poids"] is None


def test_le_vocabulaire_du_sens_est_adaptable():
    """Ce qui « aggrave » un départ « favorise » une signature : un seul module."""
    raisons = contributions_lineaires(
        [1.0, -1.0, 0.0, 0.0], [0] * 4, [1] * 4, [1.0] * 4, VARIABLES,
        sens=("favorise", "freine"))
    assert {r["sens"] for r in raisons} == {"favorise", "freine"}


def test_les_valeurs_shap_sont_ordonnees_par_influence():
    raisons = contributions_shap(
        valeurs_shap=[0.1, 0.9, 0.4, -0.7],
        valeurs=[1, 2, 3, 4], variables=VARIABLES)
    poussent = [r for r in raisons if r["sens"] == "aggrave"]
    assert [r["variable"] for r in poussent] == ["freq_12m", "ca_12m", "recence_j"]


# ── Aucun libellé n'affirme une direction ────────────────────────────────────

@pytest.mark.vitrine
def test_aucun_libelle_naffirme_une_direction():
    """Le cœur de la correction.

    Une contribution positive peut venir d'un coefficient positif avec une valeur
    haute OU d'un coefficient négatif avec une valeur basse. Un libellé qui dit
    « faible » ou « en retrait » tranche sans savoir, et se trompait : avec
    `tendance_freq = 2.0` — deux fois plus de commandes qu'avant — l'écran
    affichait « il commande moins souvent qu'avant ».
    """
    fautifs = []
    for variable, (libelle, _) in LIBELLES.items():
        bas = libelle.lower()
        for verbe in VERBES_DE_DIRECTION:
            if verbe in bas:
                fautifs.append(f"{variable} → « {libelle} » contient « {verbe} »")
    assert not fautifs, fautifs


def test_le_sens_vient_du_signe_de_la_contribution_pas_du_libelle():
    """La MÊME valeur, deux coefficients opposés : le sens doit s'inverser."""
    for signe, attendu in ((+1.0, "aggrave"), (-1.0, "protege")):
        raisons = contributions_lineaires(
            [signe, 0.0, 0.0, 0.0], [0] * 4, [1] * 4, [2.0, 0, 0, 0], VARIABLES)
        concernees = [r for r in raisons if r["variable"] == "recence_j"]
        assert concernees, f"recence_j absente pour un coefficient {signe}"
        assert concernees[0]["sens"] == attendu
        # Le libellé, lui, est identique dans les deux cas : il ne juge pas.
        assert concernees[0]["libelle"] == libelle_variable("recence_j")


def test_la_position_est_un_centile_quand_la_distribution_est_fournie():
    reference = {"recence_j": np.arange(0, 400, dtype=float)}
    raisons = contributions_lineaires(
        [1.0, 0, 0, 0], [0] * 4, [1] * 4, [360.0, 0, 0, 0], VARIABLES,
        reference=reference)
    r = [x for x in raisons if x["variable"] == "recence_j"][0]
    assert r["centile"] == 90
    assert "centile" in r["explication"]


def test_sans_distribution_la_position_reste_prudente():
    """Sans référence, on énonce le côté de la moyenne, jamais un centile."""
    raisons = contributions_lineaires(
        [1.0, 0, 0, 0], [50.0, 0, 0, 0], [10.0, 1, 1, 1], [80.0, 0, 0, 0],
        VARIABLES)
    r = [x for x in raisons if x["variable"] == "recence_j"][0]
    assert r["centile"] is None
    assert "centile" not in r["explication"]
    assert "au-dessus" in r["explication"]


JARGON = re.compile(
    r"\b(shap|coefficient|logit|feature|variable|régression|logistique|"
    r"gradient|boosting|modèle|écart-type|probabilité calibrée|score brut)\b|_",
    re.I)


@pytest.mark.vitrine
def test_aucune_phrase_affichee_ne_contient_de_jargon():
    """Les phrases servies aux écrans sont en français courant."""
    valeurs = {"recence_j": 214, "freq_12m": 3, "ca_12m": 1_240_000,
               "tendance_ca": 0.4, "marge_3m_pct": 18.2, "mois_sans_vente": 7,
               "avg_delay": 96, "exposure": 240_000, "tendance_freq": 2.0}
    for var, val in valeurs.items():
        for centile in (None, 7, 93):
            phrase = decrire_variable(var, val, centile=centile)
            assert phrase, f"{var} sans phrase"
            assert not JARGON.search(phrase), f"jargon dans « {phrase} » ({var})"


def test_une_variable_inconnue_sort_sous_un_nom_neutre_pas_une_invention():
    phrase = decrire_variable("xyz_inconnu", 12.5)
    assert "xyz" in phrase.lower()
    assert "_" not in phrase
    for mot in ("risque", "baisse", "faible"):
        assert mot not in phrase.lower()


def test_toute_variable_servie_possede_un_libelle():
    """Une variable sans libellé s'afficherait sous son nom technique."""
    manquantes = []
    for module, attribut in (
            ("ml_engine.analytics.churn_model", "FEATURES"),
            ("ml_engine.analytics.conversion_devis", "FEATURES"),
            ("ml_engine.analytics.marge_client", "FEATURES"),
            ("ml_engine.stock.fin_de_vie", "FEATURES")):
        try:
            mod = __import__(module, fromlist=[attribut])
        except Exception:
            continue
        for v in getattr(mod, attribut, []) or []:
            if v not in LIBELLES:
                manquantes.append(f"{module}:{v}")
    assert not manquantes, manquantes


# ── Règles ───────────────────────────────────────────────────────────────────

def test_une_regle_sexplique_par_le_seuil_franchi():
    raisons = raisons_seuils(
        {"mois_sans_vente": 9, "n_clients_12m": 1, "stock_actuel": 24},
        [{"variable": "mois_sans_vente", "seuil": 6, "sens": "sup", "poids": 3.0},
         {"variable": "n_clients_12m", "seuil": 3, "sens": "inf", "poids": 2.0},
         {"variable": "stock_actuel", "seuil": 1, "sens": "sup", "poids": 1.0}])
    assert len(raisons) == 3
    assert raisons[0]["variable"] == "mois_sans_vente"
    assert abs(sum(r["poids"] for r in raisons) - 1.0) < 1e-6
    assert all("seuil" in r for r in raisons)
    assert "au-dessus de" in raisons[0]["explication"]


def test_un_seuil_non_franchi_nest_pas_presente_comme_une_raison():
    raisons = raisons_seuils(
        {"mois_sans_vente": 2},
        [{"variable": "mois_sans_vente", "seuil": 6, "sens": "sup", "poids": 3.0}])
    assert raisons == []


def test_une_variable_franchissant_deux_seuils_napparait_quune_fois():
    """Sinon « au-delà de 90 » et « au-delà de 60 » chassent une autre raison."""
    raisons = raisons_seuils(
        {"avg_delay": 120, "exposure": 90_000},
        [{"variable": "avg_delay", "seuil": 90, "sens": "sup", "poids": 3.0},
         {"variable": "avg_delay", "seuil": 60, "sens": "sup", "poids": 2.0},
         {"variable": "exposure", "seuil": 50_000, "sens": "sup", "poids": 2.0}])
    assert [r["variable"] for r in raisons] == ["avg_delay", "exposure"]
    assert raisons[0]["seuil"] == 90, "le seuil le plus fort doit être retenu"


def test_une_phrase_ecrite_a_la_main_dans_une_regle_est_refusee():
    """Recopier le seuil dans une phrase, c'est le déclarer deux fois."""
    with pytest.raises(ValueError):
        raisons_seuils({"avg_delay": 120},
                       [{"variable": "avg_delay", "seuil": 90, "sens": "sup",
                         "phrase": "règle au-delà de 90 jours"}])


# ── Contrefactuel ────────────────────────────────────────────────────────────

def test_le_contrefactuel_ramene_exactement_le_score_au_seuil():
    coefs, moy, ec = [0.9, -0.7, 0.3, -0.4], [60.0, 12.0, 1.0, 5e4], [30.0, 6.0, 0.5, 4e4]
    val = [180.0, 21.0, 2.0, 138180.0]
    logit = sum(c * (v - m) / e for c, m, e, v in zip(coefs, moy, ec, val))

    cf = contrefactuel(coefs, moy, ec, val, VARIABLES, logit, 0.0,
                       {"recence_j": {"sens": "baisse", "min": 0.0}})
    assert cf is not None and cf["variable"] == "recence_j"

    modifie = list(val)
    modifie[0] = cf["valeur_cible"]
    nouveau = sum(c * (v - m) / e for c, m, e, v in zip(coefs, moy, ec, modifie))
    # `valeur_cible` est arrondie au millième pour l'affichage : le résidu est
    # celui de cet arrondi, pas celui du calcul.
    assert abs(nouveau) < 1e-3, "le contrefactuel doit atteindre le seuil visé"


def test_aucun_contrefactuel_hors_des_valeurs_observees():
    """Proposer une valeur jamais vue n'est pas une action, c'est une fiction."""
    cf = contrefactuel([0.01], [0.0], [1.0], [1000.0], ["recence_j"],
                       1000.0 * 0.01, 0.0,
                       {"recence_j": {"sens": "baisse", "min": 300.0}})
    assert cf is None


def test_aucun_contrefactuel_contre_le_sens_du_reel():
    """L'ancienneté d'une relation ne peut pas diminuer."""
    cf = contrefactuel([1.0], [0.0], [1.0], [10.0], ["anciennete_j"], 10.0, 0.0,
                       {"anciennete_j": {"sens": "hausse"}})
    assert cf is None


def test_aucun_contrefactuel_quand_le_score_est_deja_sous_le_seuil():
    cf = contrefactuel([1.0], [0.0], [1.0], [1.0], ["recence_j"], -2.0, 0.0,
                       {"recence_j": {"sens": "baisse"}})
    assert cf is None


# ── Fidélité ─────────────────────────────────────────────────────────────────

@pytest.mark.vitrine
def test_les_attributions_designent_ce_qui_porte_vraiment_le_score():
    """Courbe de suppression : l'explication fait-elle mieux que le hasard ?"""
    coefs = np.array([3.0, 0.05, 0.05, 0.05])
    moy, ec = np.zeros(4), np.ones(4)
    rng = np.random.default_rng(1)
    X = rng.normal(size=(300, 4))

    def predire(A):
        return 1.0 / (1.0 + np.exp(-((A - moy) / ec) @ coefs))

    attributions = ((X - moy) / ec) * coefs
    f = fidelite_suppression(predire, X, attributions, moy, k_max=3)
    assert f["ecart_des_aires"] > 0, (
        "les variables désignées doivent porter le score plus qu'un tirage")


def test_une_attribution_au_hasard_ne_bat_pas_le_hasard():
    """Contrôle négatif : sans ce test, le précédent ne prouverait rien."""
    coefs = np.array([3.0, 0.05, 0.05, 0.05])
    moy, ec = np.zeros(4), np.ones(4)
    rng = np.random.default_rng(2)
    X = rng.normal(size=(300, 4))

    def predire(A):
        return 1.0 / (1.0 + np.exp(-((A - moy) / ec) @ coefs))

    bidon = rng.normal(size=X.shape)
    f = fidelite_suppression(predire, X, bidon, moy, k_max=3)
    vraies = fidelite_suppression(predire, X, ((X - moy) / ec) * coefs, moy, k_max=3)
    assert f["ecart_des_aires"] < vraies["ecart_des_aires"]


# ── Aucun gabarit ne doit réapparaître ───────────────────────────────────────

@pytest.mark.vitrine
def test_aucun_gabarit_de_phrase_dans_les_modules_de_modeles():
    """Garde-fou de structure : la rédaction appartient à `explication.py`.

    Les phrases vivaient dans `churn_model.py`, où personne ne vérifiait leur
    accord avec le coefficient appris. Un dictionnaire de phrases ailleurs que
    dans le module d'explication annonce le retour du même défaut.
    """
    import ast
    from pathlib import Path

    def tables_de_phrases(source: str) -> list[str]:
        """Dictionnaires de module dont les valeurs sont des phrases."""
        trouvees = []
        for noeud in ast.parse(source).body:
            if isinstance(noeud, ast.Assign) and isinstance(noeud.value, ast.Dict):
                nom = ast.unparse(noeud.targets[0])
            elif isinstance(noeud, ast.AnnAssign) and isinstance(noeud.value, ast.Dict):
                nom = ast.unparse(noeud.target)
            else:
                continue
            phrases = [v.value for v in noeud.value.values
                       if isinstance(v, ast.Constant)
                       and isinstance(v.value, str) and " " in v.value.strip()]
            if len(phrases) >= 4:
                trouvees.append(nom)
        return trouvees

    # Le détecteur est d'abord vérifié sur le code exact qui a été retiré : un
    # garde-fou incapable de voir ce qu'il surveille ne vaut rien.
    assert tables_de_phrases(
        '_SENS_VARIABLES = {\n'
        '    "recence_j": "n\'a pas commandé depuis {v:.0f} jours",\n'
        '    "freq_12m": "seulement {v:.0f} commande(s) sur 12 mois",\n'
        '    "tendance_freq": "il commande moins souvent qu\'avant",\n'
        '    "anciennete_j": "relation encore récente",\n'
        '}\n') == ["_SENS_VARIABLES"], "le détecteur ne voit pas le défaut d'origine"

    racine = Path(__file__).resolve().parents[1]
    fautifs = []
    for chemin in sorted((racine / "ml_engine").rglob("*.py")):
        if chemin.name == "explication.py":
            continue
        try:
            tables = tables_de_phrases(
                chemin.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        fautifs += [f"{chemin.relative_to(racine)}:{t}" for t in tables]
    assert not fautifs, (
        f"tables de phrases hors du module d'explication : {fautifs}")
