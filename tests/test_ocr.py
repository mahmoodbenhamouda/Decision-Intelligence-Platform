"""Tests du service OCR transversal : parsing de montants/dates, extraction structurée de facture,…"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from ml_engine.ocr.engine import clean_text, ocr_available
from ml_engine.ocr.invoice import parse_amount, parse_date, parse_invoice
from ml_engine.ocr.reconcile import _name_similarity, reconcile_invoice

FACTURE_TND = """SOCIETE OVERLYNE
Matricule Fiscal : 1234567/A/M/000
FACTURE N° F-2026-118
Date : 12/03/2026
Echeance : 11/06/2026
Client : C.H.U. CHARLES NICOLLE
Designation           Qte    P.U.       Montant
Reactifs biochimie     10   1200,000   12000,000
Total HT                               12000,000
TVA 19%                                 2280,000
Net a payer                            14280,000 DT
"""


@pytest.mark.parametrize("raw,attendu", [
    ("14280,000", 14280.0),
    ("330,000", 330.0),
    ("1 234,567", 1234.567),
    ("1.234,56", 1234.56),
    ("1,234,567", 1234567.0),
    ("14280.00", 14280.0),
    ("980", 980.0),
    ("", None),
    ("abc", None),
])
def test_parse_amount(raw, attendu):
    assert parse_amount(raw) == attendu


def test_parse_amount_corrige_les_erreurs_ocr():
    """O lu à la place de 0, l à la place de 1 : erreurs Tesseract classiques."""
    assert parse_amount("l42OO,00") == 14200.0


@pytest.mark.parametrize("raw,iso", [
    ("Date : 12/03/2026", "2026-03-12"),
    ("le 5-1-26", "2026-01-05"),
    ("2026-03-12", "2026-03-12"),
    ("12 mars 2026", "2026-03-12"),
    ("12 février 2026", "2026-02-12"),
])
def test_parse_date(raw, iso):
    d = parse_date(raw)
    assert d is not None and d.isoformat() == iso


def test_parse_date_invalide():
    assert parse_date("32/13/2026") is None
    assert parse_date("aucune date") is None


def test_parse_invoice_champs_complets():
    inv = parse_invoice(FACTURE_TND)
    assert inv.is_invoice is True
    assert inv.numero == "F-2026-118"
    assert inv.date_facture == "2026-03-12"
    assert inv.date_echeance == "2026-06-11"
    assert inv.montant_ht == 12000.0
    assert inv.montant_tva == 2280.0
    assert inv.montant_ttc == 14280.0
    assert inv.devise == "TND"
    assert "CHARLES NICOLLE" in (inv.tiers or "").upper()
    assert inv.matricule_fiscal == "1234567/A/M/000"


def test_coherence_ht_tva_ttc_verifiee():
    inv = parse_invoice(FACTURE_TND)
    assert inv.coherence and inv.coherence.startswith("HT + TVA = TTC vérifié")


def test_coherence_signale_une_incoherence():
    """OCR ayant mal lu un chiffre : l'utilisateur doit en être averti."""
    texte = FACTURE_TND.replace("Net a payer                            14280,000",
                                "Net a payer                            19280,000")
    inv = parse_invoice(texte)
    assert inv.coherence and "Incohérence" in inv.coherence


def test_montants_en_colonnes_separees_par_une_ligne_vide():
    """Cas RÉEL de Tesseract : quand les colonnes sont éloignées, le montant tombe 2 lignes plus bas…"""
    texte = ("FACTURE N° X-1\nDate : 01/02/2026\n\nTotal HT\n\n11250.000\n\n"
             "TVA\n\n235.200\n\nNet a payer 11485.200 DT")
    inv = parse_invoice(texte)
    assert inv.montant_ht == 11250.0
    assert inv.montant_tva == 235.2
    assert inv.montant_ttc == 11485.2
    assert inv.coherence.startswith("HT + TVA = TTC vérifié")


