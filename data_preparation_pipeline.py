import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import warnings

import pandas as pd

HIDDEN_CHAR_RE = re.compile(r"[\u200B-\u200D\uFEFF]")
WHITESPACE_RE = re.compile(r"\s+")
DATE_CANDIDATE_THRESHOLD = 0.75
NUMERIC_CANDIDATE_THRESHOLD = 0.75
# Tables actually needed by the warehouse layer - skip everything else
REQUIRED_TABLES = {
    "devis_vente_ent_vv",
    "devis_achat_ent_v",
    "facture_vente_ent_v",
    "facture_achat_ent_v",
    "fournisseurs_v",
    "gsl_vente_bl_entete",
    "gsl_achat_bl_entete",
    "gsl_vente_fa_entete",
    "zz_facture_vente_ent",
    "table_nature_paiement_vcsv",
}

BUSINESS_KEYS = {
    "cle_client",
    "cle_fournisseur",
    "cle_facture",
    "cle_devis",
    "cle_bon_livraison",
}

ID_PREFIXES = ("cle_", "id_", "ent_id", "mouv_id", "fou_id", "dos_", "num_", "numero", "piece", "facture", "devis")

DATE_WORDS = ("date", "echeance", "creation", "modif", "releve", "livraison", "facture", "devis")


def normalize_column_name(name: str) -> str:
    name = str(name or "")
    name = HIDDEN_CHAR_RE.sub("", name)
    name = name.strip()
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def normalize_key_value(value: str) -> Optional[str]:
    if pd.isna(value):
        return None
    value = str(value)
    value = HIDDEN_CHAR_RE.sub("", value)
    value = value.strip().replace(" ", "")
    if value == "":
        return None
    return value.upper()


def safe_read_csv(path: Path, encodings: List[str] = ["utf-8-sig", "utf-8", "latin1"]) -> pd.DataFrame:
    for encoding in encodings:
        try:
            df = pd.read_csv(path, dtype=object, low_memory=False, encoding=encoding, skipinitialspace=True)
            return df
        except Exception:
            continue
    raise ValueError(f"Unable to read CSV {path} with fallback encodings.")


def load_all_csvs(data_dir: Path) -> Dict[str, pd.DataFrame]:
    csv_files = sorted(data_dir.glob("*.csv"))
    tables: Dict[str, pd.DataFrame] = {}
    for path in csv_files:
        stem = path.stem.lower()
        if stem not in REQUIRED_TABLES:
            print(f"  [skip] {path.name}")
            continue
        print(f"  [load] {path.name} ...")
        df = safe_read_csv(path)
        tables[stem] = df
    return tables

def clean_value_string(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value)
    text = HIDDEN_CHAR_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)
    text = text.strip()
    return text if text != "" else pd.NA


def clean_string_columns(df: pd.DataFrame) -> pd.DataFrame:
    string_cols = df.select_dtypes(include=["object"]).columns.tolist()
    for col in string_cols:
        s = df[col]
        # Truncate long values to prevent regex hangs
        s = s.where(s.isna(), s.astype(str).str[:500])
        # Remove hidden chars (fast - rare characters, almost never matches)
        s = s.str.replace(HIDDEN_CHAR_RE, "", regex=True)
        # Strip only - skip whitespace collapse for large frames
        s = s.str.strip()
        # Empty → NA
        s = s.where(s.notna() & (s != "") & (s != "nan"), other=None)
        df[col] = s
    return df

def clean_table(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [normalize_column_name(col) for col in df.columns]
    df = clean_string_columns(df)
    df = df.drop_duplicates()
    return df


def is_business_key_column(colname: str) -> bool:
    colname = colname.lower()
    return colname in BUSINESS_KEYS or any(colname.startswith(prefix) for prefix in BUSINESS_KEYS)


def is_protected_id(colname: str) -> bool:
    name = colname.lower()
    if any(name.startswith(prefix) for prefix in ID_PREFIXES):
        return True
    if any(name == key for key in BUSINESS_KEYS):
        return True
    return False


DATE_LIKE_RE = re.compile(r"[A-Za-z]|[\/\-\._]")


def safe_to_datetime(values: pd.Series, dayfirst: bool = False) -> pd.Series:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Could not infer format.*",
            category=UserWarning,
        )
        return pd.to_datetime(values, errors="coerce", dayfirst=dayfirst)


