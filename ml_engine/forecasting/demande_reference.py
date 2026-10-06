"""Prévision de la demande **par référence** — le chaînon qui manquait entre le volume agrégé et…"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from ml_engine.typologie import est_hopital_public

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE / "reports"
MODELS_DIR = BASE / "models"
RAPPORT = "demande_reference_metrics.json"

try:
    from ml_engine.analytics.kpi_engine import STORE_PATH as STORE
except Exception:  # pragma: no cover
    STORE = BASE / "output" / "analytics_store.duckdb"

DEBUT_EXPLOITABLE = "2021-01"
FAMILLE = "REACTIF"
HORIZONS = (1, 2, 3)
N_VALIDATION = 12
N_TEST = 18
MIN_MOIS_ACTIFS_24 = 6
SEUIL_GAIN_PTS = 2.0
N_BOOTSTRAP = 2000
RAFRAICHISSEMENT = 3
SEED = 42


REQUETE_LIGNES = """
    SELECT trim(reference) AS reference, upper(trim(designation)) AS designation,
           famille, client, date_trunc('month', date)::DATE AS mois,
           sum(qte) AS qte, sum(montant) AS montant, sum(cout) AS cout
    FROM sales_lines
    WHERE date IS NOT NULL AND year(date) >= 2017
    GROUP BY ALL
"""


REQUETE_DEVIS = """
    SELECT client, date_trunc('month', date)::DATE AS mois, count(*) AS n_devis, sum(ht) AS ht
    FROM devis WHERE date IS NOT NULL GROUP BY ALL
"""


@dataclass
class Donnees:
    """Tout ce que le module lit, sous une forme indépendante de la source."""
    lignes: pd.DataFrame
    positions: pd.DataFrame
    clients: pd.DataFrame
    devis: Optional[pd.DataFrame] = None
    source: str = ""


def _lire_parquet(chemin: Path) -> pd.DataFrame:
    """Lecture par DuckDB, déjà requis par la plateforme : pandas exigerait pyarrow, qui n'est pas une…"""
    import duckdb
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT * FROM read_parquet('{Path(chemin).as_posix()}')").df()
    finally:
        con.close()


def ecrire_parquet(df: pd.DataFrame, chemin: Path) -> None:
    """Pendant de `_lire_parquet`, sans pyarrow."""
    import duckdb
    con = duckdb.connect()
    try:
        con.register("t", df)
        con.execute(f"COPY t TO '{Path(chemin).as_posix()}' (FORMAT parquet)")
    finally:
        con.close()


def charger(store: Optional[Path] = None, extrait: Optional[Path] = None) -> Donnees:
    """Lit l'entrepôt (production) ou un extrait parquet (expérimentation)."""
    if extrait is not None:
        e = Path(extrait)
        lignes = _lire_parquet(e / "ventes_ref_client_mois.parquet")
        positions = _lire_parquet(e / "stock_position_mensuelle.parquet")
        clients = _lire_parquet(e / "dim_client.parquet")
        devis = (_lire_parquet(e / "devis_client_mois.parquet")
                 if (e / "devis_client_mois.parquet").exists() else None)
        src = f"extrait parquet de l'entrepôt ({e.name})"
    else:
        import duckdb
        con = duckdb.connect(str(store or STORE), read_only=True)
        try:
            try:
                from ml_engine.determinisme import limiter_duckdb
                limiter_duckdb(con)
            except Exception:
                pass
            lignes = con.execute(REQUETE_LIGNES).df()
            positions = con.execute(
                "SELECT cle, mois, entrees, sorties, position_fin, cout_unitaire "
                "FROM stock_position_mensuelle").df()
            clients = con.execute("SELECT client_code, client_name FROM dim_client").df()
            devis = con.execute(REQUETE_DEVIS).df()
        finally:
            con.close()
        src = f"entrepôt {store or STORE}"
    lignes["mois"] = pd.to_datetime(lignes["mois"])
    positions["mois"] = pd.to_datetime(positions["mois"])
    if devis is not None:
        devis["mois"] = pd.to_datetime(devis["mois"])
    return Donnees(lignes=lignes, positions=positions, clients=clients, devis=devis, source=src)


def exporter_extrait(dossier: Path, store: Optional[Path] = None) -> None:
    """Extrait parquet pour rejouer l'étude hors de l'application."""
    import duckdb
    dossier.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(store or STORE), read_only=True)
    try:
        con.execute(f"COPY ({REQUETE_LIGNES}) TO '{(dossier / 'ventes_ref_client_mois.parquet').as_posix()}' (FORMAT parquet)")
        con.execute("COPY (SELECT cle, mois, entrees, sorties, position_fin, cout_unitaire "
                    f"FROM stock_position_mensuelle) TO '{(dossier / 'stock_position_mensuelle.parquet').as_posix()}' (FORMAT parquet)")
        con.execute(f"COPY (SELECT client_code, client_name FROM dim_client) TO '{(dossier / 'dim_client.parquet').as_posix()}' (FORMAT parquet)")
        con.execute(f"COPY ({REQUETE_DEVIS}) TO '{(dossier / 'devis_client_mois.parquet').as_posix()}' (FORMAT parquet)")
    finally:
        con.close()


