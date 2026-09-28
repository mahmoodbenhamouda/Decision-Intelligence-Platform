"""
ml_engine/deep/recommandation.py
================================
Recommandation de produits par apprentissage profond — réseau **Wide & Deep**.

La question posée
-----------------
> Quels produits ce client, qui ne les a JAMAIS achetés, va-t-il adopter dans les
> six prochains mois ?

C'est la question de la **vente croisée**. Elle diffère des autres modules du
projet sur un point qui justifie le deep learning : la sortie n'est pas un score
par client ou par produit, mais un **classement de centaines de produits pour
chacun des clients** — un espace client × produit de plus de 400 000 couples,
où la similarité entre produits et entre profils d'établissement s'apprend par
des **embeddings** (représentations vectorielles denses).

Pourquoi cette cible est honnête
--------------------------------
* **Observée, jamais construite** : le client a acheté le produit pour la
  première fois dans la fenêtre, ou non. Aucun seuil déclaré, aucune simulation.
* **Non triviale** : les rachats sont exclus. Prédire qu'un laboratoire rachètera
  son réactif habituel ne sert à rien — le service achat le sait déjà.
* **Actionnable** : une adoption probable est un argument de prospection.
* **Mesurable sans fuite** : les variables se calculent sur `]-∞, t]`, la cible
  se lit sur `]t, t+6 mois]`.

Architecture — Wide & Deep (Cheng et al., Google, 2016)
------------------------------------------------------
    score(client, produit) =  wide(x)  +  deep( x ⊕ E_produit ⊕ E_famille ⊕ E_type )

* la partie **wide** (linéaire) mémorise les signaux directs — popularité,
  similarité de co-achat ;
* la partie **deep** (perceptron à deux couches cachées, ReLU, dropout) croise
  ces signaux avec trois embeddings appris : le produit (16 dimensions), sa
  famille ERP (16) et le type d'établissement du client (4) ;
* un **dropout d'identifiant** remplace aléatoirement 30 % des produits par un
  vecteur « inconnu » : le réseau apprend ainsi à recommander aussi un produit
  récent, dont l'embedding n'a pas encore vu d'exemples.

Protocole — walk-forward à trois origines
-----------------------------------------
Pour chaque origine `T`, les exemples d'entraînement sont construits à des dates
trimestrielles `t ≤ T − 6 mois` : leur fenêtre cible se termine donc au plus tard
en `T`. Aucun exemple d'entraînement ne voit la période de test.

Le nombre d'époques est choisi par **validation interne** — entraînement sur
`t ≤ T − 12 mois`, validation en `T − 6 mois` — jamais sur le test.

Six méthodes sont mesurées sur exactement les mêmes clients et candidats :

| Famille              | Méthodes                                               |
|----------------------|--------------------------------------------------------|
| références triviales | popularité 12 mois, popularité par type d'établissement, item-kNN (co-achat) |
| modèles non profonds | régression logistique, LightGBM                        |
| deep learning        | Wide & Deep                                            |

Règles de décision — déclarées AVANT la mesure
----------------------------------------------
1. **L'apprentissage doit être utile** : le meilleur modèle appris doit battre la
   meilleure référence triviale de `SEUIL_GAIN_NDCG` en NDCG@10 agrégé, avec un
   intervalle de confiance apparié (bootstrap sur les clients) entièrement positif.
2. **Parcimonie** : parmi les modèles appris, le plus SIMPLE est servi sauf si un
   plus complexe est **significativement** meilleur (IC95 de l'écart > 0). Le
   Wide & Deep n'est donc servi que s'il bat LightGBM ET la régression logistique
   au-delà du bruit d'échantillonnage.
3. Sans PyTorch, le deep learning n'est pas mesuré ; le rapport le dit.

Reproduction :  python -m ml_engine.deep.recommandation
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

MODELS_DIR = BASE / "models"
REPORTS_DIR = BASE / "reports"
OUTPUT_DIR = BASE / "output"
RAPPORT = REPORTS_DIR / "recommandation_metrics.json"
SORTIE = OUTPUT_DIR / "recommandations.json"
ARTEFACT = MODELS_DIR / "recommandation_wide_deep.pt"

SEED = 42
HORIZON_MOIS = 6
PAS_MOIS = 3                     # une date d'exemples par trimestre
DEBUT_HISTORIQUE = "2021-01-01"  # le trou 2019-2020 est une bascule d'ERP
K = 10                           # taille de la liste recommandée
NEGATIFS_PAR_POSITIF = 10
N_ORIGINES = 3
EPOQUES_CANDIDATES = (3, 6, 9, 12)
SEUIL_GAIN_NDCG = 0.02
N_TIRAGES = 2000

# Ordre de SIMPLICITÉ : sert la règle de parcimonie.
MODELES_APPRIS = ("regression_logistique", "lightgbm", "wide_deep")
REFERENCES = ("popularite_12m", "popularite_par_type", "item_knn")

VARIABLES = [
    "log_acheteurs_12m",       # popularité récente
    "log_acheteurs_3m",        # popularité très récente
    "tendance",                # log(3m × 4) − log(12m) : produit qui monte
    "log_acheteurs_meme_type", # adopté par des établissements du même type
    "part_meme_type",          # … rapporté à la taille de ce type
    "knn_somme",               # similarité de co-achat avec l'historique du client
    "knn_max",                 # produit le plus proche déjà acheté
    "anciennete_produit_ans",
    "log_ca_produit_12m",
    "log_n_references_client",
    "log_ca_client_12m",
    "mois_actifs_client_12m",
    "recence_client_ans",
    "part_famille_client",     # poids de la famille du produit chez ce client
    "famille_deja_achetee",
]


# ── Données ─────────────────────────────────────────────────────────────────
def _connect():
    import duckdb
    from ml_engine.analytics.kpi_engine import STORE_PATH
    return duckdb.connect(str(STORE_PATH), read_only=True)


def charger_achats(con=None) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Couples (client, référence, date) des ventes réelles, hors prestations.

    Les prestations (`SERVICE SAV`, `SERVICE DIVERS`…) sont exclues : un contrat
    de maintenance n'est pas un produit qu'on recommande, il suit un équipement.
    Les avoirs (montant ≤ 0) sont exclus : une annulation n'est pas une adoption.
    """
    from ml_engine.models.demand_features import classer_etablissement

    ferme = con is None
    con = con or _connect()
    try:
        df = con.execute(f"""
            SELECT client, reference,
                   any_value(designation) AS designation,
                   any_value(famille)     AS famille,
                   date, sum(montant)     AS montant
            FROM sales_lines
            WHERE date >= DATE '{DEBUT_HISTORIQUE}' AND montant > 0
              AND reference IS NOT NULL AND client IS NOT NULL
            GROUP BY client, reference, date
            ORDER BY date, client, reference
        """).df()
        noms = {str(c): str(n) for c, n in con.execute(
            "SELECT client, any_value(client_name) FROM sales "
            "WHERE client_name IS NOT NULL GROUP BY client").fetchall()}
    finally:
        if ferme:
            con.close()

    df["date"] = pd.to_datetime(df["date"])
    df["famille"] = df["famille"].fillna("NON_RENSEIGNEE")
    df = df[~df["famille"].str.upper().str.startswith("SERVICE")].copy()
    df["type_etab"] = df["client"].map(lambda c: classer_etablissement(noms.get(c)))
    return df.reset_index(drop=True), noms


