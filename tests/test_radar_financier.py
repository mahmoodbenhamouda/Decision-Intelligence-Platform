"""
tests/test_radar_financier.py
=============================
Le radar financier et la typologie des établissements publics.

Pourquoi ces tests existent
---------------------------
La carte « recouvrement public » du radar n'est jamais apparue pendant des
semaines : la liste de mots-clés qu'elle lisait avait été supprimée avec la
veille externe, et l'erreur était avalée en silence. La carte d'échéancier, elle,
affichait « créances publiques : 0 % ». En rétablissant la liste, trois autres
défauts sont apparus : « CHU » ne reconnaissait pas « C.H.U. », « ETAT »
classait public le « LABORATOIRE KETATA », et le montant cumulait neuf ans
d'historique — d'où une part publique de 755 % du mois suivant.

Ces tests fixent la correction :

1. une seule règle « établissement de santé public », identique en Python et
   en SQL, et identique à celle des modèles de demande déjà entraînés ;
2. la carte publique porte sur la MÊME fenêtre que l'exposition récente
   (6 mois d'échéances), donc sa part est un vrai pourcentage ;
3. la phrase de l'échéancier compare des factures comparables.

Tout se passe sur un entrepôt fabriqué dans un dossier temporaire.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import duckdb
import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from ml_engine.typologie import (MOTS_HOPITAL_PUBLIC,  # noqa: E402
                                 condition_sql_hopital_public, est_hopital_public)

PUBLICS = ["C.H.U. HABIB BOURGUIBA", "HOPITAL MILITAIRE DE TUNIS", "Hôpital régional",
           "INSTITUT SALAH AZAIEZ", "CENTRE HOSPITALIER X", "chu test"]
PRIVES = ["LABORATOIRE KETATA AMIRA", "CLINIQUE EL AMEN", "PHARMACIE CENTRALE DU SUD",
          "LABO ANALYSES", "SOCIETE ETATIQUE DE NEGOCE", "", None]


# ── 1. Une seule règle ──────────────────────────────────────────────────────
@pytest.mark.parametrize("nom", PUBLICS)
def test_un_etablissement_public_est_reconnu(nom):
    assert est_hopital_public(nom)


@pytest.mark.parametrize("nom", PRIVES)
def test_un_etablissement_prive_n_est_pas_classe_public(nom):
    """« KETATA » contient « ETAT » : l'ancienne liste le classait public."""
    assert not est_hopital_public(nom)