def classer_etablissement(nom: Optional[str]) -> str:
    """Même typologie que `ml_engine/models/demand_features.py` : un hôpital public achète par marché…"""
    u = (nom or "").upper()
    if est_hopital_public(nom):
        return "HOPITAL_PUBLIC"
    if any(k in u for k in ("CLINIQUE", "POLYCLINIQUE")):
        return "CLINIQUE_PRIVEE"
    if any(k in u for k in ("LABO", "LABORATOIRE", "ANALYSE", "BIOLOG")):
        return "LABORATOIRE"
    return "AUTRE"


TYPES_ETAB = ("HOPITAL_PUBLIC", "CLINIQUE_PRIVEE", "LABORATOIRE", "AUTRE")


@dataclass
class Panel:
    """La demande sous forme matricielle : une ligne par référence, une colonne par mois."""
    refs: List[str]
    mois: pd.DatetimeIndex
    Y: np.ndarray
    montant: np.ndarray
    clients_type: Dict[str, np.ndarray]
    hhi: np.ndarray
    n_clients: np.ndarray
    entrees: np.ndarray
    position: np.ndarray
    gamme: List[str]
    designation: List[str]
    C: np.ndarray = None
    couple_ref: np.ndarray = None
    couple_client: np.ndarray = None
    D: np.ndarray = None
    designations: Dict[str, List[str]] = field(default_factory=dict)
    exclus: Dict[str, Any] = field(default_factory=dict)


def construire_panel(d: Donnees, fin: Optional[str] = None) -> Panel:
    """Matrice référence × mois sur la période exploitable."""
    L = d.lignes
    L = L[(L["famille"] == FAMILLE) & L["reference"].notna() & (L["reference"] != "")]
    dernier = L["mois"].max()
    fin_ts = pd.Timestamp(fin + "-01") if fin else (dernier - pd.offsets.MonthBegin(1))
    L = L[(L["mois"] >= pd.Timestamp(DEBUT_EXPLOITABLE + "-01")) & (L["mois"] <= fin_ts)]
    mois = pd.date_range(DEBUT_EXPLOITABLE + "-01", fin_ts, freq="MS")

    q = L.groupby(["reference", "mois"])["qte"].sum()
    negatifs = int((q < 0).sum())
    Yd = q.clip(lower=0).unstack(fill_value=0.0).reindex(columns=mois, fill_value=0.0)
    refs = list(Yd.index)
    idx = {r: i for i, r in enumerate(refs)}
    col = {m: j for j, m in enumerate(mois)}
    n, T = len(refs), len(mois)

    montant = (L.groupby(["reference", "mois"])["montant"].sum()
               .unstack(fill_value=0.0).reindex(index=refs, columns=mois, fill_value=0.0).values)

    noms = dict(zip(d.clients["client_code"].astype(str), d.clients["client_name"]))
    Lc = L.assign(type_etab=L["client"].astype(str).map(lambda c: classer_etablissement(noms.get(c))))
    qc = Lc.groupby(["reference", "mois", "client", "type_etab"])["qte"].sum().clip(lower=0).reset_index()
    clients_type = {t: np.zeros((n, T)) for t in TYPES_ETAB}
    for (r, m, t), v in qc.groupby(["reference", "mois", "type_etab"])["qte"].sum().items():
        if r in idx and m in col:
            clients_type[t][idx[r], col[m]] = v
    tot = qc.groupby(["reference", "mois"])["qte"].transform("sum")
    qc["part2"] = np.where(tot > 0, (qc["qte"] / tot.replace(0, np.nan)) ** 2, 0.0)
    hhi = np.full((n, T), np.nan)
    ncl = np.zeros((n, T))
    for (r, m), g in qc.groupby(["reference", "mois"]):
        if r in idx and m in col and g["qte"].sum() > 0:
            hhi[idx[r], col[m]] = g["part2"].sum()
            ncl[idx[r], col[m]] = int((g["qte"] > 0).sum())

    des = (L.groupby(["reference", "designation"])["qte"].sum().reset_index()
           .sort_values(["reference", "qte"], ascending=[True, False])
           .drop_duplicates("reference").set_index("reference")["designation"])
    designation = [str(des.get(r, "")) for r in refs]
    premiers = [s.split()[0] if s.split() else "?" for s in designation]
    freq = pd.Series(premiers).value_counts()
    gamme = [p if freq.get(p, 0) >= 5 else "AUTRE" for p in premiers]

    rattache = (L.groupby(["designation", "reference"])["qte"].sum().reset_index()
                .sort_values(["designation", "qte"], ascending=[True, False])
                .drop_duplicates("designation").set_index("designation")["reference"])
    P = d.positions.copy()
    P["reference"] = P["cle"].map(rattache)
    P = P[P["reference"].notna() & P["mois"].isin(mois)]
    ent = (P.groupby(["reference", "mois"])["entrees"].sum().unstack(fill_value=0.0)
           .reindex(index=refs, columns=mois, fill_value=0.0).values)
    pos = (P.groupby(["reference", "mois"])["position_fin"].sum().unstack()
           .reindex(index=refs, columns=mois).values)

    cq = qc.groupby(["reference", "client", "mois"])["qte"].sum()
    couples = cq.reset_index()[["reference", "client"]].drop_duplicates().reset_index(drop=True)
    cidx = {(r, c): i for i, (r, c) in enumerate(zip(couples["reference"], couples["client"]))}
    clients_u = sorted(set(couples["client"].astype(str)) | set(
        d.devis["client"].astype(str)) if d.devis is not None else set(couples["client"].astype(str)))
    cli_idx = {c: i for i, c in enumerate(clients_u)}
    C = np.zeros((len(couples), T))
    for (r, c, m), v in cq.items():
        if m in col:
            C[cidx[(r, c)], col[m]] = v
    couple_ref = np.array([idx[r] for r in couples["reference"]])
    couple_client = np.array([cli_idx[str(c)] for c in couples["client"]])
    D = np.zeros((len(clients_u), T))
    if d.devis is not None:
        for c, m, v in zip(d.devis["client"].astype(str), d.devis["mois"], d.devis["ht"]):
            if m in col and c in cli_idx:
                D[cli_idx[c], col[m]] += float(v or 0)
    libelles = L.groupby("reference")["designation"].apply(lambda s: sorted(set(s))).to_dict()

    return Panel(refs=refs, mois=mois, Y=Yd.values.astype(float), montant=montant,
                 clients_type=clients_type, hhi=hhi, n_clients=ncl,
                 entrees=ent, position=pos, gamme=gamme, designation=designation,
                 C=C, couple_ref=couple_ref, couple_client=couple_client, D=D,
                 designations={r: libelles.get(r, []) for r in refs},
                 exclus={"mois_reference_negatifs_ramenes_a_zero": negatifs,
                         "dernier_mois_des_donnees": str(dernier.date()),
                         "dernier_mois_retenu": str(fin_ts.date())})


