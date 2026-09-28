"""API OCR : lire une fois, corriger, enregistrer du bon côté.

Application réduite au seul routeur OCR, avec la traduction des erreurs
métier en codes HTTP ; authentification, lecture du document et
rapprochement (appelés par le service OCR) sont remplacés par des doublures.
L'entrepôt est TEMPORAIRE : la base réelle n'est jamais touchée.
"""
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("fastapi")
os.environ.setdefault("AUTH_DATABASE_URL",
                      f"sqlite:///{Path(tempfile.mkdtemp()).as_posix()}/auth.db")
os.environ.setdefault("JWT_SECRET_KEY", "secret-de-test-uniquement")

import duckdb  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.auth.database import get_db  # noqa: E402
from api.auth.deps import get_current_user, require_directeur  # noqa: E402
from api.auth.models import ROLE_DIRECTEUR  # noqa: E402
from api.core.erreurs import installer_gestion_erreurs  # noqa: E402
from api.routers import ocr as route  # noqa: E402
from api.services import ocr as service  # noqa: E402
from ml_engine.ocr.engine import OCRResult  # noqa: E402
from ml_engine.ocr.invoice import InvoiceFields  # noqa: E402

PDF = b"%PDF-1.4 facture de test"


def _champs():
    return InvoiceFields(numero="FV-2026-0142", date_facture="2026-09-14",
                         montant_ht=1995.0, montant_tva=356.25,        # TVA partielle : l'erreur type
                         montant_ttc=2360.65, timbre_fiscal=1.0, net_a_payer=2337.043,
                         fournisseur="ATELIER NOVALUX", client="POLYMER SERVICE PROVIDER",
                         tiers="POLYMER SERVICE PROVIDER", is_invoice=True)


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = tmp_path / "store.duckdb"
    monkeypatch.setattr("ml_engine.analytics.kpi_engine.STORE_PATH", store)
    for v in ("ENTREPRISE_NOM", "ENTREPRISE_ALIAS", "ENTREPRISE_MF"):
        monkeypatch.delenv(v, raising=False)
    con = duckdb.connect(str(store))
    con.execute("CREATE TABLE dim_client (client_code VARCHAR, client_name VARCHAR, x VARCHAR)")
    con.execute("INSERT INTO dim_client VALUES ('CP001', 'HOPITAL MILITAIRE DE TUNIS', NULL)")
    con.execute("""CREATE TABLE sales (ent_id INT, piece_no VARCHAR, client VARCHAR, date DATE,
                   echeance DATE, ht DOUBLE, ttc DOUBLE, est_avoir BOOLEAN, mode_regl VARCHAR,
                   nbr_article INT, year INT, payment_delay_days INT, client_name VARCHAR)""")
    con.close()

    lectures = {"n": 0}

    def lire(content, name):
        lectures["n"] += 1
        return (OCRResult(text="FACTURE FV-2026-0142 ATELIER NOVALUX", confidence=91.0,
                          source="pdf-texte", pages=1, engine="test"),
                _champs(), "layoutlmv3+regles")

    monkeypatch.setattr(service, "lire_facture", lire)
    # le rapprochement renvoie le sens dans lequel on l'a appelé, et le TTC reçu
    monkeypatch.setattr(service, "reconcile_invoice", lambda f, client_code=None, sens="vente", **k: {
        "statut": f"test-{sens}", "candidats": [], "ttc_vu": f.get("montant_ttc"), "portee": client_code})
    monkeypatch.setattr(service, "audit", lambda *a, **k: None)

    app = FastAPI()
    installer_gestion_erreurs(app)
    app.include_router(route.router)
    qui = {"u": SimpleNamespace(role=ROLE_DIRECTEUR, client_code=None, username="dir")}
    app.dependency_overrides[get_current_user] = lambda: qui["u"]
    app.dependency_overrides[require_directeur] = lambda: qui["u"]
    app.dependency_overrides[get_db] = lambda: None
    return SimpleNamespace(c=TestClient(app), lectures=lectures, qui=qui, store=store)


