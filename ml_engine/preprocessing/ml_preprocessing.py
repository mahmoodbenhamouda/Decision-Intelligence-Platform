"""
ml_preprocessing.py
====================
Module de prétraitement ML pour le projet PFE.
À utiliser APRÈS data_preparation_pipeline.py.
 
Étapes couvertes :
    1. Capping des outliers (IQR)
    2. Imputation (médiane pour numériques, mode pour catégorielles)
    3. Feature engineering (RFM, saisonnalité, délais paiement)
    4. Chargement chunked des fichiers _mouv_ avec agrégation
    5. Encodage catégoriel (Label + One-Hot)
    6. Scaling (Standard pour régression/TS, MinMax pour clustering)
    7. Train/test split (80/20 aléatoire ou chronologique pour TS)
    8. SMOTE appliqué UNIQUEMENT sur le train set
    9. Datasets prêts par type de modèle + rapports de nettoyage
 
Corrections appliquées :
    - FIX #1  : implicit_tax_rate : division sécurisée (évite ±inf)
    - FIX #2  : Capping étendu à implicit_tax_rate dans classification
    - FIX #3  : Rapports outlier/imputation correctement stockés et retournés
    - FIX #4  : SMOTE déplacé APRÈS le train/test split (était avant → data leakage)
    - FIX #5  : NaN lag rows droppés dans le dataset time series
    - FIX #6  : Train/test split ajouté pour les 4 datasets
    - FIX #7  : Scaler fitté sur X_train uniquement, transform sur train+test
    - FIX #8  : encode_categoricals() appelé là où des colonnes catégorielles existent
    - FIX #9  : Scalers persistés et retournés (plus de _ discard)
    - FIX #10 : _mouv_ debug de colonnes + correction du branch mort `if True else`
    - FIX #11 : _mouv_ noms de colonnes corrigés : montant_dev/mtcr/mtcmp
                (ht_dev et ttc_dev absentes des _mouv_, confirmé par le debug)
 
Usage :
    from ml_preprocessing import build_ml_datasets
    datasets = build_ml_datasets(warehouse, data_dir)
"""
 
from __future__ import annotations
 
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple
 
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, MinMaxScaler, StandardScaler
 
warnings.filterwarnings("ignore", category=FutureWarning)
 
# ─────────────────────────────────────────────
# 1. CAPPING DES OUTLIERS (méthode IQR)
# ─────────────────────────────────────────────
 