def eligibles(p: Panel, o: int) -> np.ndarray:
    """Masque des références prévues à l'origine `o` (colonne du dernier mois observé)."""
    fen24 = p.Y[:, max(0, o - 23):o + 1]
    fen12 = p.Y[:, max(0, o - 11):o + 1]
    return ((fen24 > 0).sum(axis=1) >= MIN_MOIS_ACTIFS_24) & ((fen12 > 0).sum(axis=1) >= 1)


def origines(p: Panel) -> Dict[str, List[int]]:
    """Indices d'origine (dernier mois observé) pour la validation et le test."""
    T = p.Y.shape[1]
    test = list(range(T - 1 - N_TEST, T - 1))
    val = list(range(test[0] - N_VALIDATION, test[0]))
    return {"validation": val, "test": test}


def _croston(y: np.ndarray, alpha: float, variante: str) -> float:
    """Croston (1972), SBA (Syntetos-Boylan 2005) ou TSB (Teunter-Syntetos- Babai 2011) sur une série,…"""
    nz = np.flatnonzero(y > 0)
    if len(nz) == 0:
        return 0.0
    if variante == "tsb":
        prob, taille = float((y > 0).mean()), float(y[nz].mean())
        for t in range(len(y)):
            occ = 1.0 if y[t] > 0 else 0.0
            prob += alpha * (occ - prob)
            if occ:
                taille += alpha * (y[t] - taille)
        return prob * taille
    taille, intervalle, dernier = float(y[nz[0]]), float(nz[0] + 1), nz[0]
    for t in nz[1:]:
        taille += alpha * (y[t] - taille)
        intervalle += alpha * ((t - dernier) - intervalle)
        dernier = t
    f = taille / max(intervalle, 1.0)
    return f * (1 - alpha / 2) if variante == "sba" else f


def regles(p: Panel, o: int, h: int, masque: np.ndarray) -> Dict[str, np.ndarray]:
    """Toutes les règles simples, pour l'horizon `h`, à l'origine `o`."""
    Y = p.Y[masque, :o + 1]
    out: Dict[str, np.ndarray] = {"zero": np.zeros(len(Y)), "naif": Y[:, -1].copy()}
    s = o + h - 12
    out["naif_saisonnier"] = p.Y[masque, s] if s >= 0 else Y[:, -1].copy()
    for k in (3, 6, 12):
        out[f"moyenne_{k}"] = Y[:, -k:].mean(axis=1)
        out[f"mediane_{k}"] = np.median(Y[:, -k:], axis=1)
    hist = Y[:, -24:]
    for a in (0.1, 0.2, 0.3):
        for v in ("croston", "sba", "tsb"):
            out[f"{v}_{a:.1f}"] = np.array([_croston(y, a, v) for y in hist])
    if s >= 0:
        prec = p.Y[masque, max(0, o - 23):o - 11].mean(axis=1)
        rec = Y[:, -12:].mean(axis=1)
        ratio = np.where(prec > 0, rec / np.maximum(prec, 1e-9), 1.0)
        out["saisonnier_niveau"] = p.Y[masque, s] * np.clip(ratio, 0.5, 2.0)
    else:
        out["saisonnier_niveau"] = out["naif_saisonnier"].copy()
    return out


VARIABLES_ETENDUES = False


