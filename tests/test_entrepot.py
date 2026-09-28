"""
tests/test_entrepot.py
======================
L'ETL de l'entrepôt (etl/), sur des exports CSV fabriqués pour le test :

1. le contrat de présentation — les vues lues par l'application gardent leurs
   colonnes ;
2. les règles métier — signe des avoirs, doublons écartés, lignes décalées
   rejetées, marge sans coûts aberrants ;
3. le modèle en étoile — dimensions conformes, membres déduits, calendrier
   continu, contrôles d'intégrité ;
4. la sûreté de la construction — tables applicatives préservées, clients OCR
   conservés, construction annulée d'un bloc si un contrôle échoue.

L'entrepôt réel n'est jamais ouvert : tout se passe dans un dossier temporaire.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etl import construire as etl  # noqa: E402
from etl import presentation, qualite  # noqa: E402
from etl.sources import SOURCES  # noqa: E402


def _ecrire(dossier: Path, role: str, lignes: list[dict]) -> None:
    chemin = dossier / SOURCES[role].fichier
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0]))
        w.writeheader()
        w.writerows(lignes)


def _vente(ent, piece, tiers, date, ttc, signe=1, mode="Virement 60 JOURS", depot="DP"):
    return {"ENT_ID": ent, "PIECENOFULL": piece, "TIERS": tiers, "DATEPIECE": date,
            "DATEECHEANCE": "3/1/2024", "MONTANTSIGNE_DEV": str(signe * ttc / 1.19),
            "HT_DEV": str(round(ttc / 1.19, 3)), "TTC_DEV": str(ttc),
            "MODEREGLLIBELLE": mode, "NBREARTICLE": "2", "DEPOT": depot}


def _ligne(mouv, piece, tiers, ref, montant, qte, cout, sens="2", date="1/15/2024",
           designation=None, famille="REACTIF"):
    return {"MOUV_ID": mouv, "NUMEROFULL": piece, "TIERS": tiers, "REFERENCE": ref,
            "DESIGNATION": designation or f"PRODUIT {ref}", "ARTICLE_LIBELLE_FAM_STAT1": famille,
            "DATEFACTURE": date, "MONTANTSIGNE_DEV": str(montant),
            "QUANTITESIGNEE": str(qte), "MTCRSIGNE": str(cout), "SENS": sens}


@pytest.fixture
def sources(tmp_path):
    d = tmp_path / "sources"
    d.mkdir()
    _ecrire(d, "ventes_entetes", [
        _vente("1", "FV-001", "CP001", "1/15/2024", 1190.0),
        _vente("2", "FV-001", "CP001", "1/15/2024", 1190.0),              # doublon exact
        _vente("3", "AV-001", "CP001", "1/20/2024", 119.0, signe=-1),     # avoir
        _vente("4", "FV-002", "CP999", "2/10/2024", 2380.0,               # client hors référentiel
               mode="virement 60 jours", depot="XX"),
        _vente("5", "FV-003", "CP002", "", 500.0),                        # sans date : écarté
    ])
    _ecrire(d, "ventes_lignes", [
        _ligne("10", "FV-001", "CP001", "R1", 600.0, 6, 300.0),
        _ligne("11", "FV-001", "CP001", "R1", 600.0, 6, 300.0),           # doublon de l'en-tête dupliqué
        _ligne("12", "FV-001", "CP001", "R2", 400.0, 4, 5000.0),          # coût aberrant (> 5x)
        _ligne("13", "AV-001", "CP001", "R1", -100.0, -1, -50.0, sens="1"),
        _ligne("14", "FV-002", "CP999", "R3", 2000.0, 10, 1200.0),
        _ligne("15", "FV-002", "CP999", "R3", 99.0, 1, 1.0, sens="CULTURE"),  # colonnes décalées
    ])
    _ecrire(d, "achats_entetes", [{
        "ENT_ID": "1", "PIECENOFULL": "FA-1", "FOURNISSEURNOM": "BIOMERIEUX",
        "CLE_FOURNISSEUR": "F1", "DATEPIECE": "1/5/2024", "DATEECHEANCE": "2/5/2024",
        "MONTANTSIGNE_DEV": "1000", "HT_DEV": "1000", "TTC_DEV": "1190",
        "MONTANTTVAFOURNISSEUR_DEV": "190", "MODEREGLLIBELLE": "Virement", "PIECEEXTERNE": "BX-77"}])
    _ecrire(d, "achats_lignes", [
        {"MOUV_ID": "1", "NUMEROFULL": "FA-1", "CLE_FOURNISSEUR": "F1", "REFERENCE": "R1",
         "DESIGNATION": "PRODUIT R1", "INDICMVTSTOCK": "1", "DATEFACTURE": "1/5/2024",
         "QUANTITESIGNEE": "20", "MONTANTSIGNE_DEV": "1000"},
        {"MOUV_ID": "2", "NUMEROFULL": "FA-1", "CLE_FOURNISSEUR": "F9", "REFERENCE": "R4",
         "DESIGNATION": "PRODUIT R4", "INDICMVTSTOCK": "1", "DATEFACTURE": "1/1/1900",
         "QUANTITESIGNEE": "1", "MONTANTSIGNE_DEV": "10"}])
    _ecrire(d, "devis", [
        {"ENT_ID": "1", "PIECENOFULL": "DV-1", "TIERS": "CP001", "DATEPIECE": "1/2/2024",
         "MONTANTSIGNE_DEV": "100", "HT_DEV": "100", "TTC_DEV": "119",
         "STATUS": "A", "ETATPIECE": "8"},
        {"ENT_ID": "2", "PIECENOFULL": "DV-2", "TIERS": "CP003", "DATEPIECE": "1/3/2024",
         "MONTANTSIGNE_DEV": "50", "HT_DEV": "50", "TTC_DEV": "59.5",
         "STATUS": "A", "ETATPIECE": ""}])
    _ecrire(d, "livraisons", [
        {"ENT_CLIENT_CODE": "CP001", "ENT_DATE": "1/14/2024", "ENT_NBR_ARTICLE": "3"}])
    _ecrire(d, "gsl_factures", [
        {"ENT_CLIENT_CODE": "CP001", "ENT_CLIENT_INTITULE": "HOPITAL MILITAIRE",
         "ENT_CLIENT_VILLE": "TUNIS", "ENT_DEPOT_CODE": "DP", "ENT_DEPOT_INTITULE": "DEPOT CHARGUIA"},
        {"ENT_CLIENT_CODE": "CP002", "ENT_CLIENT_INTITULE": "CLINIQUE X",
         "ENT_CLIENT_VILLE": "SFAX", "ENT_DEPOT_CODE": "DP", "ENT_DEPOT_INTITULE": "DEPOT CHARGUIA"}])
    _ecrire(d, "fournisseurs", [
        {"CLE_FOURNISSEUR": "F1", "TIERS": "FE1", "NOMFOURNISSEUR": "BIOMERIEUX",
         "VILLE": "LYON", "PAYSLIBELLE": "NULL"}])
    return d


@pytest.fixture
def entrepot(tmp_path, sources):
    chemin = tmp_path / "entrepot.duckdb"
    etl.construire(chemin, sources, rapport=None)
    return chemin


def _q(chemin, sql):
    con = duckdb.connect(str(chemin), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# ── 1. Contrat de présentation ──────────────────────────────────────────────
COLONNES_ATTENDUES = {
    "sales": ["ent_id", "piece_no", "client", "date", "echeance", "ht", "ttc", "est_avoir",
              "mode_regl", "nbr_article", "year", "payment_delay_days", "client_name"],
    "sales_lines": ["mouv_id", "piece_no", "client", "reference", "designation", "famille",
                    "date", "montant", "qte", "cout", "format_valide"],
    "purchases": ["ent_id", "piece_no", "fournisseur", "fournisseur_code", "date", "echeance",
                  "ht", "ttc", "est_avoir", "mode_regl", "tva", "piece_externe", "year",
                  "payment_delay_days"],
    "devis": ["client", "piece_no", "date", "ht", "ttc", "status", "etat_piece", "transforme"],
    "bl": ["client", "date", "nbr_article"],
    "client_margin": ["client", "year", "period", "ca_ligne", "cout_revient", "marge",
                      "n_lignes", "n_lignes_retour"],
}


@pytest.mark.parametrize("vue", sorted(COLONNES_ATTENDUES))
def test_les_vues_gardent_le_contrat_de_l_application(entrepot, vue):
    cols = [r[0] for r in _q(entrepot, f"SELECT column_name FROM information_schema.columns "
                                       f"WHERE table_name = '{vue}' ORDER BY ordinal_position")]
    assert cols == COLONNES_ATTENDUES[vue]


def test_toutes_les_vues_de_presentation_existent(entrepot):
    vues = {r[0] for r in _q(entrepot, "SELECT table_name FROM information_schema.tables "
                                       "WHERE table_type = 'VIEW'")}
    assert set(presentation.VUES) <= vues


# ── 2. Règles métier ────────────────────────────────────────────────────────
@pytest.mark.vitrine
def test_un_avoir_est_deduit_et_un_doublon_compte_une_fois(entrepot):
    rows = _q(entrepot, "SELECT piece_no, ttc, est_avoir FROM sales ORDER BY piece_no")
    assert rows == [("AV-001", -119.0, True), ("FV-001", 1190.0, False), ("FV-002", 2380.0, False)]
    assert _q(entrepot, "SELECT sum(ttc) FROM sales")[0][0] == pytest.approx(3451.0)


def test_les_libelles_de_reglement_sont_regroupes(entrepot):
    modes = {r[0] for r in _q(entrepot, "SELECT mode_regl FROM sales")}
    assert modes == {"Virement 60 JOURS"}          # « virement 60 jours » regroupé


def test_nom_du_client_et_repli_sur_le_code(entrepot):
    noms = dict(_q(entrepot, "SELECT client, any_value(client_name) FROM sales GROUP BY 1"))
    assert noms == {"CP001": "HOPITAL MILITAIRE", "CP999": "CP999"}


def test_lignes_dedoublonnees_et_lignes_decalees_rejetees(entrepot):
    assert _q(entrepot, "SELECT count(*) FROM sales_lines WHERE reference = 'R1' "
                        "AND montant > 0")[0][0] == 1
    assert _q(entrepot, "SELECT mouv_id FROM sales_lines_rejetees") == [(15,)]
    assert _q(entrepot, "SELECT count(*) FROM sales_lines WHERE mouv_id = 15")[0][0] == 0


def test_la_marge_ecarte_les_couts_aberrants_et_garde_les_retours(entrepot):
    ca, cout = _q(entrepot, "SELECT sum(ca_ligne), sum(cout_revient) FROM client_margin "
                            "WHERE client = 'CP001'")[0]
    assert ca == pytest.approx(600.0 - 100.0)       # R2 (coût 12x) écartée, retour gardé
    assert cout == pytest.approx(300.0 - 50.0)
    assert _q(entrepot, "SELECT lignes_exclues FROM margin_quality")[0][0] == 1


def test_devis_transforme_selon_l_etat_erp(entrepot):
    assert dict(_q(entrepot, "SELECT piece_no, transforme FROM devis")) == {
        "DV-1": True, "DV-2": False}


# ── 3. Modèle en étoile ─────────────────────────────────────────────────────
def test_dimensions_conformes_et_membres_deduits(entrepot):
    clients = dict(_q(entrepot, "SELECT client_code, origine FROM dim_client"))
    assert clients == {"CP001": "erp", "CP002": "erp", "CP999": "deduit", "CP003": "deduit"}
    fournisseurs = dict(_q(entrepot, "SELECT fournisseur_code, origine FROM dim_fournisseur"))
    assert fournisseurs == {"F1": "erp", "F9": "deduit"}
    assert _q(entrepot, "SELECT pays FROM dim_fournisseur WHERE fournisseur_code = 'F1'") == [(None,)]
    depots = dict(_q(entrepot, "SELECT depot_code, origine FROM dim_depot"))
    assert depots == {"DP": "erp", "XX": "deduit"}


@pytest.mark.vitrine
def test_aucun_fait_orphelin_de_sa_dimension(entrepot):
    controles = _q(entrepot, "SELECT controle, valeur, statut FROM etl_controles")
    integrite = [c for c in controles if c[0].startswith("integrite:")]
    unicite = [c for c in controles if c[0].startswith("unicite:")]
    assert len(integrite) == len(qualite.REFERENCES) and all(v == 0 for _, v, _ in integrite)
    assert len(unicite) == len(qualite.CLES) and all(v == 0 for _, v, _ in unicite)
    assert not [c for c in controles if c[2] == "erreur"]


def test_calendrier_continu_sans_date_de_remplissage(entrepot):
    debut, fin, n = _q(entrepot, "SELECT min(date), max(date), count(*) FROM dim_date")[0]
    assert str(debut) == "2024-01-02" and str(fin) == "2024-03-01"
    assert n == (fin - debut).days + 1                 # aucun jour manquant
    alertes = dict(_q(entrepot, "SELECT controle, valeur FROM etl_controles "
                                "WHERE statut = 'alerte'"))
    assert alertes["calendrier:fait_ligne_achat.date"] == 1       # le 1/1/1900


# ── 4. Sûreté de la construction ────────────────────────────────────────────
def test_la_reconstruction_preserve_les_donnees_de_l_application(entrepot, sources):
    con = duckdb.connect(str(entrepot))
    con.execute("CREATE TABLE factures_importees (client_code VARCHAR, client_name VARCHAR, "
                "sens VARCHAR)")
    con.execute("INSERT INTO factures_importees VALUES ('OCR-0001', 'LABO NOUVEAU', 'vente')")
    con.execute("CREATE TABLE retours_taches (id INTEGER)")
    con.execute("INSERT INTO retours_taches VALUES (7)")
    con.close()

    etl.construire(entrepot, sources, rapport=None)

    assert _q(entrepot, "SELECT id FROM retours_taches") == [(7,)]
    assert _q(entrepot, "SELECT client_name, origine FROM dim_client "
                        "WHERE client_code = 'OCR-0001'") == [("LABO NOUVEAU", "ocr")]


def test_un_client_cree_par_l_application_prend_l_origine_par_defaut(entrepot):
    con = duckdb.connect(str(entrepot))
    con.execute("INSERT INTO dim_client (client_code, client_name) VALUES ('OCR-0002', 'X')")
    con.close()
    assert _q(entrepot, "SELECT origine FROM dim_client WHERE client_code = 'OCR-0002'") == [
        ("application",)]


def test_un_controle_en_echec_annule_toute_la_construction(entrepot, sources, monkeypatch):
    avant = _q(entrepot, "SELECT signature, construit_le FROM etl_execution")
    monkeypatch.setattr(qualite, "controler", lambda con: [
        {"controle": "unicite:dim_client.client_code", "niveau": "erreur", "valeur": 2.0,
         "statut": "erreur", "description": "test"}])
    (sources / SOURCES["ventes_entetes"].fichier).write_text(
        "ENT_ID,PIECENOFULL,TIERS,DATEPIECE,DATEECHEANCE,MONTANTSIGNE_DEV,HT_DEV,TTC_DEV,"
        "MODEREGLLIBELLE,NBREARTICLE,DEPOT\n9,FV-9,CP001,1/1/2024,,1,1,1,,1,DP\n",
        encoding="utf-8")
    with pytest.raises(RuntimeError, match="contrôles"):
        etl.construire(entrepot, sources, rapport=None)
    assert _q(entrepot, "SELECT signature, construit_le FROM etl_execution") == avant
    assert _q(entrepot, "SELECT count(*) FROM sales")[0][0] == 3     # l'ancien entrepôt


def test_reconstruction_seulement_si_une_source_change(entrepot, sources):
    assert etl.signature_construite(entrepot) == etl.signature(sources)
    marque = _q(entrepot, "SELECT construit_le FROM etl_execution")
    etl.assurer_a_jour(entrepot, sources)
    assert _q(entrepot, "SELECT construit_le FROM etl_execution") == marque
    p = sources / SOURCES["devis"].fichier
    p.write_text(p.read_text(encoding="utf-8") + "3,DV-3,CP001,1/4/2024,10,10,11.9,A,1\n",
                 encoding="utf-8")
    etl.assurer_a_jour(entrepot, sources)
    assert _q(entrepot, "SELECT count(*) FROM devis")[0][0] == 3


def test_un_entrepot_d_avant_la_refonte_est_migre(tmp_path, sources):
    """Les anciens noms étaient des TABLES : ils deviennent des vues."""
    chemin = tmp_path / "ancien.duckdb"
    con = duckdb.connect(str(chemin))
    con.execute("CREATE TABLE sales (x INTEGER)")
    con.execute("CREATE TABLE mode_map (norm VARCHAR, label VARCHAR)")
    con.execute("CREATE TABLE _build_info (signature VARCHAR)")
    con.close()
    etl.construire(chemin, sources, rapport=None)
    types = dict(_q(chemin, "SELECT table_name, table_type FROM information_schema.tables"))
    assert types["sales"] == "VIEW"
    assert "mode_map" not in types and "_build_info" not in types
