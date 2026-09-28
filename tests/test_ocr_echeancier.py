"""Échéancier des factures OCR : pas de double compte, net à payer, échéance déduite."""
from datetime import date

import pytest

duckdb = pytest.importorskip("duckdb")

from ml_engine.ocr import importer as imp
from ml_engine.ocr.echeancier import echeancier, marquer_reglee

AUJ = date(2026, 9, 21)


@pytest.fixture
def entrepot(tmp_path, monkeypatch):
    chemin = tmp_path / "store.duckdb"
    monkeypatch.setattr("ml_engine.analytics.kpi_engine.STORE_PATH", chemin)
    con = duckdb.connect(str(chemin))
    con.execute("CREATE TABLE dim_client (client_code VARCHAR, client_name VARCHAR, x VARCHAR)")
    con.execute("INSERT INTO dim_client VALUES ('CP001', 'HOPITAL MILITAIRE', NULL)")
    con.execute("""CREATE TABLE sales (ent_id INT, piece_no VARCHAR, client VARCHAR, date DATE,
                   echeance DATE, ht DOUBLE, ttc DOUBLE, est_avoir BOOLEAN, mode_regl VARCHAR,
                   nbr_article INT, year INT, payment_delay_days INT, client_name VARCHAR)""")
    for d in (60, 60, 90):                                 # client CP001 : 60 j habituels
        con.execute("INSERT INTO sales VALUES (1,'V','CP001',DATE '2025-01-01',NULL,1,1,FALSE,NULL,1,2025,?,'HOPITAL MILITAIRE')", [d])
    con.execute("""CREATE TABLE purchases (ent_id INT, piece_no VARCHAR, fournisseur VARCHAR,
                   fournisseur_code VARCHAR, date DATE, echeance DATE, ht DOUBLE, ttc DOUBLE,
                   est_avoir BOOLEAN, mode_regl VARCHAR, tva DOUBLE, piece_externe VARCHAR,
                   year INT, payment_delay_days INT)""")
    for d in (45, 45, -300):                               # BIOMERIEUX : 45 j (le -300 est écarté)
        con.execute("INSERT INTO purchases VALUES (1,'A','BIOMERIEUX','F1',DATE '2025-01-01',NULL,1,1,FALSE,NULL,NULL,NULL,2025,?)", [d])
    con.execute("INSERT INTO purchases VALUES (2,'A','AUTRE','F9',DATE '2025-01-01',NULL,1,1,FALSE,NULL,NULL,NULL,2025,20)")
    con.close()
    return chemin


def _achat(numero, **k):
    f = {"numero": numero, "fournisseur": "BIOMERIEUX", "date_facture": "2026-09-01",
         "montant_ttc": 1000.0}
    f.update(k)
    rappro = k.pop("_rappro", None) if "_rappro" in k else None
    f.pop("_rappro", None)
    return imp.importer_facture(f, sens="achat", rapprochement=rappro)


def test_echeance_deduite_du_delai_du_fournisseur(entrepot):
    _achat("A1")
    l = echeancier(AUJ)["factures"][0]
    assert l["echeance"] == "2026-10-16" and l["source_echeance"] == "delai_tiers"   # 1/9 + 45 j
    assert l["statut"] == "a_venir"


def test_echeance_lue_prime(entrepot):
    _achat("A1", date_echeance="2026-09-10")
    l = echeancier(AUJ)["factures"][0]
    assert l["source_echeance"] == "lue" and l["statut"] == "en_retard" and l["jours_de_retard"] == 11


def test_fournisseur_inconnu_delai_moyen(entrepot):
    _achat("A1", fournisseur="NOUVEAU FOURNISSEUR")
    l = echeancier(AUJ)["factures"][0]
    assert l["source_echeance"] == "delai_moyen" and l["delai_jours"] == 45   # médiane 20,45,45 → 45


def test_net_a_payer_et_pas_le_ttc(entrepot):
    _achat("A1", montant_ttc=2360.65, net_a_payer=2337.043)
    e = echeancier(AUJ)
    assert e["a_payer_dt"] == 2337.043 and e["factures"][0]["retenue_source_dt"] == pytest.approx(23.607)


def test_facture_deja_dans_l_erp_non_comptee_deux_fois(entrepot):
    _achat("A1", _rappro={"statut": "rapprochee", "candidats": [{"numero_erp": "X"}]})
    _achat("A2", _rappro={"statut": "introuvable", "candidats": []})
    e = echeancier(AUJ)
    assert [l["numero"] for l in e["factures"]] == ["A2"]


def test_vente_avec_delai_client(entrepot):
    imp.importer_facture({"numero": "V1", "client": "Hopital Militaire", "date_facture": "2026-08-01",
                          "montant_ttc": 500.0}, sens="vente")
    e = echeancier(AUJ)
    l = e["factures"][0]
    assert l["echeance"] == "2026-09-30" and l["sens"] == "vente"            # 1/8 + 60 j
    assert e["a_encaisser_dt"] == 500.0 and e["a_payer_dt"] == 0


def test_regroupement_par_mois_et_retard(entrepot):
    _achat("A1", date_echeance="2026-09-01")                      # en retard
    _achat("A2", date_echeance="2026-10-15")
    _achat("A3", date_echeance="2026-10-20", montant_ttc=500.0)
    imp.importer_facture({"numero": "V1", "client": "Hopital Militaire", "date_facture": "2026-09-01",
                          "date_echeance": "2026-10-05", "montant_ttc": 800.0}, sens="vente")
    mois = {m["periode"]: m for m in echeancier(AUJ)["mois"]}
    assert list(mois) == ["en_retard", "2026-10"]
    assert mois["2026-10"]["decaissements_dt"] == 1500 and mois["2026-10"]["encaissements_dt"] == 800
    assert mois["2026-10"]["solde_dt"] == -700
    assert echeancier(AUJ)["a_payer_en_retard_dt"] == 1000


def test_facture_reglee_sort_de_l_echeancier(entrepot):
    r = _achat("A1")
    assert marquer_reglee(r["id"], date(2026, 9, 20))["ok"]
    assert echeancier(AUJ)["n_factures"] == 0
    marquer_reglee(r["id"], annuler=True)
    assert echeancier(AUJ)["n_factures"] == 1
    assert not marquer_reglee(999)["ok"]