def variables_clients(p: Panel, o: int, h: int, masque: np.ndarray) -> Dict[str, np.ndarray]:
    """Deux signaux construits au niveau du client, puis ramenés à la référence."""
    n_ref = len(p.refs)
    s = o + h - 12
    reachat = np.zeros(n_ref)
    if s - 1 >= 0:
        q = p.C[:, s - 1:s + 2].sum(axis=1)
        depuis = p.C[:, s + 2:o + 1].sum(axis=1) if s + 2 <= o else np.zeros(len(q))
        garde = (q > 0) & (depuis == 0)
        reachat = np.bincount(p.couple_ref[garde], weights=q[garde], minlength=n_ref)
    v12 = p.C[:, max(0, o - 11):o + 1].sum(axis=1)
    tot = np.bincount(p.couple_ref, weights=v12, minlength=n_ref)
    w = np.where(tot[p.couple_ref] > 0, v12 / np.maximum(tot[p.couple_ref], 1e-9), 0.0)
    recent = p.D[:, max(0, o - 2):o + 1].sum(axis=1)
    habituel = p.D[:, max(0, o - 14):max(0, o - 2)].mean(axis=1) * 3 if o >= 3 else np.zeros(len(recent))
    rel_client = np.where(habituel > 0, recent / np.maximum(habituel, 1e-9), np.where(recent > 0, 2.0, 1.0))
    rel_client = np.clip(rel_client, 0, 5)
    devis_rel = np.bincount(p.couple_ref, weights=w * rel_client[p.couple_client], minlength=n_ref)
    devis_abs = np.bincount(p.couple_ref, weights=w * recent[p.couple_client], minlength=n_ref)
    return {"reachat_attendu": reachat[masque], "devis_clients_relatif": devis_rel[masque],
            "devis_clients_3m_dt": devis_abs[masque]}


def variables(p: Panel, o: int, h: int, masque: np.ndarray,
              etendues: Optional[bool] = None) -> pd.DataFrame:
    """Variables à l'origine `o` pour l'horizon `h`, strictement rétrospectives (colonnes ≤ o), sauf le…"""
    Y = p.Y[masque, :o + 1]
    n = len(Y)
    f: Dict[str, Any] = {}
    for k in range(12):
        f[f"lag_{k}"] = Y[:, -1 - k] if o - k >= 0 else np.full(n, np.nan)
    for j, nom in ((12, "saison_1"), (24, "saison_2")):
        s = o + h - j
        f[nom] = p.Y[masque, s] if s >= 0 else np.full(n, np.nan)
    for k in (3, 6, 12, 24):
        w = Y[:, -k:]
        f[f"moy_{k}"] = w.mean(axis=1)
        f[f"med_{k}"] = np.median(w, axis=1)
    f["ecart_type_12"] = Y[:, -12:].std(axis=1)
    f["max_12"] = Y[:, -12:].max(axis=1)
    f["part_zeros_12"] = (Y[:, -12:] == 0).mean(axis=1)
    prec = p.Y[masque, max(0, o - 23):o - 11] if o >= 12 else np.zeros((n, 1))
    f["moy_12_precedente"] = prec.mean(axis=1)
    f["croissance_12"] = np.where(f["moy_12_precedente"] > 0,
                                  f["moy_12"] / np.maximum(f["moy_12_precedente"], 1e-9), np.nan)
    actifs = Y > 0
    jamais = ~actifs.any(axis=1)
    f["mois_depuis_derniere_vente"] = np.where(
        jamais, float(Y.shape[1]), np.argmax(actifs[:, ::-1], axis=1).astype(float))
    f["anciennete"] = np.where(jamais, 0.0, (Y.shape[1] - np.argmax(actifs, axis=1)).astype(float))
    f["mois_actifs_24"] = (Y[:, -24:] > 0).sum(axis=1)
    h24 = Y[:, -24:]
    nzc = (h24 > 0).sum(axis=1)
    f["adi"] = np.where(nzc > 0, h24.shape[1] / np.maximum(nzc, 1), np.nan)
    mnz = np.where(nzc > 0, (h24 * (h24 > 0)).sum(axis=1) / np.maximum(nzc, 1), 0.0)
    vnz = np.array([np.var(r[r > 0]) if (r > 0).sum() > 1 else np.nan for r in h24])
    f["cv2"] = np.where(mnz > 0, vnz / np.maximum(mnz, 1e-9) ** 2, np.nan)
    tot12 = sum(p.clients_type[t][masque, max(0, o - 11):o + 1].sum(axis=1) for t in TYPES_ETAB)
    for t in TYPES_ETAB:
        v = p.clients_type[t][masque, max(0, o - 11):o + 1].sum(axis=1)
        f[f"part_{t.lower()}"] = np.where(tot12 > 0, v / np.maximum(tot12, 1e-9), np.nan)
    fen_hhi = p.hhi[masque, max(0, o - 11):o + 1]
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            f["hhi_12"] = np.nanmean(fen_hhi, axis=1)
    f["n_clients_max_mensuel_12"] = p.n_clients[masque, max(0, o - 11):o + 1].max(axis=1)
    ca12 = p.montant[masque, max(0, o - 11):o + 1].sum(axis=1)
    q12 = Y[:, -12:].sum(axis=1)
    f["prix_moyen_12"] = np.where(q12 > 0, ca12 / np.maximum(q12, 1e-9), np.nan)
    f["achats_3"] = p.entrees[masque, max(0, o - 2):o + 1].sum(axis=1)
    f["achats_12"] = p.entrees[masque, max(0, o - 11):o + 1].sum(axis=1)
    f["position_fin"] = p.position[masque, o]
    tot = p.Y.sum(axis=0)
    f["marche_dernier_mois"] = np.full(n, tot[o])
    f["marche_meme_mois_an_passe"] = np.full(n, tot[o + h - 12] if o + h - 12 >= 0 else np.nan)
    f["marche_moy_12"] = np.full(n, tot[max(0, o - 11):o + 1].mean())
    m_cible = (p.mois[o] + pd.DateOffset(months=h)).month
    f["mois_cible"] = np.full(n, m_cible)
    f["horizon"] = np.full(n, h)
    if (VARIABLES_ETENDUES if etendues is None else etendues) and p.C is not None:
        f.update(variables_clients(p, o, h, masque))
    df = pd.DataFrame(f)
    df["gamme"] = pd.Categorical(np.array(p.gamme)[masque])
    return df


