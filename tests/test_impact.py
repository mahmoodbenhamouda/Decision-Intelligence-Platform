"""Ce que vaut la plateforme en dinars — et ce que le chiffrage s'interdit.

Un montant affiché à un directeur engage plus qu'une AUC. Ces tests ne
vérifient donc pas que les chiffres sont *bons* — aucun test ne peut le dire,
puisque les taux de conversion sont des hypothèses. Ils vérifient que le
chiffrage reste HONNÊTE :

- le total est exactement la somme de ses postes, jamais un chiffre à part ;
- les 15,8 M DT de correction de données n'entrent JAMAIS dans ce total ;
- chaque poste porte son taux et sa justification, sans exception ;
- un poste par client se somme au poste global au même taux ;
- une phrase ne survit pas au poste qui la fonde.

Le dernier point est le plus important : les phrases sont ce qu'un directeur
répétera. Elles sont dérivées des montants, jamais écrites en dur, et ce test
est ce qui l'empêche de redevenir faux.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml_engine.analytics import impact as im  # noqa: E402


# --------------------------------------------------------------------------
# Jeux d'essai : des montants choisis pour que les produits soient exacts en
# arithmétique décimale, afin qu'un échec signale une erreur de logique et
# jamais un arrondi.
# --------------------------------------------------------------------------

CHURN = {
    "servi": True,
    "n_au_dessus_de_0_5": 28,
    "n_clients_scores": 300,
    "enjeu_total_dt": 1_000_000.0,
    "top": [
        {"code": "C1", "nom": "HÔPITAL A", "enjeu_dt": 500_000.0},
        {"code": "C2", "nom": "CHU B", "enjeu_dt": 300_000.0},
        {"code": "C3", "nom": "CLINIQUE C", "enjeu_dt": 200_000.0},
    ],
}

DEVIS = {
    "servi": True,
    "n_devis": 240,
    "montant_ouvert_total_dt": 8_000_000.0,
    "esperance_totale_dt": 2_000_000.0,
    "n_clients_concernes": 54,
    "top": [{"client": "C1", "nom": "HÔPITAL A", "esperance_dt": 400_000.0}],
}

MARGE = {
    "servi": True,
    "n_clients": 120,
    "horizon_mois": 3,
    "seuil_marge_basse_pct": 25.55,
    "top": [
        {"client": "C1", "nom": "HÔPITAL A", "marge_en_jeu_dt": 600_000.0},
        {"client": "C4", "nom": "HÔPITAL D", "marge_en_jeu_dt": 400_000.0},
    ],
}


@pytest.fixture
def metriques(tmp_path, monkeypatch):
    """Calcule l'impact sur des entrées maîtrisées, sans toucher à l'entrepôt."""
    monkeypatch.setattr(im, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(im, "_kpis", lambda: {
        "churn_anticipe": CHURN,
        "exposition_recente_dt": 4_000_000.0,
        "stock_flux_reel": {
            "disponible": True,
            "valeur_immobilisee_dt": 1_000_000.0,
            "perte_quasi_certaine_dt": 100_000.0,
            "n_references_accumulees": 900,
            "n_references_plus_de_2_ans": 120,
            "n_obsoletes_certains": 31,
        },
        "ca_annuel_dt": 60_000_000.0,
    })
    monkeypatch.setattr(im, "_stock", lambda: {})
    monkeypatch.setattr(im, "_devis", lambda: DEVIS)
    monkeypatch.setattr(im, "_marge", lambda: MARGE)
    return im.calculer()


# --------------------------------------------------------------------------
# Le total
# --------------------------------------------------------------------------

def test_le_total_est_exactement_la_somme_des_postes(metriques):
    assert metriques["montant_total_identifie_dt"] == pytest.approx(
        sum(p["montant_identifie_dt"] for p in metriques["postes"]))
    assert metriques["montant_total_recuperable_dt"] == pytest.approx(
        sum(p["montant_recuperable_dt"] for p in metriques["postes"]))


def test_la_correction_de_donnees_n_entre_jamais_dans_le_total(metriques):
    """15,8 M DT d'erreur supprimée n'est pas un montant à encaisser.

    L'additionner gonflerait le total de 60 % avec un chiffre qui ne
    correspond à aucun dinar récupérable. C'est la faute la plus tentante de
    tout le rapport, et celle que ce test interdit.
    """
    correction = metriques["correction_de_donnees"]["montant_dt"]
    assert correction == 15_800_000
    assert correction not in {p["montant_identifie_dt"] for p in metriques["postes"]}
    assert metriques["montant_total_identifie_dt"] < correction + sum(
        p["montant_identifie_dt"] for p in metriques["postes"])


def test_le_recuperable_est_toujours_inferieur_a_l_identifie(metriques):
    assert (metriques["montant_total_recuperable_dt"]
            < metriques["montant_total_identifie_dt"])


# --------------------------------------------------------------------------
# Les hypothèses
# --------------------------------------------------------------------------

def test_chaque_poste_declare_son_taux_et_le_justifie(metriques):
    for p in metriques["postes"]:
        taux = p["hypothese_conversion"]
        assert 0 < taux < 1, f"{p['poste']} : un taux hors ]0,1[ n'a pas de sens"
        assert len(p["justification_hypothese"]) > 80, \
            f"{p['poste']} : une hypothèse sans justification est un chiffre inventé"
        assert p["montant_recuperable_dt"] == pytest.approx(
            round(p["montant_identifie_dt"] * taux, 0))


def test_tous_les_taux_du_catalogue_sont_justifies():
    """Y compris ceux des postes qu'un entrepôt donné ne produit pas."""
    for cle, h in im.HYPOTHESES.items():
        assert 0 < h["taux"] < 1, cle
        assert len(h["justification"]) > 80, cle


