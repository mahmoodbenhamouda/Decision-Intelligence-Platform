"""Boucle d'apprentissage : mesure en production, à partir des corrections."""
import pytest

duckdb = pytest.importorskip("duckdb")

from ml_engine.ocr import importer as imp
from ml_engine.ocr.apprentissage import mesure_production


@pytest.fixture
def entrepot(tmp_path, monkeypatch):
    chemin = tmp_path / "store.duckdb"
    monkeypatch.setattr("ml_engine.analytics.kpi_engine.STORE_PATH", chemin)
    con = duckdb.connect(str(chemin))
    con.execute("CREATE TABLE dim_client (client_code VARCHAR, client_name VARCHAR, x VARCHAR)")
    con.close()
    return chemin


LU = {"numero": "F1", "date_facture": "2026-09-14", "fournisseur": "NOVALUX", "client": "PSP",
      "montant_ht": 1995.0, "montant_tva": 356.25, "montant_ttc": 2360.65, "timbre_fiscal": 1.0,
      "net_a_payer": 2337.043}


def _importer(numero, corrige=None, moteur="layoutlmv3+regles", relue=True):
    lu = dict(LU, numero=numero)
    valide = dict(lu, **(corrige or {}))
    return imp.importer_facture(valide, sens="achat", moteur=moteur, lecture=lu if relue else None)


def test_exactitude_par_champ(entrepot):
    _importer("F1", {"montant_tva": 364.65})
    _importer("F2", {"montant_tva": 364.65})
    _importer("F3")
    _importer("F4", {"montant_tva": 364.65, "numero": "F4-BIS"})
    m = mesure_production()["par_moteur"]["layoutlmv3+regles"]
    assert m["n_factures"] == 4 and m["n_sans_correction"] == 1
    assert m["champs"]["montant_tva"] == {"n": 4, "corriges": 3, "exactitude_pct": 25.0}
    assert m["champs"]["numero"]["exactitude_pct"] == 75.0
    assert m["champs"]["montant_ttc"]["exactitude_pct"] == 100.0
    assert m["factures_sans_correction_pct"] == 25.0


def test_champ_vide_des_deux_cotes_ne_compte_pas(entrepot):
    lu = dict(LU, timbre_fiscal=None)
    imp.importer_facture(lu, sens="achat", moteur="m", lecture=lu)
    assert mesure_production()["par_moteur"]["m"]["champs"]["timbre_fiscal"]["n"] == 0


def test_champ_manque_puis_saisi_est_une_erreur(entrepot):
    lu = dict(LU, timbre_fiscal=None)
    imp.importer_facture(dict(lu, timbre_fiscal=1.0), sens="achat", moteur="m", lecture=lu)
    assert mesure_production()["par_moteur"]["m"]["champs"]["timbre_fiscal"] == {
        "n": 1, "corriges": 1, "exactitude_pct": 0.0}


def test_moteurs_separes_et_sans_relecture_exclus(entrepot):
    _importer("F1", moteur="regles", corrige={"montant_ht": 2000.0})
    _importer("F2", moteur="layoutlmv3+regles")
    _importer("F3", relue=False)
    r = mesure_production()
    assert r["n_factures_relues"] == 2 and set(r["par_moteur"]) == {"regles", "layoutlmv3+regles"}
    assert r["suffisant"] is False and "instables" in r["note"]