COLONNES_QUANTITE = [f"lag_{k}" for k in range(12)] + [
    "saison_1", "saison_2", "moy_3", "moy_6", "moy_12", "moy_24", "med_3", "med_6",
    "med_12", "med_24", "ecart_type_12", "max_12", "moy_12_precedente", "achats_3",
    "achats_12", "position_fin", "reachat_attendu"]


def echelle(X: pd.DataFrame) -> np.ndarray:
    """Échelle d'une série : moyenne des 12 derniers mois, bornée par le bas."""
    return np.maximum(X["moy_12"].values, 0.5)


def jeu(p: Panel, origines_: Sequence[int], h: int, avec_cible: bool = True
        ) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """Empile les variables de plusieurs origines."""
    Xs, ys, rs, os_ = [], [], [], []
    T = p.Y.shape[1]
    for o in origines_:
        if avec_cible and o + h >= T:
            continue
        m = eligibles(p, o)
        if not m.any():
            continue
        X = variables(p, o, h, m)
        Xs.append(X)
        ys.append(p.Y[m, o + h] if avec_cible else np.full(m.sum(), np.nan))
        rs.append(np.flatnonzero(m))
        os_.append(np.full(m.sum(), o))
    X = pd.concat(Xs, ignore_index=True)
    X["gamme"] = pd.Categorical(X["gamme"].astype(str), categories=sorted(set(p.gamme)))
    return X, np.concatenate(ys), np.concatenate(rs), np.concatenate(os_)


def wape(y: np.ndarray, yhat: np.ndarray) -> float:
    s = float(np.sum(y))
    return float(100 * np.sum(np.abs(y - yhat)) / s) if s > 0 else float("nan")


def biais(y: np.ndarray, yhat: np.ndarray) -> float:
    s = float(np.sum(y))
    return float(100 * np.sum(yhat - y) / s) if s > 0 else float("nan")


def ecart_bootstrap(y: np.ndarray, a: np.ndarray, b: np.ndarray, refs: np.ndarray,
                    n: int = N_BOOTSTRAP, graine: int = SEED) -> Dict[str, Any]:
    """IC95 de WAPE(a) − WAPE(b) par rééchantillonnage des RÉFÉRENCES."""
    rng = np.random.default_rng(graine)
    u, inv = np.unique(refs, return_inverse=True)
    k = len(u)
    ea = np.bincount(inv, weights=np.abs(y - a), minlength=k)
    eb = np.bincount(inv, weights=np.abs(y - b), minlength=k)
    sy = np.bincount(inv, weights=y, minlength=k)
    diffs = np.empty(n)
    for i in range(n):
        t = rng.integers(0, k, k)
        s = sy[t].sum()
        diffs[i] = 100 * (ea[t].sum() - eb[t].sum()) / s if s > 0 else 0.0
    obs = 100 * (ea.sum() - eb.sum()) / sy.sum()
    bas, haut = np.percentile(diffs, [2.5, 97.5])
    return {"ecart_pts": round(float(obs), 2), "ic95": [round(float(bas), 2), round(float(haut), 2)],
            "significatif": bool(bas > 0 or haut < 0), "n_references": int(k)}


def predictions_regles(p: Panel, origines_: Sequence[int], h: int
                       ) -> Tuple[Dict[str, np.ndarray], np.ndarray, np.ndarray, np.ndarray]:
    T = p.Y.shape[1]
    preds: Dict[str, List[np.ndarray]] = {}
    ys, rs, os_ = [], [], []
    for o in origines_:
        if o + h >= T:
            continue
        m = eligibles(p, o)
        for nom, v in regles(p, o, h, m).items():
            preds.setdefault(nom, []).append(v)
        ys.append(p.Y[m, o + h]); rs.append(np.flatnonzero(m)); os_.append(np.full(m.sum(), o))
    return ({k: np.concatenate(v) for k, v in preds.items()},
            np.concatenate(ys), np.concatenate(rs), np.concatenate(os_))


def choisir_regle(p: Panel, h: int = 1) -> Tuple[str, Dict[str, float]]:
    """La meilleure règle SUR LA VALIDATION — jamais sur le test."""
    preds, y, _, _ = predictions_regles(p, origines(p)["validation"], h)
    scores = {k: round(wape(y, v), 2) for k, v in preds.items()}
    return min(scores, key=scores.get), scores


REGLE_DE_REFERENCE = "mediane_12"
CHALLENGER: Dict[str, Any] = {
    "famille": "lightgbm",
    "params": {"perte": "l1", "normaliser": True, "learning_rate": 0.025493358257169668,
               "n_estimators": 450, "num_leaves": 20, "min_child_samples": 13,
               "subsample": 0.7033815530200243, "colsample_bytree": 0.9536817594211415,
               "reg_lambda": 6.643439211977513},
}