def test_libelle_suivant_ne_vole_pas_le_montant():
    """« Total HT » sans montant ne doit PAS prendre celui de la ligne TVA."""
    texte = "FACTURE\nTotal HT\nTVA 19%\n2280,000\nNet a payer 14280,000"
    inv = parse_invoice(texte)
    assert inv.montant_ht != 2280.0


def test_confiance_des_champs_documentee():
    """Cette facture ne porte AUCUNE ligne « Total TTC » : seul le net à payer est écrit."""
    inv = parse_invoice(FACTURE_TND)
    assert inv.champs_confiance.get("montant_ttc") == "calcule"
    assert inv.net_a_payer == pytest.approx(14280.0, abs=0.01)
    assert inv.montant_ttc == pytest.approx(14280.0, abs=0.01)
    assert inv.champs_confiance.get("montant_ht") == "explicite"


def test_montant_deduit_quand_aucun_libelle():
    """Sans libellé « total », on prend le plus gros montant — signalé « deduit »."""
    inv = parse_invoice("Document sans libelle\nValeurs : 120,000  4500,000  330,000")
    assert inv.montant_ttc == 4500.0
    assert inv.champs_confiance.get("montant_ttc") == "deduit"


def test_devise_euro_reconnue():
    inv = parse_invoice("FACTURE\nTotal TTC : 1 250,00 EUR\nTVA 20%")
    assert inv.devise == "EUR" and inv.montant_ttc == 1250.0


def test_texte_vide_ne_plante_pas():
    inv = parse_invoice("")
    assert inv.is_invoice is False and inv.montant_ttc is None


def test_document_non_facture():
    inv = parse_invoice("Compte rendu de reunion du service technique.")
    assert inv.is_invoice is False


def test_clean_text_preserve_les_montants_et_accents():
    out = clean_text("Facture n°12\n~~~~~\nTotal : 1 234,56 €\n\n\n\nÉchéance")
    assert "1 234,56 €" in out
    assert "Échéance" in out
    assert "~~~~~" not in out


def test_similarite_de_noms():
    assert _name_similarity("C.H.U. CHARLES NICOLLE", "CHU Charles Nicolle") > 0.9
    assert _name_similarity("HOPITAL MILITAIRE", "CLINIQUE EL AMEN") == 0.0


def test_reconcile_sans_montant():
    res = reconcile_invoice({"montant_ttc": None})
    assert res["statut"] == "montant_absent"
    assert "impossible" in res["message"].lower()


def test_reconcile_montant_introuvable():
    """Montant volontairement absurde : aucun candidat, message explicite."""
    res = reconcile_invoice({"montant_ttc": 987654321.123, "date_facture": None})
    assert res["statut"] in ("introuvable", "entrepot_indisponible")


@pytest.mark.skipif(not os.path.exists(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "output", "analytics_store.duckdb")),
    reason="entrepôt DuckDB absent")
def test_reconcile_retrouve_une_facture_reelle():
    """Bout en bout sur une vraie facture de l'entrepôt : score maximal."""
    import duckdb
    from ml_engine.analytics.kpi_engine import STORE_PATH
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    row = con.execute(
        "SELECT max(client_name), strftime(date,'%Y-%m-%d'), ttc FROM sales "
        "WHERE ttc > 1000 GROUP BY client, date, ttc LIMIT 1").fetchone()
    con.close()
    if not row:
        pytest.skip("entrepôt vide")
    nom, d, ttc = row
    texte = (f"FACTURE N° T-1\nDate : {d}\nClient : {nom}\n"
             f"Net a payer {ttc:.3f} DT")
    res = reconcile_invoice(parse_invoice(texte))
    assert res["statut"] in ("rapprochee", "doublon_probable")
    assert res["candidats"] and res["candidats"][0]["ecart_montant"] < 0.01


def test_ocr_available_ne_plante_jamais():
    assert isinstance(ocr_available(), bool)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