def dates_de_coupure(df: pd.DataFrame) -> Tuple[pd.Timestamp, List[pd.Timestamp]]:
    """Dernier mois COMPLET, puis dates trimestrielles dont la cible est complète.

    Le dernier mois de l'export est presque toujours partiel : il est écarté,
    comme dans les autres modules de prévision du projet.
    """
    fin = df["date"].max()
    complet = (fin + pd.offsets.MonthEnd(0)).normalize()
    if fin.normalize() < complet:
        complet = (fin - pd.offsets.MonthEnd(1)).normalize()
    derniere = (complet - pd.DateOffset(months=HORIZON_MOIS)) + pd.offsets.MonthEnd(0)
    premiere = pd.Timestamp(DEBUT_HISTORIQUE) + pd.DateOffset(months=15)
    coupures: List[pd.Timestamp] = []
    t = derniere
    while t >= premiere:
        coupures.append(t)
        t = (t - pd.DateOffset(months=PAS_MOIS)) + pd.offsets.MonthEnd(0)
    return complet, sorted(coupures)


def construire_exemples(df: pd.DataFrame, coupure: pd.Timestamp,
                        etiquettes: bool = True,
                        graine: Optional[int] = None) -> pd.DataFrame:
    """Couples (client, produit JAMAIS acheté par ce client) vus à la date `coupure`.

    Si `graine` est fournie (exemples d'ENTRAÎNEMENT), les négatifs sont
    sous-échantillonnés à `NEGATIFS_PAR_POSITIF` par positif et les clients sans
    adoption sont écartés. Sinon (évaluation, prédiction), TOUS les candidats sont
    conservés : le classement se mesure sur le catalogue entier, pas sur un
    échantillon qui faciliterait la tâche.
    """
    coupure = pd.Timestamp(coupure)
    passe = df[df["date"] <= coupure]
    r12 = passe[passe["date"] > coupure - pd.DateOffset(months=12)]
    r3 = passe[passe["date"] > coupure - pd.DateOffset(months=3)]
    if r12.empty:
        return pd.DataFrame()

    catalogue = np.array(sorted(r12["reference"].unique()))
    ii = {r: i for i, r in enumerate(catalogue)}
    clients_actifs = sorted(r12["client"].unique())
    tous = sorted(passe["client"].unique())
    ci = {c: i for i, c in enumerate(tous)}

    acheteurs_12 = r12.groupby("reference")["client"].nunique().reindex(catalogue).fillna(0).to_numpy()
    acheteurs_3 = r3.groupby("reference")["client"].nunique().reindex(catalogue).fillna(0).to_numpy()
    ca_produit = r12.groupby("reference")["montant"].sum().reindex(catalogue).fillna(0).to_numpy()
    premiere_vente = df.groupby("reference")["date"].min().reindex(catalogue)
    anciennete = ((coupure - premiere_vente).dt.days / 365.0).fillna(0).to_numpy()
    famille_produit = (df[df["reference"].isin(ii)].groupby("reference")["famille"]
                       .agg(lambda x: x.mode().iat[0]).reindex(catalogue)
                       .fillna("NON_RENSEIGNEE").to_numpy())

    type_client = passe.groupby("client")["type_etab"].first()
    taille_type = r12.groupby("type_etab")["client"].nunique()
    adoption_type = (r12.groupby(["type_etab", "reference"])["client"].nunique()
                     .unstack(fill_value=0).reindex(columns=catalogue, fill_value=0))

    # Matrice client × produit (achats passés) et similarité cosinus produit-produit.
    X = np.zeros((len(tous), len(catalogue)), dtype=np.float32)
    p2 = passe[passe["reference"].isin(ii)]
    X[p2["client"].map(ci).to_numpy(), p2["reference"].map(ii).to_numpy()] = 1.0
    norme = np.sqrt(X.sum(axis=0)) + 1e-9
    S = (X.T @ X) / np.outer(norme, norme)
    np.fill_diagonal(S, 0.0)

    ca_client = r12.groupby("client")["montant"].sum()
    mois_actifs = r12.assign(m=r12["date"].dt.to_period("M")).groupby("client")["m"].nunique()
    dernier_achat = passe.groupby("client")["date"].max()

    adoptions: Dict[str, set] = {}
    if etiquettes:
        futur = df[(df["date"] > coupure)
                   & (df["date"] <= coupure + pd.DateOffset(months=HORIZON_MOIS))]
        adoptions = futur.groupby("client")["reference"].agg(set).to_dict()

    rng = np.random.default_rng(graine) if graine is not None else None
    blocs: List[pd.DataFrame] = []
    for cl in clients_actifs:
        u = ci[cl]
        deja = X[u] > 0
        cand = np.flatnonzero(~deja)
        if len(cand) == 0:
            continue
        y = np.zeros(len(cand), dtype=np.int8)
        if etiquettes:
            nouveaux = {ii[r] for r in adoptions.get(cl, ()) if r in ii}
            if nouveaux:
                y = np.isin(cand, list(nouveaux)).astype(np.int8)
        if rng is not None:
            if y.sum() == 0:
                continue
            pos, neg = cand[y == 1], cand[y == 0]
            neg = rng.choice(neg, size=min(len(neg), NEGATIFS_PAR_POSITIF * len(pos)),
                             replace=False)
            cand = np.concatenate([pos, np.sort(neg)])
            y = np.concatenate([np.ones(len(pos), np.int8), np.zeros(len(neg), np.int8)])

        sim = S[deja][:, cand] if deja.any() else np.zeros((1, len(cand)), np.float32)
        t = type_client.get(cl, "AUTRE")
        adopt_t = (adoption_type.loc[t].to_numpy()[cand] if t in adoption_type.index
                   else np.zeros(len(cand)))
        fam_cl = pd.Series(famille_produit[deja]).value_counts(normalize=True)
        part_fam = pd.Series(famille_produit[cand]).map(fam_cl).fillna(0.0).to_numpy()

        blocs.append(pd.DataFrame({
            "client": cl,
            "reference": catalogue[cand],
            "famille": famille_produit[cand],
            "type_etab": t,
            "y": y,
            "log_acheteurs_12m": np.log1p(acheteurs_12[cand]),
            "log_acheteurs_3m": np.log1p(acheteurs_3[cand]),
            "tendance": np.log1p(acheteurs_3[cand] * 4) - np.log1p(acheteurs_12[cand]),
            "log_acheteurs_meme_type": np.log1p(adopt_t),
            "part_meme_type": adopt_t / max(int(taille_type.get(t, 1)), 1),
            "knn_somme": sim.sum(axis=0),
            "knn_max": sim.max(axis=0),
            "anciennete_produit_ans": anciennete[cand],
            "log_ca_produit_12m": np.log1p(ca_produit[cand]),
            "log_n_references_client": np.full(len(cand), np.log1p(deja.sum())),
            "log_ca_client_12m": np.full(len(cand), np.log1p(float(ca_client.get(cl, 0.0)))),
            "mois_actifs_client_12m": np.full(len(cand), float(mois_actifs.get(cl, 0)) / 12.0),
            "recence_client_ans": np.full(len(cand), (coupure - dernier_achat[cl]).days / 365.0),
            "part_famille_client": part_fam,
            "famille_deja_achetee": (part_fam > 0).astype(float),
        }))
    if not blocs:
        return pd.DataFrame()
    out = pd.concat(blocs, ignore_index=True)
    out["coupure"] = coupure
    return out


