"""
ml_engine/stock/positions_historiques.py
=========================================
Position de stock RÉELLE, mois par mois — le socle qui rend un modèle possible.

Ce que ce module débloque
-------------------------
`flux_reels.py` calcule une position **finale** : une photo, un chiffre par
référence. C'est suffisant pour constater un surstock, et insuffisant pour
apprendre quoi que ce soit — un modèle supervisé a besoin d'un historique
d'états, pas d'un état.

Or le même calcul fonctionne **à chaque date de coupure** :

    position(référence, fin du mois m) = Σ entrées ≤ m − Σ sorties ≤ m

On obtient une série temporelle de positions par référence, entièrement issue des
factures. Les deux modèles de risque produit existants (`ml_engine/models/`)
apprenaient leurs variables de position sur le module **simulé** ; ce module leur
donne enfin un substrat réel, et rend mesurable une question qui ne l'était pas.

La limite est héritée, pas ajoutée
----------------------------------
C'est toujours une **variation cumulée**, non un inventaire : le stock antérieur
à la première facture connue reste inconnu, et le décalage constant qui en
résulte affecte chaque mois de la même manière. Conséquence à assumer : une
position négative ne signifie pas un stock négatif.

Ce décalage est constant par référence. Il est donc **inoffensif pour tout ce qui
raisonne en variation** — tendance, accélération, rythme d'achat — et
**trompeur pour tout ce qui raisonne en niveau absolu**. Cette distinction
gouverne le choix des variables du modèle de réapprovisionnement, et elle est
rappelée là où chacune est construite.

Sortie : table `stock_position_mensuelle` + `reports/positions_metrics.json`

Lancement :
    python -m ml_engine.stock.positions_historiques
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE / "reports"

# Une référence n'entre dans le panneau que si elle a été à la fois achetée et
# vendue. Sans les deux flux, la position n'a aucun sens : une référence jamais
# achetée donnerait une position négative pure, une référence jamais vendue une
# accumulation sans consommation. Ni l'une ni l'autre n'est modélisable.
MIN_MOIS_HISTORIQUE = 6


def _connect():
    from ml_engine.analytics.kpi_engine import STORE_PATH
    import duckdb
    return duckdb.connect(str(STORE_PATH))


def construire(con=None) -> Dict[str, Any]:
    """Matérialise `stock_position_mensuelle`.

    Dépend de `stock_flux_reel`, qui fournit la liste des références rapprochées
    et la valeur d'`INDICMVTSTOCK` retenue. Refuser de s'exécuter sans elle est
    volontaire : recalculer ici la sémantique du champ ERP créerait deux sources
    de vérité pour une même décision empirique.
    """
    fermer = con is None
    con = con or _connect()
    try:
        from ml_engine.stock.flux_reels import LIGNES_ACHAT, _lignes_achat_chargees
        if not _lignes_achat_chargees(con):
            return {"error": f"table {LIGNES_ACHAT} absente ou vide — lancer python -m etl.construire"}

        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "stock_flux_reel" not in tables:
            return {"error": ("table stock_flux_reel absente — lancer d'abord "
                              "python -m ml_engine.stock.flux_reels")}

        from ml_engine.stock.flux_reels import identifier_valeur_mouvement
        val_mvt = identifier_valeur_mouvement(con)["valeur_retenue"]
        if val_mvt is None:
            return {"error": "valeur de mouvement de stock non identifiable"}

        # ── Entrées mensuelles ──────────────────────────────────────────────
        con.execute(f"""
            CREATE OR REPLACE TABLE achats_mensuels AS
            SELECT
                upper(designation)                        AS cle,
                CAST(date_trunc('month', date) AS DATE)   AS mois,
                sum(qte)                                  AS qte_entree,
                sum(montant)                              AS montant_entree,
                count(*)                                  AS n_lignes_achat
            FROM {LIGNES_ACHAT}
            WHERE designation <> ''
              AND indic_mvt_stock = '{val_mvt}'
              AND qte IS NOT NULL
              AND date IS NOT NULL
            GROUP BY 1, 2
        """)

        # ── Sorties mensuelles ──────────────────────────────────────────────
        con.execute("""
            CREATE OR REPLACE TABLE ventes_mensuelles AS
            SELECT
                upper(trim(designation))                 AS cle,
                CAST(date_trunc('month', date) AS DATE)   AS mois,
                sum(qte)                                  AS qte_sortie,
                sum(montant)                              AS montant_sortie,
                count(*)                                  AS n_lignes_vente
            FROM sales_lines
            WHERE designation IS NOT NULL AND trim(designation) <> ''
              AND qte > 0 AND date IS NOT NULL
            GROUP BY 1, 2
        """)

        # ── Grille référence × mois ─────────────────────────────────────────
        #
        # Le produit cartésien est indispensable : un mois SANS mouvement est une
        # information — la position ne bouge pas, la couverture se consomme. Ne
        # garder que les mois mouvementés donnerait une série à trous où « rien
        # ne s'est passé » deviendrait invisible.
        con.execute("""
            CREATE OR REPLACE TABLE stock_position_mensuelle AS
            WITH refs AS (
                SELECT cle, any_value(produit) AS produit,
                       any_value(cout_unitaire) AS cout_unitaire
                FROM stock_flux_reel
                WHERE rapproche AND NOT est_service
                GROUP BY cle
            ),
            bornes AS (
                SELECT min(mois) AS m0, max(mois) AS m1
                FROM (SELECT mois FROM achats_mensuels
                      UNION ALL
                      SELECT mois FROM ventes_mensuelles)
            ),
            cal AS (
                SELECT CAST(unnest(generate_series(
                           CAST(m0 AS TIMESTAMP), CAST(m1 AS TIMESTAMP),
                           INTERVAL 1 MONTH)) AS DATE) AS mois
                FROM bornes
            ),
            grille AS (
                SELECT r.cle, r.produit, r.cout_unitaire, c.mois
                FROM refs r CROSS JOIN cal c
            ),
            jointe AS (
                SELECT
                    g.cle, g.produit, g.cout_unitaire, g.mois,
                    COALESCE(a.qte_entree, 0)      AS entrees,
                    COALESCE(v.qte_sortie, 0)      AS sorties,
                    COALESCE(a.montant_entree, 0)  AS montant_entree,
                    COALESCE(v.montant_sortie, 0)  AS montant_sortie
                FROM grille g
                LEFT JOIN achats_mensuels   a ON a.cle = g.cle AND a.mois = g.mois
                LEFT JOIN ventes_mensuelles v ON v.cle = g.cle AND v.mois = g.mois
            ),
            cumul AS (
                -- Chaque fenêtre est écrite en entier plutôt que partagée par une
                -- clause WINDOW : `row_number()` n'accepte pas de cadre `ROWS`,
                -- et les cumuls en exigent un explicite pour ne pas dépendre du
                -- comportement par défaut sur les ex æquo.
                SELECT *,
                    sum(entrees) OVER (PARTITION BY cle ORDER BY mois
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                        AS entrees_cumul,
                    sum(sorties) OVER (PARTITION BY cle ORDER BY mois
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                        AS sorties_cumul,
                    sum(entrees - sorties) OVER (PARTITION BY cle ORDER BY mois
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
                        AS position_fin,
                    -- Rang du mois dans l'historique de la référence : sert à
                    -- écarter les premiers mois, où aucune moyenne glissante
                    -- n'a de sens.
                    row_number() OVER (PARTITION BY cle ORDER BY mois)
                        AS rang_mois
                FROM jointe
            )
            SELECT * FROM cumul
            -- Avant le premier achat, la « position » ne serait qu'une dette
            -- cumulée de ventes servies depuis un stock antérieur inconnu.
            WHERE entrees_cumul > 0
        """)

        g = con.execute("""
            SELECT count(*), count(DISTINCT cle),
                   min(mois), max(mois),
                   count(*) FILTER (WHERE position_fin > 0),
                   count(*) FILTER (WHERE entrees > 0)
            FROM stock_position_mensuelle
        """).fetchone()
        n_lignes, n_refs, m0, m1, n_pos, n_mois_achat = g

        if not n_lignes:
            return {"error": "aucune ligne produite — vérifier sales_lines"}

        # Combien de références disposent d'un historique exploitable ? C'est ce
        # nombre, et non le total, qui borne la taille du panneau d'apprentissage.
        n_exploitables = con.execute(f"""
            SELECT count(*) FROM (
                SELECT cle FROM stock_position_mensuelle
                GROUP BY cle HAVING count(*) >= {MIN_MOIS_HISTORIQUE}
            )
        """).fetchone()[0]

        metriques = {
            "version": 1,
            "nature": "positions mensuelles reconstruites — AUCUNE simulation",
            "n_lignes": int(n_lignes or 0),
            "n_references": int(n_refs or 0),
            "n_references_exploitables": int(n_exploitables or 0),
            "min_mois_historique_exige": MIN_MOIS_HISTORIQUE,
            "periode": f"{m0} → {m1}",
            "n_mois_position_positive": int(n_pos or 0),
            "part_mois_position_positive_pct": round(
                float(n_pos or 0) / float(n_lignes or 1) * 100, 1),
            "n_mois_avec_achat": int(n_mois_achat or 0),
            "taux_de_base_achat_mensuel_pct": round(
                float(n_mois_achat or 0) / float(n_lignes or 1) * 100, 1),
            "portee": (
                "Position = entrées cumulées − sorties cumulées à la fin de "
                "chaque mois. Variation cumulée et non inventaire : le stock "
                "antérieur à l'historique reste inconnu. Le décalage est "
                "CONSTANT par référence, donc inoffensif pour les variables de "
                "variation (tendance, rythme d'achat) et trompeur pour les "
                "variables de niveau absolu."),
            "usage": (
                "Socle du modèle de réapprovisionnement "
                "(ml_engine/stock/reappro_model.py). Rend possible un protocole "
                "hors période sur données réelles, ce que la position finale "
                "seule ne permettait pas."),
        }

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        json.dump(metriques, open(REPORTS_DIR / "positions_metrics.json", "w",
                                  encoding="utf-8"), indent=2, ensure_ascii=False)
        return metriques
    finally:
        if fermer:
            con.close()


def charger_panel(con=None):
    """Panneau (référence × mois) prêt pour l'apprentissage, sous forme DataFrame."""
    import pandas as pd

    fermer = con is None
    con = con or _connect()
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "stock_position_mensuelle" not in tables:
            return pd.DataFrame()
        return con.execute("""
            SELECT cle, produit, cout_unitaire, mois,
                   entrees, sorties, montant_entree, montant_sortie,
                   entrees_cumul, sorties_cumul, position_fin, rang_mois
            FROM stock_position_mensuelle
            ORDER BY cle, mois
        """).df()
    finally:
        if fermer:
            con.close()


def afficher() -> None:
    m = construire()
    if m.get("error"):
        print(f"\nErreur : {m['error']}\n")
        return

    print("\n" + "=" * 78)
    print("  POSITIONS MENSUELLES — reconstruites des factures")
    print("=" * 78)
    print(f"\n  Période                        : {m['periode']}")
    print(f"  Références suivies              : {m['n_references']:,}".replace(",", " "))
    print(f"  Références exploitables (≥ {m['min_mois_historique_exige']} mois) : "
          f"{m['n_references_exploitables']:,}".replace(",", " "))
    print(f"  Observations référence × mois   : {m['n_lignes']:,}".replace(",", " "))
    print(f"\n  Mois à position positive       : {m['part_mois_position_positive_pct']} %")
    print(f"  Mois comportant un achat       : {m['taux_de_base_achat_mensuel_pct']} %")
    print("\n  Ce dernier taux est le TAUX DE BASE du modèle de")
    print("  réapprovisionnement : toute performance doit se juger contre lui.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
