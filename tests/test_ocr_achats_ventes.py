"""Import OCR : achats et ventes séparés, traçabilité, corrections."""
import json

import pytest

duckdb = pytest.importorskip("duckdb")

from ml_engine.ocr import importer as imp
from ml_engine.ocr.entreprise import detecter_sens, enregistrer_identite, identite, noyau_mf


@pytest.fixture
def entrepot(tmp_path, monkeypatch):
    chemin = tmp_path / "store.duckdb"
    monkeypatch.setattr("ml_engine.analytics.kpi_engine.STORE_PATH", chemin)
    for v in ("ENTREPRISE_NOM", "ENTREPRISE_ALIAS", "ENTREPRISE_MF"):
        monkeypatch.delenv(v, raising=False)
    con = duckdb.connect(str(chemin))
    con.execute("CREATE TABLE dim_client (client_code VARCHAR, client_name VARCHAR, x VARCHAR)")
    con.execute("INSERT INTO dim_client VALUES ('CP001', 'HOPITAL MILITAIRE DE TUNIS', NULL)")
    con.execute("""CREATE TABLE sales (ent_id INT, piece_no VARCHAR, client VARCHAR, date DATE,
                   echeance DATE, ht DOUBLE, ttc DOUBLE, est_avoir BOOLEAN, mode_regl VARCHAR,
                   nbr_article INT, year INT, payment_delay_days INT, client_name VARCHAR)""")
    con.execute("""INSERT INTO sales VALUES (1, 'V1', 'CP001', DATE '2025-01-10', NULL, 100, 119,
                   FALSE, 'virement', 1, 2025, NULL, 'HOPITAL MILITAIRE DE TUNIS')""")
    con.execute("""CREATE TABLE purchases (ent_id INT, piece_no VARCHAR, fournisseur VARCHAR,
                   fournisseur_code VARCHAR, date DATE, echeance DATE, ht DOUBLE, ttc DOUBLE,
                   est_avoir BOOLEAN, mode_regl VARCHAR, year INT, payment_delay_days INT)""")
    con.execute("""INSERT INTO purchases VALUES (1, 'A1', 'SUN CHEMICAL', 'F001',
                   DATE '2025-02-01', NULL, 1000, 1190, FALSE, 'LCR', 2025, NULL)""")
    con.execute("""CREATE TABLE factures_importees (id BIGINT, numero VARCHAR, client_code VARCHAR,
        client_name VARCHAR, date DATE, echeance DATE, ht DOUBLE, tva DOUBLE, ttc DOUBLE,
        timbre_fiscal DOUBLE, net_a_payer DOUBLE, devise VARCHAR, matricule_fiscal VARCHAR,
        fichier_source VARCHAR, confiance_ocr DOUBLE, qualite_lecture VARCHAR, coherence VARCHAR,
        importe_le TIMESTAMP, importe_par VARCHAR)""")
    con.execute("""INSERT INTO factures_importees VALUES (1, 'F-2026-00003', 'OCR-0001',
        'ling and consulting', DATE '2026-03-05', NULL, 10000, 1900, 11900, 1, 11901, 'TND',
        NULL, 'ancien.jpg', 70, 'moyenne', NULL, TIMESTAMP '2026-09-10 02:11:45', 'mahmood')""")
    con.close()
    return chemin


def _facture(**k):
    base = {"numero": "FV-1", "date_facture": "2026-09-14", "montant_ht": 1995.0,
            "montant_tva": 364.65, "montant_ttc": 2360.65, "timbre_fiscal": 1.0,
            "net_a_payer": 2337.043, "fournisseur": "SUN CHEMICAL SARL",
            "client": "ATELIER NOVALUX"}
    base.update(k)
    return base