# ── Métriques de classement ─────────────────────────────────────────────────
def metriques_classement(exemples: pd.DataFrame, score: np.ndarray,
                         k: int = K) -> Tuple[Dict[str, Any], pd.DataFrame]:
    """HitRate, précision, rappel, NDCG et MAP à k — par client, puis moyennés.

    Seuls les clients ayant au moins une adoption dans la fenêtre sont évalués :
    un client qui n'adopte rien ne permet pas de juger un classement.
    """
    d = exemples[["client", "reference", "y"]].assign(s=np.asarray(score, float))
    d = d.sort_values(["client", "s", "reference"], ascending=[True, False, True])
    d["rang"] = d.groupby("client").cumcount()
    n_pos = d.groupby("client")["y"].sum()
    evalues = n_pos[n_pos > 0].index
    top = d[(d["rang"] < k) & d["client"].isin(evalues)].copy()
    top["gain"] = top["y"] / np.log2(top["rang"] + 2)
    top["prec_cum"] = top.groupby("client")["y"].cumsum() / (top["rang"] + 1)

    lignes = []
    for cl, g in top.groupby("client", sort=True):
        npos = int(n_pos[cl])
        hits = int(g["y"].sum())
        idcg = float(sum(1.0 / np.log2(i + 2) for i in range(min(npos, k))))
        lignes.append({
            "client": cl,
            "hit": 1.0 if hits else 0.0,
            "precision": hits / k,
            "rappel": hits / npos,
            "ndcg": float(g["gain"].sum()) / idcg,
            "map": float((g["prec_cum"] * g["y"]).sum()) / min(npos, k),
        })
    par_client = pd.DataFrame(lignes)
    couverture = top["reference"].nunique() / max(exemples["reference"].nunique(), 1)
    resume = {
        "n_clients_evalues": int(len(par_client)),
        f"hit_rate_at_{k}": round(float(par_client["hit"].mean()), 4),
        f"precision_at_{k}": round(float(par_client["precision"].mean()), 4),
        f"recall_at_{k}": round(float(par_client["rappel"].mean()), 4),
        f"ndcg_at_{k}": round(float(par_client["ndcg"].mean()), 4),
        f"map_at_{k}": round(float(par_client["map"].mean()), 4),
        "couverture_catalogue": round(float(couverture), 4),
    }
    return resume, par_client


