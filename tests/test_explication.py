"""
tests/test_explication.py
=========================
L'explicabilité tient ses promesses — ou elle ne vaut rien.

Une justification fausse est pire qu'aucune justification : elle donne au
lecteur une confiance qu'il n'a aucun moyen de vérifier. Ces tests contrôlent
donc les promesses faites à l'écran, une par une :

1. **« Décomposition exacte »** — sur un modèle linéaire, la somme des
   contributions et de l'ordonnée à l'origine reconstitue EXACTEMENT le score du
   modèle. C'est ce qui autorise le mot « exacte » dans l'interface.
2. **« Les parts totalisent 100 % »** — les poids affichés sont des parts de
   l'influence retenue ; le facteur en sens inverse n'en reçoit aucune, pour ne
   pas laisser croire qu'il appartient à la même somme.
3. **« Aucun jargon »** — les phrases lues par un dirigeant ne contiennent ni
   nom de variable, ni terme technique.
4. **« Jamais d'explication inventée »** — une variable inconnue sort sous un
   nom neutre, et un modèle qui n'est pas de la forme attendue ne produit
   aucune explication plutôt qu'une explication d'un autre modèle.

Ce que ces tests ne couvrent plus : la « carte de méthode » affichée au
directeur. Elle a été retirée des écrans — la mécanique d'un modèle n'aide
personne à décider. Ce qui est exact et ce qui repose sur une hypothèse est
désormais écrit dans `docs/XAI.md`, avec les chiffres de
`scripts/diagnostics_shap.py`.
5. **Les règles s'expliquent par leurs seuils**, dans l'ordre de leur poids
   métier — pas dans celui du plus gros dépassement numérique.

Exécution :
    python -m pytest tests/test_explication.py -v
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from ml_engine.explication import (contributions_lineaires,  # noqa: E402
                                   contributions_shap,
                                   extraire_pipeline_lineaire, phrase_variable,
                                   raisons_seuils)

VARIABLES = ["recence_j", "freq_12m", "ca_12m", "tendance_ca"]


# ── 1. L'exactitude annoncée est vérifiée ───────────────────────────────────
@pytest.mark.vitrine
def test_la_somme_des_contributions_reconstitue_le_score_du_modele():
    """La promesse « décomposition exacte » est tenue au flottant près.

    On ajuste une régression logistique normalisée, puis on vérifie que
    intercept + somme(contributions) = logit prédit par le modèle. Si cette
    égalité tombait, l'interface mentirait en affichant « rien n'est estimé ».
    """
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
    # Contributions signées complètes (n=len(VARIABLES), sans filtrage) :
    contributions = [
        float(lin["coefficients"][i]) * (float(ligne[i]) - float(lin["moyennes"][i]))
        / (float(lin["ecarts"][i]) or 1.0)
        for i in range(len(VARIABLES))]
    intercept = float(modele.named_steps["logisticregression"].intercept_[0])

    p = float(modele.predict_proba([ligne])[0, 1])
    logit_modele = np.log(p / (1 - p))
    assert abs(intercept + sum(contributions) - logit_modele) < 1e-9


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


# ── 2. Le vocabulaire du sens dépend du modèle ──────────────────────────────
def test_le_vocabulaire_du_sens_est_adaptable():
    """Ce qui « aggrave » un risque de départ « favorise » la signature d'un
    devis : un seul vocabulaire pour les deux tromperait le lecteur."""
    raisons = contributions_lineaires(
        [1.0, -1.0, 0.0, 0.0], [0] * 4, [1] * 4, [1.0] * 4, VARIABLES,
        sens=("favorise", "freine"))
    assert {r["sens"] for r in raisons} == {"favorise", "freine"}


# ── 3. Aucun jargon dans ce que lit un dirigeant ────────────────────────────
JARGON = re.compile(
    r"\b(shap|coefficient|logit|feature|variable|régression|logistique|"
    r"gradient|boosting|modèle|probabilité calibrée|score brut)\b|_", re.I)


@pytest.mark.vitrine
def test_aucune_phrase_affichee_ne_contient_de_jargon():
    """Les phrases servies aux écrans sont en français courant.

    Le tiret bas est interdit lui aussi : il trahirait un nom de variable
    recopié tel quel (« tendance_ca »), ce que ce module existe précisément
    pour éviter.
    """
    valeurs = {"recence_j": 214, "freq_12m": 3, "ca_12m": 1_240_000,
               "tendance_ca": -1, "marge_3m_pct": 18.2, "mois_sans_vente": 7,
               "avg_delay": 96, "exposure": 240_000}
    for var, val in valeurs.items():
        for aggrave in (True, False):
            phrase = phrase_variable(var, val, aggrave)
            assert phrase, f"{var} sans phrase"
            assert not JARGON.search(phrase), f"jargon dans « {phrase} » ({var})"


def test_une_variable_inconnue_sort_sous_un_nom_neutre_pas_une_invention():
    phrase = phrase_variable("xyz_inconnu", 12.5)
    assert "xyz" in phrase.lower()
    # Aucune interprétation métier n'est fabriquée pour une variable non déclarée.
    assert "risque" not in phrase.lower() and "baisse" not in phrase.lower()


# ── 4. Refus explicites plutôt qu'approximations silencieuses ───────────────
def test_un_modele_non_lineaire_ne_produit_aucune_explication_lineaire():
    """Mieux vaut aucune explication qu'une explication d'un autre modèle."""
    from sklearn.ensemble import RandomForestClassifier

    rng = np.random.RandomState(1)
    X = rng.normal(size=(60, 4))
    y = (X[:, 0] > 0).astype(int)
    assert extraire_pipeline_lineaire(RandomForestClassifier(n_estimators=5).fit(X, y)) is None


# ── 5. Les règles s'expliquent par leurs seuils ─────────────────────────────
def test_une_regle_sexplique_par_le_seuil_franchi():
    raisons = raisons_seuils(
        {"mois_sans_vente": 9, "n_clients_12m": 1, "stock_actuel": 24},
        [{"variable": "mois_sans_vente", "seuil": 6, "sens": "sup", "poids": 3.0},
         {"variable": "n_clients_12m", "seuil": 3, "sens": "inf", "poids": 2.0},
         {"variable": "stock_actuel", "seuil": 1, "sens": "sup", "poids": 1.0}])
    assert len(raisons) == 3
    # Le poids métier prime sur l'ampleur du dépassement : un stock 24 fois
    # supérieur à son seuil ne passe pas devant « neuf mois sans vente ».
    assert raisons[0]["variable"] == "mois_sans_vente"
    assert abs(sum(r["poids"] for r in raisons) - 1.0) < 1e-6
    assert all("seuil" in r for r in raisons)


def test_un_seuil_non_franchi_nest_pas_presente_comme_une_raison():
    raisons = raisons_seuils(
        {"mois_sans_vente": 2},
        [{"variable": "mois_sans_vente", "seuil": 6, "sens": "sup", "poids": 3.0}])
    assert raisons == []


# ── 6. SHAP : mise en forme fidèle aux valeurs reçues ───────────────────────
def test_les_valeurs_shap_sont_ordonnees_par_influence():
    raisons = contributions_shap(
        valeurs_shap=[0.1, 0.9, 0.4, -0.7],
        valeurs=[1, 2, 3, 4], variables=VARIABLES)
    poussent = [r for r in raisons if r["sens"] == "aggrave"]
    assert [r["variable"] for r in poussent] == ["freq_12m", "ca_12m", "recence_j"]
