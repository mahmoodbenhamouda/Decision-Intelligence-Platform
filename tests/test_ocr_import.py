"""Extraction de facture et import en base."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_engine.ocr.importer import _norm, _similarite, rapprocher_client
from ml_engine.ocr.invoice import parse_invoice

FACTURE_FOREVERMO = """FOREVERMO GROUP
Espace Tunis BH3
1073 Montplaisir

FACTURE N° F-2026-00003
DATE          05-03-2026

FACTURER A
184707        ling and consulting

DESIGNATION                                  QTE    TVA %   P.U. HT   TOTAL HT
Audite securite site web                    1.000    19%   6 500,000  6 500,000
Mise a niveau, securisation et optimisation 1.000    19%   3 500,000  3 500,000

TAUX      BASE HT      MONTANT TVA
19%      10 000,000     1 900,000     Total HT          10 000,000
TOTAL    10 000,000     1 900,000     TVA                1 900,000
                                      Total TTC         11 900,000
                                      Timbre fiscal          1,000
                                      NET A PAYER       11 901,000

ONZE MILLE NEUF CENT UN DINARS
"""


@pytest.fixture(scope="module")
def facture():
    return parse_invoice(FACTURE_FOREVERMO)


@pytest.mark.parametrize("champ,attendu", [
    ("numero", "F-2026-00003"),
    ("tiers", "ling and consulting"),
    ("date_facture", "2026-03-05"),
    ("montant_ht", 10_000.0),
    ("montant_tva", 1_900.0),
    ("montant_ttc", 11_900.0),
    ("taux_tva", 19.0),
    ("timbre_fiscal", 1.0),
    ("net_a_payer", 11_901.0),
])
def test_champs_de_la_facture_reelle(facture, champ, attendu):
    obtenu = getattr(facture, champ)
    if isinstance(attendu, float):
        assert obtenu == pytest.approx(attendu, abs=0.01), f"{champ}: {obtenu} ≠ {attendu}"
    else:
        assert obtenu == attendu


def test_ht_et_tva_ne_sont_jamais_identiques(facture):
    """Le défaut d'origine : un même nombre alimentait les deux champs."""
    assert facture.montant_ht != facture.montant_tva


@pytest.mark.vitrine
def test_identite_comptable_verifiee(facture):
    assert facture.montant_ht + facture.montant_tva == pytest.approx(facture.montant_ttc, abs=0.01)
    assert "vérifié" in (facture.coherence or "")


def test_taux_de_tva_coherent_avec_les_montants(facture):
    assert facture.montant_tva / facture.montant_ht == pytest.approx(facture.taux_tva / 100, abs=1e-6)


def test_net_a_payer_distinct_du_ttc(facture):
    """En Tunisie, net à payer = TTC + timbre fiscal."""
    assert facture.net_a_payer == pytest.approx(facture.montant_ttc + facture.timbre_fiscal, abs=0.01)
    assert facture.net_a_payer != facture.montant_ttc


def test_entete_de_tableau_ignore():
    """Un document réduit à son en-tête et une ligne d'article ne doit produire ni HT ni TVA : il n'y a…"""
    inv = parse_invoice(
        "DESIGNATION   QTE   TVA %   P.U. HT   TOTAL HT\n"
        "Prestation   1.000   19%   6 500,000   6 500,000\n")
    assert not (inv.montant_ht == 6500.0 and inv.montant_tva == 6500.0)


def test_reconstruction_depuis_le_taux():
    """Si la TVA est illisible mais que le taux est affiché, elle se recalcule."""
    inv = parse_invoice("Total HT   1 000,000\nTVA 19%\nTotal TTC   1 190,000\n")
    assert inv.montant_tva == pytest.approx(190.0, abs=0.01)


def test_ttc_deduit_du_net_si_aucun_total_ttc():
    inv = parse_invoice("Total HT   1 000,000\nTVA        190,000\n"
                        "Timbre fiscal  1,000\nNET A PAYER  1 191,000\n")
    assert inv.montant_ttc == pytest.approx(1190.0, abs=0.01)
    assert inv.net_a_payer == pytest.approx(1191.0, abs=0.01)


@pytest.mark.parametrize("a,b", [
    ("Ling & Consulting S.A.R.L.", "LING AND CONSULTING SARL"),
    ("Société Delice", "DELICE"),
    ("Hôpital Militaire de Tunis", "HOPITAL MILITAIRE DE TUNIS"),
])
def test_variantes_de_raison_sociale_se_ressemblent(a, b):
    assert _similarite(a, b) >= 0.72, f"{_norm(a)!r} vs {_norm(b)!r}"


def test_clients_differents_ne_se_confondent_pas():
    assert _similarite("HOPITAL MILITAIRE DE TUNIS", "LABORATOIRE MEZGHANI") < 0.6


def test_rapprochement_client_connu():
    r = rapprocher_client("HOPITAL MILITAIRE DE TUNIS")
    assert r["statut"] in {"existant", "ambigu"}
    if r["statut"] == "existant":
        assert "HOPITAL MILITAIRE" in r["client"]["nom"].upper()


def test_tiers_vide_ne_cree_pas_de_client():
    assert rapprocher_client("")["statut"] == "inconnu"


def test_les_imports_ne_touchent_pas_la_table_sales():
    """Garde-fou d'architecture : `sales` est l'export ERP, la seule source vérifiable."""
    source = (open(os.path.join(os.path.dirname(__file__), "..", "ml_engine",
                                "ocr", "importer.py"), encoding="utf-8").read())
    assert "INSERT INTO sales" not in source
    assert "UPDATE sales" not in source
    assert "factures_importees" in source
