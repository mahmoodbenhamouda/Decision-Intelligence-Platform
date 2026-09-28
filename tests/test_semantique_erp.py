"""
tests/test_semantique_erp.py
=============================
Prouve, sur les donnees reelles, ce que chaque colonne de l'ERP SIGNIFIE.

Pourquoi ces tests existent
---------------------------
Le CA a ete faux de 5,44 % parce qu'on croyait savoir ce que contenait
`TTC_DEV`. Personne n'avait verifie que le signe comptable etait ailleurs, dans
`MONTANTSIGNE_DEV`. L'erreur n'etait pas de calcul : elle etait d'INTERPRETATION.

Aucun invariant comptable ne pouvait la detecter, parce que le calcul etait
coherent avec lui-meme. Ce qui l'a revelee, c'est d'avoir relu le fichier
colonne par colonne.

Ces tests figent cette relecture. Chaque hypothese sur laquelle repose l'ETL est
ecrite, puis VERIFIEE contre les donnees. Si un export futur change de
semantique -- meme sans changer de structure -- ils echouent.

    python -m pytest tests/test_semantique_erp.py -v

Le detail des conclusions est dans docs/SEMANTIQUE_COLONNES.md.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etl.sources import chemin, lecture  # noqa: E402

pytestmark = pytest.mark.skipif(
    not chemin("ventes_entetes").exists(), reason="CSV source absent")

#: Ces tests vérifient le SENS des colonnes brutes de l'ERP : ils lisent donc
#: la source elle-même, par le catalogue de l'ETL.
ROLES = {"sales": "ventes_entetes", "lines": "ventes_lignes", "devis": "devis"}


def lire(nom: str) -> str:
    return lecture(ROLES[nom])


@pytest.fixture(scope="module")
def con():
    import duckdb
    c = duckdb.connect()
    yield c
    c.close()


NUM = "TRY_CAST({} AS DOUBLE)"


# ── MONTANTSIGNE_DEV : le porteur du sens comptable ────────────────────────
def test_montantsigne_est_le_seul_a_porter_un_signe(con):
    """HYPOTHESE CENTRALE DE TOUT L'ETL.

    `TTC_DEV` et `HT_DEV` sont des VALEURS ABSOLUES : ils ne descendent jamais
    sous zero, meme pour un avoir. Seul `MONTANTSIGNE_DEV` porte le sens.
    C'est precisement ce que l'ETL ignorait.
    """
    v = lire("sales")
    neg_ttc, neg_ht, neg_sig = con.execute(f"""
        SELECT count(*) FILTER (WHERE {NUM.format('TTC_DEV')} < 0),
               count(*) FILTER (WHERE {NUM.format('HT_DEV')}  < 0),
               count(*) FILTER (WHERE {NUM.format('MONTANTSIGNE_DEV')} < 0)
        FROM {v}
    """).fetchone()
    assert neg_ttc == 0, (
        f"{neg_ttc} TTC négatifs : `TTC_DEV` n'est plus une valeur absolue, "
        "l'hypothèse de l'ETL ne tient plus")
    assert neg_ht == 0, f"{neg_ht} HT négatifs — même conclusion"
    assert neg_sig > 0, (
        "aucun `MONTANTSIGNE_DEV` négatif : soit il n'y a plus d'avoirs, soit "
        "cette colonne ne porte plus le signe comptable")


def test_montantsigne_vaut_le_ht_au_signe_pres(con):
    """`MONTANTSIGNE_DEV` est un HT signe, pas un TTC signe. C'est pourquoi le
    CA corrige se calcule en appliquant SON SIGNE au TTC, et non en le sommant
    directement."""
    v = lire("sales")
    n_ht, n_ttc = con.execute(f"""
        SELECT count(*) FILTER (WHERE abs(abs({NUM.format('MONTANTSIGNE_DEV')})
                                        - {NUM.format('HT_DEV')}) < 0.01),
               count(*) FILTER (WHERE abs(abs({NUM.format('MONTANTSIGNE_DEV')})
                                        - {NUM.format('TTC_DEV')}) < 0.01)
        FROM {v} WHERE {NUM.format('MONTANTSIGNE_DEV')} IS NOT NULL
    """).fetchone()
    assert n_ht > n_ttc, (
        "`MONTANTSIGNE_DEV` colle au TTC plutôt qu'au HT : l'interprétation "
        "retenue par l'ETL est à revoir")


# ── PIECENOFULL vs ENT_ID : cle metier contre identifiant technique ─────────
def test_ent_id_est_unique_donc_aveugle_aux_doublons(con):
    """`ENT_ID` est un identifiant d'export : unique PAR CONSTRUCTION. Verifier
    l'unicite sur cette colonne ne peut donc JAMAIS reveler un doublon. C'est
    l'erreur qui a laisse passer 1 324 factures en double."""
    v = lire("sales")
    n, distincts = con.execute(
        f"SELECT count(*), count(DISTINCT ENT_ID) FROM {v}").fetchone()
    assert n == distincts, (
        "`ENT_ID` n'est plus unique — la nature de cette colonne a changé")