def _lgbm(cfg: Dict[str, Any]):
    import lightgbm as lgb
    q = {k: v for k, v in cfg.items() if k not in ("perte", "normaliser", "tweedie_p")}
    perte = cfg.get("perte", "l1")
    extra: Dict[str, Any] = {"objective": perte}
    if perte == "tweedie":
        extra["tweedie_variance_power"] = cfg.get("tweedie_p", 1.5)
    if perte == "quantile":
        extra["alpha"] = 0.5
    return lgb.LGBMRegressor(**q, **extra, subsample_freq=1, random_state=SEED, n_jobs=1,
                             deterministic=True, force_row_wise=True, verbose=-1)


def _normaliser(X: pd.DataFrame, actif: bool) -> Tuple[pd.DataFrame, np.ndarray]:
    X = X.copy()
    e = echelle(X) if actif else np.ones(len(X))
    if actif:
        for c in COLONNES_QUANTITE:
            if c in X:
                X[c] = X[c] / e
    return X, e


def entrainer_lgbm(p: Panel, jusqu_a: int, h: int, cfg: Optional[Dict[str, Any]] = None):
    """Entraîne sur toutes les origines dont la cible est connue à `jusqu_a`."""
    cfg = cfg or CHALLENGER["params"]
    X, y, _, _ = jeu(p, range(12, jusqu_a - h + 1), h)
    X, e = _normaliser(X, cfg.get("normaliser", True))
    m = _lgbm(cfg)
    m.fit(X, y / e)
    return m


def predire_lgbm(modele, p: Panel, o: int, h: int, masque: np.ndarray,
                 cfg: Optional[Dict[str, Any]] = None) -> np.ndarray:
    cfg = cfg or CHALLENGER["params"]
    X = variables(p, o, h, masque)
    X["gamme"] = pd.Categorical(X["gamme"].astype(str), categories=sorted(set(p.gamme)))
    X, e = _normaliser(X, cfg.get("normaliser", True))
    return np.maximum(modele.predict(X) * e, 0.0)