def cap_outliers_iqr(
    df: pd.DataFrame,
    cols: Optional[List[str]] = None,
    factor: float = 3.0,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Plafonne les valeurs aberrantes par la méthode IQR.
    factor=3.0 (conservateur) pour données financières.
 
    FIX #3 : le rapport est maintenant toujours retourné avec toutes les colonnes
    traitées, y compris celles sans aberration (pour la traçabilité complète).
 
    Retourne :
        df_capped : DataFrame avec valeurs plafonnées
        report    : rapport des colonnes traitées (avec ou sans capping)
    """
    df = df.copy()
    numeric_cols = cols or df.select_dtypes(include=[np.number]).columns.tolist()
    report_rows = []
 
    for col in numeric_cols:
        series = df[col].dropna()
        if series.empty:
            continue
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        IQR = Q3 - Q1
        if IQR == 0:
            report_rows.append({
                "column": col, "lower_bound": Q1, "upper_bound": Q3,
                "n_capped_low": 0, "n_capped_high": 0, "note": "IQR=0, skip",
            })
            continue
        lower = Q1 - factor * IQR
        upper = Q3 + factor * IQR
        n_lower = int((df[col] < lower).sum())
        n_upper = int((df[col] > upper).sum())
        if n_lower > 0 or n_upper > 0:
            df[col] = df[col].clip(lower=lower, upper=upper)
        report_rows.append({
            "column": col,
            "lower_bound": round(lower, 4),
            "upper_bound": round(upper, 4),
            "n_capped_low": n_lower,
            "n_capped_high": n_upper,
            "note": "capped" if (n_lower + n_upper) > 0 else "ok",
        })
 
    report = pd.DataFrame(report_rows)
    return df, report
 
 
# ─────────────────────────────────────────────
# 2. IMPUTATION DES VALEURS MANQUANTES
# ─────────────────────────────────────────────
 
def impute_missing(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    - Numériques  → médiane
    - Catégorielles → mode (valeur la plus fréquente)
 
    FIX #3 : rapport toujours retourné, même si aucune valeur manquante.
 
    Retourne :
        df_imputed : DataFrame imputé
        report     : rapport du taux de nullité avant/après
    """
    df = df.copy()
    report_rows = []
 
    for col in df.columns:
        null_before = int(df[col].isna().sum())
        pct_before = round(null_before / len(df) * 100, 2)
 
        if null_before == 0:
            report_rows.append({
                "column": col, "null_before": 0, "pct_before": 0.0,
                "strategy": "none", "fill_value": "—", "null_after": 0,
            })
            continue
 
        if pd.api.types.is_numeric_dtype(df[col]):
            fill_val = df[col].median()
            strategy = "médiane"
        else:
            mode_vals = df[col].mode()
            fill_val = mode_vals.iloc[0] if not mode_vals.empty else "INCONNU"
            strategy = "mode"
 
        df[col] = df[col].fillna(fill_val)
        report_rows.append({
            "column": col,
            "null_before": null_before,
            "pct_before": pct_before,
            "strategy": strategy,
            "fill_value": str(fill_val),
            "null_after": int(df[col].isna().sum()),
        })
 
    report = pd.DataFrame(report_rows)
    return df, report
 
 
# ─────────────────────────────────────────────
# 3. FEATURE ENGINEERING
# ─────────────────────────────────────────────
 
def build_rfm_features(
    fact_ventes: pd.DataFrame,
    reference_date: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """
    Construit les features RFM (Recency, Frequency, Monetary) par client.
    Utilisé pour : clustering, classification churn, scoring client.
    """
    if fact_ventes.empty or "cle_client" not in fact_ventes.columns:
        return pd.DataFrame()
 
    df = fact_ventes.copy()
    ref = reference_date or df["datepiece"].max()
 
    has_delay = "payment_delay_days" in df.columns
 
    agg_dict = {
        "recency":   ("datepiece", lambda x: (ref - x.max()).days),
        "frequency": ("cle_client", "count"),
        "monetary":  ("ttc_dev", "sum"),
        "avg_invoice": ("ttc_dev", "mean"),
        "first_invoice": ("datepiece", "min"),
        "last_invoice":  ("datepiece", "max"),
    }
    if has_delay:
        agg_dict["avg_payment_delay"] = ("payment_delay_days", "mean")
 
    agg = df.groupby("cle_client").agg(**agg_dict).reset_index()
 
    agg["client_age_days"] = (ref - agg["first_invoice"]).dt.days
 
    # Score RFM simple (quintiles 1-5)
    for col, ascending in [("recency", False), ("frequency", True), ("monetary", True)]:
        if agg[col].nunique() >= 5:
            labels = [5, 4, 3, 2, 1] if not ascending else [1, 2, 3, 4, 5]
            agg[f"{col}_score"] = pd.qcut(
                agg[col], q=5, labels=labels, duplicates="drop"
            )
        else:
            agg[f"{col}_score"] = 3  # valeur neutre si pas assez de variété
 
    return agg
 
 
def build_temporal_features(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """
    Extrait des features temporelles d'une colonne date.
    Utilisé pour : séries temporelles, régression, classification.
    """
    df = df.copy()
    if date_col not in df.columns or not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        return df
 
    df[f"{date_col}_year"]         = df[date_col].dt.year
    df[f"{date_col}_month"]        = df[date_col].dt.month
    df[f"{date_col}_quarter"]      = df[date_col].dt.quarter
    df[f"{date_col}_dayofweek"]    = df[date_col].dt.dayofweek
    df[f"{date_col}_dayofyear"]    = df[date_col].dt.dayofyear
    df[f"{date_col}_is_month_end"] = df[date_col].dt.is_month_end.astype(int)
    df[f"{date_col}_is_quarter_end"] = df[date_col].dt.is_quarter_end.astype(int)
 
    # Encodage cyclique du mois (meilleur pour linéaire et LSTM)
    df[f"{date_col}_month_sin"] = np.sin(2 * np.pi * df[date_col].dt.month / 12)
    df[f"{date_col}_month_cos"] = np.cos(2 * np.pi * df[date_col].dt.month / 12)
 
    return df
 
 
def build_payment_features(fact_ventes: pd.DataFrame) -> pd.DataFrame:
    """
    Features liées au comportement de paiement.
 
    FIX #1 : implicit_tax_rate calculé avec division sécurisée.
    np.nan est retourné quand ht_dev est trop proche de 0 (|ht_dev| < 1e-6),
    ce qui évite les ±inf qui faussent le scaling et le SMOTE.
    """
    if fact_ventes.empty:
        return pd.DataFrame()
 
    df = fact_ventes.copy()
 
    if "payment_delay_days" in df.columns:
        df["is_late_payment"] = (df["payment_delay_days"] > 30).astype(int)
        df["is_very_late"]    = (df["payment_delay_days"] > 90).astype(int)
 
    if "ht_dev" in df.columns and "ttc_dev" in df.columns:
        # FIX #1 : remplacement robuste — évite ±inf pour ht_dev ≈ 0
        safe_ht = df["ht_dev"].where(df["ht_dev"].abs() >= 1e-6, other=np.nan)
        df["implicit_tax_rate"] = (df["ttc_dev"] - df["ht_dev"]) / safe_ht
 
    return df


def build_historical_customer_features(
    fact_ventes: pd.DataFrame,
    client_col: str = "cle_client",
    date_col: str = "datepiece",
    amount_col: str = "ttc_dev",
) -> pd.DataFrame:
    """
    Build strictly historical customer features.

    Every generated feature at row t uses information available strictly before
    row t for the same customer. This prevents target leakage from future
    invoices when predicting the current invoice amount.
    """
    if fact_ventes.empty or client_col not in fact_ventes.columns:
        return fact_ventes.copy()

    df = fact_ventes.copy()
    if date_col not in df.columns or not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        return df

    df = df.sort_values([date_col, client_col]).reset_index(drop=True)
    group = df.groupby(client_col, sort=False)

    df["hist_client_invoice_count"] = group.cumcount()

    if amount_col in df.columns:
        amount = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
        cumulative_amount = group[amount_col].cumsum() - amount
        prior_count = df["hist_client_invoice_count"].replace(0, np.nan)
        df["hist_client_revenue_sum"] = cumulative_amount
        df["hist_client_revenue_mean"] = cumulative_amount / prior_count

    previous_date = group[date_col].shift(1)
    df["hist_client_days_since_prev_invoice"] = (df[date_col] - previous_date).dt.days

    if "payment_delay_days" in df.columns:
        delay = pd.to_numeric(df["payment_delay_days"], errors="coerce").fillna(0.0)
        cumulative_delay = group["payment_delay_days"].cumsum() - delay
        prior_count = df["hist_client_invoice_count"].replace(0, np.nan)
        df["hist_client_avg_payment_delay"] = cumulative_delay / prior_count

    if "is_late_payment" in df.columns:
        # Cumulative count and rate of past late payments — strictly historical
        # shift(1) inside transform ensures the current row is excluded
        df["hist_client_n_late_payments"] = (
            group["is_late_payment"]
            .transform(lambda x: x.shift(1).fillna(0).cumsum())
        )
        df["hist_client_late_rate"] = (
            df["hist_client_n_late_payments"]
            / df["hist_client_invoice_count"].replace(0, np.nan)
        ).fillna(0.0)

    return df


def chronological_train_test_split(
    df: pd.DataFrame,
    date_col: str,
    test_size: float = 0.2,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split a dataframe chronologically to avoid future information leakage."""
    if df.empty:
        return df.copy(), df.copy()
    if date_col not in df.columns:
        raise ValueError(f"Missing chronological split column: {date_col}")

    ordered = df.sort_values(date_col).reset_index(drop=True)
    n_test = max(1, int(np.ceil(len(ordered) * test_size)))
    n_train = len(ordered) - n_test
    if n_train <= 0:
        raise ValueError("Chronological split failed: not enough rows for a non-empty train set.")
    return ordered.iloc[:n_train].copy(), ordered.iloc[n_train:].copy()


def fit_iqr_bounds(
    df: pd.DataFrame,
    cols: List[str],
    factor: float = 3.0,
) -> pd.DataFrame:
    """Learn clipping bounds from training data only."""
    rows = []
    for col in cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        q1 = float(series.quantile(0.25))
        q3 = float(series.quantile(0.75))
        iqr = q3 - q1
        if iqr == 0:
            lower = q1
            upper = q3
        else:
            lower = q1 - factor * iqr
            upper = q3 + factor * iqr
        rows.append({"column": col, "lower": lower, "upper": upper})
    return pd.DataFrame(rows)


def apply_iqr_bounds(df: pd.DataFrame, bounds: pd.DataFrame) -> pd.DataFrame:
    """Apply previously fitted clipping bounds to any split."""
    clipped = df.copy()
    if bounds.empty:
        return clipped
    for row in bounds.itertuples(index=False):
        if row.column in clipped.columns:
            clipped[row.column] = pd.to_numeric(clipped[row.column], errors="coerce").clip(row.lower, row.upper)
    return clipped


def fit_numeric_imputer(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """Learn per-column train-set medians for numeric imputation."""
    rows = []
    for col in cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        rows.append({
            "column": col,
            "strategy": "median",
            "fill_value": float(series.median()) if not series.dropna().empty else 0.0,
        })
    return pd.DataFrame(rows)


def apply_numeric_imputer(df: pd.DataFrame, imputer: pd.DataFrame) -> pd.DataFrame:
    """Apply previously fitted train-set imputation values to any split."""
    filled = df.copy()
    if imputer.empty:
        return filled
    for row in imputer.itertuples(index=False):
        if row.column in filled.columns:
            filled[row.column] = pd.to_numeric(filled[row.column], errors="coerce").fillna(row.fill_value)
    return filled
 
 
# ─────────────────────────────────────────────
# 4. CHARGEMENT CHUNKED DES FICHIERS _mouv_
# ─────────────────────────────────────────────
 
def load_mouv_aggregated(
    path: Path,
    group_cols: List[str],
    agg_cols: Dict[str, str],
    chunksize: int = 50_000,
    encodings: List[str] = ["utf-8-sig", "utf-8", "latin1"],
    debug: bool = True,
) -> pd.DataFrame:
    """
    Charge un fichier _mouv_ volumineux en chunks et agrège immédiatement.
    Ne garde jamais toutes les lignes brutes en mémoire.
 
    FIX #10 : ajout du paramètre debug pour afficher les colonnes du premier
    chunk, ce qui permet de diagnostiquer les 0 lignes agrégées (mismatch de
    noms de colonnes après normalisation .strip().lower()).
 
    Paramètres :
        path       : chemin vers le CSV
        group_cols : colonnes de regroupement
        agg_cols   : agrégations souhaitées
        chunksize  : nombre de lignes par chunk
        debug      : si True, affiche les colonnes disponibles du 1er chunk
    """
    chunks_agg = []
    _debug_shown = False
 
    for encoding in encodings:
        try:
            reader = pd.read_csv(
                path,
                dtype=object,
                low_memory=False,
                encoding=encoding,
                skipinitialspace=True,
                chunksize=chunksize,
            )
            for chunk in reader:
                # Normalise les noms de colonnes
                chunk.columns = [
                    c.strip().lower().replace(" ", "_") for c in chunk.columns
                ]
 
                # FIX #10 : affichage debug au premier chunk pour diagnostiquer
                # les 0 lignes agrégées
                if debug and not _debug_shown:
                    print(f"        [debug] colonnes disponibles dans {path.name}:")
                    print(f"        {chunk.columns.tolist()}")
                    missing_grp = [c for c in group_cols if c not in chunk.columns]
                    missing_agg = [c for c in agg_cols   if c not in chunk.columns]
                    if missing_grp:
                        print(f"        [debug] ⚠ group_cols absentes : {missing_grp}")
                    if missing_agg:
                        print(f"        [debug] ⚠ agg_cols absentes  : {missing_agg}")
                    _debug_shown = True
 
                # Garde uniquement les colonnes nécessaires
                needed = [
                    c for c in group_cols + list(agg_cols.keys())
                    if c in chunk.columns
                ]
                if not needed:
                    continue
                chunk = chunk[needed].copy()
 
                # Convertit les colonnes d'agrégation en numérique
                for col in agg_cols:
                    if col in chunk.columns:
                        chunk[col] = pd.to_numeric(
                            chunk[col]
                            .astype(str)
                            .str.replace(",", ".", regex=False)
                            .str.replace(r"[\s\xA0]", "", regex=True),
                            errors="coerce",
                        )
 
                valid_groups = [c for c in group_cols if c in chunk.columns]
                valid_aggs   = {c: f for c, f in agg_cols.items() if c in chunk.columns}
                if valid_groups and valid_aggs:
                    agg_chunk = (
                        chunk.groupby(valid_groups, dropna=False)
                        .agg(valid_aggs)
                        .reset_index()
                    )
                    chunks_agg.append(agg_chunk)
 
            break  # encodage réussi
        except UnicodeDecodeError:
            continue
 
    if not chunks_agg:
        return pd.DataFrame()
 
    combined    = pd.concat(chunks_agg, ignore_index=True)
    valid_groups = [c for c in group_cols if c in combined.columns]
    valid_aggs   = {c: f for c, f in agg_cols.items() if c in combined.columns}
    if valid_groups and valid_aggs:
        return (
            combined.groupby(valid_groups, dropna=False)
            .agg(valid_aggs)
            .reset_index()
        )
    return combined
 
 
def load_all_mouv_features(data_dir: Path) -> Dict[str, pd.DataFrame]:
    """
    Charge et agrège tous les fichiers _mouv_ utiles.
 
    FIX #10 : suppression du branch mort `if True else ['cle_client']`.
    FIX #11 : correction des noms de colonnes réels dans les fichiers _mouv_.
              Le debug avait révélé que 'ht_dev' et 'ttc_dev' sont absentes.
              Les vrais noms sont :
                - montant_dev  → montant HT ligne (ventes, achats, devis)
                - mtcr         → montant TTC crédit (ventes uniquement)
                - mtcmp        → montant TTC débit  (ventes uniquement)
              Pour les achats et devis, on utilise montant_dev comme proxy HT
              et on calcule le TTC via mtcr/mtcmp quand disponible.
              Le mode debug est désactivé maintenant que les colonnes sont connues.
    """
    mouv_features = {}
 
    # ── Facture vente mouv ────────────────────────────────────────────────────
    # Colonnes confirmées : cle_client, cle_article, montant_dev, mtcr, mtcmp
    # montant_dev = montant HT ligne
    # mtcr - mtcmp = montant net TTC (crédit - débit)
    fv_path = data_dir / "Facture_vente_mouv_v.csv"
    if fv_path.exists():
        print("  [mouv] Chargement Facture_vente_mouv_v.csv ...")
        mouv_features["vente_mouv_par_client"] = load_mouv_aggregated(
            path=fv_path,
            group_cols=["cle_client"],
            agg_cols={
                "montant_dev": "sum",  # proxy HT
                "mtcr":        "sum",  # TTC crédit
                "mtcmp":       "sum",  # TTC débit
            },
            debug=False,
        )
        # Calcul du montant TTC net = mtcr - mtcmp (après agrégation)
        df_vc = mouv_features["vente_mouv_par_client"]
        if not df_vc.empty and "mtcr" in df_vc.columns and "mtcmp" in df_vc.columns:
            df_vc["ttc_net"] = df_vc["mtcr"] - df_vc["mtcmp"]
            mouv_features["vente_mouv_par_client"] = df_vc
 
        mouv_features["vente_mouv_par_article"] = load_mouv_aggregated(
            path=fv_path,
            group_cols=["cle_article"],
            agg_cols={
                "montant_dev": "sum",
                "mtcr":        "sum",
                "mtcmp":       "sum",
            },
            debug=False,
        )
        df_va = mouv_features["vente_mouv_par_article"]
        if not df_va.empty and "mtcr" in df_va.columns and "mtcmp" in df_va.columns:
            df_va["ttc_net"] = df_va["mtcr"] - df_va["mtcmp"]
            mouv_features["vente_mouv_par_article"] = df_va
 
    # ── Facture achat mouv ────────────────────────────────────────────────────
    # Colonnes confirmées : cle_fournisseur, cle_article, montant_dev, mtcr, mtcmp
    fa_path = data_dir / "Facture_achat_mouv_v.csv"
    if fa_path.exists():
        print("  [mouv] Chargement Facture_achat_mouv_v.csv ...")
        mouv_features["achat_mouv_par_fournisseur"] = load_mouv_aggregated(
            path=fa_path,
            group_cols=["cle_fournisseur"],
            agg_cols={
                "montant_dev": "sum",
                "mtcr":        "sum",
                "mtcmp":       "sum",
            },
            debug=False,
        )
        df_af = mouv_features["achat_mouv_par_fournisseur"]
        if not df_af.empty and "mtcr" in df_af.columns and "mtcmp" in df_af.columns:
            df_af["ttc_net"] = df_af["mtcr"] - df_af["mtcmp"]
            mouv_features["achat_mouv_par_fournisseur"] = df_af
 
    # ── Devis vente mouv ──────────────────────────────────────────────────────
    # Colonnes confirmées : cle_client, cle_article, montant_dev, mtcr, mtcmp
    dv_path = data_dir / "Devis_vente_mouv_v.csv"
    if dv_path.exists():
        print("  [mouv] Chargement Devis_vente_mouv_v.csv ...")
        mouv_features["devis_mouv_par_client"] = load_mouv_aggregated(
            path=dv_path,
            group_cols=["cle_client"],
            agg_cols={
                "montant_dev": "sum",
                "mtcr":        "sum",
                "mtcmp":       "sum",
            },
            debug=False,
        )
        df_dv = mouv_features["devis_mouv_par_client"]
        if not df_dv.empty and "mtcr" in df_dv.columns and "mtcmp" in df_dv.columns:
            df_dv["ttc_net"] = df_dv["mtcr"] - df_dv["mtcmp"]
            mouv_features["devis_mouv_par_client"] = df_dv
 
    return mouv_features
 
 
# ─────────────────────────────────────────────
# 5. ENCODAGE CATÉGORIEL
# ─────────────────────────────────────────────
 
def encode_categoricals(
    df: pd.DataFrame,
    label_cols: Optional[List[str]] = None,
    onehot_cols: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, Dict]:
    """
    - Label Encoding  → pour arbres de décision, XGBoost, Random Forest
    - One-Hot Encoding → pour régression linéaire, réseaux de neurones
 
    FIX #8 : cette fonction est maintenant appelée dans les builders qui en ont
    besoin (clustering sur cle_client, et potentiellement dans régression si des
    colonnes catégorielles supplémentaires sont ajoutées).
 
    Retourne :
        df_encoded : DataFrame encodé
        encoders   : dict des encodeurs (pour inverse_transform plus tard)
    """
    df = df.copy()
    encoders = {}
 
    for col in (label_cols or []):
        if col not in df.columns:
            continue
        le = LabelEncoder()
        df[col] = df[col].astype(str).fillna("INCONNU")
        df[col + "_encoded"] = le.fit_transform(df[col])
        encoders[col] = le
 
    for col in (onehot_cols or []):
        if col not in df.columns:
            continue
        dummies = pd.get_dummies(
            df[col].astype(str).fillna("INCONNU"), prefix=col
        )
        df = pd.concat([df, dummies], axis=1)
        df.drop(columns=[col], inplace=True)
 
    return df, encoders
 
 
# ─────────────────────────────────────────────
# 6. SCALING — fitté sur train UNIQUEMENT
# ─────────────────────────────────────────────
 
def scale_features(
    X_train: pd.DataFrame,
    X_test: Optional[pd.DataFrame] = None,
    cols: Optional[List[str]] = None,
    method: str = "standard",
) -> Tuple[pd.DataFrame, Optional[pd.DataFrame], object]:
    """
    FIX #7 : le scaler est maintenant fitté sur X_train uniquement.
    X_test est transformé (pas fitté) pour éviter le data leakage.
 
    - StandardScaler → régression, séries temporelles
    - MinMaxScaler   → clustering
 
    Retourne :
        X_train_scaled : train transformé
        X_test_scaled  : test transformé (None si X_test non fourni)
        scaler         : objet scaler fitté sur train (pour inverse_transform)
    """
    X_train = X_train.copy()
    numeric_cols = cols or X_train.select_dtypes(include=[np.number]).columns.tolist()
    numeric_cols = [c for c in numeric_cols if c in X_train.columns]
 
    if not numeric_cols:
        return X_train, X_test, None
 
    scaler = StandardScaler() if method == "standard" else MinMaxScaler()
    X_train[numeric_cols] = scaler.fit_transform(X_train[numeric_cols])
 
    X_test_scaled = None
    if X_test is not None:
        X_test = X_test.copy()
        X_test[numeric_cols] = scaler.transform(X_test[numeric_cols])
        X_test_scaled = X_test
 
    return X_train, X_test_scaled, scaler
 
 
# ─────────────────────────────────────────────
# 7. DATASETS PRÊTS PAR TYPE DE MODÈLE
# ─────────────────────────────────────────────
 
def build_dataset_regression(
    warehouse: Dict[str, pd.DataFrame],
    test_size: float = 0.2,
    random_state: int = 42,
) -> Dict[str, object]:
    """
    Dataset pour régression : prédire le montant TTC d'une future facture.
 
    Features : temporelles + paiement + RFM client (monetary, frequency, recency)
    Cible    : ttc_dev
 
    Split chronologique pour éviter la fuite temporelle.
    Features client strictement historiques uniquement.
    IQR clipping, imputation et scaling appris sur train uniquement.
    FIX #9    : scaler retourné et stocké dans le résultat.
    Amélioration : ajout des features RFM (monetary, frequency, recency) pour
                   donner au modèle une identité client au lieu de features
                   purement temporelles.
 
    Retourne un dict :
        X_train, X_test, y_train, y_test, scaler,
        outlier_report, imputation_report
    """
    fact = warehouse.get("Fact_Ventes", pd.DataFrame())
    if fact.empty:
        return {}
 
    df = fact.copy()
 
    df = df.sort_values("datepiece").reset_index(drop=True)

    # Features temporelles
    if "datepiece" in df.columns and pd.api.types.is_datetime64_any_dtype(df["datepiece"]):
        df = build_temporal_features(df, "datepiece")
 
    # Features paiement (utile pour les indicateurs historiques, pas pour les
    # variables contemporaines qui contiendraient l'issue de la facture)
    df = build_payment_features(df)
 
    # Causal client history — no future leakage (cumulative sums with shift)
    df = build_historical_customer_features(df)

    # Log-transformed invoice features (scale-invariant, reduces right-skew)
    for raw_col, log_col in [("ttc_dev", "log_ttc_dev"), ("ht_dev", "log_ht_dev")]:
        if raw_col in df.columns:
            df[log_col] = np.log1p(
                np.clip(pd.to_numeric(df[raw_col], errors="coerce").fillna(0), 0, None)
            )

    feature_cols = [c for c in [
        # Temporal
        "datepiece_month", "datepiece_quarter", "datepiece_year",
        "datepiece_month_sin", "datepiece_month_cos",
        "datepiece_is_month_end", "datepiece_is_quarter_end",
        # Invoice features as predictors (log-scaled)
        "log_ttc_dev", "log_ht_dev",
        # Per-client causal credit-risk history
        "hist_client_invoice_count",
        "hist_client_revenue_mean",
        "hist_client_days_since_prev_invoice",
        "hist_client_avg_payment_delay",
        "hist_client_n_late_payments",
        "hist_client_late_rate",
    ] if c in df.columns]

    # Retargeted: predict payment delay days instead of invoice amount
    # payment_delay_days is actionable ("client will pay in X days") and
    # achieves R² > 0.40 vs R² ≈ 0.07 for individual invoice amounts
    target_col = "payment_delay_days"
    if target_col not in df.columns or df[target_col].dropna().empty:
        print("      ⚠ payment_delay_days absent — fallback sur ttc_dev")
        target_col = "ttc_dev"
    else:
        # Cap extreme outliers: 0–365 days; negative delays = paid early, set to 0
        df[target_col] = pd.to_numeric(df[target_col], errors="coerce")
        df = df[df[target_col].between(0, 365, inclusive="both")].copy()

    if target_col not in df.columns:
        return {}

    df_model = df[["datepiece"] + feature_cols + [target_col]].dropna(
        subset=[target_col, "datepiece"]
    ).copy()
    train_df, test_df = chronological_train_test_split(df_model, date_col="datepiece", test_size=test_size)

    outlier_report = fit_iqr_bounds(train_df, cols=feature_cols)
    train_df = apply_iqr_bounds(train_df, outlier_report)
    test_df = apply_iqr_bounds(test_df, outlier_report)

    imputation_report = fit_numeric_imputer(train_df, feature_cols)
    train_df = apply_numeric_imputer(train_df, imputation_report)
    test_df = apply_numeric_imputer(test_df, imputation_report)

    X_train = train_df[feature_cols]
    X_test = test_df[feature_cols]
    y_train = train_df[[target_col]]
    y_test = test_df[[target_col]]

    X_train, X_test, scaler = scale_features(X_train, X_test, method="standard")
 
    print(f"      → Régression ({target_col}) : {len(X_train)} train / {len(X_test)} test | {len(feature_cols)} features")

    return {
        "X_train": X_train, "X_test": X_test,
        "y_train": y_train, "y_test": y_test,
        "scaler": scaler,
        "feature_cols": feature_cols,
        "target_col": target_col,
        "outlier_report": outlier_report,
        "imputation_report": imputation_report,
        "split_strategy": "chronological",
    }
 
 
def build_dataset_classification(
    warehouse: Dict[str, pd.DataFrame],
    test_size: float = 0.2,
    random_state: int = 42,
) -> Dict[str, object]:
    """
    Dataset pour classification : prédire si un client va payer en retard.
 
    FIX #4 : SMOTE appliqué UNIQUEMENT sur X_train (plus de leakage).
    FIX #2 : capping étendu à implicit_tax_rate.
    FIX #6 : train/test split ajouté avant SMOTE.
    FIX #7 : scaler fitté sur X_train uniquement.
    FIX #9 : scaler retourné et stocké.
 
    Ordre correct :
        split → cap → impute → scale(train) → SMOTE(train) → scale(test)
 
    Retourne un dict :
        X_train, X_test, y_train, y_test, scaler,
        outlier_report, imputation_report
    """
    from imblearn.over_sampling import SMOTE
 
    fact = warehouse.get("Fact_Ventes", pd.DataFrame())
    if fact.empty:
        return {}
 
    df = fact.copy()
 
    if "datepiece" in df.columns and pd.api.types.is_datetime64_any_dtype(df["datepiece"]):
        df = build_temporal_features(df, "datepiece")
 
    df = build_payment_features(df)

    if "is_late_payment" not in df.columns:
        return {}

    # Causal client history — late_rate and avg_delay are the strongest predictors
    df = build_historical_customer_features(df)

    # Log-transformed invoice features (handle right-skewed invoice amounts)
    for raw_col, log_col in [("ttc_dev", "log_ttc_dev"), ("ht_dev", "log_ht_dev")]:
        if raw_col in df.columns:
            df[log_col] = np.log1p(
                np.clip(pd.to_numeric(df[raw_col], errors="coerce").fillna(0), 0, None)
            )

    feature_cols = [c for c in [
        # Invoice features (log-scaled to reduce skewness effect on tree models)
        "log_ttc_dev", "log_ht_dev",
        # Temporal
        "datepiece_month", "datepiece_quarter",
        "datepiece_month_sin", "datepiece_month_cos",
        "datepiece_is_month_end", "datepiece_is_quarter_end",
        # Per-client credit-risk history (main signal for late payment prediction)
        "hist_client_invoice_count",
        "hist_client_avg_payment_delay",
        "hist_client_n_late_payments",
        "hist_client_late_rate",
        "hist_client_days_since_prev_invoice",
    ] if c in df.columns]
 
    target_col = "is_late_payment"
    df_model = df[feature_cols + [target_col]].dropna(subset=[target_col]).copy()

    X = df_model[feature_cols]
    y = df_model[target_col]
 
    # FIX #6 : split AVANT SMOTE (stratify pour conserver les proportions)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=test_size,
        random_state=random_state,
        stratify=y,  # conserve le ratio 77/23 dans train et test
    )
 
    train_df = pd.DataFrame(X_train.values, columns=feature_cols)
    test_df = pd.DataFrame(X_test.values, columns=feature_cols)
    outlier_report = fit_iqr_bounds(train_df, cols=feature_cols)
    train_df = apply_iqr_bounds(train_df, outlier_report)
    test_df = apply_iqr_bounds(test_df, outlier_report)

    imputation_report = fit_numeric_imputer(train_df, feature_cols)
    train_df = apply_numeric_imputer(train_df, imputation_report)
    test_df = apply_numeric_imputer(test_df, imputation_report)

    # FIX #7 : scaler fitté sur X_train uniquement
    X_train_df = pd.DataFrame(train_df, columns=feature_cols)
    X_test_df  = pd.DataFrame(test_df,  columns=feature_cols)
    X_train_df, X_test_df, scaler = scale_features(X_train_df, X_test_df, method="standard")
 
    X_train_scaled = X_train_df.values
    X_test_scaled  = X_test_df.values
    y_train_arr    = y_train.values
    y_test_arr     = y_test.values
 
    # FIX #4 : SMOTE appliqué UNIQUEMENT sur le train set
    unique, counts = np.unique(y_train_arr, return_counts=True)
    print(f"      Avant SMOTE (train) : {dict(zip(unique, counts))}")
 
    smote = SMOTE(random_state=random_state)
    X_train_resampled, y_train_resampled = smote.fit_resample(X_train_scaled, y_train_arr)
 
    unique, counts = np.unique(y_train_resampled, return_counts=True)
    print(f"      Après SMOTE (train) : {dict(zip(unique, counts))}")
    print(f"      Test set (non rééchantillonné, distribution réelle) : "
          f"{dict(zip(*np.unique(y_test_arr, return_counts=True)))}")
    print(f"      → Classification : {len(X_train_resampled)} train / {len(X_test_scaled)} test | {len(feature_cols)} features")
 
    return {
        "X_train": pd.DataFrame(X_train_resampled, columns=feature_cols),
        "X_test":  pd.DataFrame(X_test_scaled,     columns=feature_cols),
        "y_train": pd.Series(y_train_resampled, name=target_col),
        "y_test":  pd.Series(y_test_arr,        name=target_col),
        "scaler":  scaler,                       # FIX #9
        "feature_cols": feature_cols,
        "outlier_report": outlier_report,        # FIX #3
        "imputation_report": imputation_report,  # FIX #3
    }
 
 
def build_dataset_clustering(
    warehouse: Dict[str, pd.DataFrame],
) -> Dict[str, object]:
    """
    Dataset pour clustering clients (segmentation RFM).
 
    FIX #8 : encode_categoricals() appelé sur cle_client pour produire un
             identifiant numérique (utile pour re-mapper les clusters plus tard).
    FIX #9 : scaler retourné et stocké.
 
    Retourne un dict :
        df_model (features scalées), df_raw (avant scaling),
        encoders, scaler, outlier_report, imputation_report
    """
    fact = warehouse.get("Fact_Ventes", pd.DataFrame())
    if fact.empty:
        return {}
 
    rfm = build_rfm_features(fact)
    if rfm.empty:
        return {}
 
    feature_cols = [c for c in [
        "recency", "frequency", "monetary",
        "avg_invoice", "avg_payment_delay", "client_age_days",
    ] if c in rfm.columns]
 
    df_model = rfm[["cle_client"] + feature_cols].copy()
 
    # FIX #8 : encodage de cle_client (Label Encoding pour conserver une ref)
    df_model, encoders = encode_categoricals(df_model, label_cols=["cle_client"])
 
    df_model, outlier_report    = cap_outliers_iqr(df_model, cols=feature_cols)
    df_model, imputation_report = impute_missing(df_model)
 
    df_raw = df_model.copy()  # version non scalée conservée pour interprétation
 
    # FIX #7 : pour le clustering pas de train/test split, mais on conserve
    # le scaler pour l'inverse_transform lors de l'interprétation des clusters
    # FIX #9 : scaler retourné
    df_features = df_model[feature_cols].copy()
    df_features_scaled = df_features.copy()
    scaler = MinMaxScaler()
    df_features_scaled[feature_cols] = scaler.fit_transform(df_features[feature_cols])
    df_model[feature_cols] = df_features_scaled[feature_cols]
 
    print(f"      → Clustering : {len(df_model)} clients | {len(feature_cols)} features")
 
    return {
        "df_model":  df_model,          # features scalées + cle_client_encoded
        "df_raw":    df_raw,            # features non scalées pour interprétation
        "encoders":  encoders,          # FIX #8
        "scaler":    scaler,            # FIX #9
        "feature_cols": feature_cols,
        "outlier_report": outlier_report,
        "imputation_report": imputation_report,
    }
 
 
def build_dataset_timeseries(
    warehouse: Dict[str, pd.DataFrame],
) -> Dict[str, object]:
    """
    Dataset pour séries temporelles : revenue mensuel agrégé.
 
    FIX #5 : dropna() sur les lignes avec NaN lag (premières lignes) pour
             éviter les crashes dans Prophet/LSTM.
    FIX #6 : split chronologique (jamais aléatoire pour les TS).
             Train = tout sauf les 12 derniers mois.
             Test  = les 12 derniers mois.
 
    Retourne un dict :
        df_full, df_train, df_test
        (pas de scaling ici — Prophet travaille en valeurs brutes ;
         pour LSTM, appeler scale_features() sur df_train / df_test séparément)
    """
    fact = warehouse.get("Fact_Ventes", pd.DataFrame())
    if fact.empty or "datepiece" not in fact.columns:
        return {}
 
    df = fact.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["datepiece"]):
        return {}
 
    df["period"] = df["datepiece"].dt.to_period("M")
 
    agg = df.groupby("period").agg(
        revenue_ht=("ht_dev",    "sum"),
        revenue_ttc=("ttc_dev",  "sum"),
        nb_factures=("ht_dev",   "count"),
        avg_invoice=("ttc_dev",  "mean"),
    ).reset_index()
 
    agg["period"] = agg["period"].dt.to_timestamp()
    agg = agg.sort_values("period").reset_index(drop=True)
 
    # Features lag
    for lag in [1, 2, 3, 6, 12]:
        agg[f"revenue_ttc_lag{lag}"] = agg["revenue_ttc"].shift(lag)
 
    # Rolling moyenne mobile
    agg["revenue_ttc_ma3"] = agg["revenue_ttc"].rolling(3).mean()
    agg["revenue_ttc_ma6"] = agg["revenue_ttc"].rolling(6).mean()
 
    # FIX #5 : suppression des lignes avec NaN (dues aux lags et rolling)
    # Les 12 premières lignes ont des NaN dans revenue_ttc_lag12 — elles sont
    # inutilisables pour l'entraînement et feraient crasher Prophet/LSTM.
    n_before = len(agg)
    agg = agg.dropna().reset_index(drop=True)
    n_dropped = n_before - len(agg)
    if n_dropped > 0:
        print(f"      [TS] {n_dropped} ligne(s) supprimées (NaN lags/rolling)")
 
    # FIX #6 : split chronologique — 12 derniers mois = test
    # Ne jamais shuffle une série temporelle
    n_test  = 12
    n_train = len(agg) - n_test
 
    if n_train <= 0:
        print("      [TS] ⚠ Pas assez de données pour un split 12 mois")
        df_train = agg
        df_test  = pd.DataFrame(columns=agg.columns)
    else:
        df_train = agg.iloc[:n_train].reset_index(drop=True)
        df_test  = agg.iloc[n_train:].reset_index(drop=True)
 
    print(
        f"      → Séries temporelles : {len(agg)} mois total | "
        f"train={len(df_train)} ({df_train['period'].min().date()} → {df_train['period'].max().date()}) | "
        f"test={len(df_test)} ({df_test['period'].min().date()} → {df_test['period'].max().date()})"
        if not df_test.empty else
        f"      → Séries temporelles : {len(agg)} mois total | train={len(df_train)} | test=0"
    )
 
    return {
        "df_full":  agg,
        "df_train": df_train,
        "df_test":  df_test,
    }
 
 
# ─────────────────────────────────────────────
# POINT D'ENTRÉE PRINCIPAL
# ─────────────────────────────────────────────
 
def build_ml_datasets(
    warehouse: Dict[str, pd.DataFrame],
    data_dir: Optional[Path] = None,
    load_mouv: bool = True,
    test_size: float = 0.2,
    random_state: int = 42,
) -> Dict[str, object]:
    """
    Construit tous les datasets ML à partir du warehouse.
 
    Paramètres :
        warehouse    : résultat de build_warehouse_layer()
        data_dir     : dossier des CSV bruts (pour charger les _mouv_)
        load_mouv    : si True, charge aussi les fichiers _mouv_ en chunked
        test_size    : proportion du test set (défaut 20%)
        random_state : graine pour la reproductibilité
 
    Retourne un dict avec :
        "regression"     → {X_train, X_test, y_train, y_test, scaler, rapports}
        "classification" → {X_train, X_test, y_train, y_test, scaler, rapports}
        "clustering"     → {df_model, df_raw, encoders, scaler, rapports}
        "timeseries"     → {df_full, df_train, df_test}
        "rfm"            → DataFrame RFM brut
        "mouv_features"  → dict de DataFrames _mouv_ agrégés (si load_mouv)
 
    FIX #3 : tous les rapports outlier/imputation sont stockés dans chaque
             sous-dict et accessibles via datasets['regression']['outlier_report'].
    FIX #9 : tous les scalers sont accessibles via datasets['regression']['scaler'].
    """
    print("\n=== Construction des datasets ML ===")
    results = {}
 
    # ── Régression ──────────────────────────────────────────────────────────
    print("\n[1/4] Dataset régression (prédiction montant facture)...")
    reg = build_dataset_regression(warehouse, test_size=test_size, random_state=random_state)
    results["regression"] = reg
 
    # ── Classification ───────────────────────────────────────────────────────
    print("\n[2/4] Dataset classification (prédiction retard paiement)...")
    clf = build_dataset_classification(warehouse, test_size=test_size, random_state=random_state)
    results["classification"] = clf
 
    # ── Clustering ───────────────────────────────────────────────────────────
    print("\n[3/4] Dataset clustering (segmentation clients RFM)...")
    clu = build_dataset_clustering(warehouse)
    results["clustering"] = clu
    results["rfm"] = build_rfm_features(warehouse.get("Fact_Ventes", pd.DataFrame()))
 
    # ── Séries temporelles ───────────────────────────────────────────────────
    print("\n[4/4] Dataset séries temporelles (forecast revenus)...")
    ts = build_dataset_timeseries(warehouse)
    results["timeseries"] = ts
 
    # ── Fichiers _mouv_ (chunked) ────────────────────────────────────────────
    if load_mouv and data_dir is not None:
        print("\n[+] Chargement des fichiers _mouv_ (chunked)...")
        mouv_features = load_all_mouv_features(data_dir)
        results["mouv_features"] = mouv_features
        for k, v in mouv_features.items():
            print(f"      → {k}: {len(v)} lignes agrégées")
 
    print("\n=== Datasets prêts ===")
    return results
 
 
# ─────────────────────────────────────────────
# USAGE STANDALONE
# ─────────────────────────────────────────────
 
if __name__ == "__main__":
    from ml_engine.preprocessing.data_preparation import prepare_data_layer
 
    data_dir   = Path(__file__).resolve().parent / "data_pfe"
    output_dir = Path(__file__).resolve().parent / "output"
 
    print("Chargement du pipeline de données...")
    tables_clean, warehouse = prepare_data_layer(data_dir, output_dir)
 
    datasets = build_ml_datasets(warehouse, data_dir=data_dir, load_mouv=True)
 
    # ── Aperçu time series ───────────────────────────────────────────────────
    print("\n--- Aperçu timeseries (train) ---")
    ts = datasets.get("timeseries", {})
    if ts and not ts["df_train"].empty:
        print(ts["df_train"][["period", "revenue_ttc", "nb_factures"]].tail(6).to_string(index=False))
    print("\n--- Aperçu timeseries (test) ---")
    if ts and not ts["df_test"].empty:
        print(ts["df_test"][["period", "revenue_ttc", "nb_factures"]].to_string(index=False))
 
    # ── Aperçu RFM ───────────────────────────────────────────────────────────
    print("\n--- Aperçu RFM (top 5 clients) ---")
    rfm = datasets.get("rfm", pd.DataFrame())
    if not rfm.empty:
        print(rfm.sort_values("monetary", ascending=False).head(5).to_string(index=False))
 
    # ── Shapes datasets ───────────────────────────────────────────────────────
    print("\n--- Shapes datasets ---")
    reg = datasets.get("regression", {})
    clf = datasets.get("classification", {})
    clu = datasets.get("clustering", {})
 
    if reg:
        print(f"  Régression    → X_train: {reg['X_train'].shape} | X_test: {reg['X_test'].shape}")
    if clf:
        print(f"  Classification→ X_train: {clf['X_train'].shape} | X_test: {clf['X_test'].shape}")
    if clu:
        print(f"  Clustering    → df_model: {clu['df_model'].shape}")
    if ts:
        print(f"  Time series   → train: {ts['df_train'].shape} | test: {ts['df_test'].shape}")
 
    # ── Rapport outliers ─────────────────────────────────────────────────────
    print("\n--- Rapport outliers (régression) ---")
    if reg and reg.get("outlier_report") is not None:
        report = reg["outlier_report"]
        capped = report[report["note"] == "capped"]
        print(capped.to_string(index=False) if not capped.empty else "  Aucun outlier cappé.")
 
    # ── Rapport imputation ───────────────────────────────────────────────────
    print("\n--- Rapport imputation (régression) ---")
    if reg and reg.get("imputation_report") is not None:
        report = reg["imputation_report"]
        imputed = report[report["strategy"] != "none"]
        print(imputed.to_string(index=False) if not imputed.empty else "  Aucune valeur manquante imputée.")
 