def test_piecenofull_est_la_vraie_cle_metier(con):
    """Le numero de facture, lui, se repete : c'est la cle a controler."""
    v = lire("sales")
    n, distincts = con.execute(f"""
        SELECT count(*), count(DISTINCT trim(PIECENOFULL))
        FROM {v} WHERE trim(PIECENOFULL) <> ''
    """).fetchone()
    assert distincts < n, (
        "`PIECENOFULL` est devenu unique : soit les doublons ont disparu de la "
        "source, soit cette colonne a changé de rôle")


# ── SENS : le sens de mouvement des lignes ─────────────────────────────────
def test_sens_ne_prend_que_deux_valeurs_metier(con):
    """`SENS` vaut 1 (retour) ou 2 (vente). Toute autre valeur signale un
    DECALAGE DE COLONNES -- une virgule non echappee dans un champ texte."""
    v = lire("lines")
    rows = con.execute(
        f"SELECT trim(SENS) s, count(*) FROM {v} GROUP BY 1").fetchall()
    hors = {s: n for s, n in rows if s not in ("1", "2") and s}
    total = sum(n for _, n in rows)
    n_hors = sum(hors.values())
    # Tolerance : quelques lignes corrompues sont connues et ecartees par l'ETL.
    assert n_hors / total < 0.001, (
        f"{n_hors} lignes au `SENS` invalide ({hors}) — au-delà du bruit connu, "
        "le fichier a un problème de parsing plus large")


def test_sens_concorde_avec_le_signe_du_montant(con):
    """Deux colonnes independantes decrivent le meme fait : un retour doit
    porter `SENS = 1` ET un montant negatif. Leur concordance valide les deux."""
    v = lire("lines")
    sens1, negatifs, accord = con.execute(f"""
        SELECT count(*) FILTER (WHERE trim(SENS) = '1'),
               count(*) FILTER (WHERE {NUM.format('MONTANTSIGNE_DEV')} < 0),
               count(*) FILTER (WHERE trim(SENS) = '1'
                                  AND {NUM.format('MONTANTSIGNE_DEV')} < 0)
        FROM {v}
    """).fetchone()
    assert sens1 > 0 and negatifs > 0
    # L'ecart connu (quelques dizaines de lignes) correspond a des retours a
    # montant nul : le sens est 1, le montant n'est pas strictement negatif.
    concordance = accord / max(sens1, negatifs)
    assert concordance > 0.97, (
        f"`SENS` et le signe du montant ne concordent qu'à {concordance:.1%} — "
        "l'une des deux colonnes ne signifie plus ce qu'on croit")


# ── MTCRSIGNE : le cout de revient ─────────────────────────────────────────
def test_le_cout_de_revient_suit_le_signe_de_la_vente(con):
    """`MTCRSIGNE` est SIGNE comme le montant : sur un retour, le cout revient
    en stock, donc en negatif. C'est ce qui permet a la marge de se compenser
    correctement."""
    v = lire("lines")
    accord, total = con.execute(f"""
        SELECT count(*) FILTER (
                 WHERE sign({NUM.format('MTCRSIGNE')})
                     = sign({NUM.format('MONTANTSIGNE_DEV')})),
               count(*)
        FROM {v}
        WHERE {NUM.format('MTCRSIGNE')} <> 0
          AND {NUM.format('MONTANTSIGNE_DEV')} <> 0
    """).fetchone()
    assert accord / total > 0.95, (
        f"le coût de revient ne suit le signe de la vente que dans "
        f"{accord / total:.1%} des cas — la marge des retours serait fausse")


