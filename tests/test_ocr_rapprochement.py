"""Rapprochement ERP d'une facture lue : achats et ventes."""
import pytest

duckdb = pytest.importorskip("duckdb")

from ml_engine.ocr import importer as imp
from ml_engine.ocr.reconcile import reconcile_invoice

ACHATS = [
    ("A1", "BIOMERIEUX", "F1", "2025-06-10", 1190.0, "7901796236"),
    ("A2", "Diagnostic Grifols SA", "F2", "2023-09-14", 6338.31, "7902508924"),
    ("A3", "Diagnostic Grifols SA", "F2", "2023-09-14", 2429.69, "7902508924"),
    ("A4", "LIFOTRONIC", "F3", "2024-11-01", 15223.0, "004802-TN-006"),
    ("A5", "LIFOTRONIC", "F3", "2025-10-06", 183782.0, "004802-TN-006"),
    ("A6", "SUN CHEMICAL", "F4", "2025-03-01", 500.0, "SC-77"),
    ("A7", "SUN CHEMICAL", "F4", "2025-03-02", 500.0, "SC-77"),
    ("A8", "ORANGE TUNISIE", "F5", "2025-08-01", 300.0, None),
]


@pytest.fixture
def entrepot(tmp_path, monkeypatch):
    chemin = tmp_path / "store.duckdb"
    monkeypatch.setattr("ml_engine.analytics.kpi_engine.STORE_PATH", chemin)
    con = duckdb.connect(str(chemin))
    con.execute("CREATE TABLE dim_client (client_code VARCHAR, client_name VARCHAR, x VARCHAR)")
    con.execute("""CREATE TABLE sales (ent_id INT, piece_no VARCHAR, client VARCHAR, date DATE,
                   echeance DATE, ht DOUBLE, ttc DOUBLE, est_avoir BOOLEAN, mode_regl VARCHAR,
                   nbr_article INT, year INT, payment_delay_days INT, client_name VARCHAR)""")
    con.execute("""INSERT INTO sales VALUES (1, 'V100', 'CP001', DATE '2025-05-05', NULL, 1000, 1190,
                   FALSE, NULL, 1, 2025, NULL, 'HOPITAL MILITAIRE DE TUNIS')""")
    con.execute("""CREATE TABLE purchases (ent_id INT, piece_no VARCHAR, fournisseur VARCHAR,
                   fournisseur_code VARCHAR, date DATE, echeance DATE, ht DOUBLE, ttc DOUBLE,
                   est_avoir BOOLEAN, mode_regl VARCHAR, tva DOUBLE, piece_externe VARCHAR,
                   year INT, payment_delay_days INT)""")
    for i, (p, n, c, d, t, ext) in enumerate(ACHATS):
        con.execute("INSERT INTO purchases VALUES (?, ?, ?, ?, ?, NULL, ?, ?, FALSE, NULL, NULL, ?, 2025, NULL)",
                    [i, p, n, c, d, t / 1.19, t, ext])
    con.close()
    return chemin


def _achat(**k):
    return reconcile_invoice(k, sens="achat")


def test_retrouvee_par_numero(entrepot):
    r = _achat(numero="7901-796-236", fournisseur="bioMérieux", date_facture="2025-06-10", montant_ttc=1190.0)
    assert r["statut"] == "rapprochee" and "par son numéro" in r["message"]
    assert r["candidats"][0]["meme_numero"] and r["recherche_par_numero"]


def test_meme_numero_montant_different_est_un_litige(entrepot):
    r = _achat(numero="7901796236", fournisseur="BIOMERIEUX", date_facture="2025-06-10", montant_ttc=1309.0)
    assert r["statut"] == "ecart_detecte" and "litige" in r["message"]


def test_facture_saisie_en_deux_pieces(entrepot):
    r = _achat(numero="7902508924", fournisseur="Grifols", date_facture="2023-09-14", montant_ttc=8768.0)
    assert r["statut"] == "rapprochee" and "2 pièces" in r["message"]