def walk_forward_appris(p: Panel, origines_: Sequence[int], h: int,
                        entrainer: Callable[[int], Any],
                        predire: Callable[[Any, int, np.ndarray], np.ndarray],
                        rafraichissement: int = RAFRAICHISSEMENT
                        ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Walk-forward d'un modèle appris : réentraîné tous les `rafraichissement` mois sur le seul passé,…"""
    T = p.Y.shape[1]
    modele, depuis = None, None
    yh, ys, rs, os_ = [], [], [], []
    for o in origines_:
        if o + h >= T:
            continue
        if modele is None or o - depuis >= rafraichissement:
            modele, depuis = entrainer(o), o
        m = eligibles(p, o)
        yh.append(predire(modele, o, m))
        ys.append(p.Y[m, o + h]); rs.append(np.flatnonzero(m)); os_.append(np.full(m.sum(), o))
    return np.concatenate(yh), np.concatenate(ys), np.concatenate(rs), np.concatenate(os_)


def _long_methode(p: Panel, origines_: Sequence[int], methode: str) -> pd.DataFrame:
    """Prévisions h = 1..3 d'une méthode (règle ou challenger), format long."""
    lignes = []
    for h in HORIZONS:
        if methode == "challenger":
            yh, y, r, o = walk_forward_appris(
                p, origines_, h, entrainer=lambda o_: entrainer_lgbm(p, o_, h),
                predire=lambda m_, o_, mk: predire_lgbm(m_, p, o_, h, mk))
        else:
            preds, y, r, o = predictions_regles(p, origines_, h)
            yh = preds[methode]
        lignes.append(pd.DataFrame({"h": h, "origine": o, "ref": r, "y": y, "yhat": yh}))
    return pd.concat(lignes, ignore_index=True)


def _wape_h(df: pd.DataFrame, h: int) -> float:
    s = df[df.h == h]
    return round(wape(s.y.values, s.yhat.values), 2)


def _cumul(df: pd.DataFrame) -> pd.DataFrame:
    piv = df.pivot_table(index=["origine", "ref"], columns="h", values=["y", "yhat"]).dropna()
    return pd.DataFrame({"origine": piv.index.get_level_values(0), "ref": piv.index.get_level_values(1),
                         "y": piv["y"].sum(axis=1).values, "yhat": piv["yhat"].sum(axis=1).values})


def classe_demande(y: np.ndarray) -> str:
    """Classe de demande de Syntetos & Boylan (2005) : ADI (intervalle moyen entre deux ventes) et CV²…"""
    nz = y[y > 0]
    if len(nz) < 2:
        return "insuffisante"
    adi = len(y) / len(nz)
    cv2 = (nz.std() / nz.mean()) ** 2
    if adi < 1.32:
        return "reguliere" if cv2 < 0.49 else "erratique"
    return "intermittente" if cv2 < 0.49 else "irreguliere"


def groupe_de_calibration(p: Panel, r: int, o: int) -> str:
    """« reguliere » ou « autre », d'après les 24 mois précédant l'origine."""
    return "reguliere" if classe_demande(p.Y[r, max(0, o - 23):o + 1]) == "reguliere" else "autre"


GROUPES = ("reguliere", "autre")


def _ecarts(p: Panel, sub: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    ech = np.array([max(p.Y[r, max(0, o - 11):o + 1].mean(), 0.5)
                    for r, o in zip(sub.ref.values, sub.origine.values)])
    grp = np.array([groupe_de_calibration(p, r, o) for r, o in zip(sub.ref.values, sub.origine.values)])
    return (sub.y.values - sub.yhat.values) / ech, ech, grp


def calibrer_borne(p: Panel, df: pd.DataFrame, niveau: float = 0.8) -> Dict[str, Dict[str, float]]:
    """Quantiles conformes de l'écart normalisé (y − ŷ) / échelle, par groupe, à 1 mois et sur le cumul…"""
    out: Dict[str, Dict[str, float]] = {}
    for cle, sub in (("h1", df[df.h == 1]), ("cumul_3_mois", _cumul(df))):
        e, _, g = _ecarts(p, sub)
        out[cle] = {k: round(float(np.quantile(e[g == k], niveau)), 4) for k in GROUPES if (g == k).any()}
    return out


def couverture(p: Panel, df: pd.DataFrame, qs: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """Part des cas où la demande réelle reste sous la borne — par groupe."""
    out: Dict[str, Dict[str, float]] = {}
    for cle, sub in (("h1", df[df.h == 1]), ("cumul_3_mois", _cumul(df))):
        e, _, g = _ecarts(p, sub)
        q = np.array([qs[cle].get(k, max(qs[cle].values())) for k in g])
        ok = e <= q
        out[cle] = {"ensemble": round(float(ok.mean()), 4),
                    **{k: round(float(ok[g == k].mean()), 4) for k in GROUPES if (g == k).any()}}
    return out


def train(store: Optional[Path] = None, extrait: Optional[Path] = None,
          ecrire: bool = True) -> Dict[str, Any]:
    """Rejoue le duel règle de référence / challenger sur les 18 derniers mois, applique la règle de…"""
    try:
        from ml_engine.determinisme import etat as etat_determinisme, limiter_threads
    except Exception:  # pragma: no cover
        from contextlib import nullcontext as limiter_threads  # type: ignore
        etat_determinisme = lambda: {}  # noqa: E731
    d = charger(store=store, extrait=extrait)
    p = construire_panel(d)
    O = origines(p)
    with limiter_threads(1):
        try:
            ch_test = _long_methode(p, O["test"], "challenger")
            ch_val = _long_methode(p, O["validation"], "challenger")
            challenger_ok, motif_indispo = True, None
        except ImportError as e:
            challenger_ok, motif_indispo = False, f"challenger indisponible ({e})"
        ref_test = _long_methode(p, O["test"], REGLE_DE_REFERENCE)
        ref_val = _long_methode(p, O["validation"], REGLE_DE_REFERENCE)

    comp = None
    servi = False
    if challenger_ok:
        a = ref_test[ref_test.h == 1].sort_values(["origine", "ref"])
        b = ch_test[ch_test.h == 1].sort_values(["origine", "ref"])
        comp = ecart_bootstrap(a.y.values, a.yhat.values, b.yhat.values, a.ref.values)
        servi = bool(comp["ecart_pts"] >= SEUIL_GAIN_PTS and comp["ic95"][0] > 0)
    val_servie, test_servie = (ch_val, ch_test) if servi else (ref_val, ref_test)
    qs = calibrer_borne(p, val_servie)

    def bloc(df: Optional[pd.DataFrame]) -> Optional[Dict[str, Any]]:
        if df is None:
            return None
        s1 = df[df.h == 1]
        cu = _cumul(df)
        return {"wape_h1_pct": _wape_h(df, 1), "wape_h2_pct": _wape_h(df, 2), "wape_h3_pct": _wape_h(df, 3),
                "wape_cumul_3_mois_pct": round(wape(cu.y.values, cu.yhat.values), 2),
                "biais_h1_pct": round(biais(s1.y.values, s1.yhat.values), 2)}

    nom_ch = f"{CHALLENGER['famille']} (perte {CHALLENGER['params'].get('perte')})"
    rapport = {
        "version": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "modele": "prévision de la demande par référence (réactifs), 1 à 3 mois",
        "donnees": {"source": d.source, "references": len(p.refs), "mois": len(p.mois),
                    "periode": f"{p.mois[0]:%Y-%m} → {p.mois[-1]:%Y-%m}", **p.exclus},
        "protocole": {
            "validation": f"{p.mois[O['validation'][0] + 1]:%Y-%m} → {p.mois[O['validation'][-1] + 1]:%Y-%m}",
            "test": f"{p.mois[O['test'][0] + 1]:%Y-%m} → {p.mois[O['test'][-1] + 1]:%Y-%m}",
            "walk_forward": f"origine mensuelle ; modèle appris réentraîné tous les {RAFRAICHISSEMENT} mois",
            "eligibilite": f">= {MIN_MOIS_ACTIFS_24} mois de vente sur 24 et >= 1 sur 12, décidée à l'origine",
            "metrique": "WAPE = Σ|y − ŷ| / Σy",
            "regle_de_deploiement": (f"challenger servi seulement s'il bat la règle de référence de "
                                     f"{SEUIL_GAIN_PTS} points de WAPE à 1 mois sur le test, IC95 "
                                     "bootstrap (références rééchantillonnées) entièrement positif"),
            "choix_figes_par": "evaluation_demande/comparer_modeles.py (validation seule)"},
        "regle_de_reference": {"nom": REGLE_DE_REFERENCE, "test": bloc(ref_test), "validation": bloc(ref_val)},
        "challenger": {"nom": nom_ch, "reglages": CHALLENGER["params"],
                       "test": bloc(ch_test) if challenger_ok else None,
                       "validation": bloc(ch_val) if challenger_ok else None,
                       "indisponible": motif_indispo},
        "comparaison_challenger_vs_reference_h1": comp,
        "methode_servie": {
            "nom": nom_ch if servi else REGLE_DE_REFERENCE,
            "methode_servie": (
                f"{nom_ch} servi : +{comp['ecart_pts']} points de WAPE sur la règle simple "
                f"(IC95 {comp['ic95']})" if servi else
                (f"médiane des 12 derniers mois servie — {motif_indispo}" if motif_indispo else
                 f"médiane des 12 derniers mois servie : {nom_ch} fait {comp['ecart_pts']:+} points "
                 f"au test (IC95 {comp['ic95']}), il en faut +{SEUIL_GAIN_PTS}")),
            "statut": "servi",
            "nature": "modele_appris" if servi else "methode_statistique",
            "wape_h1_pct": bloc(test_servie)["wape_h1_pct"],
            "borne_p80": {"quantiles_ecart_normalise": qs,
                          "couverture_test": couverture(p, test_servie, qs)}},
        "decision": {
            "challenger_servi": servi,
            "motif": (motif_indispo or (
                f"{nom_ch} bat {REGLE_DE_REFERENCE} de {comp['ecart_pts']} points (IC95 {comp['ic95']})"
                if servi else
                f"{nom_ch} : {comp['ecart_pts']:+} points face à {REGLE_DE_REFERENCE} sur le test "
                f"(IC95 {comp['ic95']}) — il faut +{SEUIL_GAIN_PTS} points et un intervalle "
                "entièrement positif : la règle simple est servie"))},
        "reference_evaluation_etendue": "reports/demande_reference_comparaison.json",
        "determinisme": etat_determinisme(),
    }
    if servi and ecrire:
        import joblib
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        T = p.Y.shape[1]
        joblib.dump({h: entrainer_lgbm(p, T - 1, h) for h in HORIZONS},
                    MODELS_DIR / "demande_reference.joblib")
    if ecrire:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / RAPPORT).write_text(json.dumps(rapport, ensure_ascii=False, indent=1, default=str),
                                           encoding="utf-8")
    return rapport


def prevoir(store: Optional[Path] = None, extrait: Optional[Path] = None,
            limite: Optional[int] = None) -> Dict[str, Any]:
    """Prévision des trois prochains mois pour chaque référence éligible, avec la méthode que le…"""
    chemin = REPORTS_DIR / RAPPORT
    if not chemin.exists():
        return {"servi": False, "motif": f"rapport {RAPPORT} absent — lancer l'entraînement"}
    r = json.loads(chemin.read_text(encoding="utf-8"))
    qs = r["methode_servie"]["borne_p80"]["quantiles_ecart_normalise"]
    d = charger(store=store, extrait=extrait)
    p = construire_panel(d)
    o = p.Y.shape[1] - 1
    m = eligibles(p, o)
    idx = np.flatnonzero(m)
    methode = REGLE_DE_REFERENCE
    modeles = None
    if r["decision"]["challenger_servi"]:
        try:
            import joblib
            modeles = joblib.load(MODELS_DIR / "demande_reference.joblib")
            methode = r["methode_servie"]["nom"]
        except Exception as e:
            r["decision"]["motif"] += f" · artefact illisible ({type(e).__name__}), règle servie"
    prev = []
    for h in HORIZONS:
        if modeles is not None:
            prev.append(predire_lgbm(modeles[h], p, o, h, m))
        else:
            prev.append(regles(p, o, h, m)[REGLE_DE_REFERENCE])
    prev = np.vstack(prev).T
    ech = np.maximum(p.Y[m, max(0, o - 11):o + 1].mean(axis=1), 0.5)
    grp = [groupe_de_calibration(p, i, o) for i in idx]
    q3 = np.array([qs["cumul_3_mois"].get(g, max(qs["cumul_3_mois"].values())) for g in grp])
    cumul = prev.sum(axis=1)
    borne = np.maximum(cumul + q3 * ech, cumul)
    mois = [(p.mois[o] + pd.DateOffset(months=h)).strftime("%Y-%m") for h in HORIZONS]
    lignes = [{"reference": p.refs[i], "designation": p.designation[i],
               "designations": p.designations.get(p.refs[i], []),
               "prevision": [round(float(v), 1) for v in prev[k]],
               "cumul_3_mois": round(float(cumul[k]), 1),
               "borne_haute_3_mois": round(float(borne[k]), 1),
               "groupe": grp[k],
               "moyenne_12_mois": round(float(p.Y[i, max(0, o - 11):o + 1].mean()), 1),
               "moyenne_3_mois": round(float(p.Y[i, max(0, o - 2):o + 1].mean()), 1),
               "dernier_mois": round(float(p.Y[i, o]), 1)}
              for k, i in enumerate(idx)]
    lignes.sort(key=lambda x: -x["cumul_3_mois"])
    return {"servi": True, "methode": methode, "origine": f"{p.mois[o]:%Y-%m}", "mois": mois,
            "n_references": len(lignes), "niveau_borne": 0.8,
            "wape_h1_pct": r["methode_servie"]["wape_h1_pct"],
            "references": lignes[:limite] if limite else lignes}


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    rap = train()
    print(json.dumps({k: rap[k] for k in ("methode_servie", "decision",
                                           "comparaison_challenger_vs_reference_h1")},
                     ensure_ascii=False, indent=1, default=str))
