"""Boucle d'apprentissage : une facture validée en production rejoint le jeu d'entraînement."""
import hashlib
import importlib.util
import json
import shutil
import zipfile
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("pytesseract")
if not shutil.which("tesseract"):
    pytest.skip("binaire tesseract absent", allow_module_level=True)

RACINE = Path(__file__).resolve().parents[1]
FACTURE = RACINE / "evaluation_ocr" / "test_nouvelles" / "FV-2026-0142_numerique.pdf"
ZIP_REEL = RACINE / "evaluation_ocr" / "layoutlmv3" / "layoutlmv3_factures.zip"
if not FACTURE.exists():
    pytest.skip("facture de test absente", allow_module_level=True)


def _script():
    spec = importlib.util.spec_from_file_location(
        "integrer", RACINE / "evaluation_ocr" / "preparation" / "6_integrer_production.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


@pytest.fixture
def importee(tmp_path, monkeypatch):
    monkeypatch.setattr("ml_engine.analytics.kpi_engine.STORE_PATH", tmp_path / "store.duckdb")
    monkeypatch.setattr("ml_engine.ocr.layoutlm.mots.LANG", "eng")
    con = duckdb.connect(str(tmp_path / "store.duckdb"))
    con.execute("CREATE TABLE dim_client (client_code VARCHAR, client_name VARCHAR, x VARCHAR)")
    con.close()
    from ml_engine.ocr import importer as imp
    from ml_engine.ocr.lectures import dossier
    contenu = FACTURE.read_bytes()
    sha = hashlib.sha256(contenu).hexdigest()
    (dossier() / f"{sha}.pdf").write_bytes(contenu)
    lu = {"numero": "FV-2026-0142", "date_facture": "2026-09-14", "fournisseur": "ATELIER NOVALUX",
          "client": "STE DELTA COMPOSITES", "montant_ht": 1995.0, "montant_tva": 356.25,
          "timbre_fiscal": 1.0, "montant_ttc": 2360.65, "net_a_payer": 2337.043}
    r = imp.importer_facture(dict(lu, montant_tva=364.65), sens="achat", lecture=lu,
                             fichier="FV-2026-0142_numerique.pdf", fichier_sha256=sha)
    assert r["ok"] and r["statut_validation"] == "corrigee"
    return tmp_path


def test_la_verite_est_la_valeur_corrigee_et_elle_est_etiquetee(importee):
    m = _script()
    fact = m.factures_validees()
    lignes, verite, regles, rapports, images, absents = m.construire_exemples(fact)
    (doc,) = verite
    assert doc.startswith("p_") and not absents
    assert verite[doc]["total_tva"] == 364.65 and verite[doc]["origine"] == "production"
    rap = rapports[doc]
    assert rap["source"] == "natif"
    for champ in ("NUMERO", "DATE", "TOTAL_HT", "TVA", "TTC", "NET"):
        assert rap[champ] == "trouve", (champ, rap)
    etq = [e for l in lignes for e in l["etiquettes"]]
    mots = [w for l in lignes for w in l["mots"]]
    tva = [w for w, e in zip(mots, etq) if e.endswith("-TVA")]
    assert tva == ["364,650"], tva
    assert all(len(l["mots"]) == len(l["boites"]) == len(l["etiquettes"]) for l in lignes)
    assert set(images) == {l["image"] for l in lignes}


@pytest.mark.skipif(not ZIP_REEL.exists(), reason="jeu d'entraînement absent")
def test_fusion_dans_une_copie_du_vrai_zip(importee):
    m = _script()
    copie = importee / "jeu.zip"
    shutil.copyfile(ZIP_REEL, copie)
    ex = m.construire_exemples(m.factures_validees())[:5]
    n = m.fusionner_zip(copie, *ex)
    assert n["documents_origine"] == 89 and n["documents_production"] == 1
    assert m.fusionner_zip(copie, *ex) == n
    z = zipfile.ZipFile(copie)
    v = json.loads(z.read("verite.json"))
    assert len(v) == 90 and all("devise" in x for x in v.values())
    pages = [json.loads(l) for l in z.read("pages.jsonl").decode().splitlines()]
    assert all(p["image"] in z.namelist() for p in pages)
    assert "champs.py" in z.namelist()
    r = json.loads(z.read("regles.json"))
    assert set(r) == set(v) and all("meme_ocr" in x for x in r.values())