def test_reference_partagee_n_est_pas_un_doublon(entrepot):
    r = _achat(numero="004802-TN-006", fournisseur="LIFOTRONIC", date_facture="2025-10-06", montant_ttc=183782.0)
    assert r["statut"] == "rapprochee" and "2 pièces de l'ERP" in r["message"]


def test_vrai_doublon_meme_numero_meme_montant(entrepot):
    r = _achat(numero="SC-77", fournisseur="SUN CHEMICAL", date_facture="2025-03-01", montant_ttc=500.0)
    assert r["statut"] == "doublon_probable"


def test_achat_absent_de_l_erp(entrepot):
    r = _achat(numero="X-1", fournisseur="FOURNISSEUR INCONNU", date_facture="2025-06-01", montant_ttc=4321.987)
    assert r["statut"] == "introuvable" and "NON SAISIE" in r["message"]


def test_meme_montant_autre_fournisseur_n_est_pas_retrouvee(entrepot):
    r = _achat(numero=None, fournisseur="ENNASR MARBRE", date_facture="2025-08-01", montant_ttc=300.0)
    assert r["statut"] == "introuvable" and "autre fournisseur" in r["message"]


def test_sans_numero_par_montant(entrepot):
    r = _achat(numero=None, fournisseur="Orange Tunisie", date_facture="2025-08-02", montant_ttc=300.0)
    assert r["statut"] == "rapprochee"


def test_posterieure_a_l_export_ne_prouve_rien(entrepot):
    r = _achat(numero="FV-2026-0142", fournisseur="ATELIER NOVALUX", date_facture="2026-09-14", montant_ttc=2360.65)
    assert r["statut"] == "hors_periode" and "30/03/2026" not in r["message"]
    assert r["erp_jusqu_au"] == "2025-10-06"


def test_une_vente_se_cherche_dans_les_ventes(entrepot):
    r = reconcile_invoice({"numero": "V100", "client": "Hopital Militaire de Tunis",
                           "date_facture": "2025-05-05", "montant_ttc": 1190.0}, sens="vente")
    assert r["statut"] == "rapprochee" and r["candidats"][0]["tiers_code"] == "CP001"
    assert all(c["tiers_code"] == "CP001" for c in r["candidats"])


def test_entrepot_sans_numero_fournisseur(entrepot):
    con = duckdb.connect(str(entrepot))
    con.execute("ALTER TABLE purchases DROP COLUMN piece_externe")
    con.close()
    r = _achat(numero="7901796236", fournisseur="BIOMERIEUX", date_facture="2025-06-10", montant_ttc=1190.0)
    assert r["statut"] == "rapprochee" and r["recherche_par_numero"] is False


def test_rapprochement_conserve_puis_refait_apres_maj_erp(entrepot):
    f = {"numero": "N-9", "fournisseur": "BIOMERIEUX", "date_facture": "2025-12-01",
         "montant_ttc": 999.0}
    r0 = reconcile_invoice(f, sens="achat")
    assert r0["statut"] == "hors_periode"
    res = imp.importer_facture(f, sens="achat", rapprochement=r0)
    assert res["ok"] and res["rapprochement_statut"] == "hors_periode"
    assert imp.stats_import()["rapprochements"] == {"achat:hors_periode": 1}
    con = duckdb.connect(str(entrepot))
    con.execute("""INSERT INTO purchases VALUES (99, 'A99', 'BIOMERIEUX', 'F1', DATE '2025-12-02', NULL,
                   839.5, 999.0, FALSE, NULL, NULL, 'N-9', 2025, NULL)""")
    con.close()
    bilan = imp.rerapprocher_imports(["hors_periode"])
    assert bilan["n_changes"] == 1 and bilan["changements"][0]["apres"] == "rapprochee"
    liste = imp.factures_importees(rapprochement="rapprochee")
    assert liste[0]["numero"] == "N-9" and "par son numéro" in liste[0]["rapprochement_message"]