# ── Colonnes vides : ce que l'ERP N'a PAS ──────────────────────────────────
def test_les_colonnes_de_paiement_sont_bien_vides(con):
    """Limite fondamentale du projet, a affirmer sans ambiguite : l'ERP ne
    contient AUCUNE date de paiement reelle. Tout indicateur de « retard » est
    donc un proxy du delai ACCORDE, jamais un retard CONSTATE.

    Si un futur export alimentait ces colonnes, ce test echouerait -- et ce
    serait une excellente nouvelle : les vrais retards deviendraient calculables.
    """
    v = lire("sales")
    # On INTERROGE le schéma au lieu de supposer que telle colonne existe.
    # `REG` et `REGTYP` sont en réalité ABSENTES de cet export, ce qui est une
    # affirmation plus forte que « vides » — et que la documentation énonçait
    # imprécisément.
    colonnes = {d[0].upper() for d in con.execute(f"DESCRIBE SELECT * FROM {v}").fetchall()}

    # Aucune colonne ne doit porter une date ou un montant de RÈGLEMENT reçu.
    candidates = {"REG", "REGTYP", "DATEREGLEMENT", "DATEPAIEMENT",
                  "DATEREGL", "MTREGLE_DEV", "MTPAYE_DEV"}
    presentes = candidates & colonnes
    for col in sorted(presentes):
        n = con.execute(
            f"SELECT count(*) FROM {v} WHERE trim(coalesce({col}, '')) <> ''"
        ).fetchone()[0]
        assert n == 0, (
            f"la colonne `{col}` est alimentée sur {n} lignes — le projet peut "
            "enfin calculer de VRAIS retards de paiement (mettre à jour "
            "docs/SEMANTIQUE_COLONNES.md et KPI_FORMULES.md)")

    # `SOLDEACOMPTE_DEV` existe et doit rester à zéro.
    assert "SOLDEACOMPTE_DEV" in colonnes
    n_solde = con.execute(
        f"SELECT count(*) FROM {v} WHERE {NUM.format('SOLDEACOMPTE_DEV')} <> 0"
    ).fetchone()[0]
    assert n_solde == 0, f"{n_solde} lignes ont un solde d'acompte non nul"

    # `ETAT` : constante si présente.
    if "ETAT" in colonnes:
        n_etats = con.execute(
            f"SELECT count(DISTINCT trim(coalesce(ETAT, ''))) FROM {v}").fetchone()[0]
        assert n_etats <= 1, f"`ETAT` prend {n_etats} valeurs : il est désormais alimenté"


# ── ETATPIECE = 8 : le devis transforme ────────────────────────────────────
def test_etat_8_correspond_bien_au_devis_transforme(con):
    """Interpretation VALIDEE empiriquement, pas supposee : un devis en etat 8
    doit avoir une facture du meme client, au meme montant. C'est ce qui autorise
    a lire cet etat comme « transforme »."""
    d, v = lire("devis"), lire("sales")
    taux = con.execute(f"""
        WITH dv AS (
            SELECT trim(TIERS) cli, {NUM.format('TTC_DEV')} m
            FROM {d} WHERE CAST(ETATPIECE AS VARCHAR) = '8'
              AND {NUM.format('TTC_DEV')} > 0
        ),
        fa AS (
            SELECT trim(TIERS) cli, {NUM.format('TTC_DEV')} m
            FROM {v} WHERE {NUM.format('TTC_DEV')} > 0
        )
        SELECT avg(CASE WHEN EXISTS (
                   SELECT 1 FROM fa
                   WHERE fa.cli = dv.cli AND abs(fa.m - dv.m) <= 0.01 * dv.m
               ) THEN 1.0 ELSE 0.0 END)
        FROM dv
    """).fetchone()[0]
    assert taux is not None and taux > 0.75, (
        f"seuls {(taux or 0):.1%} des devis en état 8 ont une facture "
        "correspondante — l'état 8 ne signifie plus « transformé »")