def comparer_ndcg(a: np.ndarray, b: np.ndarray, graine: int = SEED) -> Dict[str, Any]:
    """Écart de NDCG@10 moyen (a − b), bootstrap APPARIÉ sur les clients."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    rng = np.random.default_rng(graine)
    n = len(a)
    ecarts = np.empty(N_TIRAGES)
    for i in range(N_TIRAGES):
        idx = rng.integers(0, n, size=n)
        ecarts[i] = a[idx].mean() - b[idx].mean()
    bas, haut = float(np.percentile(ecarts, 2.5)), float(np.percentile(ecarts, 97.5))
    return {
        "ecart_moyen": round(float(a.mean() - b.mean()), 4),
        "ecart_ic95": [round(bas, 4), round(haut, 4)],
        "part_tirages_gagnants_pct": round(float((ecarts > 0).mean() * 100), 1),
        "significatif": bool(bas > 0.0),
        "n_clients": int(n),
    }


# ── Modèles ─────────────────────────────────────────────────────────────────
def _torch_disponible() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def _construire_reseau(n_variables: int, n_produits: int, n_familles: int, n_types: int):
    import torch
    from torch import nn

    class WideDeep(nn.Module):
        """Wide & Deep : partie linéaire + perceptron sur variables ⊕ embeddings."""

        def __init__(self) -> None:
            super().__init__()
            d = 16
            self.emb_produit = nn.Embedding(n_produits + 1, d)    # 0 = inconnu
            self.emb_famille = nn.Embedding(n_familles + 1, d)
            self.emb_type = nn.Embedding(n_types + 1, 4)
            self.wide = nn.Linear(n_variables, 1)
            self.deep = nn.Sequential(
                nn.Linear(n_variables + 2 * d + 4, 64), nn.ReLU(), nn.Dropout(0.2),
                nn.Linear(64, 32), nn.ReLU(),
                nn.Linear(32, 1))

        def forward(self, x, produit, famille, type_etab):
            profond = torch.cat([x, self.emb_produit(produit),
                                 self.emb_famille(famille), self.emb_type(type_etab)], dim=-1)
            return (self.wide(x) + self.deep(profond)).squeeze(-1)

    return WideDeep()


class WideDeepEntraine:
    """Réseau entraîné + tout ce qu'il faut pour scorer de nouveaux couples."""

    def __init__(self, reseau, moyennes, ecarts, produits, familles, types):
        self.reseau = reseau
        self.moyennes = moyennes
        self.ecarts = ecarts
        self.produits = produits
        self.familles = familles
        self.types = types

    def _encoder(self, d: pd.DataFrame):
        import torch
        x = ((d[VARIABLES].to_numpy(dtype=np.float32) - self.moyennes) / self.ecarts)
        return (torch.tensor(x, dtype=torch.float32),
                torch.tensor(d["reference"].map(self.produits).fillna(0).astype(np.int64).to_numpy()),
                torch.tensor(d["famille"].map(self.familles).fillna(0).astype(np.int64).to_numpy()),
                torch.tensor(d["type_etab"].map(self.types).fillna(0).astype(np.int64).to_numpy()))

    def scorer(self, d: pd.DataFrame, lot: int = 65536) -> np.ndarray:
        import torch
        self.reseau.eval()
        sorties = []
        with torch.no_grad():
            for i in range(0, len(d), lot):
                sorties.append(self.reseau(*self._encoder(d.iloc[i:i + lot])).numpy())
        return np.concatenate(sorties) if sorties else np.array([])

    def etat(self) -> Dict[str, Any]:
        return {"state_dict": self.reseau.state_dict(), "moyennes": self.moyennes,
                "ecarts": self.ecarts, "produits": self.produits,
                "familles": self.familles, "types": self.types,
                "variables": VARIABLES}