def _q(chemin, sql):
    con = duckdb.connect(str(chemin), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_migration_garde_l_ancienne_ligne_comme_vente(entrepot):
    imp.factures_importees()
    assert _q(entrepot, "SELECT count(*) FROM factures_importees")[0][0] == 1
    assert _q(entrepot, "SELECT count(*) FROM sales_augmentee WHERE source = 'ocr'")[0][0] == 1
    assert _q(entrepot, "SELECT count(*) FROM purchases_augmentee WHERE source = 'ocr'")[0][0] == 0
    assert imp.factures_importees()[0]["sens"] == "vente"


def test_un_achat_ne_gonfle_jamais_les_ventes(entrepot):
    r = imp.importer_facture(_facture(), sens="achat", utilisateur="t")
    assert r["ok"] and r["sens"] == "achat"
    assert r["tiers_code"] == "F001" and r["statut_tiers"] == "existant"
    assert _q(entrepot, "SELECT count(*) FROM sales_augmentee WHERE source = 'ocr'")[0][0] == 1
    assert _q(entrepot, "SELECT count(*) FROM purchases_augmentee WHERE source = 'ocr'")[0][0] == 1
    assert _q(entrepot, "SELECT count(*) FROM dim_client")[0][0] == 1


def test_nouveau_fournisseur_puis_rattachement(entrepot):
    r1 = imp.importer_facture(_facture(fournisseur="ATELIER NOVALUX"), sens="achat")
    assert r1["tiers_code"] == "OCR-F-0001" and r1["statut_tiers"] == "nouveau"
    r2 = imp.importer_facture(_facture(numero="FV-2", fournisseur="Atelier Novalux"), sens="achat")
    assert r2["tiers_code"] == "OCR-F-0001" and r2["statut_tiers"] == "existant"
    assert r2["n_factures_tiers"] == 2


def test_vente_rattachee_au_client(entrepot):
    r = imp.importer_facture(_facture(client="Hopital Militaire de Tunis"), sens="vente")
    assert r["ok"] and r["client_code"] == "CP001" and r["sens"] == "vente"


def test_meme_numero_chez_deux_fournisseurs_n_est_pas_un_doublon(entrepot):
    assert imp.importer_facture(_facture(numero="000975"), sens="achat")["ok"]
    assert imp.importer_facture(_facture(numero="000975", fournisseur="ENNASR MARBRE"),
                                sens="achat")["ok"]


def test_meme_numero_meme_fournisseur_est_un_doublon(entrepot):
    assert imp.importer_facture(_facture(numero="FA 250853"), sens="achat")["ok"]
    r = imp.importer_facture(_facture(numero="FA-250853"), sens="achat")
    assert not r["ok"] and r["statut_client"] == "doublon"


def test_meme_document_est_un_doublon(entrepot):
    assert imp.importer_facture(_facture(), sens="achat", fichier_sha256="ab" * 32)["ok"]
    r = imp.importer_facture(_facture(numero="AUTRE"), sens="achat", fichier_sha256="ab" * 32)
    assert not r["ok"] and "déjà été importé" in r["erreur"]


def test_corrections_enregistrees(entrepot):
    lu = _facture(montant_tva=356.25, numero="FV-2026-0142")
    valide = _facture(montant_tva=364.65, numero="FV-2026-0142")
    r = imp.importer_facture(valide, sens="achat", lecture=lu, moteur="layoutlmv3+regles")
    assert r["statut_validation"] == "corrigee"
    assert r["corrections"] == {"montant_tva": {"lu": 356.25, "valide": 364.65}}
    row = _q(entrepot, "SELECT corrections, lecture_origine, moteur, retenue_source "
                       "FROM factures_importees WHERE numero = 'FV-2026-0142'")[0]
    assert json.loads(row[0])["montant_tva"]["valide"] == 364.65
    assert json.loads(row[1])["montant_tva"] == 356.25
    assert row[2] == "layoutlmv3+regles"
    assert row[3] == pytest.approx(23.607)


def test_validation_sans_correction(entrepot):
    r = imp.importer_facture(_facture(), sens="achat", lecture=_facture(montant_ttc=2360.6504))
    assert r["statut_validation"] == "validee_telle_quelle" and r["n_corrections"] == 0
    s = imp.stats_import()
    assert s["n_achats"] == 1 and s["n_ventes"] == 1 and s["part_corrigees"] == 0.0


def test_saisie_nettoyee():
    s = imp.nettoyer_saisie({"montant_ttc": "2 360,650", "date_facture": "2026-09-14T00:00",
                             "numero": "  FV   1 ", "colonne_pirate": "DROP TABLE"})
    assert s == {"montant_ttc": 2360.65, "date_facture": "2026-09-14", "numero": "FV 1"}


NOUS = {"nom": "POLYMER SERVICE PROVIDER", "alias": ["PSP"], "mf": "1234567/A/M/000",
        "configuree": True}


@pytest.mark.parametrize("fournisseur,client,sens,confiance", [
    ("ATL Leasing", "STE POLYMER SERVICE PROVIDER", "achat", "haute"),
    ("Polymer Service Provider SARL", "SUEZ TUNISIE", "vente", "haute"),
    (None, "SUEZ TUNISIE", "vente", "faible"),
    ("ORANGE TUNISIE", None, "achat", "faible"),
    ("ORANGE TUNISIE", "SUEZ TUNISIE", "inconnu", None),
])
def test_detecter_sens(fournisseur, client, sens, confiance):
    r = detecter_sens(fournisseur, client, ident=NOUS)
    assert (r["sens"], r["confiance"]) == (sens, confiance)


def test_sens_inconnu_sans_identite(entrepot):
    assert identite()["configuree"] is False
    assert detecter_sens("A", "B")["sens"] == "inconnu"
    enregistrer_identite("Polymer Service Provider", alias=["PSP"], mf="1234567 A M 000")
    assert identite()["configuree"] and detecter_sens("A", "Polymer Service Provider")["sens"] == "achat"


def test_identite_par_variable_d_environnement(entrepot, monkeypatch):
    monkeypatch.setenv("ENTREPRISE_NOM", "Delta Composites")
    assert identite()["nom"] == "Delta Composites" and identite()["source"] == "environnement"


def test_noyau_mf():
    assert noyau_mf("1234567/A/M/000") == noyau_mf("1234567 a m 000") == "1234567A"
    assert noyau_mf("MF : illisible") is None
