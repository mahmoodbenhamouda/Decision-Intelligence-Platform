"""Tests de la segmentation client."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from ml_engine.analytics import segmentation as seg  # noqa: E402


def _profil_defaut(ca: float, reg: float, rec: float,
                   n: int = 10, panier: float = 1000.0, fam: int = 5) -> pd.Series:
    return pd.Series({
        "ca_total": ca, "regularite": reg, "recence_j": rec,
        "n_factures": n, "panier": panier, "n_familles": fam,
    })


def _profils_en_collision() -> list:
    """Cinq profils dont DEUX partagent forcément la même base de nom."""
    return [
        _profil_defaut(ca=5_000_000, reg=0.90, rec=20, n=60, panier=40_000, fam=30),
        _profil_defaut(ca=2_000_000, reg=0.50, rec=40, n=30, panier=20_000, fam=20),
        _profil_defaut(ca=900_000, reg=0.70, rec=60, n=25, panier=12_000, fam=15),
        _profil_defaut(ca=40_000, reg=0.10, rec=30, n=3, panier=1_200, fam=3),
        _profil_defaut(ca=25_000, reg=0.05, rec=400, n=2, panier=900, fam=2),
    ]


def test_le_nommage_ne_depend_pas_de_l_ordre_des_clusters():
    """Permuter les identifiants de cluster ne doit RIEN changer aux noms."""
    profils = _profils_en_collision()

    noms_directs = [d["nom"] for d in seg._nommer_tous(profils)]

    inverses = seg._nommer_tous(list(reversed(profils)))
    noms_inverses = list(reversed([d["nom"] for d in inverses]))

    assert noms_directs == noms_inverses, (
        "le nommage dépend de l'ordre des clusters : "
        f"{noms_directs} vs {noms_inverses}")
    assert len(set(noms_directs)) == len(noms_directs), (
        f"noms en double : {noms_directs}")


def test_dans_une_collision_aucun_segment_ne_garde_le_nom_nu():
    """Les deux homonymes doivent être qualifiés — et eux seuls."""
    noms = [d["nom"] for d in seg._nommer_tous(_profils_en_collision())]

    assert len(set(noms)) == 5, f"noms en double : {noms}"

    for n in noms[:3]:
        assert "—" not in n, f"segment sans homonyme inutilement décoré : {n}"

    assert all("—" in n for n in noms[3:]), (
        f"un segment en collision garde son nom nu : {noms[3:]}")

    assert "encore actifs" in noms[3], f"récence mal attribuée : {noms[3:]}"
    assert "en sommeil" in noms[4], f"récence mal attribuée : {noms[3:]}"


def _profil(ca: float, reg: float, rec: float,
            n: int = 10, panier: float = 1000.0, fam: int = 5) -> pd.Series:
    return pd.Series({
        "ca_total": ca, "regularite": reg, "recence_j": rec,
        "n_factures": n, "panier": panier, "n_familles": fam,
    })


def test_les_noms_de_segments_sont_uniques():
    """Deux segments homonymes sont indiscernables dans l'interface."""
    profils = [
        _profil(5_000_000, 0.80, 20),
        _profil(300_000, 0.30, 400),
        _profil(120_000, 0.25, 420),
        _profil(90_000, 0.22, 450),
        _profil(50_000, 0.20, 500),
    ]
    noms = [d["nom"] for d in seg._nommer_tous(profils)]
    assert len(set(noms)) == len(noms), f"noms en double : {noms}"


def test_unicite_tenue_meme_sur_des_segments_presque_identiques():
    """Le cas le plus dur : des profils que rien ne sépare nettement."""
    profils = [_profil(100_000 + i, 0.30, 300 + i) for i in range(5)]
    noms = [d["nom"] for d in seg._nommer_tous(profils)]
    assert len(set(noms)) == len(noms), f"noms en double : {noms}"