def entrainer_wide_deep(train: pd.DataFrame, epoques: int,
                        graine: int = SEED,
                        suivi: Optional[Tuple[pd.DataFrame, Tuple[int, ...]]] = None
                        ) -> Tuple[WideDeepEntraine, Dict[int, float]]:
    """Entraîne le réseau. `suivi` = (exemples de validation, époques où mesurer)."""
    import torch

    torch.manual_seed(graine)
    np.random.seed(graine)
    torch.use_deterministic_algorithms(True, warn_only=True)

    moyennes = train[VARIABLES].mean().to_numpy(dtype=np.float32)
    ecarts = (train[VARIABLES].std().to_numpy(dtype=np.float32) + 1e-6)
    produits = {r: i + 1 for i, r in enumerate(sorted(train["reference"].unique()))}
    familles = {f: i + 1 for i, f in enumerate(sorted(train["famille"].unique()))}
    types = {t: i + 1 for i, t in enumerate(sorted(train["type_etab"].unique()))}

    reseau = _construire_reseau(len(VARIABLES), len(produits), len(familles), len(types))
    modele = WideDeepEntraine(reseau, moyennes, ecarts, produits, familles, types)
    X, P, F, T = modele._encoder(train)
    y = torch.tensor(train["y"].to_numpy(dtype=np.float32))
    poids_positif = torch.tensor(float((1 - y.mean()) / max(float(y.mean()), 1e-6)))
    opt = torch.optim.Adam(reseau.parameters(), lr=3e-3, weight_decay=1e-5)
    gen = torch.Generator().manual_seed(graine)

    mesures: Dict[int, float] = {}
    for ep in range(1, epoques + 1):
        reseau.train()
        ordre = torch.randperm(len(y), generator=gen)
        for debut in range(0, len(y), 1024):
            idx = ordre[debut:debut + 1024]
            produit = P[idx].clone()
            # Dropout d'identifiant : apprendre à recommander un produit inconnu.
            produit[torch.rand(len(idx), generator=gen) < 0.3] = 0
            perte = torch.nn.functional.binary_cross_entropy_with_logits(
                reseau(X[idx], produit, F[idx], T[idx]), y[idx], pos_weight=poids_positif)
            opt.zero_grad()
            perte.backward()
            opt.step()
        if suivi is not None and ep in suivi[1]:
            resume, _ = metriques_classement(suivi[0], modele.scorer(suivi[0]))
            mesures[ep] = resume[f"ndcg_at_{K}"]
    return modele, mesures


