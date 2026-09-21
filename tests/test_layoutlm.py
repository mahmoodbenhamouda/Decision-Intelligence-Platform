"""Tests de la chaîne LayoutLMv3 (sans modèle ni GPU : tout ce qui entoure le réseau)."""
from datetime import date

import pytest

from ml_engine.ocr.engine import SEUIL_QUALITE_TEXTE_PDF, qualite_texte
from ml_engine.ocr.invoice import InvoiceFields
from ml_engine.ocr.layoutlm import disponible, lire_facture
from ml_engine.ocr.layoutlm.champs import (coherence, decoder, depuis_regles, evaluer,
                                          juste, lire_date, lire_montant, spans)
from ml_engine.ocr.layoutlm.extracteur import combiner
from ml_engine.ocr.layoutlm.mots import boites_normalisees, fusion, texte_par_lignes


@pytest.mark.parametrize("brut,attendu", [
    ("2 381,000", 2381.0), ("1.600,000", 1600.0), ("6,720.00", 6720.0),
    ("12.193,50", 12193.5), ("5891-500", 5891.5), ("2931/000", 2931.0),
    ("2364,500TND", 2364.5), ("3.463,900", 3463.9), ("41,40 €", 41.4),
    ("1,000", 1.0), ("TOTAL", None),
])
def test_lire_montant(brut, attendu):
    assert lire_montant(brut) == attendu


@pytest.mark.parametrize("brut,attendu", [
    ("28/02/2025", date(2025, 2, 28)), ("06/11/25", date(2025, 11, 6)),
    ("28-Feb-2025", date(2025, 2, 28)), ("31 août 2025", date(2025, 8, 31)),
    ("140CTOBER25", date(2025, 10, 14)), ("24. décembre 2025", date(2025, 12, 24)),
    ("20.03.2025", date(2025, 3, 20)), ("Facture", None),
])
def test_lire_date(brut, attendu):
    assert lire_date(brut) == attendu


def test_spans_bio():
    mots = ["Total", "TTC", "2", "381,000", "DT"]
    etq = ["O", "O", "B-TTC", "I-TTC", "O"]
    s = spans(mots, etq, [0.1, 0.1, 0.9, 0.8, 0.2])
    assert s["TTC"][0][0] == "2 381,000"
    assert abs(s["TTC"][0][1] - 0.85) < 1e-9


def test_decoder_prend_le_plus_sur_et_controle_arithmetique():
    pages = [{"mots": ["2000,000", "380,000", "1,000", "2381,000", "999,000"],
              "etiquettes": ["B-TOTAL_HT", "B-TVA", "B-TIMBRE", "B-TTC", "B-TTC"],
              "probas": [0.9, 0.9, 0.9, 0.6, 0.7]}]
    r = decoder(pages)
    # 999 est « plus sûr » mais faux : l'arithmétique choisit 2381
    assert r["total_ttc"] == 2381.0 and r["coherent"]
    assert r["net_a_payer"] == 2381.0          # net absent → TTC


def test_coherence_sans_solution_garde_le_modele():
    r = coherence({"total_ht": 10.0, "total_tva": 1.9, "total_ttc": 50.0, "_candidats": {}})
    assert r["total_ttc"] == 50.0 and r["coherent"] is False


def test_juste_et_evaluer():
    assert juste("numero", "N°F00007", "F00007")
    assert juste("client", "SUEZ TUNISIE SA", "Ste SUEZ Tunisie")
    assert juste("total_ttc", 2381.001, 2381.0)          # 1 millime : toléré
    assert not juste("total_ttc", 2380.0, 2381.0)
    v = {"d1": {"total_ttc": 10.0, "devise": "TND"}, "d2": {"total_ttc": 5.0, "devise": "TND"}}
    e = evaluer({"d1": {"total_ttc": 10.0}, "d2": {"total_ttc": 4.0}}, v)
    assert e["total_ttc"] == {"justes": 1, "n": 2, "taux": 50.0}


def test_depuis_regles():
    r = depuis_regles({"numero": "F1", "date_facture": "2025-01-02", "montant_ttc": 10.0,
                       "net_a_payer": None, "tiers": "X"})
    assert r["net_a_payer"] == 10.0 and r["client"] == "X"


def test_qualite_texte_couche_scanner():
    assert qualite_texte("§rxraæsr &Tar&re ef Granit SUARL au capital de 24.000 "
                         "Dinars 2 Rue lbn Abbes Gité errafaha") < SEUIL_QUALITE_TEXTE_PDF
    assert qualite_texte("Facture N° 14/2025 Total HT 1 600,000 TVA 19% 304,000") >= SEUIL_QUALITE_TEXTE_PDF


def test_fusion_recolle_un_nombre_coupe():
    a = [{"t": "2931.0", "x": 100, "y": 10, "w": 60, "h": 12, "c": 73, "psm": 11},
         {"t": "000", "x": 162, "y": 10, "w": 30, "h": 12, "c": 90, "psm": 11}]
    b = [{"t": "2931/000", "x": 100, "y": 10, "w": 92, "h": 12, "c": 41, "psm": 6},
         {"t": "Total", "x": 10, "y": 10, "w": 40, "h": 12, "c": 95, "psm": 3}]
    mots = fusion([a, b])
    assert [m["t"] for m in mots] == ["Total", "2931/000"]
    assert texte_par_lignes(mots) == "Total 2931/000"


