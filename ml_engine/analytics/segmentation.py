"""
ml_engine/analytics/segmentation.py
====================================
Segmentation de la clientèle — apprentissage NON SUPERVISÉ.

Ce que ce module apporte que les autres ne donnent pas
------------------------------------------------------
Le tableau de bord répond déjà à « quels clients ? » : les plus gros, ceux qui
décrochent, ceux qui paient tard. Il ne répond pas à « **quels TYPES de clients
servons-nous ?** ».

La différence est opérationnelle. Une liste de 945 clients ne se pilote pas ; une
poignée de segments, si. Un directeur commercial n'a pas de politique par client,
il en a une par catégorie — et cette catégorisation est aujourd'hui implicite,
dans la tête des commerciaux, jamais mesurée.

Trois exigences, sans lesquelles une segmentation reste décorative
------------------------------------------------------------------
Un clustering produit toujours un résultat : c'est précisément son danger. Trois
conditions sont donc vérifiées, et le module refuse de servir si elles échouent.

1. **Séparation** — les groupes sont-ils distincts, ou découpe-t-on un nuage
   homogène ? Mesuré par le coefficient de silhouette.

2. **Stabilité** — un même client retombe-t-il dans le même groupe si l'on
   ré-échantillonne ? Une segmentation instable décrit le hasard du tirage, pas
   la clientèle. Mesurée par l'indice de Rand ajusté sur ré-échantillonnages.

3. **Interprétabilité** — chaque segment porte un nom métier DÉRIVÉ de ses
   caractéristiques mesurées, jamais choisi à la main. « Segment 3 » n'est pas
   exploitable ; « grands comptes réguliers » l'est.

Le croisement qui justifie l'existence du module
------------------------------------------------
Segmentation et décrochage se répondent : le premier dit *qui sont* les clients,
le second *lesquels partent*. Croiser les deux donne une lecture qu'aucun ne
produit seul — **quel type de clientèle perdons-nous ?** Un décrochage concentré
sur les petits comptes occasionnels n'appelle pas la même réaction qu'un
décrochage sur les comptes stratégiques.

Sortie
------
- `models/segmentation.joblib`         : modèle + normalisation
- `reports/segmentation_metrics.json`  : qualité, profils, croisement
- `output/client_segments.json`        : segment par client

Lancement :
    python -m ml_engine.analytics.segmentation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

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

SEED = 42
K_MIN, K_MAX = 3, 6          # au-delà de 6, une segmentation cesse d'être pilotable
MIN_FACTURES = 3             # sous ce seuil, aucun comportement n'est caractérisable
DEBUT_EXPLOITABLE = "2021-01-01"

# Seuils d'acceptation, posés AVANT la mesure.
SILHOUETTE_MIN = 0.25        # en dessous, les groupes se chevauchent trop
STABILITE_MIN = 0.60         # indice de Rand ajusté médian sur ré-échantillonnage

VARIABLES = [
    "log_ca_total", "log_frequence", "recence_j",
    "regularite", "log_panier", "anciennete_mois", "log_diversite",
]


# ── Construction du profil client ───────────────────────────────────────────
def charger_profils(data_dir: Optional[Path] = None) -> pd.DataFrame:
    """Un profil comportemental par client, sur données réelles.

    Les avoirs sont exclus et les factures dédupliquées — même nettoyage que
    partout ailleurs. Un avoir compté comme commande ferait passer une
    annulation pour un signe d'activité.
    """
    from ml_engine.analytics.kpi_engine import _connect

    con = _connect(data_dir)
    try:
        df = con.execute(f"""
            WITH base AS (
                SELECT client,
                       any_value(client_name) AS nom,
                       count(*)               AS n_factures,
                       sum(ttc)               AS ca_total,
                       avg(ttc)               AS panier,
                       min(date)              AS premiere,
                       max(date)              AS derniere,
                       count(DISTINCT strftime(date, '%Y-%m')) AS mois_actifs
                FROM sales
                WHERE date IS NOT NULL AND NOT est_avoir
                  AND date >= DATE '{DEBUT_EXPLOITABLE}'
                  AND client_name IS NOT NULL
                  AND client_name NOT ILIKE '%passager%'
                  AND client_name NOT ILIKE '%comptant%'
                  AND client_name NOT ILIKE '%divers%'
                GROUP BY client
                HAVING count(*) >= {MIN_FACTURES} AND sum(ttc) > 0
            ),
            -- Étendue de gamme : nombre de références distinctes achetées.
            -- `client_product_demand` porte le lien client-produit réel ;
            -- `product_sales` est agrégé par produit et par année, sans client.
            familles AS (
                SELECT client, count(DISTINCT produit) AS n_familles
                FROM client_product_demand
                WHERE produit IS NOT NULL
                GROUP BY client
            ),
            ref AS (SELECT max(date) AS md FROM sales)
            SELECT b.*, coalesce(f.n_familles, 1) AS n_familles,
                   datediff('day', b.derniere, (SELECT md FROM ref)) AS recence_j,
                   datediff('month', b.premiere, (SELECT md FROM ref)) AS anciennete_mois
            FROM base b LEFT JOIN familles f ON f.client = b.client
        """).df()
    finally:
        con.close()

    if df.empty:
        return df

    # Les montants suivent une loi très asymétrique : quelques hôpitaux pèsent
    # mille fois un petit laboratoire. Sans passage au logarithme, la distance
    # euclidienne ne verrait plus que la taille et produirait une segmentation
    # qui se réduit à « gros » contre « petits ».
    df["log_ca_total"] = np.log1p(df["ca_total"].clip(lower=0))
    df["log_panier"] = np.log1p(df["panier"].clip(lower=0))
    df["log_frequence"] = np.log1p(df["n_factures"].clip(lower=0))
    df["anciennete_mois"] = df["anciennete_mois"].clip(lower=1)
    # L'étendue de gamme suit la même loi asymétrique que les montants : un CHU
    # achète des centaines de références, un cabinet trois.
    df["log_diversite"] = np.log1p(df["n_familles"].clip(lower=1))

    # Régularité : part des mois où le client a commandé depuis son arrivée.
    # 1,0 = il commande tous les mois ; 0,1 = un mois sur dix.
    df["regularite"] = (df["mois_actifs"] / df["anciennete_mois"]).clip(0, 1)
    return df.reset_index(drop=True)


# ── Choix du nombre de segments ─────────────────────────────────────────────
def _evaluer_k(X: np.ndarray) -> Dict[int, Dict[str, float]]:
    """Silhouette et stabilité pour chaque k envisagé.

    Les deux comptent, et pas dans le même sens. La silhouette monte souvent
    quand k baisse ; la stabilité aussi. Un k trop petit donnerait donc de bons
    scores et aucune information exploitable — d'où la borne inférieure de 3.
    """
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score, silhouette_score

    from ml_engine.determinisme import limiter_threads

    rng = np.random.default_rng(SEED)
    out: Dict[int, Dict[str, float]] = {}

    # ══ UN SEUL THREAD PENDANT LA MESURE ══
    #
    # La graine est fixée et le générateur est semé, et pourtant deux exécutions
    # identiques donnaient des stabilités différentes (k=3 : 0,9283 puis 0,9754).
    # Les centroïdes de KMeans sont des moyennes parallélisées : l'addition
    # flottante n'étant pas associative, un client à égale distance de deux
    # centres basculait d'un groupe à l'autre selon l'ordonnancement des threads.
    #
    # La conséquence était VISIBLE pour l'utilisateur, et c'est ce qui rend ce
    # défaut sérieux : deux segments de tailles voisines échangeaient leur nom
    # entre deux exécutions — « Petits comptes occasionnels » et « … en sommeil »
    # permutaient. Le tableau de bord renommait donc des segments sans qu'aucune
    # donnée ait changé. Cf. ml_engine/determinisme.py.
    with limiter_threads(1):
        for k in range(K_MIN, K_MAX + 1):
            km = KMeans(n_clusters=k, n_init=20, random_state=SEED)
            lab = km.fit_predict(X)
            sil = float(silhouette_score(X, lab)) if len(set(lab)) > 1 else 0.0

            # Stabilité : on ré-échantillonne 80 % des clients, on resegmente, et
            # on compare les affectations sur les clients communs. Si elles
            # divergent, la segmentation décrit le tirage plutôt que la clientèle.
            scores = []
            for _ in range(8):
                idx = rng.choice(len(X), size=int(len(X) * 0.8), replace=False)
                lab2 = KMeans(n_clusters=k, n_init=10,
                              random_state=SEED).fit_predict(X[idx])
                scores.append(adjusted_rand_score(lab[idx], lab2))
            out[k] = {"silhouette": round(sil, 4),
                      "stabilite": round(float(np.median(scores)), 4),
                      "inertie": round(float(km.inertia_), 1)}
    return out


# ── Nommage métier ──────────────────────────────────────────────────────────
def _nommer_tous(profils: List[pd.Series]) -> List[Dict[str, str]]:
    """Nomme les segments les uns PAR RAPPORT AUX AUTRES, en garantissant l'unicité.

    Première version, écartée : chaque segment était comparé à la médiane globale
    de la clientèle. Deux défauts l'ont invalidée. D'abord la médiane globale est
    tirée par le segment majoritaire — 605 clients sur 938 — si bien qu'un
    segment pesant 10 % du chiffre d'affaires se retrouvait qualifié de « petits
    comptes ». Ensuite et surtout, rien ne garantissait l'unicité : trois
    segments distincts portaient le même nom, ce qui les rendait indiscernables
    dans l'interface.

    Le nommage se fait donc par RANG entre segments, jamais par seuil absolu, et
    l'unicité est vérifiée puis forcée par l'ajout du trait le plus distinctif.
    """
    n = len(profils)
    ca = np.array([float(p["ca_total"]) for p in profils])
    reg = np.array([float(p["regularite"]) for p in profils])
    rec = np.array([float(p["recence_j"]) for p in profils])
    div = np.array([float(p["n_familles"]) for p in profils])
    pan = np.array([float(p["panier"]) for p in profils])

    def rang(v: np.ndarray) -> np.ndarray:
        """Rang normalisé dans [0,1] : 1 = le plus élevé des segments."""
        ordre = np.argsort(np.argsort(v))
        return ordre / max(n - 1, 1)

    r_ca, r_reg, r_rec, r_div, r_pan = (rang(x) for x in (ca, reg, rec, div, pan))

    # Chaque axe fournit un qualificatif possible. Le trait distinctif d'un
    # segment est celui où il s'écarte le plus des autres — c'est ce qui le
    # rend reconnaissable, et donc actionnable.
    noms: List[Dict[str, str]] = []
    for i in range(n):
        if r_ca[i] >= 0.75:
            valeur = "Comptes stratégiques"
        elif r_ca[i] >= 0.4:
            valeur = "Comptes intermédiaires"
        else:
            valeur = "Petits comptes"

        if r_reg[i] >= 0.7:
            rythme = "réguliers"
        elif r_reg[i] <= 0.3:
            rythme = "occasionnels"
        else:
            rythme = "actifs"

        nom = f"{valeur} {rythme}"

        # Traits complémentaires, classés par force de l'écart. Le plus marqué
        # est ajouté au nom uniquement s'il départage vraiment.
        traits: List[tuple] = []
        if r_rec[i] >= 0.75:
            traits.append((r_rec[i], "en sommeil"))
        if r_div[i] >= 0.75:
            traits.append((r_div[i], "à gamme large"))
        elif r_div[i] <= 0.25:
            traits.append((1 - r_div[i], "mono-produit"))
        if r_pan[i] >= 0.75:
            traits.append((r_pan[i], "à gros paniers"))
        traits.sort(key=lambda t: -t[0])

        noms.append({
            "base": nom,
            "traits": [t[1] for t in traits],
            "caracterisation": (
                f"{int(profils[i]['n_factures'])} commandes médianes, "
                f"panier {profils[i]['panier']:,.0f} DT, "
                f"{int(profils[i]['n_familles'])} références distinctes, "
                f"dernière commande il y a {int(rec[i])} jours"
            ).replace(",", " "),
        })

    # ── Unicité : un nom porté par deux segments ne désigne plus rien ────────
    #
    # ══ DÉFAUT CORRIGÉ ICI, ET IL ÉTAIT VISIBLE PAR L'UTILISATEUR ══
    #
    # La version précédente parcourait les segments dans l'ordre de leurs
    # IDENTIFIANTS DE CLUSTER. Or ces identifiants sont arbitraires : KMeans les
    # attribue dans l'ordre où ses centroïdes convergent, qui varie au dernier
    # bit d'une exécution à l'autre (cf. ml_engine/determinisme.py).
    #
    # Conséquence observée : deux segments partageant la base « Petits comptes
    # occasionnels » — le premier rencontré gardait le nom nu, le second héritait
    # du suffixe « — en sommeil ». L'ordre changeant, **le suffixe changeait de
    # segment entre deux exécutions**, et le tableau de bord renommait des
    # segments sans qu'aucune donnée ait bougé.
    #
    # Deux corrections, indépendantes du hasard d'étiquetage :
    #
    #   1. Les collisions sont résolues dans un ordre CANONIQUE, déduit des
    #      données (chiffre d'affaires décroissant) et non de l'étiquetage.
    #   2. Dans un groupe en collision, AUCUN membre ne garde le nom nu. Tous
    #      reçoivent un qualificatif. Il n'y a donc plus de « premier arrivé »
    #      à départager, et la question de l'ordre disparaît au lieu d'être
    #      seulement stabilisée.
    finaux: List[str] = [""] * n

    groupes: Dict[str, List[int]] = {}
    for i, d in enumerate(noms):
        groupes.setdefault(d["base"], []).append(i)

    for base, membres in sorted(groupes.items()):
        if len(membres) == 1:
            finaux[membres[0]] = base
            continue

        # Collision. On départage par la RÉCENCE, l'axe qui distingue le plus
        # naturellement deux segments de poids voisin : l'un commande encore,
        # l'autre s'est arrêté. Les ex æquo de récence sont départagés par le
        # chiffre d'affaires, puis par le panier — trois critères, comme pour les
        # tris SQL du projet, afin qu'aucun ordre ne reste indéterminé.
        membres = sorted(membres, key=lambda i: (rec[i], -ca[i], -pan[i]))

        for rang_dans_groupe, i in enumerate(membres):
            if rang_dans_groupe == 0:
                suffixe = "encore actifs"
            elif rang_dans_groupe == len(membres) - 1:
                suffixe = "en sommeil"
            else:
                # Cas à trois membres ou plus : on nomme par la récence réelle,
                # lisible et nécessairement distincte après le tri ci-dessus.
                suffixe = f"sans commande depuis {int(rec[i])} j"
            finaux[i] = f"{base} — {suffixe}"

    # Garde-fou final : si deux noms coïncidaient encore, l'interface afficherait
    # deux lignes indiscernables. On le refuse explicitement plutôt que de le
    # laisser passer silencieusement.
    if len(set(finaux)) != n:
        for i in range(n):
            if finaux.count(finaux[i]) > 1:
                finaux[i] = f"{finaux[i]} ({int(ca[i]):,} DT)".replace(",", " ")

    return [{"nom": finaux[i], "caracterisation": noms[i]["caracterisation"]}
            for i in range(n)]


# ── Entraînement ────────────────────────────────────────────────────────────
def train(data_dir: Optional[Path] = None) -> Dict[str, Any]:
    import joblib
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    print("[segmentation] Chargement des profils clients…")
    df = charger_profils(data_dir)
    if df.empty or len(df) < 50:
        raise RuntimeError(f"profils insuffisants ({len(df)})")
    print(f"[segmentation] {len(df)} clients · {df['ca_total'].sum()/1e6:.1f} M DT")

    scaler = StandardScaler()
    X = scaler.fit_transform(df[VARIABLES].to_numpy())

    print("[segmentation] Évaluation du nombre de segments…")
    grille = _evaluer_k(X)
    for k, m in grille.items():
        print(f"[segmentation]   k={k} · silhouette {m['silhouette']:.4f} "
              f"· stabilité {m['stabilite']:.4f}")

    # Parmi les k acceptables, on retient la meilleure silhouette. Si aucun ne
    # passe les deux seuils, on prend le moins mauvais et le module se déclare
    # NON servi — mieux vaut une segmentation refusée qu'une segmentation fausse.
    admissibles = [k for k, m in grille.items()
                   if m["silhouette"] >= SILHOUETTE_MIN
                   and m["stabilite"] >= STABILITE_MIN]
    k_retenu = (max(admissibles, key=lambda k: grille[k]["silhouette"])
                if admissibles else max(grille, key=lambda k: grille[k]["silhouette"]))
    servi = bool(admissibles)

    # La segmentation SERVIE est calculée sous la même contrainte d'un thread que
    # la grille ci-dessus : sans cela, les segments affichés pourraient différer
    # de ceux sur lesquels la silhouette et la stabilité ont été mesurées.
    from ml_engine.determinisme import limiter_threads
    with limiter_threads(1):
        km = KMeans(n_clusters=k_retenu, n_init=30, random_state=SEED)
        brut = km.fit_predict(X)

    # ══ ÉTIQUETTES CANONIQUES ══
    #
    # KMeans numérote ses groupes dans l'ordre où ses centroïdes convergent. Cet
    # ordre est arbitraire et varie au dernier bit d'une exécution à l'autre : le
    # même segment portait l'identifiant 3 puis 0. Tout ce qui en dépend — l'ordre
    # de nommage, les jointures du croisement avec le décrochage — héritait de
    # cette instabilité.
    #
    # Les étiquettes sont donc réécrites selon un critère déduit des DONNÉES :
    # 0 = le groupe au plus fort chiffre d'affaires cumulé, puis par ordre
    # décroissant. Les ex æquo sont départagés par l'effectif puis par la récence,
    # pour qu'aucun ordre ne reste indéterminé — même règle que pour les tris SQL
    # du projet.
    #
    # La correction est appliquée ICI, à la source, et non dans chaque
    # consommateur : c'est la seule manière de garantir que rien en aval ne
    # dépende d'un numéro arbitraire.
    df["segment"] = brut
    poids = (df.groupby("segment")
               .agg(ca=("ca_total", "sum"),
                    n=("ca_total", "size"),
                    rec=("recence_j", "median"))
               .reset_index())
    ordre = poids.sort_values(["ca", "n", "rec"],
                              ascending=[False, False, True])["segment"].tolist()
    correspondance = {ancien: nouveau for nouveau, ancien in enumerate(ordre)}
    df["segment"] = df["segment"].map(correspondance).astype(int)

    # ── Profils et noms ─────────────────────────────────────────────────────
    ids = sorted(df["segment"].unique())
    profils = [df[df["segment"] == s][
        ["ca_total", "regularite", "recence_j", "n_factures",
         "panier", "n_familles"]].median() for s in ids]
    noms = _nommer_tous(profils)

    segments: List[Dict[str, Any]] = []
    for j, s in enumerate(ids):
        sub = df[df["segment"] == s]
        p = profils[j]
        segments.append({
            "segment": int(s),
            "nom": noms[j]["nom"],
            "caracterisation": noms[j]["caracterisation"],
            "n_clients": int(len(sub)),
            "part_clients_pct": round(len(sub) / len(df) * 100, 1),
            "ca_total_dt": round(float(sub["ca_total"].sum()), 0),
            "part_ca_pct": round(float(sub["ca_total"].sum() / df["ca_total"].sum() * 100), 1),
            "ca_median_dt": round(float(p["ca_total"]), 0),
            "panier_median_dt": round(float(p["panier"]), 0),
            "commandes_medianes": int(p["n_factures"]),
            "regularite_mediane": round(float(p["regularite"]), 3),
            "recence_mediane_j": int(p["recence_j"]),
            "references_medianes": int(p["n_familles"]),
        })
    segments.sort(key=lambda x: -x["ca_total_dt"])

    print(f"\n[segmentation] {k_retenu} segments retenus "
          f"({'servi' if servi else 'NON SERVI — seuils non atteints'}) :")
    for s in segments:
        print(f"[segmentation]   {s['nom']:<42} {s['n_clients']:>4} clients · "
              f"{s['part_ca_pct']:>5.1f} % du CA")

    # ── Croisement avec le décrochage ───────────────────────────────────────
    croisement = _croiser_churn(df)

    metrics = {
        "version": 1,
        "methode": "K-means sur profil comportemental normalisé (RFM enrichi)",
        "pourquoi_non_supervise": (
            "Il n'existe pas d'étiquette « type de client » à prédire : la "
            "typologie est à découvrir, pas à reproduire. Un modèle supervisé "
            "exigerait qu'un expert étiquette d'abord 945 clients à la main."),
        "n_clients": int(len(df)),
        "variables": VARIABLES,
        "transformation": (
            "logarithme sur les montants et la fréquence : sans lui, quelques "
            "hôpitaux pesant mille fois un petit laboratoire réduiraient la "
            "segmentation à « gros » contre « petits »"),
        "grille_k": {str(k): v for k, v in grille.items()},
        "k_retenu": k_retenu,
        "qualite": {
            "silhouette": grille[k_retenu]["silhouette"],
            "stabilite_rand_ajuste": grille[k_retenu]["stabilite"],
            "seuils": {"silhouette_min": SILHOUETTE_MIN,
                       "stabilite_min": STABILITE_MIN},
            "lecture_silhouette": (
                "mesure la séparation des groupes : au-dessus de 0,25 les "
                "segments sont distincts, en dessous on découpe un nuage homogène"),
            "lecture_stabilite": (
                "part d'accord entre segmentations obtenues sur des "
                "ré-échantillons à 80 % : une valeur basse signifierait que les "
                "groupes décrivent le tirage, non la clientèle"),
        },
        "segments": segments,
        "croisement_decrochage": croisement,
        "servi": servi,
        "motif": ("segmentation servie : séparation et stabilité confirmées"
                  if servi else
                  "seuils non atteints — la clientèle ne présente pas de "
                  "structure de groupes nette ; servir une segmentation "
                  "instable induirait en erreur"),
    }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # `correspondance` DOIT accompagner le modèle. `km.predict()` renvoie les
    # étiquettes brutes de KMeans ; sans cette table, un client scoré plus tard
    # recevrait un numéro de l'ancienne numérotation et donc le nom d'un autre
    # segment. Sauvegarder le modèle sans sa table de correspondance serait le
    # type de désynchronisation qui ne lève aucune erreur.
    joblib.dump({"kmeans": km, "scaler": scaler, "variables": VARIABLES,
                 "correspondance_etiquettes": correspondance,
                 "noms": {s["segment"]: s["nom"] for s in segments},
                 "servi": servi}, MODELS_DIR / "segmentation.joblib")
    json.dump(metrics, open(REPORTS_DIR / "segmentation_metrics.json", "w",
                            encoding="utf-8"), indent=2, ensure_ascii=False)

    noms = {s["segment"]: s["nom"] for s in segments}
    json.dump({str(r["client"]): {"segment": int(r["segment"]),
                                  "nom_segment": noms[int(r["segment"])],
                                  "nom_client": r["nom"]}
               for _, r in df.iterrows()},
              open(OUTPUT_DIR / "client_segments.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    print(f"[segmentation] → {REPORTS_DIR / 'segmentation_metrics.json'}")
    return metrics


def _croiser_churn(df: pd.DataFrame) -> Dict[str, Any]:
    """Quel type de clientèle perdons-nous ?

    Ni la segmentation ni le modèle de décrochage ne répondent seuls. Le premier
    dit qui sont les clients, le second lesquels partent. Le croisement dit
    lesquels **de quel type** partent — et c'est cette réponse qui oriente une
    politique commerciale plutôt qu'une liste d'appels.
    """
    try:
        from ml_engine.analytics.churn_model import load_client_churn
        from ml_engine.registre import est_deploye
        if not est_deploye("churn"):
            return {"disponible": False, "motif": "modèle de décrochage non servi"}
        scores = load_client_churn()
    except Exception:
        return {"disponible": False, "motif": "scores de décrochage indisponibles"}

    if not scores:
        return {"disponible": False, "motif": "aucun score disponible"}

    df = df.copy()
    df["p"] = df["client"].astype(str).map(
        {k: float(v.get("probabilite_decrochage") or 0) for k, v in scores.items()})
    couvert = df[df["p"].notna()]
    if len(couvert) < 30:
        return {"disponible": False,
                "motif": f"seulement {len(couvert)} clients communs"}

    lignes = []
    for s in sorted(couvert["segment"].unique()):
        sub = couvert[couvert["segment"] == s]
        menace = sub[sub["p"] >= 0.5]
        lignes.append({
            "segment": int(s),
            "n_clients_evalues": int(len(sub)),
            "risque_moyen": round(float(sub["p"].mean()), 4),
            "n_menaces": int(len(menace)),
            "part_menacee_pct": round(len(menace) / len(sub) * 100, 1),
            "ca_menace_dt": round(float(menace["ca_total"].sum()), 0),
        })
    lignes.sort(key=lambda x: -x["part_menacee_pct"])

    return {
        "disponible": True,
        "n_clients_croises": int(len(couvert)),
        "par_segment": lignes,
        "lecture": (
            "Un décrochage concentré sur les petits comptes occasionnels est un "
            "phénomène de fond qui n'appelle pas la même réaction qu'un "
            "décrochage sur les comptes stratégiques. La part menacée par "
            "segment oriente la politique ; la liste nominative oriente les appels."),
    }


def load_segments() -> Dict[str, Any]:
    p = OUTPUT_DIR / "client_segments.json"
    if p.exists():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    m = train()
    cr = m.get("croisement_decrochage") or {}
    if cr.get("disponible"):
        print("\n[segmentation] Décrochage par segment :")
        noms = {s["segment"]: s["nom"] for s in m["segments"]}
        for l in cr["par_segment"]:
            print(f"[segmentation]   {noms.get(l['segment'], l['segment']):<42} "
                  f"{l['part_menacee_pct']:>5.1f} % menacés · "
                  f"{l['ca_menace_dt']/1e3:>8.0f} K DT")
