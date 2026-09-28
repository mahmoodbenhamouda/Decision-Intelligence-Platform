"""
tests/test_segmentation.py
===========================
Tests de la segmentation client.

Ce qui est vérifié ici n'est pas la qualité du clustering — elle dépend des
données et se mesure, elle ne se teste pas. Ce sont les propriétés sans
lesquelles une segmentation, même statistiquement bonne, devient inexploitable :

  * des noms UNIQUES — deux segments homonymes ne désignent plus rien ;
  * des noms DÉRIVÉS des mesures, jamais écrits en dur, sans quoi ils
    deviendraient faux au premier réentraînement sans que rien ne le signale ;
  * un refus de servir quand la séparation ou la stabilité manquent.

Le premier point vient d'un défaut constaté : la première version produisait
trois segments nommés « Petits comptes occasionnels — en sommeil ».

    python -m pytest tests/test_segmentation.py -v
"""

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
    """Cinq profils dont DEUX partagent forcément la même base de nom.

    La première version de ces tests n'en fournissait que deux, et ne testait
    donc rien : les qualificatifs sont attribués par RANG entre segments, et avec
    deux segments les rangs valent nécessairement 0 et 1 sur chaque axe. Aucune
    collision n'était possible, et les tests passaient — ou échouaient — pour de
    mauvaises raisons.

    Il faut cinq segments pour que deux d'entre eux tombent dans la même tranche
    de chiffre d'affaires ET la même tranche de régularité. C'est la construction
    ci-dessous : les deux derniers sont tous deux « Petits comptes occasionnels ».
    """
    return [
        # r_ca 1,00 · r_reg 1,00 -> Comptes stratégiques réguliers
        _profil_defaut(ca=5_000_000, reg=0.90, rec=20, n=60, panier=40_000, fam=30),
        # r_ca 0,75 · r_reg 0,50 -> Comptes stratégiques actifs
        _profil_defaut(ca=2_000_000, reg=0.50, rec=40, n=30, panier=20_000, fam=20),
        # r_ca 0,50 · r_reg 0,75 -> Comptes intermédiaires réguliers
        _profil_defaut(ca=900_000, reg=0.70, rec=60, n=25, panier=12_000, fam=15),
        # r_ca 0,25 · r_reg 0,25 -> Petits comptes occasionnels  <- collision
        _profil_defaut(ca=40_000, reg=0.10, rec=30, n=3, panier=1_200, fam=3),
        # r_ca 0,00 · r_reg 0,00 -> Petits comptes occasionnels  <- collision
        _profil_defaut(ca=25_000, reg=0.05, rec=400, n=2, panier=900, fam=2),
    ]


def test_le_nommage_ne_depend_pas_de_l_ordre_des_clusters():
    """Permuter les identifiants de cluster ne doit RIEN changer aux noms.

    Défaut observé en production, et visible par l'utilisateur : deux segments
    partageant la base « Petits comptes occasionnels » étaient nommés selon leur
    ordre d'arrivée — le premier gardait le nom nu, le second héritait du suffixe
    « — en sommeil ». Or KMeans numérote ses groupes dans l'ordre où ses
    centroïdes convergent, ordre qui varie au dernier bit d'une exécution à
    l'autre. Le suffixe changeait donc de segment, et le tableau de bord renommait
    des segments sans qu'aucune donnée ait bougé.
    """
    profils = _profils_en_collision()

    noms_directs = [d["nom"] for d in seg._nommer_tous(profils)]

    # Même contenu, ordre inversé : les noms doivent suivre les profils.
    inverses = seg._nommer_tous(list(reversed(profils)))
    noms_inverses = list(reversed([d["nom"] for d in inverses]))

    assert noms_directs == noms_inverses, (
        "le nommage dépend de l'ordre des clusters : "
        f"{noms_directs} vs {noms_inverses}")
    assert len(set(noms_directs)) == len(noms_directs), (
        f"noms en double : {noms_directs}")


def test_dans_une_collision_aucun_segment_ne_garde_le_nom_nu():
    """Les deux homonymes doivent être qualifiés — et eux seuls.

    Laisser le nom nu à l'un d'eux recrée la question « lequel est le premier ? »,
    dont la réponse dépendait d'un étiquetage arbitraire. La supprimer valait
    mieux que la stabiliser.

    Symétriquement, un segment SANS homonyme ne doit pas être décoré : un suffixe
    inutile alourdit l'interface sans rien distinguer.
    """
    noms = [d["nom"] for d in seg._nommer_tous(_profils_en_collision())]

    assert len(set(noms)) == 5, f"noms en double : {noms}"

    # Les trois premiers sont uniques : aucun qualificatif de départage.
    for n in noms[:3]:
        assert "—" not in n, f"segment sans homonyme inutilement décoré : {n}"

    # Les deux derniers sont en collision : tous deux qualifiés.
    assert all("—" in n for n in noms[3:]), (
        f"un segment en collision garde son nom nu : {noms[3:]}")

    # Et le départage suit la RÉCENCE, la lecture métier : celui qui commande
    # encore contre celui qui s'est arrêté. Jamais un numéro de cluster.
    assert "encore actifs" in noms[3], f"récence mal attribuée : {noms[3:]}"
    assert "en sommeil" in noms[4], f"récence mal attribuée : {noms[3:]}"


def _profil(ca: float, reg: float, rec: float,
            n: int = 10, panier: float = 1000.0, fam: int = 5) -> pd.Series:
    return pd.Series({
        "ca_total": ca, "regularite": reg, "recence_j": rec,
        "n_factures": n, "panier": panier, "n_familles": fam,
    })


# ── Unicité des noms ────────────────────────────────────────────────────────
def test_les_noms_de_segments_sont_uniques():
    """Deux segments homonymes sont indiscernables dans l'interface.

    Cas réel : la première version comparait chaque segment à la médiane
    GLOBALE de la clientèle. Celle-ci étant tirée par le segment majoritaire
    (605 clients sur 938), trois segments distincts recevaient le même nom.
    """
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
    """Le nommage se fait par RANG entre segments, pas par seuil absolu.

    C'est la seconde faute de la première version : un segment pesant 10 % du
    chiffre d'affaires était qualifié de « petits comptes » parce qu'il tombait
    sous une médiane écrasée par le segment majoritaire.
    """
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
        _profil(500_000, 0.90, 15),      # très régulier
        _profil(500_000, 0.05, 15),      # très occasionnel
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


# ── Seuils d'acceptation ────────────────────────────────────────────────────
def test_les_seuils_sont_declares_avant_la_mesure():
    """Un seuil ajusté après coup ne prouve rien."""
    assert 0 < seg.SILHOUETTE_MIN < 1
    assert 0 < seg.STABILITE_MIN < 1
    # Une segmentation instable est plus dangereuse qu'une absence de
    # segmentation : elle affiche des noms rassurants sur des groupes fortuits.
    assert seg.STABILITE_MIN >= 0.5


def test_le_nombre_de_segments_reste_pilotable():
    """Au-delà de six segments, une politique commerciale par segment n'existe plus."""
    assert seg.K_MIN >= 2
    assert seg.K_MAX <= 8


# ── Cohérence du module entraîné ────────────────────────────────────────────
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