def is_date_candidate(series: pd.Series) -> bool:
    if series.empty:
        return False
    values = series.dropna().astype(str).head(200)
    if values.empty:
        return False
    date_like = values[values.str.contains(DATE_LIKE_RE, regex=True)]
    if date_like.empty:
        return False
    parsed = safe_to_datetime(date_like, dayfirst=False)
    score = parsed.notna().mean()
    return score >= DATE_CANDIDATE_THRESHOLD


def is_numeric_candidate(series: pd.Series) -> bool:
    if series.empty:
        return False
    values = series.dropna().astype(str).head(200)
    if values.empty:
        return False
    cleaned = values.str.replace(r"[\s\xA0]", "", regex=True).str.replace(",", ".", regex=False)
    parsed = pd.to_numeric(cleaned, errors="coerce")
    score = parsed.notna().mean()
    return score >= NUMERIC_CANDIDATE_THRESHOLD


def standardize_column_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if is_protected_id(col):
            # Use object instead of "string" to avoid slow StringDtype conversion
            df[col] = df[col].astype(object)
            continue
        if is_date_candidate(df[col]):
            df[col] = safe_to_datetime(df[col], dayfirst=False)
            continue
        if is_numeric_candidate(df[col]):
            cleaned = df[col].astype(str).str.replace(r"[\s\xA0]", "", regex=True).str.replace(",", ".", regex=False)
            numeric = pd.to_numeric(cleaned, errors="coerce")
            if numeric.dropna().map(lambda x: float(x).is_integer()).all():
                df[col] = numeric.astype("Int64")
            else:
                df[col] = numeric.astype("Float64")
            continue
        # Default: keep as object, don't call .astype("string")
        df[col] = df[col].astype(object)
    return df