def _scores_references(ex: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Directions fixées A PRIORI, jamais révisées au vu du résultat."""
    depart = 1e-3 * ex["log_acheteurs_12m"].to_numpy()      # départage stable
    return {
        "popularite_12m": ex["log_acheteurs_12m"].to_numpy(),
        "popularite_par_type": ex["part_meme_type"].to_numpy() + depart,
        "item_knn": ex["knn_somme"].to_numpy() + depart,
    }


def _entrainer_non_profonds(train: pd.DataFrame) -> Dict[str, Callable[[pd.DataFrame], np.ndarray]]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import lightgbm as lgb

    rl = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
    rl.fit(train[VARIABLES], train["y"])
    gb = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                            min_child_samples=50, subsample=0.8, subsample_freq=1,
                            colsample_bytree=0.8, random_state=SEED, verbose=-1,
                            deterministic=True, force_row_wise=True, n_jobs=1)
    gb.fit(train[VARIABLES], train["y"])
    return {
        "regression_logistique": lambda d: rl.decision_function(d[VARIABLES]),
        "lightgbm": lambda d: gb.predict_proba(d[VARIABLES])[:, 1],
    }


# ── Évaluation walk-forward ─────────────────────────────────────────────────
def evaluer(df: pd.DataFrame, verbose: bool = True) -> Dict[str, Any]:
    _, coupures = dates_de_coupure(df)
    if len(coupures) < N_ORIGINES + 4:
        return {"applicable": False, "motif": f"{len(coupures)} dates de coupure seulement"}
    origines = coupures[::-2][:N_ORIGINES][::-1]      # les plus récentes, espacées de 6 mois
    avec_torch = _torch_disponible()

    cache_train: Dict[pd.Timestamp, pd.DataFrame] = {}

    def exemples_train(jusqu_a: pd.Timestamp) -> pd.DataFrame:
        blocs = []
        for t in coupures:
            if t + pd.DateOffset(months=HORIZON_MOIS) <= jusqu_a + pd.Timedelta(days=1):
                if t not in cache_train:
                    cache_train[t] = construire_exemples(
                        df, t, graine=SEED + int(t.strftime("%Y%m")))
                blocs.append(cache_train[t])
        return pd.concat(blocs, ignore_index=True)

    par_origine: List[Dict[str, Any]] = []
    par_client: Dict[str, List[pd.DataFrame]] = {m: [] for m in REFERENCES + MODELES_APPRIS}
    epoques_retenues: List[int] = []

    for T in origines:
        t0 = time.time()
        test = construire_exemples(df, T)
        train = exemples_train(T)
        bloc: Dict[str, Any] = {
            "origine": str(T.date()),
            "fenetre_test": f"]{T.date()} ; {(T + pd.DateOffset(months=HORIZON_MOIS)).date()}]",
            "n_exemples_train": int(len(train)),
            "n_adoptions_train": int(train["y"].sum()),
            "n_couples_test": int(len(test)),
            "n_adoptions_test": int(test["y"].sum()),
            "methodes": {},
        }
        scores = _scores_references(test)
        for nom, f in _entrainer_non_profonds(train).items():
            scores[nom] = f(test)

        if avec_torch:
            # Nombre d'époques choisi en validation INTERNE, jamais sur le test.
            T_val = (T - pd.DateOffset(months=HORIZON_MOIS)) + pd.offsets.MonthEnd(0)
            train_int = exemples_train(T_val)
            val = construire_exemples(df, T_val)
            _, courbe = entrainer_wide_deep(
                train_int, max(EPOQUES_CANDIDATES),
                suivi=(val, EPOQUES_CANDIDATES))
            ep = max(courbe, key=lambda e: (courbe[e], -e))
            epoques_retenues.append(ep)
            modele, _ = entrainer_wide_deep(train, ep)
            scores["wide_deep"] = modele.scorer(test)
            bloc["validation_interne_ndcg_par_epoque"] = {str(k): v for k, v in courbe.items()}
            bloc["epoques_retenues"] = ep

        for nom, s in scores.items():
            resume, pc = metriques_classement(test, s)
            bloc["methodes"][nom] = resume
            par_client[nom].append(pc.assign(origine=str(T.date())))
        bloc["duree_s"] = round(time.time() - t0, 1)
        par_origine.append(bloc)
        if verbose:
            print(f"[reco] origine {T.date()} · "
                  + " · ".join(f"{n} {r[f'ndcg_at_{K}']:.4f}"
                               for n, r in bloc["methodes"].items())
                  + f" ({bloc['duree_s']} s)")

    # ── Agrégation sur les trois origines ────────────────────────────────────
    agrege: Dict[str, Dict[str, Any]] = {}
    ndcg_client: Dict[str, np.ndarray] = {}
    for nom, blocs in par_client.items():
        if not blocs:
            continue
        pc = pd.concat(blocs, ignore_index=True).sort_values(["origine", "client"])
        ndcg_client[nom] = pc["ndcg"].to_numpy()
        agrege[nom] = {
            "n_evaluations_client": int(len(pc)),
            f"hit_rate_at_{K}": round(float(pc["hit"].mean()), 4),
            f"precision_at_{K}": round(float(pc["precision"].mean()), 4),
            f"recall_at_{K}": round(float(pc["rappel"].mean()), 4),
            f"ndcg_at_{K}": round(float(pc["ndcg"].mean()), 4),
            f"map_at_{K}": round(float(pc["map"].mean()), 4),
        }

    meilleure_ref = max(REFERENCES, key=lambda n: agrege[n][f"ndcg_at_{K}"])
    appris = [m for m in MODELES_APPRIS if m in agrege]
    meilleur_appris = max(appris, key=lambda n: agrege[n][f"ndcg_at_{K}"])

    # Règle 2 — parcimonie : le plus simple non significativement inférieur au meilleur.
    comparaisons_parcimonie = {}
    retenu = meilleur_appris
    for m in appris:                                   # ordre de simplicité
        if m == meilleur_appris:
            retenu = m
            break
        c = comparer_ndcg(ndcg_client[meilleur_appris], ndcg_client[m])
        comparaisons_parcimonie[f"{meilleur_appris}_vs_{m}"] = c
        if not c["significatif"]:
            retenu = m
            break

    # Règle 1 — utilité de l'apprentissage.
    vs_ref = comparer_ndcg(ndcg_client[retenu], ndcg_client[meilleure_ref])
    gain = agrege[retenu][f"ndcg_at_{K}"] - agrege[meilleure_ref][f"ndcg_at_{K}"]
    utile = bool(vs_ref["significatif"] and gain >= SEUIL_GAIN_NDCG)

    duel_dl = {}
    if "wide_deep" in agrege:
        for m in ("lightgbm", "regression_logistique", meilleure_ref):
            duel_dl[f"wide_deep_vs_{m}"] = comparer_ndcg(ndcg_client["wide_deep"], ndcg_client[m])

    methode_servie = retenu if utile else meilleure_ref
    return {
        "applicable": True,
        "protocole": (f"walk-forward à {len(origines)} origines espacées de 6 mois ; "
                      f"exemples d'entraînement trimestriels dont la fenêtre cible "
                      f"se termine au plus tard à l'origine ; fenêtre de test "
                      f"{HORIZON_MOIS} mois ; classement sur le catalogue ENTIER"),
        "origines": [str(t.date()) for t in origines],
        "torch_disponible": avec_torch,
        "epoques_retenues_par_origine": epoques_retenues,
        "par_origine": par_origine,
        "agrege": agrege,
        "meilleure_reference_triviale": {"nom": meilleure_ref, **agrege[meilleure_ref]},
        "meilleur_modele_appris": meilleur_appris,
        "modele_retenu_par_parcimonie": retenu,
        "comparaisons_parcimonie": comparaisons_parcimonie,
        "duels_du_deep_learning": duel_dl,
        "retenu_vs_meilleure_reference": {**vs_ref, "gain_ndcg": round(gain, 4)},
        "apprentissage_utile": utile,
        "methode_servie": {"nom": methode_servie, **agrege[methode_servie]},
    }


# ── Entraînement complet ────────────────────────────────────────────────────
def train(verbose: bool = True) -> Dict[str, Any]:
    from ml_engine.determinisme import limiter_threads

    t0 = time.time()
    df, noms = charger_achats()
    if df.empty:
        return {"error": "aucune vente exploitable"}

    with limiter_threads(1):
        if _torch_disponible():
            import torch
            torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        ev = evaluer(df, verbose=verbose)
    if not ev.get("applicable"):
        rapport = {"version": 1, "evaluation": ev,
                   "decision_deploiement": {"servi": False, "motif": ev.get("motif")}}
        _ecrire(rapport)
        return rapport

    servie = ev["methode_servie"]["nom"]
    complet, coupures = dates_de_coupure(df)

    # ── Modèle final : toutes les fenêtres complètes, puis prédiction à la fin ──
    blocs = [construire_exemples(df, t, graine=SEED + int(t.strftime("%Y%m")))
             for t in coupures]
    train_final = pd.concat([b for b in blocs if not b.empty], ignore_index=True)
    candidats = construire_exemples(df, complet, etiquettes=False)
    candidats = candidats.drop(columns=["y"])

    if servie == "wide_deep":
        ep = int(round(float(np.median(ev["epoques_retenues_par_origine"]))))
        modele, _ = entrainer_wide_deep(train_final, ep)
        score = modele.scorer(candidats)
        import torch
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        torch.save(modele.etat(), ARTEFACT)
    else:
        if ARTEFACT.exists():
            ARTEFACT.unlink()          # un artefact présent finit par être chargé
        if servie in ("regression_logistique", "lightgbm"):
            score = _entrainer_non_profonds(train_final)[servie](candidats)
        else:
            score = _scores_references(candidats)[servie]

    recommandations = _formater(df, candidats, score, complet, noms)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json.dump({"methode": servie, "date_de_reference": str(complet.date()),
               "horizon_mois": HORIZON_MOIS, "clients": recommandations},
              open(SORTIE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    rapport = {
        "version": 1,
        "question": ("quels produits, JAMAIS achetés par ce client, adoptera-t-il "
                     f"dans les {HORIZON_MOIS} prochains mois ?"),
        "nature_du_modele_profond": (
            "Wide & Deep (Cheng et al., 2016) : partie linéaire + perceptron "
            "64-32 sur 15 variables et trois embeddings appris (produit 16 d, "
            "famille 16 d, type d'établissement 4 d), perte d'entropie croisée "
            "pondérée, Adam, dropout 0,2 et dropout d'identifiant produit 30 %"),
        "variables": VARIABLES,
        "donnees": {
            "n_couples_client_date_produit": int(len(df)),
            "n_clients": int(df["client"].nunique()),
            "n_produits": int(df["reference"].nunique()),
            "periode": f"{df['date'].min().date()} → {df['date'].max().date()}",
            "dernier_mois_complet": str(complet.date()),
            "prestations_exclues": True,
        },
        "seuils_declares_avant_mesure": {
            "gain_ndcg_min_vs_reference_triviale": SEUIL_GAIN_NDCG,
            "significativite": "IC95 apparié (bootstrap clients) entièrement positif",
            "parcimonie": ("le modèle appris le plus simple est servi sauf si un plus "
                           "complexe est significativement meilleur"),
        },
        "evaluation": ev,
        "decision_deploiement": {
            "servi": True,
            "methode_servie": servie,
            "deep_learning_servi": servie == "wide_deep",
            "motif": _motif(ev),
        },
        "n_clients_avec_recommandations": len(recommandations),
        "duree_totale_s": round(time.time() - t0, 1),
    }
    _ecrire(rapport)
    if verbose:
        print(f"[reco] méthode servie : {servie} — {rapport['decision_deploiement']['motif']}")
    return rapport


def _motif(ev: Dict[str, Any]) -> str:
    servie = ev["methode_servie"]["nom"]
    ref = ev["meilleure_reference_triviale"]
    vs = ev["retenu_vs_meilleure_reference"]
    if not ev["apprentissage_utile"]:
        return (f"aucun modèle appris ne bat « {ref['nom']} » de {SEUIL_GAIN_NDCG} de "
                f"NDCG@{K} avec un écart significatif — la référence est servie")
    txt = (f"{servie} : NDCG@{K} {ev['agrege'][servie][f'ndcg_at_{K}']:.4f} contre "
           f"{ref[f'ndcg_at_{K}']:.4f} pour « {ref['nom']} » "
           f"(écart {vs['ecart_moyen']:+.4f}, IC95 {vs['ecart_ic95']})")
    if servie != "wide_deep" and "wide_deep" in ev["agrege"]:
        txt += ("; le Wide & Deep n'est pas significativement meilleur que ce modèle "
                "plus simple, qui est donc servi par parcimonie")
    return txt


def _formater(df: pd.DataFrame, candidats: pd.DataFrame, score: np.ndarray,
              date_ref: pd.Timestamp, noms: Dict[str, str]) -> Dict[str, Any]:
    """Top K par client, enrichi de ce qui rend la recommandation vérifiable."""
    r12 = df[df["date"] > date_ref - pd.DateOffset(months=12)]
    designation = df.groupby("reference")["designation"].agg(lambda x: x.mode().iat[0])
    # Montant annuel médian dépensé par un acheteur de ce produit : un ORDRE DE
    # GRANDEUR observé, pas une prévision de chiffre d'affaires.
    ca_par_acheteur = (r12.groupby(["reference", "client"])["montant"].sum()
                       .groupby("reference").median())
    c = candidats.assign(score=np.asarray(score, float))
    c = c.sort_values(["client", "score", "reference"], ascending=[True, False, True])
    c["rang"] = c.groupby("client").cumcount() + 1
    top = c[c["rang"] <= K]
    sortie: Dict[str, Any] = {}
    for cl, g in top.groupby("client"):
        sortie[cl] = {
            "nom": noms.get(cl, cl),
            "type_etablissement": str(g["type_etab"].iat[0]),
            "produits": [{
                "rang": int(r["rang"]),
                "reference": r["reference"],
                "designation": str(designation.get(r["reference"], r["reference"])),
                "famille": r["famille"],
                "score": round(float(r["score"]), 4),
                "acheteurs_12m": int(round(float(np.expm1(r["log_acheteurs_12m"])))),
                "adoption_meme_type_pct": round(float(r["part_meme_type"]) * 100, 1),
                "montant_annuel_median_par_acheteur_dt": round(
                    float(ca_par_acheteur.get(r["reference"], 0.0)), 0),
            } for _, r in g.iterrows()],
        }
    return sortie


def _ecrire(rapport: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(rapport, open(RAPPORT, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False, default=str)


# ── Lecture (API, agents) — aucune dépendance à PyTorch ─────────────────────
def _avec_raisons(produit: Dict[str, Any],
                  type_etab: Optional[str] = None) -> Dict[str, Any]:
    """Pourquoi CE produit est proposé à CE client.

    Les recommandations sont précalculées : le modèle n'est pas rejoué ici. Mais
    les trois grandeurs qui fondent son classement sont, elles, déjà dans le
    fichier — combien d'établissements l'achètent, quelle part des établissements
    du même type l'a adopté, et ce que cela représente par an. Les rendre
    lisibles suffit à justifier la proposition ; inventer une attribution à
    partir d'un fichier de sortie serait, lui, malhonnête.
    """
    acheteurs = int(produit.get("acheteurs_12m") or 0)
    adoption = float(produit.get("adoption_meme_type_pct") or 0.0)
    montant = float(produit.get("montant_annuel_median_par_acheteur_dt") or 0.0)

    raisons: List[Dict[str, Any]] = []
    if adoption > 0:
        # Le type d'établissement sert de comparaison ; quand il vaut « autre »,
        # le nommer donnerait « 13,9 % des autre l'achètent déjà ».
        t = (type_etab or "").strip().lower()
        comparables = ("établissements comparables"
                       if not t or t in {"autre", "autres", "inconnu"}
                       else f"{t}x" if t.endswith("al") else f"{t}s")
        raisons.append({
            "variable": "adoption_meme_type_pct", "valeur": round(adoption, 1),
            "poids": None, "sens": "favorise",
            "explication": (f"{adoption:.1f} %".replace(".", ",")
                            + f" des {comparables} l'achètent déjà"),
        })
    if acheteurs > 0:
        raisons.append({
            "variable": "acheteurs_12m", "valeur": acheteurs, "poids": None,
            "sens": "favorise",
            "explication": f"{acheteurs} établissement(s) l'ont acheté sur 12 mois",
        })
    if montant > 0:
        m = (f"{montant / 1e3:.0f} K DT" if montant >= 1e3 else f"{montant:.0f} DT")
        raisons.append({
            "variable": "montant_annuel_median_par_acheteur_dt",
            "valeur": montant, "poids": None, "sens": "favorise",
            "explication": f"{m} par an en moyenne chez ceux qui l'achètent",
        })
    return {**produit, "raisons": raisons}


def predire(client: Optional[str] = None, limite: int = 10,
            n_clients: int = 15) -> Dict[str, Any]:
    """Recommandations précalculées, si le registre l'autorise.

    `client` fourni : la liste de ce client. Sinon : les clients dont les
    recommandations pèsent le plus, pour l'agent Commercial.
    """
    from ml_engine.registre import est_deploye, etat_modele

    if not est_deploye("recommandation"):
        return {"servi": False, "motif": etat_modele("recommandation").get("motif")}
    if not SORTIE.exists():
        return {"servi": False, "motif": "recommandations absentes — lancer l'entraînement"}
    try:
        doc = json.load(open(SORTIE, encoding="utf-8"))
    except Exception as e:
        return {"servi": False, "motif": f"fichier illisible ({type(e).__name__})"}

    base = {"servi": True, "methode": doc.get("methode"),
            "deep_learning": doc.get("methode") == "wide_deep",
            "date_de_reference": doc.get("date_de_reference"),
            "horizon_mois": doc.get("horizon_mois")}
    clients = doc.get("clients") or {}
    if client is not None:
        c = clients.get(str(client))
        if not c:
            return {**base, "client": client, "produits": [],
                    "motif": "aucune recommandation pour ce client"}
        return {**base, "client": client, "nom": c["nom"],
                "produits": [_avec_raisons(p, c.get("type_etablissement"))
                             for p in c["produits"][:limite]]}

    def potentiel(c: Dict[str, Any]) -> float:
        return float(sum(p["montant_annuel_median_par_acheteur_dt"]
                         for p in c["produits"][:3]))

    classes = sorted(clients.items(), key=lambda kv: -potentiel(kv[1]))[:n_clients]
    return {**base, "n_clients": len(clients),
            "top": [{"client": code, "nom": c["nom"],
                     "type_etablissement": c["type_etablissement"],
                     "potentiel_top3_dt": round(potentiel(c), 0),
                     "produits": [_avec_raisons(p, c["type_etablissement"])
                                  for p in c["produits"][:3]]} for code, c in classes],
            "lecture": ("potentiel = montant annuel médian dépensé par les clients "
                        "qui achètent déjà ces trois produits — un ordre de grandeur "
                        "observé, pas une prévision de chiffre d'affaires")}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    r = train()
    ev = r.get("evaluation", {})
    for nom, m in (ev.get("agrege") or {}).items():
        print(f"  {nom:24} NDCG@10 {m['ndcg_at_10']:.4f} · Recall@10 "
              f"{m['recall_at_10']:.4f} · HitRate@10 {m['hit_rate_at_10']:.4f}")
