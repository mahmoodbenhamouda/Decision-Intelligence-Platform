"""
ml_engine/analytics/kpi_engine.py
=================================
Moteur de KPIs financiers haute performance basé sur **DuckDB**.

Pourquoi DuckDB ?
-----------------
Les datasets bruts pèsent ~2,5 Go (certains CSV de mouvements dépassent 500 Mo).
Les charger entièrement en mémoire avec pandas est impossible. DuckDB lit les CSV
directement sur disque, en colonnes, sans tout charger en RAM.

Architecture
------------
1. `build_store()` : matérialise UNE FOIS un entrepôt DuckDB compact
   (`output/analytics_store.duckdb`) en ne projetant que les colonnes utiles et en
   pré-agrégeant les gros fichiers de lignes. Reconstruit seulement si les CSV
   sources ont changé.
2. `compute_dashboard(filters)` : interroge l'entrepôt matérialisé (quelques
   millisecondes) en appliquant les filtres en SQL, et renvoie un dictionnaire
   complet de KPIs + séries prêtes pour les graphes du dashboard.

Toutes les datasets sont exploitées (ventes, achats, lignes produits, devis,
fournisseurs, paiements), contrairement à l'ancienne liste blanche qui en
excluait la majorité.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

try:
    from config.settings import settings
    _DEFAULT_DATA_DIR = Path(settings.data_dir)
    _DEFAULT_OUTPUT_DIR = Path(settings.output_dir)
except Exception:  # pragma: no cover - fallback hors application
    _DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data_pfe"
    _DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

STORE_PATH = Path(os.environ.get("ANALYTICS_STORE_PATH", _DEFAULT_OUTPUT_DIR / "analytics_store.duckdb"))

# ─────────────────────────────────────────────────────────────────────────────
# Sources : fichier CSV -> rôle. On choisit UNE source faisant autorité par fait
# pour éviter le double comptage, tout en exploitant les gros fichiers de lignes.
# ─────────────────────────────────────────────────────────────────────────────
SOURCES = {
    "sales":     "Facture_vente_ent_v.csv",      # 128k factures, HT/TTC/échéance/client
    "purchases": "Facture_achat_ent_v.csv",      # factures fournisseurs
    "lines":     "ZZ_Facture_vente_mouv.csv",    # 340k lignes : produits, quantités
    "devis":     "Devis_vente_ent_vv.csv",       # devis (pipeline commercial)
    "suppliers": "Fournisseurs_v.csv",           # référentiel fournisseurs
    "bl":        "Gsl_vente_bl_entete.csv",       # bons de livraison
    "gsl_fa":    "Gsl_vente_fa_entete.csv",       # noms/villes clients + dépôts (dimensions)
}


def _csv(data_dir: Path, name: str) -> str:
    return str((data_dir / name).as_posix())


def _read(name_path: str, sample: int = 8000) -> str:
    return f"read_csv_auto('{name_path}', sample_size={sample}, ignore_errors=true, all_varchar=true)"


def _date(col: str) -> str:
    """Parsing de date robuste : les CSV utilisent le format US M/D/Y (non zéro-paddé).
    On essaie plusieurs formats puis un CAST direct en dernier recours."""
    return (f"COALESCE("
            f"TRY_STRPTIME({col}, '%m/%d/%Y'), "
            f"TRY_STRPTIME({col}, '%Y-%m-%d'), "
            f"TRY_STRPTIME({col}, '%d/%m/%Y'))::DATE")


# ── Normalisation des modes de règlement (déduplication des libellés) ─────────
# Les libellés sources sont incohérents (casse, espaces, "90JOURS", "NULL").
# On nettoie l'affichage, on calcule une clé normalisée pour regrouper les
# variantes (ex. "Virement 60 JOURS" == "Virement 60 jours"), et le libellé
# affiché est la variante réelle la plus fréquente de chaque groupe.
def _mode_clean(col: str = "MODEREGLLIBELLE") -> str:
    # trim + espaces multiples -> un seul + espace entre chiffre et "JOURS"
    return (f"regexp_replace(regexp_replace(trim({col}), '\\s+', ' ', 'g'), "
            f"'([0-9])(JOURS)', '\\1 \\2', 'g')")


def _mode_norm(col: str = "MODEREGLLIBELLE") -> str:
    return (f"CASE WHEN {col} IS NULL OR upper(trim({col})) IN ('', 'NULL') "
            f"THEN 'NON RENSEIGNE' ELSE upper({_mode_clean(col)}) END")


def _mode_label(col: str = "MODEREGLLIBELLE") -> str:
    return (f"CASE WHEN {col} IS NULL OR upper(trim({col})) IN ('', 'NULL') "
            f"THEN 'Non renseigné' ELSE {_mode_clean(col)} END")


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTION DE L'ENTREPÔT MATÉRIALISÉ
# ─────────────────────────────────────────────────────────────────────────────

# Version du schéma de l'entrepôt. À INCRÉMENTER à chaque changement de la logique
# de construction (build_store) pour forcer une reconstruction automatique du store,
# même si les fichiers CSV sources n'ont pas changé.
SCHEMA_VERSION = "v7"


def _sources_signature(data_dir: Path) -> str:
    parts = [f"schema:{SCHEMA_VERSION}"]
    for name in SOURCES.values():
        p = data_dir / name
        if p.exists():
            st = p.stat()
            parts.append(f"{name}:{st.st_size}:{int(st.st_mtime)}")
    return "|".join(sorted(parts))


def build_store(data_dir: Path | None = None, force: bool = False) -> Path:
    """Matérialise l'entrepôt DuckDB compact. Idempotent (reconstruit si CSV modifiés)."""
    data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    signature = _sources_signature(data_dir)

    if STORE_PATH.exists() and not force:
        try:
            con = duckdb.connect(str(STORE_PATH), read_only=True)
            row = con.execute("SELECT signature FROM _build_info LIMIT 1").fetchone()
            con.close()
            if row and row[0] == signature:
                return STORE_PATH  # déjà à jour
        except Exception:
            pass  # entrepôt absent/corrompu -> reconstruire

    con = duckdb.connect(str(STORE_PATH))
    con.execute("SET threads=4;")

    sales_csv = _read(_csv(data_dir, SOURCES["sales"]))
    # Table de correspondance : clé normalisée -> libellé canonique (variante la plus fréquente)
    con.execute(f"""
        CREATE OR REPLACE TABLE mode_map AS
        WITH base AS (
            SELECT {_mode_norm()} AS norm, {_mode_label()} AS orig, count(*) AS n
            FROM {sales_csv} GROUP BY 1, 2
        )
        SELECT norm, max_by(orig, n) AS label FROM base GROUP BY norm
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE sales AS
        WITH raw AS (
            SELECT
                trim(TIERS)                       AS client,
                {_date('DATEPIECE')}              AS date,
                CASE WHEN year({_date('DATEECHEANCE')}) BETWEEN 2000 AND 2035
                     THEN {_date('DATEECHEANCE')} END AS echeance,
                TRY_CAST(HT_DEV      AS DOUBLE)    AS ht,
                TRY_CAST(TTC_DEV     AS DOUBLE)    AS ttc,
                {_mode_norm()}                    AS mode_norm,
                TRY_CAST(NBREARTICLE AS DOUBLE)   AS nbr_article
            FROM {sales_csv}
            WHERE {_date('DATEPIECE')} IS NOT NULL AND TRY_CAST(TTC_DEV AS DOUBLE) IS NOT NULL
        )
        SELECT raw.client, raw.date, raw.echeance, raw.ht, raw.ttc,
               COALESCE(mm.label, 'Non renseigné') AS mode_regl, raw.nbr_article
        FROM raw LEFT JOIN mode_map mm ON raw.mode_norm = mm.norm
    """)
    con.execute("""
        ALTER TABLE sales ADD COLUMN year INTEGER;
        UPDATE sales SET year = year(date);
    """)
    con.execute("""
        ALTER TABLE sales ADD COLUMN payment_delay_days INTEGER;
        UPDATE sales SET payment_delay_days =
            CASE WHEN echeance IS NOT NULL THEN datediff('day', date, echeance) END;
    """)

    # ── DIMENSIONS (schéma en étoile) ────────────────────────────────────────
    gsl_csv = _read(_csv(data_dir, SOURCES["gsl_fa"]))
    # Dim_Client : code -> nom + ville (source fiable GSL, ~97% du CA couvert)
    con.execute(f"""
        CREATE OR REPLACE TABLE dim_client AS
        WITH b AS (
            SELECT trim(ENT_CLIENT_CODE) AS client_code,
                   trim(ENT_CLIENT_INTITULE) AS client_name,
                   trim(ENT_CLIENT_VILLE) AS ville, count(*) AS n
            FROM {gsl_csv}
            WHERE ENT_CLIENT_CODE IS NOT NULL AND trim(ENT_CLIENT_CODE) <> ''
            GROUP BY 1, 2, 3
        )
        SELECT client_code, max_by(client_name, n) AS client_name, max_by(ville, n) AS ville
        FROM b GROUP BY client_code
    """)
    # Dim_Depot
    con.execute(f"""
        CREATE OR REPLACE TABLE dim_depot AS
        WITH b AS (
            SELECT trim(ENT_DEPOT_CODE) AS depot_code, trim(ENT_DEPOT_INTITULE) AS depot_label, count(*) n
            FROM {gsl_csv} WHERE ENT_DEPOT_CODE IS NOT NULL AND trim(ENT_DEPOT_CODE) <> '' GROUP BY 1, 2
        )
        SELECT depot_code, max_by(depot_label, n) AS depot_label FROM b GROUP BY depot_code
    """)
    # Enrichit sales avec le nom client (repli sur le code si absent)
    con.execute("ALTER TABLE sales ADD COLUMN client_name VARCHAR;")
    con.execute("UPDATE sales SET client_name = dc.client_name FROM dim_client dc WHERE dc.client_code = sales.client;")
    con.execute("UPDATE sales SET client_name = client WHERE client_name IS NULL OR client_name = '';")
    # Dim_Date
    con.execute("""
        CREATE OR REPLACE TABLE dim_date AS
        SELECT DISTINCT date, year(date) AS year, month(date) AS month,
               quarter(date) AS quarter, dayofweek(date) AS dow
        FROM sales WHERE date IS NOT NULL
    """)

    purch_csv = _read(_csv(data_dir, SOURCES["purchases"]))
    con.execute(f"""
        CREATE OR REPLACE TABLE purchases AS
        SELECT
            trim(FOURNISSEURNOM)              AS fournisseur,
            trim(CLE_FOURNISSEUR)             AS fournisseur_code,
            {_date('DATEPIECE')}              AS date,
            CASE WHEN year({_date('DATEECHEANCE')}) BETWEEN 2000 AND 2035
                 THEN {_date('DATEECHEANCE')} END AS echeance,
            TRY_CAST(HT_DEV  AS DOUBLE)       AS ht,
            TRY_CAST(TTC_DEV AS DOUBLE)       AS ttc,
            trim(MODEREGLLIBELLE)             AS mode_regl
        FROM {purch_csv}
        WHERE {_date('DATEPIECE')} IS NOT NULL
    """)
    con.execute("ALTER TABLE purchases ADD COLUMN year INTEGER; UPDATE purchases SET year = year(date);")
    con.execute("""
        ALTER TABLE purchases ADD COLUMN payment_delay_days INTEGER;
        UPDATE purchases SET payment_delay_days =
            CASE WHEN echeance IS NOT NULL THEN datediff('day', date, echeance) END;
    """)

    # Lignes produits : pré-agrégé par produit (et par mois pour la tendance)
    lines_csv = _read(_csv(data_dir, SOURCES["lines"]))
    con.execute(f"""
        CREATE OR REPLACE TABLE product_sales AS
        SELECT
            trim(DESIGNATION)                       AS produit,
            year({_date('DATEFACTURE')})            AS year,
            sum(TRY_CAST(MONTANT_DEV AS DOUBLE))    AS ca,
            sum(TRY_CAST(QTEFACTURE  AS DOUBLE))    AS qte,
            count(*)                                AS lignes
        FROM {lines_csv}
        WHERE DESIGNATION IS NOT NULL AND trim(DESIGNATION) <> ''
        GROUP BY 1, 2
    """)
    # Dim_Produit / familles de produits (REACTIF, EQUIPEMENT, SERVICE… ~99% du CA réel)
    con.execute(f"""
        CREATE OR REPLACE TABLE product_family AS
        SELECT
            trim(ARTICLE_LIBELLE_FAM_STAT1)         AS famille,
            year({_date('DATEFACTURE')})            AS year,
            sum(TRY_CAST(MONTANT_DEV AS DOUBLE))    AS ca,
            sum(TRY_CAST(QTEFACTURE  AS DOUBLE))    AS qte
        FROM {lines_csv}
        WHERE ARTICLE_LIBELLE_FAM_STAT1 IS NOT NULL AND trim(ARTICLE_LIBELLE_FAM_STAT1) <> ''
          -- exclut la pollution « démo » résiduelle (fournitures d'art, < 1% du CA)
          AND NOT regexp_matches(upper(trim(ARTICLE_LIBELLE_FAM_STAT1)),
                '(^_)|PEINTURE|LITHOGRAPH|CHEVALET|PINCEAU|BROSSE|AQUARELLE|HUILE')
        GROUP BY 1, 2
    """)

    # Devis (pipeline commercial)
    devis_csv = _read(_csv(data_dir, SOURCES["devis"]))
    con.execute(f"""
        CREATE OR REPLACE TABLE devis AS
        SELECT
            trim(TIERS)                       AS client,
            {_date('DATEPIECE')}              AS date,
            TRY_CAST(HT_DEV  AS DOUBLE)       AS ht,
            TRY_CAST(TTC_DEV AS DOUBLE)       AS ttc,
            trim(STATUS)                      AS status
        FROM {devis_csv}
        WHERE {_date('DATEPIECE')} IS NOT NULL
    """)

    # Bons de livraison
    try:
        bl_csv = _read(_csv(data_dir, SOURCES["bl"]))
        con.execute(f"""
            CREATE OR REPLACE TABLE bl AS
            SELECT
                trim(ENT_CLIENT_CODE)            AS client,
                {_date('ENT_DATE')}              AS date,
                TRY_CAST(ENT_NBR_ARTICLE AS DOUBLE) AS nbr_article
            FROM {bl_csv}
        """)
    except Exception:
        con.execute("CREATE OR REPLACE TABLE bl AS SELECT NULL::VARCHAR client, NULL::DATE date, NULL::DOUBLE nbr_article WHERE 1=0")

    con.execute("CREATE OR REPLACE TABLE _build_info AS SELECT ? AS signature, now() AS built_at", [signature])
    con.close()
    return STORE_PATH