def _lire(api):
    r = api.c.post("/api/ocr/invoice", files={"file": ("f.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def test_flux_complet_achat_corrige_sans_relire(api):
    api.c.put("/api/ocr/entreprise", data={"nom": "Polymer Service Provider", "alias": "PSP"})
    lu = _lire(api)
    assert len(lu["lecture_id"]) == 64
    assert lu["sens"]["sens"] == "achat" and lu["sens"]["confiance"] == "haute"
    assert lu["entreprise"]["configuree"]

    corrige = dict(lu["facture"], montant_tva=364.65)
    r = api.c.post("/api/ocr/invoice/import", data={
        "lecture_id": lu["lecture_id"], "facture": json.dumps(corrige), "sens": "achat"})
    assert r.status_code == 200, r.text
    imp = r.json()["import"]
    assert imp["sens"] == "achat" and imp["tiers_code"] == "OCR-F-0001"
    assert imp["statut_validation"] == "corrigee"
    assert imp["corrections"] == {"montant_tva": {"lu": 356.25, "valide": 364.65}}
    assert api.lectures["n"] == 1                               # le document n'a PAS été relu
    assert r.json()["facture"]["coherence"].startswith("HT + TVA = TTC")   # recalculée
    con = duckdb.connect(str(api.store), read_only=True)
    assert con.execute("SELECT count(*) FROM sales_augmentee WHERE source='ocr'").fetchone()[0] == 0
    con.close()


def test_sens_inconnu_refuse_plutot_que_devine(api):
    lu = _lire(api)                                             # aucune identité configurée
    assert lu["sens"]["sens"] == "inconnu"
    r = api.c.post("/api/ocr/invoice/import", data={
        "lecture_id": lu["lecture_id"], "facture": json.dumps(lu["facture"])})
    assert r.status_code == 409 and r.json()["detail"]["statut_client"] == "sens_inconnu"
    r = api.c.post("/api/ocr/invoice/import", data={
        "lecture_id": lu["lecture_id"], "facture": json.dumps(lu["facture"]), "sens": "vente"})
    assert r.status_code == 200 and r.json()["import"]["statut_validation"] == "validee_telle_quelle"


def test_compte_client_force_vente_et_son_code(api):
    lu = _lire(api)
    api.qui["u"] = SimpleNamespace(role="client", client_code="CP001", username="cli")
    r = api.c.post("/api/ocr/invoice/import", data={
        "lecture_id": lu["lecture_id"], "facture": json.dumps(lu["facture"]),
        "sens": "achat", "tiers_code": "F999", "client_code": "CP777"})
    assert r.status_code == 200, r.text
    imp = r.json()["import"]
    assert imp["sens"] == "vente" and imp["client_code"] == "CP001"


def test_identifiant_de_lecture_malveillant(api):
    r = api.c.post("/api/ocr/invoice/import", data={"lecture_id": "../../etc/passwd"})
    assert r.status_code == 404


def test_chemin_historique_marque_sans_relecture(api):
    r = api.c.post("/api/ocr/invoice/import", data={"sens": "achat"},
                   files={"file": ("f.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["import"]["statut_validation"] == "sans_relecture"


def test_meme_document_deux_fois(api):
    lu = _lire(api)
    d = {"lecture_id": lu["lecture_id"], "facture": json.dumps(lu["facture"]), "sens": "achat"}
    assert api.c.post("/api/ocr/invoice/import", data=d).status_code == 200
    r = api.c.post("/api/ocr/invoice/import", data=d)
    assert r.status_code == 409 and r.json()["detail"]["statut_client"] == "doublon"


def test_imports_liste_le_sens(api):
    lu = _lire(api)
    api.c.post("/api/ocr/invoice/import", data={
        "lecture_id": lu["lecture_id"], "facture": json.dumps(lu["facture"]), "sens": "achat"})
    r = api.c.get("/api/ocr/imports", params={"sens": "achat"}).json()
    assert r["factures"][0]["sens"] == "achat" and r["stats"]["n_achats"] == 1


def test_rapprochement_suit_le_sens(api):
    lu = _lire(api)                                     # identité non configurée : sens inconnu
    assert lu["rapprochement"]["statut"] == "sens_a_choisir"
    r = api.c.post("/api/ocr/rapprocher", data={
        "lecture_id": lu["lecture_id"], "sens": "achat",
        "facture": json.dumps({"montant_ttc": "2 360,650"})}).json()
    assert r["statut"] == "test-achat" and r["ttc_vu"] == 2360.65      # sur la valeur corrigée
    imp = api.c.post("/api/ocr/invoice/import", data={
        "lecture_id": lu["lecture_id"], "facture": json.dumps(lu["facture"]), "sens": "achat"}).json()
    assert imp["rapprochement"]["statut"] == "test-achat"
    assert imp["import"]["rapprochement_statut"] == "test-achat"
    liste = api.c.get("/api/ocr/imports", params={"rapprochement": "test-achat"}).json()
    assert len(liste["factures"]) == 1


def test_rapprocher_compte_client_reste_dans_son_perimetre(api):
    lu = _lire(api)
    api.qui["u"] = SimpleNamespace(role="client", client_code="CP001", username="cli")
    r = api.c.post("/api/ocr/rapprocher", data={"lecture_id": lu["lecture_id"], "sens": "achat"}).json()
    assert r["statut"] == "test-vente" and r["portee"] == "CP001"


def test_echeancier_et_reglement(api):
    lu = _lire(api)
    r = api.c.post("/api/ocr/invoice/import", data={
        "lecture_id": lu["lecture_id"], "facture": json.dumps(lu["facture"]), "sens": "achat"}).json()
    e = api.c.get("/api/ocr/echeancier").json()
    assert e["n_factures"] == 1 and e["a_payer_dt"] == 2337.043        # net, pas le TTC
    assert e["factures"][0]["source_echeance"].startswith("delai_moyen")
    fid = r["import"]["id"]
    assert api.c.post(f"/api/ocr/imports/{fid}/reglement", data={"le": "2026-09-20"}).status_code == 200
    assert api.c.get("/api/ocr/echeancier").json()["n_factures"] == 0
    assert api.c.post("/api/ocr/imports/999/reglement").status_code == 404


def test_qualite_en_production(api):
    lu = _lire(api)
    corrige = dict(lu["facture"], montant_tva=364.65)
    api.c.post("/api/ocr/invoice/import", data={
        "lecture_id": lu["lecture_id"], "facture": json.dumps(corrige), "sens": "achat"})
    q = api.c.get("/api/ocr/qualite").json()
    m = q["par_moteur"]["layoutlmv3+regles"]
    assert q["n_factures_relues"] == 1 and m["champs"]["montant_tva"]["exactitude_pct"] == 0.0
    assert m["champs"]["montant_ttc"]["exactitude_pct"] == 100.0