def standardize_business_keys(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for key in BUSINESS_KEYS:
        if key in df.columns:
            df[key] = df[key].astype(object).apply(normalize_key_value)
    return df


def standardize_tables(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    cleaned_tables: Dict[str, pd.DataFrame] = {}
    for name, df in tables.items():
        df = clean_table(df)
        df = standardize_business_keys(df)
        df = standardize_column_types(df)
        cleaned_tables[name] = df
    return cleaned_tables


def find_primary_keys(df: pd.DataFrame) -> List[str]:
    primary_keys: List[str] = []
    if df.empty:
        return primary_keys
    n = len(df)
    for col in df.columns:
        non_null = df[col].notna().sum()
        unique = df[col].nunique(dropna=True)
        if non_null == n and unique == n:
            primary_keys.append(col)
    return primary_keys


def detect_foreign_keys(tables: Dict[str, pd.DataFrame], sample_size: int = 2000) -> List[Dict[str, str]]:
    relationships: List[Dict[str, str]] = []
    table_names = list(tables.keys())
    for src in table_names:
        left = tables[src]
        for dst in table_names:
            if src == dst:
                continue
            right = tables[dst]
            for left_col in left.columns:
                if left_col not in right.columns:
                    continue
                if left_col in BUSINESS_KEYS or left_col.endswith("_id") or left_col.endswith("_code"):
                    left_vals = left[left_col].dropna().astype(str).head(sample_size).unique()
                    right_vals = right[left_col].dropna().astype(str).head(sample_size).unique()
                    if len(left_vals) == 0 or len(right_vals) == 0:
                        continue
                    common = set(left_vals) & set(right_vals)
                    if not common:
                        continue
                    relationships.append({
                        "from_table": src,
                        "from_column": left_col,
                        "to_table": dst,
                        "to_column": left_col,
                        "common_values": len(common),
                    })
    return relationships


def build_dim_client(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    candidates = []
    for name in ["devis_vente_ent_vv", "facture_vente_ent_v", "zz_facture_vente_ent", "gsl_vente_fa_entete"]:
        if name in tables:
            df = tables[name]
            if "cle_client" in df.columns:
                bloc = df[["cle_client"]].dropna().drop_duplicates().copy()
                candidates.append(bloc)
    if not candidates:
        return pd.DataFrame()
    dim = pd.concat(candidates, ignore_index=True).drop_duplicates()
    dim["client_key"] = dim["cle_client"]
    return dim[["client_key"]].drop_duplicates()


def build_dim_fournisseur(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    candidates = []
    if "fournisseurs_v" in tables:
        candidates.append(tables["fournisseurs_v"][['cle_fournisseur', 'nomfournisseur']].rename(columns={'nomfournisseur': 'supplier_name'}))
    if "facture_achat_ent_v" in tables:
        df = tables["facture_achat_ent_v"]
        if "cle_fournisseur" in df.columns:
            candidates.append(df[["cle_fournisseur"]].drop_duplicates())
    if candidates:
        dim = pd.concat(candidates, ignore_index=True, sort=False)
        dim = dim.drop_duplicates(subset=["cle_fournisseur"]) if "cle_fournisseur" in dim.columns else dim
        dim = dim.rename(columns={"cle_fournisseur": "supplier_key"})
        return dim
    return pd.DataFrame()


def build_dim_date(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    date_cols = [col for df in tables.values() for col in df.columns if "date" in col]
    unique_cols = sorted(set(date_cols))
    rows = []
    for df in tables.values():
        for col in unique_cols:
            if col in df.columns and pd.api.types.is_datetime64_any_dtype(df[col]):
                vals = df[col].dropna().astype("datetime64[ns]")
                rows.append(vals)
    if not rows:
        return pd.DataFrame()
    all_dates = pd.Series(pd.concat(rows, ignore_index=True).drop_duplicates()).sort_values().reset_index(drop=True)
    dim = pd.DataFrame({"date": all_dates})
    dim["year"] = dim["date"].dt.year
    dim["month"] = dim["date"].dt.month
    dim["day"] = dim["date"].dt.day
    dim["quarter"] = dim["date"].dt.to_period("Q").astype(str)
    return dim


def build_dim_payment(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    candidates = []
    if "table_nature_paiement_vcsv" in tables:
        df = tables["table_nature_paiement_vcsv"]
        if "naturepaiement" in df.columns:
            candidates.append(df[["naturepaiement", "libelle"]].rename(columns={"naturepaiement": "payment_code", "libelle": "payment_label"}))
    for name in ["gsl_vente_fa_entete", "zz_facture_vente_ent"]:
        if name in tables:
            df = tables[name]
            if "ent_mode_reglement_code" in df.columns or "ent_mode_reglement_libelle" in df.columns:
                cols = [c for c in ["ent_mode_reglement_code", "ent_mode_reglement_libelle"] if c in df.columns]
                candidates.append(df[cols].drop_duplicates().rename(columns={"ent_mode_reglement_code": "payment_code", "ent_mode_reglement_libelle": "payment_label"}))
    if not candidates:
        return pd.DataFrame()
    dim = pd.concat(candidates, ignore_index=True, sort=False).drop_duplicates()
    return dim


def build_fact_ventes(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    source_names = ["facture_vente_ent_v", "zz_facture_vente_ent"]
    facts = []
    for name in source_names:
        if name in tables:
            df = tables[name]
            cols = [col for col in ["cle_client", "cle_devis", "ent_id", "ent_numero", "datepiece", "dateecheance", "ht_dev", "ttc_dev", "devise", "ent_mode_reglement_code", "ent_mode_reglement_libelle"] if col in df.columns]
            if not cols:
                continue
            facts.append(df[cols].assign(source_table=name))
    if not facts:
        return pd.DataFrame()
    fact = pd.concat(facts, ignore_index=True, sort=False).drop_duplicates()
    if "datepiece" in fact.columns:
        fact["payment_delay_days"] = (fact["dateecheance"] - fact["datepiece"]).dt.days if "dateecheance" in fact.columns else pd.NA
    if "ht_dev" in fact.columns and "ttc_dev" in fact.columns:
        fact["tax_amount"] = fact["ttc_dev"] - fact["ht_dev"]
    return fact


def build_fact_achats(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    if "facture_achat_ent_v" not in tables:
        return pd.DataFrame()
    df = tables["facture_achat_ent_v"]
    cols = [col for col in ["cle_fournisseur", "cle_devis", "ent_id", "ent_numero", "datepiece", "dateecheance", "ht_dev", "ttc_dev", "devise", "modereglement", "modereglementlibelle"] if col in df.columns]
    fact = df[cols].copy()
    if "datepiece" in fact.columns and "dateecheance" in fact.columns:
        fact["payment_delay_days"] = (fact["dateecheance"] - fact["datepiece"]).dt.days
    if "ht_dev" in fact.columns and "ttc_dev" in fact.columns:
        fact["tax_amount"] = fact["ttc_dev"] - fact["ht_dev"]
    return fact


def build_fact_devis(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    relevant = [name for name in ["devis_vente_ent_vv", "devis_achat_ent_v"] if name in tables]
    facts = []
    for name in relevant:
        df = tables[name]
        cols = [col for col in ["cle_devis", "cle_client", "cle_fournisseur", "ent_id", "datepiece", "datecreation", "ht_dev", "ttc_dev", "devise", "status"] if col in df.columns]
        if cols:
            row = df[cols].copy()
            row["document_type"] = "purchase" if "achat" in name else "sales"
            facts.append(row)
    if not facts:
        return pd.DataFrame()
    return pd.concat(facts, ignore_index=True, sort=False).drop_duplicates()


def build_fact_bl(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    facts = []
    if "gsl_vente_bl_entete" in tables:
        df = tables["gsl_vente_bl_entete"]
        cols = [col for col in ["ent_numero", "ent_date", "ent_client_code", "ent_client_intitule", "ent_nbr_article", "ent_ht", "ent_ttc", "ent_reference", "ent_depot_code"] if col in df.columns]
        if cols:
            facts.append(df[cols].assign(side="sales"))
    if "gsl_achat_bl_entete" in tables:
        df = tables["gsl_achat_bl_entete"]
        cols = [col for col in ["ent_numero", "ent_date", "ent_fournisseur_code", "ent_fournisseur_intitule", "ent_nbr_article", "ent_ht", "ent_ttc", "ent_reference"] if col in df.columns]
        if cols:
            facts.append(df[cols].assign(side="purchases"))
    if not facts:
        return pd.DataFrame()
    return pd.concat(facts, ignore_index=True, sort=False).drop_duplicates()


def build_fact_payments(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    candidates = []
    if "facture_vente_ent_v" in tables:
        df = tables["facture_vente_ent_v"]
        if "dateecheance" in df.columns:
            cols = [col for col in ["ent_id", "cle_client", "datepiece", "dateecheance", "ttc_dev", "ht_dev", "ent_mode_reglement_code", "ent_mode_reglement_libelle"] if col in df.columns]
            candidates.append(df[cols].assign(document_type="sales_invoice"))
    if "facture_achat_ent_v" in tables:
        df = tables["facture_achat_ent_v"]
        if "dateecheance" in df.columns:
            cols = [col for col in ["ent_id", "cle_fournisseur", "datepiece", "dateecheance", "ttc_dev", "ht_dev", "modereglement", "modereglementlibelle"] if col in df.columns]
            candidates.append(df[cols].assign(document_type="purchase_invoice"))
    if not candidates:
        return pd.DataFrame()
    fact = pd.concat(candidates, ignore_index=True, sort=False).drop_duplicates()
    if "datepiece" in fact.columns and "dateecheance" in fact.columns:
        fact["payment_delay_days"] = (fact["dateecheance"] - fact["datepiece"]).dt.days
        fact["outstanding_estimate"] = fact["ttc_dev"]
    return fact


def build_warehouse_layer(tables_clean: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    warehouse = {
        "Dim_Client": build_dim_client(tables_clean),
        "Dim_Fournisseur": build_dim_fournisseur(tables_clean),
        "Dim_Date": build_dim_date(tables_clean),
        "Dim_Payment": build_dim_payment(tables_clean),
        "Fact_Ventes": build_fact_ventes(tables_clean),
        "Fact_Achats": build_fact_achats(tables_clean),
        "Fact_Devis": build_fact_devis(tables_clean),
        "Fact_BL": build_fact_bl(tables_clean),
        "Fact_Paiements": build_fact_payments(tables_clean),
    }
    return warehouse


def summarize_tables(tables: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, df in tables.items():
        rows.append({
            "table": name,
            "rows": len(df),
            "columns": len(df.columns),
            "primary_keys": find_primary_keys(df),
        })
    return pd.DataFrame(rows)


def prepare_data_layer(data_dir: Path, output_dir: Optional[Path] = None) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]:
    tables = load_all_csvs(data_dir)
    tables_clean = standardize_tables(tables)
    warehouse_tables = build_warehouse_layer(tables_clean)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, df in {**tables_clean, **warehouse_tables}.items():
            if df.empty:
                continue
            path = output_dir / f"{name}.csv"
            df.to_csv(path, index=False)
    return tables_clean, warehouse_tables


if __name__ == "__main__":
    data_dir = Path(__file__).resolve().parent / "data_pfe"
    output_dir = Path(__file__).resolve().parent / "output"
    tables_clean, warehouse = prepare_data_layer(data_dir, output_dir)
    print("Clean tables:")
    print(summarize_tables(tables_clean).to_string(index=False))
    print("\nWarehouse tables:")
    print(summarize_tables(warehouse).to_string(index=False))
