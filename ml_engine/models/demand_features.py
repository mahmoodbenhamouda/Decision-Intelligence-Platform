"""
ml_engine/models/demand_features.py
===================================
CRISP-DM — PHASE 3 : PRÉPARATION DES DONNÉES

Construit le jeu d'apprentissage pour la prévision de demande multi-horizon,
à partir des **lignes de vente réelles** (`ZZ_Facture_vente_mouv.csv`,
340 912 lignes, 2017-01 → 2026-04).

## Granularité retenue et pourquoi

| Option | Observations | Verdict |
|---|---|---|
| client × produit × mois | ~44 000, très creuse (la plupart des couples n'ont que 1-2 achats) | **écartée** : trop peu de signal par série |
| **produit × mois** | 23 088 lignes, 328 produits avec ≥ 24 mois | **retenue** |

La dimension client n'est pas perdue : elle entre comme **features agrégées**
(part du public, nombre de clients actifs, concentration) — l'information est
conservée sans exploser la dispersion.

## Features (toutes anti-fuite : calculées sur le PASSÉ strict)

| Groupe | Variables | Justification métier |
|---|---|---|
| Retards (lags) | `lag_1, lag_2, lag_3, lag_6, lag_12` | l'historique récent porte l'essentiel du signal |
| Tendance | `ma_3, ma_6, ma_12` (moyennes mobiles) | lisse le bruit mensuel |
| Volatilité | `std_3, std_6` | un produit erratique est plus dur à prévoir |
| Saisonnalité | `mois`, `trimestre`, `lag_12` | les campagnes de dépistage sont saisonnières |
| Dynamique | `ratio_3_12` (élan), `tendance_3m` | détecte accélération / décrochage |
| Clientèle | `n_clients`, `part_public`, `part_labo`, `hhi_clients` | un produit vendu à un seul hôpital est plus volatil |
| Cycle de vie | `anciennete_mois`, `mois_actifs`, `taux_activite` | un produit récent ou intermittent se prévoit autrement |
| Prix | `prix_moyen`, `variation_prix` | un changement tarifaire déplace la demande |

**Garantie anti-fuite** : chaque ligne à la date *t* n'utilise que des valeurs
observées jusqu'à *t−1*. Les cibles sont les demandes cumulées futures à 30,
60 et 90 jours (soit 1, 2 et 3 mois), donc strictement postérieures.

Usage :
    from ml_engine.models import build_demand_dataset
    df = build_demand_dataset()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from etl.sources import chemin as chemin_source
from ml_engine.typologie import est_hopital_public

BASE = Path(__file__).resolve().parents[2]
DATA_DIR = BASE / "data_pfe"
# Jeu d'apprentissage construit sur la source brute, avec ses propres règles
# (voir docs/DATA_WAREHOUSE.md, « Ce qui lit encore les CSV ») ; le chemin vient
# du catalogue de l'ETL, seul endroit qui nomme un fichier source.
LINES_CSV = chemin_source("ventes_lignes", DATA_DIR)

MIN_MOIS_HISTORIQUE = 24        # série trop courte = non modélisable
HORIZONS = (1, 2, 3)            # mois → 30, 60, 90 jours

FEATURES: List[str] = [
    # retards
    "lag_1", "lag_2", "lag_3", "lag_6", "lag_12",
    # tendance et volatilité
    "ma_3", "ma_6", "ma_12", "std_3", "std_6",
    # dynamique
    "ratio_3_12", "tendance_3m",
    # saisonnalité
    "mois", "trimestre",
    # clientèle
    "n_clients", "part_public", "part_labo", "hhi_clients",
    # cycle de vie
    "anciennete_mois", "mois_actifs", "taux_activite",
    # prix
    "prix_moyen", "variation_prix",
]

TARGETS = {1: "y_h1", 2: "y_h2", 3: "y_h3"}


# ── Typologie d'établissement (feature métier) ──────────────────────────────
def classer_etablissement(nom: Optional[str]) -> str:
    """Type d'établissement déduit de la raison sociale.

    Les comportements d'achat diffèrent nettement : un hôpital public commande
    par marché annuel (volumes lissés), un laboratoire privé au fil de l'eau.
    """
    u = (nom or "").upper()
    if est_hopital_public(nom):          # règle commune : ml_engine/typologie.py
        return "HOPITAL_PUBLIC"
    if any(k in u for k in ("CLINIQUE", "POLYCLINIQUE")):
        return "CLINIQUE_PRIVEE"
    if any(k in u for k in ("LABO", "LABORATOIRE", "ANALYSE", "BIOLOG")):
        return "LABORATOIRE"
    if any(k in u for k in ("PHARMACIE", "PHARMA")):
        return "PHARMACIE"
    return "AUTRE"


def _connect():
    import duckdb
    return duckdb.connect()


def _load_monthly() -> pd.DataFrame:
    """Séries mensuelles produit × mois, depuis les lignes de vente réelles."""
    con = _connect()
    d = ("COALESCE(TRY_STRPTIME(DATEFACTURE,'%m/%d/%Y'),"
         "TRY_STRPTIME(DATEFACTURE,'%Y-%m-%d'))::DATE")
    src = (f"read_csv_auto('{LINES_CSV.as_posix()}', sample_size=20000, "
           f"ignore_errors=true, all_varchar=true)")
    df = con.execute(f"""
        SELECT trim(DESIGNATION)                        AS produit,
               strftime({d}, '%Y-%m')                   AS period,
               trim(TIERS)                              AS client,
               sum(TRY_CAST(QTEFACTURE AS DOUBLE))      AS qte,
               sum(TRY_CAST(MONTANTSIGNE_DEV AS DOUBLE)) AS ca
        FROM {src}
        WHERE {d} IS NOT NULL
          AND DESIGNATION IS NOT NULL AND trim(DESIGNATION) <> ''
          AND TRY_CAST(QTEFACTURE AS DOUBLE) > 0
        GROUP BY 1, 2, 3
    """).df()
    con.close()
    return df


def _noms_clients() -> Dict[str, str]:
    """Code client → raison sociale (pour la typologie d'établissement)."""
    try:
        import duckdb
        from ml_engine.analytics.kpi_engine import STORE_PATH
        con = duckdb.connect(str(STORE_PATH), read_only=True)
        rows = con.execute("SELECT client_code, client_name FROM dim_client").fetchall()
        con.close()
        return {str(r[0]): str(r[1] or r[0]) for r in rows}
    except Exception:
        return {}


def build_demand_dataset(min_mois: int = MIN_MOIS_HISTORIQUE,
                         verbose: bool = True) -> pd.DataFrame:
    """Construit le jeu d'apprentissage complet (features + 3 cibles).

    Returns:
        DataFrame indexé par (produit, period) avec `FEATURES` et `y_h1/2/3`.
    """
    raw = _load_monthly()
    if raw.empty:
        raise RuntimeError("Aucune ligne de vente exploitable.")

    noms = _noms_clients()
    raw["type_etab"] = raw["client"].map(lambda c: classer_etablissement(noms.get(str(c), str(c))))

    # ── Agrégat produit × mois, avec structure de clientèle ──
    def _hhi(series: pd.Series) -> float:
        tot = series.sum()
        if tot <= 0:
            return 0.0
        parts = (series / tot * 100) ** 2
        return float(parts.sum())

    grp = raw.groupby(["produit", "period"])
    agg = grp.agg(
        qte=("qte", "sum"),
        ca=("ca", "sum"),
        n_clients=("client", "nunique"),
    ).reset_index()

    # Part des hôpitaux publics et des laboratoires dans le volume du mois
    pivot = (raw.pivot_table(index=["produit", "period"], columns="type_etab",
                             values="qte", aggfunc="sum", fill_value=0)
             .reset_index())
    for col in ("HOPITAL_PUBLIC", "LABORATOIRE"):
        if col not in pivot.columns:
            pivot[col] = 0.0
    pivot["_tot"] = pivot[[c for c in pivot.columns
                           if c not in ("produit", "period")]].sum(axis=1)
    pivot["part_public"] = np.where(pivot["_tot"] > 0,
                                    pivot["HOPITAL_PUBLIC"] / pivot["_tot"], 0.0)
    pivot["part_labo"] = np.where(pivot["_tot"] > 0,
                                  pivot["LABORATOIRE"] / pivot["_tot"], 0.0)
    agg = agg.merge(pivot[["produit", "period", "part_public", "part_labo"]],
                    on=["produit", "period"], how="left")

    hhi = grp["qte"].apply(_hhi).rename("hhi_clients").reset_index()
    agg = agg.merge(hhi, on=["produit", "period"], how="left")

    # ── Ne garder que les séries suffisamment longues ──
    counts = agg.groupby("produit")["period"].count()
    gardes = counts[counts >= min_mois].index
    agg = agg[agg["produit"].isin(gardes)].copy()
    if agg.empty:
        raise RuntimeError(f"Aucun produit avec ≥ {min_mois} mois d'historique.")

    # ── Reindexation mensuelle continue (les mois sans vente valent 0) ──
    agg["dt"] = pd.to_datetime(agg["period"] + "-01")
    frames: List[pd.DataFrame] = []
    for produit, g in agg.groupby("produit", sort=False):
        g = g.sort_values("dt")
        idx = pd.date_range(g["dt"].min(), g["dt"].max(), freq="MS")
        g = g.set_index("dt").reindex(idx)
        g["produit"] = produit
        g["qte"] = g["qte"].fillna(0.0)
        g["ca"] = g["ca"].fillna(0.0)
        g["n_clients"] = g["n_clients"].fillna(0)
        for c in ("part_public", "part_labo", "hhi_clients"):
            g[c] = g[c].ffill().fillna(0.0)
        g.index.name = "dt"
        frames.append(g.reset_index())
    df = pd.concat(frames, ignore_index=True)
    df["period"] = df["dt"].dt.strftime("%Y-%m")

    # ── FEATURES (toutes calculées sur le PASSÉ strict : shift(1)) ──
    g = df.groupby("produit", sort=False)["qte"]
    for lag in (1, 2, 3, 6, 12):
        df[f"lag_{lag}"] = g.shift(lag)
    for w in (3, 6, 12):
        df[f"ma_{w}"] = g.shift(1).rolling(w, min_periods=1).mean()
    for w in (3, 6):
        df[f"std_{w}"] = g.shift(1).rolling(w, min_periods=2).std()

    df["ratio_3_12"] = df["ma_3"] / df["ma_12"].replace(0, np.nan)
    df["tendance_3m"] = df["ma_3"] - df.groupby("produit", sort=False)["ma_3"].shift(3)

    df["mois"] = df["dt"].dt.month
    df["trimestre"] = df["dt"].dt.quarter

    # Clientèle : décalée d'un mois (on ne connaît pas le mois courant)
    for c in ("n_clients", "part_public", "part_labo", "hhi_clients"):
        df[c] = df.groupby("produit", sort=False)[c].shift(1)

    # Cycle de vie
    df["anciennete_mois"] = df.groupby("produit", sort=False).cumcount()
    actifs = (df["qte"] > 0).astype(int)
    df["mois_actifs"] = (actifs.groupby(df["produit"]).cumsum().shift(1))
    df["taux_activite"] = df["mois_actifs"] / df["anciennete_mois"].replace(0, np.nan)

    # Prix
    prix = (df["ca"] / df["qte"].replace(0, np.nan))
    df["prix_moyen"] = prix.groupby(df["produit"]).shift(1)
    df["variation_prix"] = (df["prix_moyen"] /
                            df.groupby("produit", sort=False)["prix_moyen"].shift(3)) - 1

    # ── CIBLES : demande cumulée FUTURE à 1, 2 et 3 mois ──
    gq = df.groupby("produit", sort=False)["qte"]
    df["y_h1"] = gq.shift(-1)
    df["y_h2"] = gq.shift(-1).fillna(0) + gq.shift(-2).fillna(0)
    df["y_h3"] = (gq.shift(-1).fillna(0) + gq.shift(-2).fillna(0)
                  + gq.shift(-3).fillna(0))
    # y_h2/h3 invalides si le futur est incomplet
    df.loc[gq.shift(-2).isna(), "y_h2"] = np.nan
    df.loc[gq.shift(-3).isna(), "y_h3"] = np.nan

    # Nettoyage : les 12 premiers mois de chaque série n'ont pas tous les lags
    df = df.replace([np.inf, -np.inf], np.nan)
    df[FEATURES] = df[FEATURES].fillna(0.0)
    df = df.dropna(subset=["y_h1"]).reset_index(drop=True)

    if verbose:
        print(f"[features] {df['produit'].nunique()} produits · {len(df):,} observations "
              f"· {df['period'].min()} → {df['period'].max()}".replace(",", " "))
        print(f"[features] {len(FEATURES)} variables explicatives, 3 cibles (h1/h2/h3)")
    return df


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    df = build_demand_dataset()
    print("\nAperçu des cibles :")
    print(df[["produit", "period", "qte", "y_h1", "y_h2", "y_h3"]].tail(5).to_string(index=False))
    print(f"\nValeurs manquantes dans les features : {df[FEATURES].isna().sum().sum()}")