def test_le_segment_le_plus_riche_n_est_jamais_dit_petit():
    """Le nommage se fait par RANG entre segments, pas par seuil absolu."""
    profils = [
        _profil(9_000_000, 0.70, 30),
        _profil(200_000, 0.40, 200),
        _profil(80_000, 0.20, 400),
    ]
    noms = [d["nom"] for d in seg._nommer_tous(profils)]
    assert "Petits comptes" not in noms[0], (
        f"le segment le plus riche est nommé « {noms[0]} »")
    assert "stratégiques" in noms[0].lower()


def test_le_nom_reflete_le_rythme_de_commande():
    """Un segment régulier et un segment occasionnel ne portent pas le même nom."""
    profils = [
        _profil(500_000, 0.90, 15),
        _profil(500_000, 0.05, 15),
        _profil(500_000, 0.45, 15),
    ]
    noms = [d["nom"] for d in seg._nommer_tous(profils)]
    assert "réguliers" in noms[0]
    assert "occasionnels" in noms[1]


def test_la_caracterisation_cite_des_valeurs_mesurees():
    """Le texte descriptif doit contenir les chiffres, pas des adjectifs seuls."""
    d = seg._nommer_tous([_profil(500_000, 0.5, 42, n=17, fam=8)])[0]
    c = d["caracterisation"]
    assert "17" in c, "le nombre de commandes doit figurer"
    assert "8" in c, "le nombre de références doit figurer"
    assert "42" in c, "la récence doit figurer"


def test_aucun_nom_ne_contient_de_numero_de_segment():
    """« Segment 3 » n'est pas exploitable par un commercial."""
    profils = [_profil(100_000 * (i + 1), 0.3, 100) for i in range(5)]
    for d in seg._nommer_tous(profils):
        assert not any(m in d["nom"].lower() for m in ("segment", "cluster",
                                                       "groupe 0", "classe")), \
            f"nom technique : {d['nom']}"


def test_les_seuils_sont_declares_avant_la_mesure():
    """Un seuil ajusté après coup ne prouve rien."""
    assert 0 < seg.SILHOUETTE_MIN < 1
    assert 0 < seg.STABILITE_MIN < 1
    assert seg.STABILITE_MIN >= 0.5


def test_le_nombre_de_segments_reste_pilotable():
    """Au-delà de six segments, une politique commerciale par segment n'existe plus."""
    assert seg.K_MIN >= 2
    assert seg.K_MAX <= 8


def _rapport():
    import json
    p = os.path.join(RACINE, "reports", "segmentation_metrics.json")
    if not os.path.exists(p):
        pytest.skip("segmentation non entraînée")
    return json.load(open(p, encoding="utf-8"))


def test_le_rapport_est_coherent_avec_ses_seuils():
    r = _rapport()
    q = r["qualite"]
    attendu = (q["silhouette"] >= seg.SILHOUETTE_MIN
               and q["stabilite_rand_ajuste"] >= seg.STABILITE_MIN)
    assert r["servi"] is attendu, (
        f"servi={r['servi']} alors que silhouette={q['silhouette']} "
        f"et stabilité={q['stabilite_rand_ajuste']}")


def test_les_parts_de_clients_et_de_ca_totalisent_cent():
    r = _rapport()
    assert abs(sum(s["part_clients_pct"] for s in r["segments"]) - 100) < 1.5
    assert abs(sum(s["part_ca_pct"] for s in r["segments"]) - 100) < 1.5


def test_les_noms_du_rapport_sont_uniques():
    """Vérification sur les données RÉELLES, pas seulement synthétiques."""
    r = _rapport()
    noms = [s["nom"] for s in r["segments"]]
    assert len(set(noms)) == len(noms), f"noms en double : {noms}"


def test_chaque_client_appartient_a_un_seul_segment():
    import json
    p = os.path.join(RACINE, "output", "client_segments.json")
    if not os.path.exists(p):
        pytest.skip("segments non générés")
    d = json.load(open(p, encoding="utf-8"))
    assert d, "fichier de segments vide"
    for code, v in d.items():
        assert isinstance(v.get("segment"), int)
        assert v.get("nom_segment"), f"segment sans nom pour {code}"