def test_chaque_poste_dit_sa_source_et_ce_qu_il_mesure(metriques):
    for p in metriques["postes"]:
        assert p["ce_qui_est_mesure"].strip()
        assert p["source_du_chiffre"].strip()


# --------------------------------------------------------------------------
# Le détail par client — « sur qui appeler demain matin »
# --------------------------------------------------------------------------

def test_le_detail_par_client_applique_le_taux_du_poste(metriques):
    for p in metriques["postes"]:
        for c in p["par_client"]:
            assert c["montant_recuperable_dt"] == pytest.approx(
                round(c["montant_identifie_dt"] * p["hypothese_conversion"], 0)), \
                f"{p['poste']} / {c['nom']} : un client ne convertit pas mieux " \
                "que son poste, sinon le total n'est plus la somme de ses parts"


def test_le_detail_par_client_est_classe_du_plus_lourd_au_plus_leger(metriques):
    for p in metriques["postes"]:
        montants = [c["montant_identifie_dt"] for c in p["par_client"]]
        assert montants == sorted(montants, reverse=True), p["poste"]


def test_le_detail_par_client_ne_depasse_pas_son_poste(metriques):
    for p in metriques["postes"]:
        assert sum(c["montant_identifie_dt"] for c in p["par_client"]) <= \
            p["montant_identifie_dt"] + 1, p["poste"]


def test_un_client_sans_montant_n_est_pas_liste():
    lignes = [{"code": "A", "nom": "A", "enjeu_dt": 10.0},
              {"code": "B", "nom": "B", "enjeu_dt": 0.0},
              {"code": "C", "nom": "C", "enjeu_dt": None}]
    out = im._par_client(lignes, "code", "nom", "enjeu_dt", 0.2)
    assert [c["client"] for c in out] == ["A"]


# --------------------------------------------------------------------------
# Les postes ajoutés : devis et marge
# --------------------------------------------------------------------------

def test_le_poste_des_devis_part_de_l_esperance_et_non_du_montant_brut(metriques):
    """Appliquer un taux au montant ouvert compterait le risque une seule fois.

    L'espérance est déjà pondérée par la probabilité de signature. Partir des
    8 M DT ouverts au lieu des 2 M DT d'espérance quadruplerait le poste.
    """
    p = next(x for x in metriques["postes"] if x["cle"] == "conversion_devis")
    assert p["montant_identifie_dt"] == pytest.approx(2_000_000.0)
    assert p["montant_identifie_dt"] != pytest.approx(8_000_000.0)
    assert "ESPÉRANCE" in p["reserve"]