def test_python_et_sql_rendent_le_meme_verdict():
    noms = PUBLICS + PRIVES
    con = duckdb.connect()
    con.execute("CREATE TABLE t (client_name VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [[n] for n in noms])
    rows = con.execute(
        f"SELECT client_name, coalesce({condition_sql_hopital_public()}, false) FROM t").fetchall()
    assert {r[0]: bool(r[1]) for r in rows} == {n: est_hopital_public(n) for n in noms}


def test_les_modeles_de_demande_gardent_leur_typologie():
    """Les deux modèles de demande lisent la règle commune ; leurs variables
    d'entrée ne doivent pas changer (mêmes classes pour les mêmes noms)."""
    from ml_engine.forecasting.demande_reference import classer_etablissement as ref
    from ml_engine.models.demand_features import classer_etablissement as feat

    attendu_feat = {"C.H.U. HABIB BOURGUIBA": "HOPITAL_PUBLIC", "CLINIQUE EL AMEN": "CLINIQUE_PRIVEE",
                    "LABORATOIRE KETATA AMIRA": "LABORATOIRE", "PHARMACIE CENTRALE DU SUD": "PHARMACIE",
                    "SOCIETE ETATIQUE DE NEGOCE": "AUTRE", None: "AUTRE"}
    for nom, classe in attendu_feat.items():
        assert feat(nom) == classe, nom
        # la typologie de la demande par référence n'a pas de classe PHARMACIE
        assert ref(nom) == ("AUTRE" if classe == "PHARMACIE" else classe), nom
    assert MOTS_HOPITAL_PUBLIC[:2] == ("C.H.U", "CHU")


# ── 2. Le radar sur un entrepôt fabriqué ────────────────────────────────────
#: (client, raison sociale, TTC, date, échéance) — le délai accordé en découle.
FACTURES = [
    # dans la fenêtre des 6 derniers mois d'échéances (référence : 2026-06-30)
    ("P1", "C.H.U. HABIB BOURGUIBA", 1000.0, "2026-03-01", "2026-06-30"),   # 121 j
    ("P1", "C.H.U. HABIB BOURGUIBA", 400.0, "2026-04-15", "2026-05-30"),    # 45 j
    ("P2", "HOPITAL MILITAIRE DE TUNIS", 300.0, "2026-02-01", "2026-04-15"),  # 73 j
    ("L1", "LABORATOIRE KETATA AMIRA", 500.0, "2026-02-01", "2026-05-01"),    # 89 j
    ("C1", "CLINIQUE EL AMEN", 200.0, "2026-05-01", "2026-06-20"),          # 50 j
    # hors fenêtre : l'ancien calcul cumulait ces factures-là
    ("P1", "C.H.U. HABIB BOURGUIBA", 9000.0, "2021-01-01", "2021-05-01"),
    ("P2", "HOPITAL MILITAIRE DE TUNIS", 7000.0, "2019-01-01", "2019-06-01"),
]


@pytest.fixture
def entrepot(tmp_path: Path, monkeypatch):
    """Un entrepôt réduit à la vue `sales`, branché à la place du vrai."""
    chemin = tmp_path / "radar.duckdb"
    con = duckdb.connect(str(chemin))
    con.execute("""CREATE TABLE sales (client VARCHAR, client_name VARCHAR, ttc DOUBLE,
                   date DATE, echeance DATE, payment_delay_days INTEGER, est_avoir BOOLEAN,
                   year INTEGER, mode_regl VARCHAR)""")
    con.executemany("""INSERT INTO sales VALUES (?, ?, ?, CAST(? AS DATE), CAST(? AS DATE),
                       datediff('day', CAST(? AS DATE), CAST(? AS DATE)), FALSE,
                       year(CAST(? AS DATE)), 'VIREMENT')""",
                    [[c, n, t, d, e, d, e, d] for c, n, t, d, e in FACTURES])
    con.close()

    from ml_engine.analytics import kpi_engine
    monkeypatch.setattr(kpi_engine, "_connect",
                        lambda data_dir=None: duckdb.connect(str(chemin), read_only=True))
    return chemin


def _sans_echeancier(monkeypatch):
    import ml_engine.registre as registre
    monkeypatch.setattr(registre, "est_deploye", lambda nom: False)


def _carte(cartes, id_):
    trouvees = [c for c in cartes if c["id"] == id_]
    assert trouvees, f"carte {id_} absente : {[c['id'] for c in cartes]}"
    return trouvees[0]


def test_la_carte_publique_porte_sur_l_exposition_recente(entrepot, monkeypatch):
    from ml_engine.analytics.kpi_engine import finance_radar
    _sans_echeancier(monkeypatch)
    c = _carte(finance_radar({}, {}), "recouvrement_public")

    # publics à plus de 60 j dans la fenêtre : 1000 (C.H.U.) + 300 (HMT) ;
    # les 16 000 DT anciens et le laboratoire KETATA n'y entrent pas
    assert c["montant_dt"] == 1300
    # exposition récente totale (> 60 j) : 1000 + 300 + 500 (KETATA) = 1800
    assert re.search(r"soit 72 % de l'exposition récente", c["constat"]), c["constat"]
    assert "sur 2 établissement(s)" in c["constat"]
    assert c["severite"] == "haute"                     # 1000 DT à plus de 90 j
    assert [t["client"] for t in c["top"]] == ["C.H.U. HABIB BOURGUIBA",
                                               "HOPITAL MILITAIRE DE TUNIS"]
    assert "6 mois" not in c["titre"]                   # cf. test_modules_branches


def test_la_carte_publique_suit_le_perimetre_filtre(entrepot, monkeypatch):
    from ml_engine.analytics.kpi_engine import finance_radar
    _sans_echeancier(monkeypatch)
    c = _carte(finance_radar({}, {"selected_clients": ["P2", "L1"]}), "recouvrement_public")
    assert c["montant_dt"] == 300
    assert c["titre"].endswith("(périmètre filtré)")
    assert "soit 38 %" in c["constat"]                  # 300 / (300 + 500)


def test_sans_client_public_la_carte_n_apparait_pas(entrepot, monkeypatch):
    from ml_engine.analytics.kpi_engine import finance_radar
    _sans_echeancier(monkeypatch)
    ids = {c["id"] for c in finance_radar({}, {"selected_clients": ["L1", "C1"]})}
    assert "recouvrement_public" not in ids


def test_la_part_publique_de_l_echeancier_est_un_vrai_pourcentage(entrepot, monkeypatch):
    """La phrase compare ce qui est déjà inscrit au carnet pour le mois suivant
    (factures émises jusqu'à l'origine, échéance au mois cible) : numérateur et
    dénominateur portent sur les mêmes factures."""
    import ml_engine.forecasting.carnet_echeances as carnet
    import ml_engine.registre as registre
    from ml_engine.analytics.kpi_engine import finance_radar

    monkeypatch.setattr(registre, "est_deploye", lambda nom: nom == "echeancier")
    monkeypatch.setattr(carnet, "prevoir", lambda f, o, h, d: (2000.0, "multiplicatif", 0.9))
    c = _carte(finance_radar({}, {}), "echeancier_1m")

    # dernière émission : 2026-05 → origine 2026-04, cible 2026-05.
    # Inscrit pour mai (émis jusqu'en avril) : 400 (C.H.U.) + 500 (KETATA) = 900
    # → part publique 400 / 900 = 44 %
    assert c["constat"].endswith("Les établissements de santé publics en portent "
                                 "44 % de la part déjà inscrite."), c["constat"]


def test_une_erreur_de_la_carte_publique_est_journalisee(entrepot, monkeypatch, caplog):
    """Plus d'erreur avalée en silence : le radar reste servi, le journal le dit."""
    from ml_engine.analytics import kpi_engine
    _sans_echeancier(monkeypatch)
    monkeypatch.setattr(kpi_engine, "condition_sql_hopital_public",
                        lambda col="client_name": "(colonne_inexistante = 1)")
    with caplog.at_level("WARNING"):
        cartes = kpi_engine.finance_radar({}, {})
    assert "recouvrement_public" not in {c["id"] for c in cartes}
    assert "recouvrement public" in caplog.text