def _connect(data_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    build_store(data_dir)
    return duckdb.connect(str(STORE_PATH), read_only=True)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTION DES FILTRES SQL
# ─────────────────────────────────────────────────────────────────────────────

def _sales_where(f: Dict[str, Any]) -> str:
    f = f or {}
    clauses: List[str] = ["1=1"]
    years = f.get("selected_years") or []
    if years:
        clauses.append("year IN (" + ",".join(str(int(y)) for y in years) + ")")
    if f.get("date_start"):
        clauses.append(f"date >= DATE '{f['date_start']}'")
    if f.get("date_end"):
        clauses.append(f"date <= DATE '{f['date_end']}'")
    clients = f.get("selected_clients") or []
    if clients:
        vals = ",".join("'" + str(c).replace("'", "''") + "'" for c in clients)
        clauses.append(f"client IN ({vals})")
    modes = f.get("payment_modes") or []
    if modes:
        vals = ",".join("'" + str(m).replace("'", "''") + "'" for m in modes)
        clauses.append(f"mode_regl IN ({vals})")
    if f.get("min_amount") is not None:
        clauses.append(f"ttc >= {float(f['min_amount'])}")
    if f.get("max_amount") is not None:
        clauses.append(f"ttc <= {float(f['max_amount'])}")
    risk = f.get("risk_level") or "Tous"
    if risk and risk != "Tous":
        if "heure" in risk:
            clauses.append("payment_delay_days <= 0")
        elif "30" in risk:
            clauses.append("payment_delay_days > 30")
        elif "90" in risk:
            clauses.append("payment_delay_days > 90")
    return " AND ".join(clauses)


def _apply_fidelity(con, where: str, fidelity: str) -> str:
    """Renvoie une clause supplémentaire restreignant aux clients du segment de fidélité."""
    if not fidelity or fidelity == "Tous":
        return ""
    rows = con.execute(f"""
        SELECT client, count(*) n FROM sales WHERE {where} GROUP BY client
    """).fetchall()
    if "Fid" in fidelity:
        keep = [r[0] for r in rows if r[1] > 5]
    elif "gul" in fidelity or "égul" in fidelity or "Regul" in fidelity:
        keep = [r[0] for r in rows if 2 <= r[1] <= 5]
    else:
        keep = [r[0] for r in rows if r[1] == 1]
    if not keep:
        return " AND 1=0"
    vals = ",".join("'" + str(c).replace("'", "''") + "'" for c in keep)
    return f" AND client IN ({vals})"


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONS DE FILTRES (pour l'UI)
# ─────────────────────────────────────────────────────────────────────────────

def get_filter_options(data_dir: Path | None = None) -> Dict[str, Any]:
    con = _connect(data_dir)
    years = [int(r[0]) for r in con.execute(
        "SELECT DISTINCT year FROM sales WHERE year IS NOT NULL ORDER BY year").fetchall()]
    client_rows = con.execute(
        "SELECT client, any_value(client_name) FROM sales GROUP BY client ORDER BY sum(ttc) DESC NULLS LAST LIMIT 400").fetchall()
    clients = [r[0] for r in client_rows if r[0]]
    client_names = {r[0]: (r[1] or r[0]) for r in client_rows if r[0]}
    modes = [r[0] for r in con.execute(
        "SELECT DISTINCT mode_regl FROM sales WHERE mode_regl IS NOT NULL AND mode_regl <> '' ORDER BY 1").fetchall()]
    max_amount = con.execute("SELECT max(ttc) FROM sales").fetchone()[0] or 0.0
    con.close()
    return {
        "available_years": years,
        "available_clients": clients,
        "client_names": client_names,
        "fidelity_options": ["Tous", "Fidèles (> 5 achats)", "Réguliers (2-5 achats)", "Occasionnels (1 achat)"],
        "available_payment_modes": modes,
        "risk_levels": ["Tous", "Payé à l'heure", "Retard > 30j", "Critique > 90j"],
        "max_amount_possible": float(max_amount),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CALCUL COMPLET DES KPIs
# ─────────────────────────────────────────────────────────────────────────────

def _scalar(con, sql: str, default=0):
    r = con.execute(sql).fetchone()
    return r[0] if r and r[0] is not None else default


def _load_client_risk() -> Dict[str, Any]:
    """Scores de risque crédit par client (produits par credit_risk_model.train()).
    Vide si le modèle n'a pas encore été entraîné — l'intégration est optionnelle."""
    path = Path(os.environ.get("CLIENT_RISK_PATH", STORE_PATH.parent / "client_risk.json"))
    if path.exists():
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return {}
    return {}


# Mots-clés métier (pertinence commerciale d'une opportunité) et mots vides pour
# l'extraction de noms de clients depuis un titre d'appel d'offres.
_OPP_KEYWORDS = ["REACTIF", "RÉACTIF", "DIAGNOSTIC", "LABORATOIRE", "IMMUNOLOG", "VIDAS",
                 "SEROLOG", "SÉROLOG", "HEMATOLOG", "HÉMATOLOG", "BIOCHIMIE", "PCR",
                 "ANALYSE", "HOSPITALIER", "HÔPITAL", "HOPITAL", "CHU", "BIOLOGIE"]
_NAME_STOPWORDS = {"LABORATOIRE", "LABO", "HOPITAL", "HÔPITAL", "CENTRE", "CLINIQUE",
                   "POLYCLINIQUE", "SOCIETE", "SOCIÉTÉ", "SARL", "MEDICAL", "MÉDICAL",
                   "SANTE", "SANTÉ", "UNIVERSITAIRE", "REGIONAL", "RÉGIONAL", "GENERAL",
                   "GÉNÉRAL", "PUBLIC", "NATIONAL", "TUNIS", "TUNISIE"}

# Termes MÉTIER FORTS : une opportunité n'est retenue que si l'un d'eux est présent
# (le mot « diagnostic » seul est trop ambigu : diagnostic technique, immobilier…).
_DOMAIN_STRONG = ["REACTIF", "RÉACTIF", "REACTIFS", "RÉACTIFS", "LABORATOIRE", "LABORATOIRES",
                  "BIOLOGIE", "BIOLOGIQUE", "IMMUNOLOG", "SEROLOG", "SÉROLOG", "HEMATOLOG",
                  "HÉMATOLOG", "BIOCHIMIE", "MICROBIOLOG", "BACTERIOLOG", "VIROLOG",
                  "PCR", "VIDAS", "ELISA", "AUTOMATE", "ANALYSEUR", "REACTIF DE LABORATOIRE",
                  "ANALYSES MEDICALES", "ANALYSES MÉDICALES", "DIAGNOSTIC IN VITRO",
                  "DISPOSITIF MEDICAL", "DISPOSITIF MÉDICAL", "DIAGNOSTIC MEDICAL",
                  "DIAGNOSTIC MÉDICAL", "EQUIPEMENT MEDICAL", "ÉQUIPEMENT MÉDICAL",
                  "CONSOMMABLE MEDICAL", "CHU", "HOSPITALIER"]
# Contextes HORS-DOMAINE : si présents, l'opportunité est écartée d'office.
_OFF_DOMAIN = ["MUSEE", "MUSÉE", "BARDO", "PATRIMOINE", "MONUMENT", "TOURIS", "HUILE",
               "OLIVE", "AGRICOL", "AGRICULTURE", "PECHE", "PÊCHE", "IMMOBILIER",
               "BATIMENT", "BÂTIMENT", "ROUTE", "AUTOROUTE", "FOOTBALL", "SPORT",
               "ENERGIE", "ÉNERGIE", "SOLAIRE", "TRANSPORT", "TEXTILE", "PHOSPHATE",
               "EDUCATION", "ÉDUCATION", "UNIVERSITE", "UNIVERSITÉ", "CULTURE"]


def _opp_is_relevant(title_up: str) -> bool:
    """Garde uniquement les opportunités réellement liées au diagnostic médical /
    biologie / réactifs : un terme métier fort doit être présent, et aucun terme
    manifestement hors-domaine."""
    if any(bad in title_up for bad in _OFF_DOMAIN):
        return False
    return any(good in title_up for good in _DOMAIN_STRONG)


def enrich_opportunities(news: List[Dict[str, Any]], data_dir: Path | None = None) -> List[Dict[str, Any]]:
    """Transforme une liste d'opportunités (titres) en aide à la décision :
    croise chaque opportunité avec les clients existants (nom + CA), la qualifie
    (client existant / prospect) et produit une recommandation d'action."""
    import re
    if not news:
        return []
    # Filtre de pertinence métier : on écarte tout ce qui n'est pas diagnostic/labo/santé
    news = [n for n in news if _opp_is_relevant(str(n.get("title") or "").upper())]
    if not news:
        return []
    try:
        con = _connect(data_dir)
        rows = con.execute("""
            SELECT any_value(client_name) nom, sum(ttc) ca
            FROM sales WHERE client_name IS NOT NULL GROUP BY client ORDER BY ca DESC NULLS LAST
        """).fetchall()
        con.close()
    except Exception:
        rows = []

    # token distinctif -> (nom client, CA) — on garde le client au plus fort CA par token
    token_map: Dict[str, Any] = {}
    name_ca: Dict[str, float] = {}
    for nom, ca in rows:
        if not nom:
            continue
        name_ca[nom] = float(ca or 0)
        for tok in re.split(r"[^A-ZÀ-Ÿ0-9]+", str(nom).upper()):
            if len(tok) >= 5 and tok not in _NAME_STOPWORDS:
                if tok not in token_map or (ca or 0) > token_map[tok][1]:
                    token_map[tok] = (nom, float(ca or 0))

    # NLP sémantique (embeddings ou TF-IDF) — rattrape les formulations différentes
    matcher = None
    try:
        from ml_engine.nlp.tender_matcher import TenderMatcher
        cand_names = list(name_ca.keys())
        matcher = TenderMatcher(cand_names) if cand_names else None
    except Exception:
        matcher = None

    out: List[Dict[str, Any]] = []
    for n in news:
        title = str(n.get("title") or "")
        title_up = title.upper()
        item = dict(n)
        item["relevance"] = sum(1 for k in _OPP_KEYWORDS if k in title_up)
        matched = None
        match_method = None
        # 1) chevauchement de tokens (rapide, précis sur noms exacts)
        for tok, (nom, ca) in token_map.items():
            if tok in title_up:
                matched = (nom, ca); match_method = "token"
                break
        # 2) repli sémantique NLP (formulations différentes) si aucun token
        if matched is None and matcher is not None:
            try:
                j, score = matcher.match(title)
                if j >= 0 and score >= 0.55:
                    nom = matcher.candidates[j]
                    matched = (nom, name_ca.get(nom, 0.0)); match_method = f"nlp:{score:.2f}"
                    item["match_score"] = round(float(score), 2)
            except Exception:
                pass
        if matched:
            nom, ca = matched
            item["client"] = nom
            item["client_ca"] = ca
            item["type"] = "Client existant"
            item["match_method"] = match_method
            if ca >= 2_000_000:
                item["reco"] = f"Compte stratégique ({ca/1e6:.1f} M DT de CA) — sécuriser avec une offre dédiée."
            else:
                item["reco"] = "Client existant — relancer et positionner une offre."
        else:
            item["type"] = "Nouveau prospect"
            item["reco"] = "Prospect — qualifier et préparer un devis."
        out.append(item)

    # priorité : clients existants d'abord, puis par pertinence métier
    out.sort(key=lambda x: (x.get("type") != "Client existant", -x.get("relevance", 0)))
    return out


# Mots-clés identifiant un acheteur du secteur public / hospitalier (adossé au
# budget santé public) — sert à mesurer l'exposition du CA au budget santé.
_PUBLIC_CLIENT_KEYWORDS = ["HOPITAL", "HÔPITAL", "CHU", "MILITAIRE", "UNIVERSITAIRE",
                           "REGIONAL", "RÉGIONAL", "INSTITUT", "MINISTERE", "MINISTÈRE",
                           "CNAM", "PUBLIC", "ETAT", "ÉTAT", "FACULTE", "FACULTÉ",
                           "DISPENSAIRE", "SANTE PUBLIQUE", "SANTÉ PUBLIQUE"]


def fx_margin_sensitivity(fx: Dict[str, Any] | None, filters: Dict[str, Any] | None = None,
                          data_dir: Path | None = None) -> Optional[Dict[str, Any]]:
    """Quantifie l'exposition au change SUR LES DONNÉES RÉELLES d'Overlyne.
    Les réactifs étant importés, les achats fournisseurs (`purchases`) forment la
    base de coût libellée en devise. On chiffre donc, en dinars, l'impact d'une
    variation du change sur le coût d'achat annuel — le vrai lien veille ↔ P&L.
    Respecte le filtre ANNÉE (les achats ne suivent que l'année, pas le client)."""
    if not fx:
        return None
    filters = filters or {}
    year_clause = ""
    yrs = filters.get("selected_years") or []
    if yrs:
        year_clause = " AND year IN (" + ",".join(str(int(y)) for y in yrs) + ")"
    try:
        con = _connect(data_dir)
        rows = con.execute(f"""
            SELECT year, sum(ttc) FROM purchases
            WHERE year IS NOT NULL AND year BETWEEN 2015 AND 2035{year_clause}
            GROUP BY year ORDER BY year
        """).fetchall()
        con.close()
    except Exception:
        return None
    years = [(int(y), float(v or 0)) for y, v in rows if v]
    if not years:
        return None
    # Base annuelle = moyenne des années observées (run-rate stable), + dernière année connue
    annual_base = sum(v for _, v in years) / len(years)
    last_year, last_base = years[-1]
    per_1pct = annual_base * 0.01
    res: Dict[str, Any] = {
        "annual_fx_base_dt": round(annual_base, 0),
        "last_year": last_year,
        "last_year_base_dt": round(last_base, 0),
        "impact_per_1pct_dt": round(per_1pct, 0),
        "assumption": "Hypothèse prudente : achats fournisseurs traités comme base de coût en devise (import de réactifs).",
    }
    var = fx.get("eur_tnd_var_pct")
    if isinstance(var, (int, float)) and var:
        res["var_pct"] = round(float(var), 2)
        res["var_impact_dt"] = round(annual_base * float(var) / 100.0, 0)
    return res


def macro_market_context(macro: Dict[str, Any] | None, data_dir: Path | None = None) -> Optional[Dict[str, Any]]:
    """Relie l'indicateur de budget santé à la DÉPENDANCE RÉELLE d'Overlyne au
    secteur public : part du CA réalisée avec des acheteurs publics/hospitaliers."""
    if not macro:
        return None
    try:
        con = _connect(data_dir)
        kw = " OR ".join([f"upper(client_name) LIKE '%{k}%'" for k in _PUBLIC_CLIENT_KEYWORDS])
        row = con.execute(f"""
            SELECT
              sum(ttc) FILTER (WHERE {kw}) AS pub,
              sum(ttc) AS tot
            FROM sales WHERE client_name IS NOT NULL
        """).fetchone()
        con.close()
    except Exception:
        return None
    pub = float(row[0] or 0)
    tot = float(row[1] or 0)
    if tot <= 0:
        return None
    share = pub / tot * 100.0
    sante = (macro.get("sante_pct_pib") or {}).get("value")
    res: Dict[str, Any] = {
        "public_ca_share_pct": round(share, 1),
        "public_ca_dt": round(pub, 0),
        "sante_pct_pib": sante,
    }
    res["note"] = (
        f"{share:.0f}% du CA dépend d'acheteurs publics/hospitaliers, adossés au budget santé "
        f"({sante}% du PIB). Une hausse du budget santé soutient ce segment ; une compression l'expose."
        if sante is not None else
        f"{share:.0f}% du CA dépend d'acheteurs publics/hospitaliers (sensibles au budget santé public)."
    )
    return res


def finance_radar(mi: Dict[str, Any] | None, filters: Dict[str, Any] | None = None,
                  data_dir: Path | None = None) -> List[Dict[str, Any]]:
    """RADAR FINANCIER EXTERNE — traduit les signaux externes en ACTIONS finance
    priorisées et CHIFFRÉES sur les données réelles d'Overlyne, RECALCULÉES SUR LE
    PÉRIMÈTRE FILTRÉ (année, client, mode de règlement, montant, risque, fidélité).

    Trois leviers, chacun reliant un signal externe à un montant interne :
      1. Recouvrement secteur public : créances publiques à terme long (ERP)
         × budget santé public (externe) → priorité de recouvrement.
      2. Exposition change / COGS : base d'achat en devise (ERP) × variation du
         dinar (externe) → décision d'achat / couverture.
      3. Pipeline d'appels d'offres : opportunités qualifiées (externe) croisées
         avec la base clients (ERP) → potentiel commercial.

    Retourne une liste de cartes triées par sévérité puis par montant à risque.
    """
    mi = mi or {}
    filters = filters or {}
    cards: List[Dict[str, Any]] = []
    try:
        con = _connect(data_dir)
    except Exception:
        return []

    # Périmètre dynamique : mêmes filtres que le tableau de bord
    base_where = _sales_where(filters)
    try:
        W = base_where + _apply_fidelity(con, base_where, filters.get("fidelity_filter", "Tous"))
    except Exception:
        W = base_where
    filtre_actif = W.strip() not in ("1=1", "")
    suffixe_perim = " (périmètre filtré)" if filtre_actif else ""

    # ── Levier 1 : recouvrement secteur public ───────────────────────────────
    try:
        kw = " OR ".join([f"upper(client_name) LIKE '%{k}%'" for k in _PUBLIC_CLIENT_KEYWORDS])
        row = con.execute(f"""
            SELECT
              sum(ttc) FILTER (WHERE payment_delay_days > 60)  AS risque,
              sum(ttc) FILTER (WHERE payment_delay_days > 90)  AS critique,
              count(DISTINCT client) FILTER (WHERE payment_delay_days > 60) AS nb_cli
            FROM sales WHERE ({W}) AND client_name IS NOT NULL AND ({kw})
        """).fetchone()
        pub_risque = float(row[0] or 0)
        pub_crit = float(row[1] or 0)
        pub_nb = int(row[2] or 0)
        top = con.execute(f"""
            SELECT any_value(client_name) nom, sum(ttc) FILTER (WHERE payment_delay_days > 60) m
            FROM sales WHERE ({W}) AND client_name IS NOT NULL AND ({kw})
            GROUP BY client HAVING m > 0 ORDER BY m DESC NULLS LAST LIMIT 3
        """).fetchall()
        top_debiteurs = [{"client": (r[0] or "—")[:34], "montant": float(r[1] or 0)} for r in top]
    except Exception:
        pub_risque = pub_crit = 0.0
        pub_nb = 0
        top_debiteurs = []

    # Contexte externe = budget santé public (source officielle Banque Mondiale),
    # proxy de la capacité de paiement du secteur public — bien plus fiable qu'un
    # flux de news généraliste.
    sante = ((mi.get("macro") or {}).get("sante_pct_pib") or {}).get("value")
    if pub_risque > 0:
        sev = "haute" if pub_crit > 0 else "moyenne"
        noms = ", ".join(d["client"] for d in top_debiteurs) or "vos principaux comptes publics"
        ext = (f"Budget santé public à {sante}% du PIB — capacité de paiement du secteur adossée aux "
               f"finances publiques (délais structurellement longs)."
               if sante is not None else
               "Payeurs publics : délais de règlement structurellement longs.")
        cards.append({
            "id": "recouvrement_public", "categorie": "Recouvrement", "severite": sev,
            "titre": "Risque de recouvrement — secteur public" + suffixe_perim,
            "montant_dt": round(pub_risque, 0), "montant_label": "exposition à terme long (>60j)",
            "constat": (f"{pub_risque/1e6:.2f} M DT de créances sur {pub_nb} client(s) public(s) à terme long "
                        f"(>60j), dont {pub_crit/1e6:.2f} M DT critiques (>90j)."),
            "signal_externe": ext,
            "action": (f"Prioriser le recouvrement de {noms}. Exiger un acompte ou une garantie de paiement "
                       f"sur les nouveaux marchés publics à terme long."),
            "top": top_debiteurs,
        })

    # ── Levier 2 : exposition change / COGS ──────────────────────────────────
    fxs = fx_margin_sensitivity(mi.get("fx"), filters, data_dir) or mi.get("fx_sensitivity")
    if fxs:
        var = fxs.get("var_pct")
        var_impact = fxs.get("var_impact_dt")
        base = fxs.get("annual_fx_base_dt") or 0
        if isinstance(var_impact, (int, float)) and var_impact:
            sev = "haute" if var_impact > 0 and abs(var) >= 1.5 else "moyenne"
            sens = "défavorable" if var_impact > 0 else "favorable"
            cards.append({
                "id": "change_cogs", "categorie": "Change / COGS", "severite": sev,
                "titre": "Exposition au change sur les achats importés",
                "montant_dt": round(var_impact, 0), "montant_label": "impact annuel sur le coût d'achat",
                "constat": (f"Variation du dinar de {var:+.1f}% → effet {sens} de {abs(var_impact)/1e3:.0f} K DT "
                            f"sur une base d'achat importée de {base/1e6:.1f} M DT/an."),
                "signal_externe": f"Change EUR/TND : {var:+.1f}% depuis le dernier relevé",
                "action": ("Avancer les commandes fournisseurs et négocier des prix en devise fixes ; "
                           "envisager une couverture de change sur les prochains imports."
                           if var_impact > 0 else
                           "Fenêtre favorable : sécuriser les prochains achats importés au taux actuel."),
                "top": [],
            })
        else:
            per1 = fxs.get("impact_per_1pct_dt") or 0
            cards.append({
                "id": "change_cogs", "categorie": "Change / COGS", "severite": "faible",
                "titre": "Sensibilité au change sur les achats importés",
                "montant_dt": round(per1, 0), "montant_label": "impact par ±1% du dinar",
                "constat": (f"Base d'achat importée de {base/1e6:.1f} M DT/an : ±1% du dinar ≈ "
                            f"±{per1/1e3:.0f} K DT de coût."),
                "signal_externe": "Change EUR/TND stable (référence en cours de constitution)",
                "action": "Surveiller la tendance ; définir un seuil d'alerte de couverture (ex. −2%/mois).",
                "top": [],
            })

    # ── Levier 3 : pipeline d'appels d'offres qualifiés ──────────────────────
    news = mi.get("news") or []
    if news:
        existants = [n for n in news if n.get("type") == "Client existant"]
        # Enjeu = CA annuel des comptes existants concernés (relations à défendre/étendre)
        enjeu = sum(float(n.get("client_ca") or 0) for n in existants)
        cards.append({
            "id": "pipeline", "categorie": "Développement", "severite": "moyenne" if existants else "faible",
            "titre": "Pipeline d'appels d'offres — marché diagnostic",
            "montant_dt": round(enjeu, 0), "montant_label": "CA annuel des comptes concernés",
            "constat": (f"{len(news)} opportunité(s) qualifiée(s), dont {len(existants)} sur des clients existants."),
            "signal_externe": "Marchés publics / actualités du secteur diagnostic (TUNEPS & presse spécialisée)",
            "action": ("Prioriser les opportunités sur clients existants (cycle de vente plus court) ; "
                       "cadrer un devis pour les nouveaux prospects."),
            "top": [{"client": (n.get("client") or n.get("title") or "")[:34],
                     "montant": float(n.get("client_ca") or 0)} for n in existants[:3]],
        })

    try:
        con.close()
    except Exception:
        pass

    # ── Levier 4 : trésorerie prévisionnelle (DEEP LEARNING — LSTM) ───────────
    try:
        from ml_engine.forecasting.lstm_cashflow import load_or_forecast
        fc = load_or_forecast(horizon=6, data_dir=data_dir)
        if fc and fc.get("forecast"):
            total = float(fc.get("encaissement_prevu_total") or 0)
            couverture = (pub_risque / total * 100) if total else 0
            cards.append({
                "id": "tresorerie_lstm", "categorie": "Trésorerie", "severite": "moyenne",
                "titre": "Trésorerie prévisionnelle — 6 mois",
                "montant_dt": round(total, 0), "montant_label": "encaissements prévus (6 mois)",
                "constat": (f"Encaissements attendus sur 6 mois : {total/1e6:.1f} M DT "
                            f"(estimation indicative basée sur l'historique des paiements). "
                            f"L'exposition publique à risque représente {couverture:.0f}% de cet encaissement."),
                "signal_externe": "Projection basée sur l'historique des encaissements et des échéances clients",
                "action": ("Aligner l'intensité des relances sur les mois de moindre encaissement prévu ; "
                           "sécuriser la trésorerie avant les creux."),
                "serie": fc.get("forecast"), "history": fc.get("history"), "top": [],
            })
    except Exception:
        pass

    order = {"haute": 0, "moyenne": 1, "faible": 2}
    cards.sort(key=lambda c: (order.get(c.get("severite"), 3), -(c.get("montant_dt") or 0)))
    for i, c in enumerate(cards):
        c["priorite"] = i + 1
    return cards


def compute_dashboard(filters: Dict[str, Any] | None = None, data_dir: Path | None = None) -> Dict[str, Any]:
    """Calcule l'ensemble des KPIs et séries graphiques sur le périmètre filtré."""
    filters = filters or {}
    con = _connect(data_dir)
    base_where = _sales_where(filters)
    fid_clause = _apply_fidelity(con, base_where, filters.get("fidelity_filter", "Tous"))
    W = base_where + fid_clause  # clause ventes complète
    is_client_scope = bool(filters.get("selected_clients"))
    # La marge n'est fiable que globale ou filtrée par année (les achats suivent
    # l'année mais pas les filtres client/risque/montant/paiement/fidélité).
    marge_non_attribuable = bool(
        filters.get("selected_clients") or filters.get("payment_modes")
        or (filters.get("risk_level") and filters.get("risk_level") != "Tous")
        or filters.get("min_amount") is not None or filters.get("max_amount") is not None
        or (filters.get("fidelity_filter") and filters.get("fidelity_filter") != "Tous")
    )

    k: Dict[str, Any] = {"monthly_sales": [], "top_clients": [], "anomalies_details": []}

    # ── 1. Chiffre d'affaires ────────────────────────────────────────────────
    row = con.execute(f"""
        SELECT sum(ttc) ttc, sum(ht) ht, count(*) nb, count(DISTINCT client) clients,
               avg(payment_delay_days) dso
        FROM sales WHERE {W}
    """).fetchone()
    ca_ttc, ca_ht, nb_fact, nb_clients, dso = (row or (0, 0, 0, 0, 0))
    k["ca_total_ttc"] = float(ca_ttc or 0)
    k["ca_total_ht"] = float(ca_ht or 0)
    k["nb_factures_vente"] = int(nb_fact or 0)
    k["nb_clients"] = int(nb_clients or 0)
    k["panier_moyen"] = (k["ca_total_ttc"] / k["nb_factures_vente"]) if k["nb_factures_vente"] else 0
    k["dso_jours"] = float(dso or 0)

    # ── 2. Tendance mensuelle CA + marge mensuelle ───────────────────────────
    monthly = con.execute(f"""
        SELECT strftime(date, '%Y-%m') period, sum(ttc) revenue, sum(ht) ht
        FROM sales WHERE {W} GROUP BY 1 ORDER BY 1
    """).fetchall()
    k["monthly_sales"] = [{"period": m[0], "revenue": float(m[1] or 0)} for m in monthly]
    if len(monthly) >= 2:
        last, prev = float(monthly[-1][1] or 0), float(monthly[-2][1] or 0)
        k["mom_growth"] = ((last - prev) / prev * 100) if prev else 0
        k["tendance"] = "Haussiere" if last >= prev else "Baissiere"
    else:
        k["mom_growth"] = 0
        k["tendance"] = "Stable"

    # ── 3. CA annuel + croissance YoY ────────────────────────────────────────
    yearly = con.execute(f"SELECT year, sum(ttc) FROM sales WHERE {W} GROUP BY year ORDER BY year").fetchall()
    k["yearly_sales"] = [{"year": int(y[0]), "revenue": float(y[1] or 0)} for y in yearly if y[0] is not None]
    # Croissance sur 12 mois glissants (robuste aux années partielles)
    ttm = con.execute(f"""
        WITH m AS (SELECT max(date) mx FROM sales WHERE {W})
        SELECT
          sum(ttc) FILTER (WHERE date >  (SELECT mx FROM m) - INTERVAL '12 months')                                  AS ttm_v,
          sum(ttc) FILTER (WHERE date <= (SELECT mx FROM m) - INTERVAL '12 months'
                             AND date >  (SELECT mx FROM m) - INTERVAL '24 months')                                 AS prev_v
        FROM sales WHERE {W}
    """).fetchone()
    ttm_v, prior_v = float(ttm[0] or 0), float(ttm[1] or 0)
    k["ttm_revenue"] = ttm_v
    k["yoy_growth"] = ((ttm_v - prior_v) / prior_v * 100) if prior_v else 0

    # ── 2bis. Comparaison année courante vs année précédente (par mois) ───────
    yrs = [int(r[0]) for r in con.execute(
        f"SELECT DISTINCT year FROM sales WHERE {W} AND year IS NOT NULL ORDER BY year DESC").fetchall()]
    mois_lbl = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    if yrs:
        cy = yrs[0]
        py = yrs[1] if len(yrs) > 1 else None
        prev_expr = f"sum(ttc) FILTER (WHERE year = {py})" if py is not None else "NULL"
        rows = con.execute(f"""
            SELECT month(date) m, sum(ttc) FILTER (WHERE year = {cy}) cur, {prev_expr} prev
            FROM sales WHERE {W} GROUP BY 1 ORDER BY 1
        """).fetchall()
        k["yoy_comparison"] = {
            "current_year": cy, "previous_year": py,
            "data": [{
                "month": mois_lbl[int(r[0]) - 1],
                "courante": (float(r[1]) if r[1] is not None else None),
                "precedente": (float(r[2]) if r[2] is not None else None),
            } for r in rows if r[0]],
        }
        ca_cur = sum((d["courante"] or 0) for d in k["yoy_comparison"]["data"])
        ca_prev = sum((d["precedente"] or 0) for d in k["yoy_comparison"]["data"])
        k["yoy_comparison"]["delta_pct"] = ((ca_cur - ca_prev) / ca_prev * 100) if ca_prev else None
    else:
        k["yoy_comparison"] = {"current_year": None, "previous_year": None, "data": [], "delta_pct": None}

    # ── 4. Saisonnalité (CA moyen par mois calendaire) ───────────────────────
    seas = con.execute(f"""
        SELECT month(date) m, sum(ttc) total, count(DISTINCT year) ny
        FROM sales WHERE {W} GROUP BY 1 ORDER BY 1
    """).fetchall()
    mois = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    k["seasonality"] = [{"month": mois[int(s[0]) - 1], "revenue": float((s[1] or 0) / (s[2] or 1))} for s in seas if s[0]]

    # ── 5. Délais de paiement / DSO / risque ─────────────────────────────────
    # NB : les données contiennent la date de pièce et la date d'échéance mais PAS
    # la date de paiement effective. `payment_delay_days` = délai de crédit ACCORDÉ.
    # On qualifie de "à risque" les termes longs (> 60 j) et de "critiques" (> 90 j),
    # car un délai accordé long accroît le DSO et l'exposition au risque de crédit.
    drow = con.execute(f"""
        SELECT
          count(*) FILTER (WHERE payment_delay_days > 90)              c90,
          count(*) FILTER (WHERE payment_delay_days > 60)              c60,
          count(*) FILTER (WHERE payment_delay_days > 30)              c30,
          count(*) FILTER (WHERE payment_delay_days IS NOT NULL)       tot,
          sum(ttc) FILTER (WHERE payment_delay_days > 60)              montant_risque,
          sum(ttc) FILTER (WHERE payment_delay_days > 90)              montant_critique
        FROM sales WHERE {W}
    """).fetchone()
    c90, c60, c30, tot_delay, mt_risque, mt_crit = drow
    k["retards_critiques"] = int(c90 or 0)
    k["retards_30j"] = int(c30 or 0)
    k["retards_60j"] = int(c60 or 0)
    k["paiements_total_analyses"] = int(tot_delay or 0)
    k["paiements_a_risque_count"] = int(c60 or 0)
    k["paiements_a_risque_pct"] = float((c60 or 0) / tot_delay * 100) if tot_delay else 0
    k["montant_risque_ttc"] = float(mt_risque or 0)
    k["montant_critique_ttc"] = float(mt_crit or 0)
    # Libellé honnête : montant_risque_ttc additionne le TTC de TOUTES les factures
    # de l'historique réglées avec >60j de retard → c'est un comportement de paiement,
    # PAS un encours dû aujourd'hui (le schéma n'a ni statut payé/impayé ni solde).
    k["ca_retard_historique_ttc"] = float(mt_risque or 0)
    k["ca_retard_historique_critique_ttc"] = float(mt_crit or 0)

    # ── Exposition RÉCENTE (proxy actionnable pour le recouvrement) ───────────
    # On borne aux échéances des 6 derniers mois (relatif à la dernière échéance
    # des données) → chiffre réaliste au lieu de 5 ans d'historique cumulé.
    rec = con.execute(f"""
        WITH ref AS (SELECT max(echeance) md FROM sales WHERE {W})
        SELECT sum(ttc) FILTER (WHERE payment_delay_days > 60) expo,
               sum(ttc) FILTER (WHERE payment_delay_days > 90) crit,
               count(*) FILTER (WHERE payment_delay_days > 60) cnt,
               strftime((SELECT md FROM ref), '%Y-%m') ref_mois
        FROM sales
        WHERE {W} AND echeance >= (SELECT md FROM ref) - INTERVAL 6 MONTH
    """).fetchone()
    k["exposition_recente_dt"] = float(rec[0] or 0)
    k["exposition_recente_critique_dt"] = float(rec[1] or 0)
    k["exposition_recente_count"] = int(rec[2] or 0)
    k["exposition_recente_periode"] = f"échéances des 6 mois jusqu'à {rec[3]}" if rec[3] else "6 derniers mois"

    # Clients à relancer, bornés à l'exposition récente
    k["clients_relance"] = [{
        "client": r[0], "nom": r[1] or r[0], "montant_risque": float(r[2] or 0), "factures": int(r[3] or 0),
    } for r in con.execute(f"""
        WITH ref AS (SELECT max(echeance) md FROM sales WHERE {W})
        SELECT client, any_value(client_name) nom,
               sum(ttc) FILTER (WHERE payment_delay_days > 60) m,
               count(*) FILTER (WHERE payment_delay_days > 60) n
        FROM sales
        WHERE {W} AND client_name IS NOT NULL
          AND echeance >= (SELECT md FROM ref) - INTERVAL 6 MONTH
        GROUP BY client HAVING m > 0 ORDER BY m DESC NULLS LAST LIMIT 8
    """).fetchall()]

    # Structure des délais accordés (tranches) -> graphe empilé / barres
    aging = con.execute(f"""
        SELECT
          sum(ttc) FILTER (WHERE payment_delay_days <= 0)                         AS comptant,
          sum(ttc) FILTER (WHERE payment_delay_days > 0  AND payment_delay_days <= 30) AS j30,
          sum(ttc) FILTER (WHERE payment_delay_days > 30 AND payment_delay_days <= 60) AS j60,
          sum(ttc) FILTER (WHERE payment_delay_days > 60 AND payment_delay_days <= 90) AS j90,
          sum(ttc) FILTER (WHERE payment_delay_days > 90)                          AS j90p
        FROM sales WHERE {W}
    """).fetchone()
    labels = ["Comptant", "0-30 j", "31-60 j", "61-90 j", "90 j +"]
    k["aging_creances"] = [{"bucket": labels[i], "montant": float(aging[i] or 0)} for i in range(5)]

    # ── 6. Top clients + concentration (HHI, Pareto) ─────────────────────────
    top = con.execute(f"""
        SELECT client, any_value(client_name) nom, sum(ttc) revenue, count(*) invoices,
               sum(ttc) FILTER (WHERE payment_delay_days > 30) risque
        FROM sales WHERE {W} GROUP BY client ORDER BY revenue DESC NULLS LAST LIMIT 10
    """).fetchall()
    g = k["ca_total_ttc"] or 1
    k["top_clients"] = [{
        "client": t[0], "nom": t[1] or t[0], "revenue": float(t[2] or 0), "invoices": int(t[3] or 0),
        "share": float((t[2] or 0) / g * 100), "rank": i + 1,
        "risque": float(t[4] or 0),
    } for i, t in enumerate(top)]
    k["top_clients_revenue_share"] = float(sum(c["revenue"] for c in k["top_clients"][:5]) / g * 100)

    # ── Clients fidèles : la fidélité = RÉCURRENCE dans le temps, pas seulement
    # le CA. On classe par nb de mois d'achat distincts, puis nb de factures, puis CA.
    fideles = con.execute(f"""
        SELECT client, any_value(client_name) nom, sum(ttc) revenue, count(*) invoices,
               count(DISTINCT strftime(date, '%Y-%m')) mois_actifs,
               strftime(min(date), '%Y-%m') premier, strftime(max(date), '%Y-%m') dernier
        FROM sales WHERE {W} AND client_name IS NOT NULL AND date IS NOT NULL
          AND client_name NOT ILIKE '%passager%' AND client_name NOT ILIKE '%comptant%'
          AND client_name NOT ILIKE '%divers%' AND client_name NOT ILIKE '%espèce%'
        GROUP BY client
        HAVING count(*) >= 2
        ORDER BY mois_actifs DESC, invoices DESC, revenue DESC NULLS LAST
        LIMIT 8
    """).fetchall()
    k["clients_fideles"] = [{
        "client": r[0], "nom": r[1] or r[0], "revenue": float(r[2] or 0),
        "invoices": int(r[3] or 0), "mois_actifs": int(r[4] or 0),
        "premier": r[5], "dernier": r[6], "share": float((r[2] or 0) / g * 100),
    } for r in fideles]

    # ── Clients qui décrochent : clients établis (>=6 mois d'activité) dont le CA
    # des 90 derniers jours a chuté de >60% vs les 90 jours précédents.
    decroche = con.execute(f"""
        WITH ref AS (SELECT max(date) md FROM sales WHERE {W}),
        pc AS (
          SELECT client, any_value(client_name) nom, max(date) last_date,
                 count(DISTINCT strftime(date, '%Y-%m')) mois_actifs,
                 sum(ttc) FILTER (WHERE date >= (SELECT md FROM ref) - INTERVAL 90 DAY) ca_recent,
                 sum(ttc) FILTER (WHERE date >= (SELECT md FROM ref) - INTERVAL 180 DAY
                                   AND date <  (SELECT md FROM ref) - INTERVAL 90 DAY) ca_prev
          FROM sales WHERE {W} AND client_name IS NOT NULL AND date IS NOT NULL
            AND client_name NOT ILIKE '%passager%' AND client_name NOT ILIKE '%comptant%'
            AND client_name NOT ILIKE '%divers%'
          GROUP BY client
        )
        SELECT nom, strftime(last_date, '%Y-%m') dernier, mois_actifs,
               coalesce(ca_recent, 0) cr, coalesce(ca_prev, 0) cp,
               datediff('day', last_date, (SELECT md FROM ref)) jours_inactif
        FROM pc
        WHERE mois_actifs >= 6 AND coalesce(ca_prev, 0) > 0
          AND coalesce(ca_recent, 0) < ca_prev * 0.4
        ORDER BY (ca_prev - coalesce(ca_recent, 0)) DESC NULLS LAST
        LIMIT 8
    """).fetchall()
    k["clients_decrochent"] = [{
        "nom": d[0], "dernier": d[1], "mois_actifs": int(d[2] or 0),
        "ca_recent": float(d[3] or 0), "ca_prev": float(d[4] or 0),
        "jours_inactif": int(d[5] or 0),
        "chute_pct": float((1 - (d[3] or 0) / d[4]) * 100) if d[4] else 0.0,
    } for d in decroche]

    # ── Concentration du CA : nb de clients réalisant 80% du CA (règle de Pareto)
    conc = con.execute(f"""
        WITH s AS (SELECT client, sum(ttc) r FROM sales WHERE {W} GROUP BY client),
        ranked AS (
          SELECT r, sum(r) OVER () tot, sum(r) OVER (ORDER BY r DESC) cum,
                 row_number() OVER (ORDER BY r DESC) rn, count(*) OVER () n FROM s
        )
        SELECT min(rn) FILTER (WHERE cum >= 0.8 * tot), max(n) FROM ranked
    """).fetchone()
    k["clients_pour_80pct"] = int(conc[0] or 0)
    k["nb_clients_ca"] = int(conc[1] or 0)

    # HHI clients (indice de Herfindahl-Hirschman, sur 10000)
    hhi = con.execute(f"""
        WITH s AS (SELECT client, sum(ttc) r FROM sales WHERE {W} GROUP BY client),
             tot AS (SELECT sum(r) t FROM s)
        SELECT sum(power(r/(SELECT t FROM tot)*100, 2)) FROM s WHERE (SELECT t FROM tot) > 0
    """).fetchone()[0]
    k["hhi_clients"] = float(hhi or 0)

    # Courbe de Pareto (concentration) : part cumulée du CA par décile de clients
    pareto = con.execute(f"""
        WITH s AS (
          SELECT client, sum(ttc) r FROM sales WHERE {W} GROUP BY client
        ), ranked AS (
          SELECT r, row_number() OVER (ORDER BY r DESC) rn, count(*) OVER () n,
                 sum(r) OVER () tot, sum(r) OVER (ORDER BY r DESC) cum
          FROM s
        )
        SELECT round(rn*100.0/n) pct_clients, max(cum/tot*100) pct_ca
        FROM ranked GROUP BY 1 ORDER BY 1
    """).fetchall()
    # réduit à ~20 points pour le graphe
    k["client_pareto"] = [{"pct_clients": float(p[0]), "pct_ca": float(p[1] or 0)} for p in pareto if p[0] % 5 == 0]

    # ── 7. Mix des modes de paiement (camembert) ─────────────────────────────
    mix = con.execute(f"""
        SELECT coalesce(NULLIF(mode_regl, ''), 'Non renseigné') AS mode_label,
               sum(ttc) montant, count(*) nb
        FROM sales WHERE {W} GROUP BY 1 ORDER BY montant DESC NULLS LAST LIMIT 8
    """).fetchall()
    k["payment_mix"] = [{"mode": m[0], "montant": float(m[1] or 0), "count": int(m[2] or 0)} for m in mix]

    # ── 8. Prévision d'encaissement (échéances par mois) ─────────────────────
    cash = con.execute(f"""
        SELECT strftime(echeance, '%Y-%m') m, sum(ttc) montant
        FROM sales WHERE {W} AND echeance IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    k["cash_forecast"] = [{"period": c[0], "montant": float(c[1] or 0)} for c in cash][-18:]

    # ── 9. Distribution des montants de facture (histogramme) ────────────────
    dist = con.execute(f"""
        SELECT CASE
                 WHEN ttc < 500   THEN '< 500'
                 WHEN ttc < 1000  THEN '0.5-1K'
                 WHEN ttc < 5000  THEN '1-5K'
                 WHEN ttc < 10000 THEN '5-10K'
                 WHEN ttc < 50000 THEN '10-50K'
                 ELSE '50K +' END tranche,
               count(*) nb
        FROM sales WHERE {W}
        GROUP BY 1
    """).fetchall()
    order = {'< 500': 0, '0.5-1K': 1, '1-5K': 2, '5-10K': 3, '10-50K': 4, '50K +': 5}
    k["amount_distribution"] = sorted(
        [{"tranche": d[0], "count": int(d[1] or 0)} for d in dist],
        key=lambda x: order.get(x["tranche"], 9))

    # ── 10. Achats / fournisseurs (toutes ventes hors périmètre client) ──────
    # Les achats ne dépendent pas du filtre client ; on applique l'année si choisie.
    purch_where = "1=1"
    if filters.get("selected_years"):
        purch_where = "year IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    prow = con.execute(f"""
        SELECT sum(ttc) ttc, count(*) nb, count(DISTINCT fournisseur) nf, avg(payment_delay_days) dpo
        FROM purchases WHERE {purch_where}
    """).fetchone()
    k["achats_total_ttc"] = float(prow[0] or 0)
    k["nb_factures_achat"] = int(prow[1] or 0)
    k["nb_fournisseurs"] = int(prow[2] or 0)
    k["dpo_jours"] = float(prow[3] or 0)

    k["top_fournisseurs"] = [{
        "fournisseur": (r[0] or r[1] or "—")[:32], "montant": float(r[2] or 0),
        "share": float((r[2] or 0) / (k["achats_total_ttc"] or 1) * 100), "rank": i + 1,
    } for i, r in enumerate(con.execute(f"""
        SELECT fournisseur, fournisseur_code, sum(ttc) m
        FROM purchases WHERE {purch_where} GROUP BY 1,2 ORDER BY m DESC NULLS LAST LIMIT 8
    """).fetchall())]
    hhi_f = con.execute(f"""
        WITH s AS (SELECT fournisseur, sum(ttc) r FROM purchases WHERE {purch_where} GROUP BY 1),
             tot AS (SELECT sum(r) t FROM s)
        SELECT sum(power(r/(SELECT t FROM tot)*100,2)) FROM s WHERE (SELECT t FROM tot) > 0
    """).fetchone()[0]
    k["hhi_fournisseurs"] = float(hhi_f or 0)

    # Tendance achats mensuelle (pour comparer à la vente)
    pm = con.execute(f"""
        SELECT strftime(date, '%Y-%m') period, sum(ttc) achats
        FROM purchases WHERE {purch_where} GROUP BY 1 ORDER BY 1
    """).fetchall()
    pm_map = {p[0]: float(p[1] or 0) for p in pm}
    # série combinée ventes vs achats alignée sur les mois de vente
    k["sales_vs_purchases"] = [
        {"period": m["period"], "ventes": m["revenue"], "achats": pm_map.get(m["period"], 0)}
        for m in k["monthly_sales"]
    ]

    # ── 11. Marge ────────────────────────────────────────────────────────────
    if marge_non_attribuable:
        k["marge_brute"] = None
        k["taux_marge"] = None
        k["marge_quality_score"] = None
        k["marge_note"] = "Marge non attribuable sur ce périmètre filtré (les achats ne suivent que le filtre année)."
    else:
        marge = k["ca_total_ht"] - k["achats_total_ttc"]
        k["marge_brute"] = float(marge)
        k["taux_marge"] = float(marge / k["ca_total_ht"] * 100) if k["ca_total_ht"] else 0
        k["marge_quality_score"] = float(max(0, min(100, k["taux_marge"])))
        k["marge_note"] = ("Marge commerciale estimée (CA HT − achats TTC). Le périmètre des achats "
                           "peut différer de celui des ventes.")

    # marge mensuelle estimée (CA HT - achats du mois)
    k["monthly_margin"] = [
        {"period": m["period"],
         "marge": float(con_row_ht(con, W, m["period"]) - pm_map.get(m["period"], 0))}
        for m in k["monthly_sales"]
    ] if not marge_non_attribuable else []

    # ── 11bis. Cascade « du CA au résultat » (waterfall P&L) ─────────────────
    if not marge_non_attribuable and k.get("ca_total_ht"):
        k["waterfall"] = [
            {"step": "CA HT", "value": float(k["ca_total_ht"]), "kind": "start"},
            {"step": "Achats", "value": -float(k["achats_total_ttc"]), "kind": "neg"},
            {"step": "Marge brute", "value": float(k["marge_brute"]), "kind": "total"},
        ]
    else:
        k["waterfall"] = []

    # ── 12. Devis (pipeline) + taux de conversion ────────────────────────────
    dwhere = "1=1"
    if filters.get("selected_years"):
        dwhere = "year(date) IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    drow = con.execute(f"SELECT count(*), sum(ttc), count(DISTINCT client) FROM devis WHERE {dwhere}").fetchone()
    k["nb_devis"] = int(drow[0] or 0)
    k["montant_devis_total"] = float(drow[1] or 0)
    nb_clients_devis = int(drow[2] or 0)
    # Taux de transformation = % des clients prospectés (devisés) ayant effectivement facturé
    converted = int(_scalar(con, f"""
        SELECT count(DISTINCT d.client) FROM devis d
        WHERE {dwhere.replace('year(date)', 'year(d.date)')}
          AND d.client IN (SELECT DISTINCT client FROM sales WHERE {W})
    """)) if nb_clients_devis else 0
    k["taux_conversion_devis"] = float(min(100, converted / nb_clients_devis * 100)) if nb_clients_devis else 0
    nb_bl = int(_scalar(con, "SELECT count(*) FROM bl"))
    k["nb_bl"] = nb_bl
    k["montant_bl_total"] = None
    k["funnel"] = [
        {"etape": "Devis", "valeur": k["nb_devis"]},
        {"etape": "Clients convertis", "valeur": converted},
        {"etape": "Clients facturés", "valeur": k["nb_clients"]},
    ]

    # ── 13. Top produits (respecte le filtre année) ──────────────────────────
    prod_where = "1=1"
    if filters.get("selected_years"):
        prod_where = "year IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    prods = con.execute(f"""
        SELECT produit, sum(ca) ca, sum(qte) qte FROM product_sales
        WHERE {prod_where} GROUP BY produit ORDER BY ca DESC NULLS LAST LIMIT 10
    """).fetchall()
    k["top_produits"] = [{
        "produit": (p[0] or "—").strip()[:38], "ca": float(p[1] or 0), "qte": float(p[2] or 0),
    } for p in prods]
    k["nb_produits"] = int(_scalar(con, f"SELECT count(DISTINCT produit) FROM product_sales WHERE {prod_where}"))

    # Top familles de produits (REACTIF, EQUIPEMENT, SERVICE…)
    fam = con.execute(f"""
        SELECT famille, sum(ca) ca FROM product_family
        WHERE {prod_where} GROUP BY famille ORDER BY ca DESC NULLS LAST LIMIT 6
    """).fetchall()
    k["top_familles"] = [{"famille": (f[0] or "—").strip()[:28], "ca": float(f[1] or 0)} for f in fam]

    # ── 14. Clients à risque (exposition échue) ──────────────────────────────
    k["clients_a_risque"] = [{
        "client": r[0], "nom": r[1] or r[0], "montant_risque": float(r[2] or 0), "factures": int(r[3] or 0),
    } for r in con.execute(f"""
        SELECT client, any_value(client_name) nom,
               sum(ttc) FILTER (WHERE payment_delay_days > 60) m,
               count(*) FILTER (WHERE payment_delay_days > 60) n
        FROM sales WHERE {W} GROUP BY client HAVING m > 0 ORDER BY m DESC LIMIT 8
    """).fetchall()]

    # ── 15bis. Score de risque crédit PRÉDIT (modèle ML, si entraîné) ─────────
    # Table de noms clients (code -> nom) pour enrichir les classements
    name_map = {r[0]: (r[1] or r[0]) for r in con.execute("SELECT client_code, client_name FROM dim_client").fetchall()}

    risk_map = _load_client_risk()
    if risk_map:
        for c in k["top_clients"]:
            c["risk_score"] = risk_map.get(c["client"], {}).get("score")
        for c in k["clients_a_risque"]:
            c["risk_score"] = risk_map.get(c["client"], {}).get("score")
        scope_clients = [r[0] for r in con.execute(f"SELECT DISTINCT client FROM sales WHERE {W}").fetchall()]
        enriched = []
        expo_ponderee = 0.0
        nb_high = 0
        for cl in scope_clients:
            v = risk_map.get(cl)
            if not v:
                continue
            score = float(v.get("score", 0))
            expo = float(v.get("exposure", 0))
            # Exposition pondérée par le risque = probabilité × encours (argent à risque)
            priority = score / 100.0 * expo
            expo_ponderee += priority
            if score > 70:
                nb_high += 1
            enriched.append({
                "client": cl, "nom": name_map.get(cl, cl), "score": score, "exposure": expo,
                "avg_delay": float(v.get("avg_delay", 0)), "priority": priority,
            })
        k["nb_clients_risque_predit"] = nb_high
        k["exposition_risque_ponderee"] = expo_ponderee
        # Classement par priorité de recouvrement (argent à risque), pas juste la proba
        k["risk_ranking"] = sorted(enriched, key=lambda x: -x["priority"])[:10]
        k["risk_model_active"] = True
    else:
        k["nb_clients_risque_predit"] = None
        k["exposition_risque_ponderee"] = None
        k["risk_ranking"] = []
        k["risk_model_active"] = False

    # ── 15. Anomalies ────────────────────────────────────────────────────────
    neg = int(_scalar(con, f"SELECT count(*) FROM sales WHERE {W} AND ttc < 0"))
    zero = int(_scalar(con, f"SELECT count(*) FROM sales WHERE {W} AND ttc = 0"))
    if k["retards_critiques"]:
        k["anomalies_details"].append(f"{k['retards_critiques']} facture(s) avec délai accordé > 90 jours.")
    warn = k["retards_30j"] - k["retards_critiques"]
    if warn > 0:
        k["anomalies_details"].append(f"{warn} facture(s) avec délai accordé de 30 à 90 jours.")
    if neg:
        k["anomalies_details"].append(f"{neg} facture(s) avec montant négatif (avoirs).")
    if zero:
        k["anomalies_details"].append(f"{zero} facture(s) avec montant nul.")
    if k["hhi_clients"] > 2500:
        k["anomalies_details"].append(f"Forte concentration client (HHI={k['hhi_clients']:.0f} > 2500).")
    k["anomalies_detectees"] = int(k["retards_critiques"] + neg + zero)
    if not k["anomalies_details"]:
        k["anomalies_details"] = ["Aucune anomalie majeure détectée."]

    # ── 16. BFR / cycle de trésorerie ────────────────────────────────────────
    k["cash_conversion_cycle"] = float(k["dso_jours"] - k["dpo_jours"])

    con.close()
    return k


def con_row_ht(con, where: str, period: str) -> float:
    r = con.execute(f"SELECT sum(ht) FROM sales WHERE {where} AND strftime(date,'%Y-%m') = '{period}'").fetchone()
    return float(r[0] or 0) if r else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# CLI de test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    force = "--force" in os.sys.argv
    print("Construction de l'entrepôt…")
    build_store(force=force)
    print("OK. Calcul des KPIs (sans filtre)…")
    kpis = compute_dashboard({})
    preview = {key: v for key, v in kpis.items() if not isinstance(v, list)}
    print(json.dumps(preview, indent=2, ensure_ascii=False, default=str))
    print("\nSéries:", {key: len(v) for key, v in kpis.items() if isinstance(v, list)})