def test_le_poste_de_marge_somme_tout_le_portefeuille(metriques):
    p = next(x for x in metriques["postes"] if x["cle"] == "marge")
    assert p["montant_identifie_dt"] == pytest.approx(1_000_000.0)
    assert p["montant_recuperable_dt"] == pytest.approx(250_000.0)


def test_un_poste_dont_le_modele_n_est_pas_servi_disparait(tmp_path, monkeypatch):
    """Un modèle indisponible retire son poste : il n'est jamais estimé."""
    monkeypatch.setattr(im, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(im, "_kpis", lambda: {"churn_anticipe": CHURN})
    monkeypatch.setattr(im, "_stock", lambda: {})
    monkeypatch.setattr(im, "_devis", lambda: {})
    monkeypatch.setattr(im, "_marge", lambda: {})
    m = im.calculer()
    cles = {p["cle"] for p in m["postes"]}
    assert "conversion_devis" not in cles and "marge" not in cles
    assert "retention" in cles


def test_un_entrepot_vide_ne_produit_aucun_montant(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "REPORTS_DIR", tmp_path)
    for nom in ("_kpis", "_stock", "_devis", "_marge"):
        monkeypatch.setattr(im, nom, lambda: {})
    m = im.calculer()
    assert m["postes"] == []
    assert m["montant_total_identifie_dt"] == 0
    assert m["montant_total_recuperable_dt"] == 0


# --------------------------------------------------------------------------
# Les phrases — ce qu'un directeur répétera
# --------------------------------------------------------------------------

@pytest.mark.vitrine
def test_les_phrases_citent_les_montants_calcules(metriques):
    phrases = " ".join(metriques["phrases"])
    assert im._dt(metriques["montant_total_identifie_dt"]) in phrases
    assert im._dt(metriques["montant_total_recuperable_dt"]) in phrases
    for p in metriques["postes"]:
        if p["cle"] in ("retention", "conversion_devis", "marge",
                        "recouvrement", "peremption"):
            assert im._dt(p["montant_identifie_dt"]) in phrases, p["poste"]


@pytest.mark.vitrine
def test_une_phrase_ne_survit_pas_au_poste_qui_la_fonde(tmp_path, monkeypatch):
    """Sans le poste, la phrase disparaît — jamais un chiffre orphelin.

    C'est la garantie qui rend les phrases citables : elles ne peuvent pas
    rester vraies dans le texte et fausses dans les données.
    """
    monkeypatch.setattr(im, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(im, "_kpis", lambda: {"churn_anticipe": CHURN})
    monkeypatch.setattr(im, "_stock", lambda: {})
    monkeypatch.setattr(im, "_devis", lambda: {})
    monkeypatch.setattr(im, "_marge", lambda: {})
    phrases = " ".join(im.calculer()["phrases"])
    assert "devis sont ouverts" not in phrases
    assert "de marge se dégradent" not in phrases
    assert "risquent de ne plus commander" in phrases


def test_la_phrase_de_retention_nomme_les_trois_premiers_clients(metriques):
    phrases = " ".join(metriques["phrases"])
    assert "HÔPITAL A" in phrases and "CHU B" in phrases and "CLINIQUE C" in phrases


def test_la_correction_est_dite_comme_non_additionnable(metriques):
    derniere = metriques["phrases"][-1]
    assert "15 800 000 DT" in derniere.replace(" ", " ")
    assert "Rien à encaisser" in derniere


def test_l_avertissement_dit_que_la_plateforme_n_encaisse_rien(metriques):
    assert "ne génère aucun encaissement" in metriques["avertissement_principal"]


def test_les_pourcentages_sont_ecrits_a_la_francaise():
    assert im._pct(25.55) == "25,6 %"
    assert im._dt(1_234_567).replace(" ", " ") == "1 234 567 DT"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