def test_boites_normalisees():
    assert boites_normalisees([{"x": 0, "y": 50, "w": 100, "h": 50}], 200, 100) == [[0, 500, 500, 1000]]


def test_combiner_complete_les_regles():
    f = InvoiceFields(montant_ht=2000.0, montant_tva=380.0, montant_ttc=2831.0)  # TTC mal lu
    lu = {"numero": "F00007", "date": "2025-02-28", "total_ht": None, "total_tva": 380.0,
          "timbre": 1.0, "total_ttc": 2381.0, "net_a_payer": 2309.57,
          "fournisseur": "MW Solutions", "_candidats": {}}
    combiner(f, lu)
    assert f.numero == "F00007" and f.montant_ttc == 2381.0 and f.montant_ht == 2000.0
    assert f.net_a_payer == 2309.57 and f.coherence == "ok"
    assert f.champs_confiance["montant_ttc"] == "layoutlmv3"


def test_sans_modele_la_chaine_historique_reste(tmp_path, monkeypatch):
    monkeypatch.setenv("OVERLYNE_LAYOUTLM_DIR", str(tmp_path / "absent"))
    assert disponible() is False
    from PIL import Image, ImageDraw
    import io
    im = Image.new("RGB", (900, 300), "white")
    ImageDraw.Draw(im).text((20, 20), "FACTURE N F00007 TOTAL TTC 2381,000", fill="black")
    buf = io.BytesIO(); im.save(buf, format="PNG")
    res, fields, moteur = lire_facture(buf.getvalue(), "f.png")
    assert moteur == "regles"


def test_hybride_prefere_les_regles_quand_le_modele_hesite():
    from ml_engine.ocr.layoutlm.champs import fusionner_avec_regles
    lu = {"numero": "XX9", "total_ttc": 2381.0, "total_ht": 2000.0, "total_tva": 380.0,
          "timbre": 1.0, "_scores": {"numero": 0.3, "total_ttc": 0.95}, "_candidats": {}}
    h = fusionner_avec_regles(lu, {"numero": "F00007", "total_ttc": 2831.0})
    assert h["numero"] == "F00007"            # modèle hésitant → règles
    assert h["total_ttc"] == 2381.0 and h["coherent"]


# ── filtre de vraisemblance des montants venus des règles ──────────────────
def test_filtre_d002_tva_absurde_des_regles_ecartee():
    from ml_engine.ocr.layoutlm.champs import fusionner_avec_regles
    # cas réel : le modèle n'a pas lu de TVA, les règles proposent 101 296
    lu = {"total_ht": 1416.123, "total_tva": None, "timbre": 1.0,
          "total_ttc": 1855.276, "net_a_payer": 1855.276, "_candidats": {}}
    regles = {"total_ht": 157610700.0, "total_tva": 101296.0, "total_ttc": 157711996.0}
    h = fusionner_avec_regles(lu, regles)
    assert h["total_tva"] is None                       # plutôt vide que faux
    assert h["total_ht"] == 1416.123 and h["total_ttc"] == 1855.276
    assert ("total_tva", 101296.0) in h["_rejetes"]
    assert 101296.0 not in h["_candidats"].get("total_tva", [])


def test_filtre_garde_un_montant_credible_des_regles():
    from ml_engine.ocr.layoutlm.champs import fusionner_avec_regles
    h = fusionner_avec_regles({"total_ht": None, "total_tva": 380.0, "timbre": 1.0,
                               "total_ttc": 2381.0, "_candidats": {}},
                              {"total_ht": 2000.0})
    assert h["total_ht"] == 2000.0 and h["coherent"] and h["_rejetes"] == []


def test_filtre_tva_superieure_au_ht():
    from ml_engine.ocr.layoutlm.champs import fusionner_avec_regles
    h = fusionner_avec_regles({"total_ht": 1000.0, "total_tva": None,
                               "total_ttc": None, "_candidats": {}},
                              {"total_tva": 1500.0})
    assert h["total_tva"] is None


@pytest.mark.parametrize("cle,v,lu,attendu", [
    ("total_tva", 7.0, {"total_ttc": 107.0}, True),        # taux 7 % : TTC ≈ 15 × TVA
    ("total_ht", -5.0, {}, False),
    ("total_ttc", 157711996.0, {"total_ht": 1416.1}, False),
    ("timbre", 1.0, {"total_ttc": 52.0}, True),
    ("net_a_payer", 2309.57, {"total_ttc": 2381.0}, True),  # net < TTC : retenue à la source
    ("total_ht", 2000.0, {}, True),                         # rien à comparer : on ne juge pas
])
def test_montant_plausible(cle, v, lu, attendu):
    from ml_engine.ocr.layoutlm.champs import montant_plausible
    assert montant_plausible(cle, v, lu) is attendu


def test_combiner_signale_un_montant_ecarte():
    f = InvoiceFields(montant_ht=1416.123, montant_tva=101296.0, montant_ttc=None)
    combiner(f, {"total_ht": 1416.123, "total_tva": None, "timbre": 1.0,
                 "total_ttc": 1855.276, "net_a_payer": 1855.276, "_candidats": {}})
    assert f.montant_ttc == 1855.276
    assert f.montant_tva is None                        # effacée, pas seulement signalée
    assert f.champs_confiance["montant_tva"] == "ecarte"
    assert any("total_tva" in a and "101 296,000" in a for a in f.avertissements)
