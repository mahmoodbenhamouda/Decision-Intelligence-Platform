"""
ml_engine/stock/generator.py
============================
Générateur de STOCK SIMULÉ, calibré sur la demande réelle.

⚠️ Les données produites sont **SIMULÉES**, jamais observées. Voir le module
`ml_engine.stock` et `docs/STOCK_SIMULE.md`.

## Modèle de simulation (entièrement explicite)

Pour chaque produit, la demande réelle observée (`product_sales`, 6 ans)
détermine tous les paramètres — aucune valeur n'est tirée « au hasard » sans
ancrage :

1. **Demande journalière moyenne** `d = qté annuelle récente ÷ 365`.
2. **Variabilité** `σ` : écart-type des volumes mensuels réels, ramené au jour.
3. **Délai de réapprovisionnement** `L` (jours), selon la famille de produit :
   - RÉACTIF : 45 j (import, fournisseur unique dominant — Biomérieux 84,6 %)
   - ÉQUIPEMENT : 75 j (matériel lourd, fabrication à la commande)
   - CONSOMMABLE / autres : 30 j
   - SERVICE : sans stock (exclu)
4. **Stock de sécurité** `SS = z × σ × √L`, avec `z = 1,65` (taux de service
   visé de 95 %) — formule standard de gestion des stocks.
5. **Point de commande** `s = d × L + SS`.
6. **Niveau de recomplètement** `S = s + d × période_de_couverture`
   (période = 60 j pour les réactifs, 90 j pour les équipements).
7. **Stock actuel** : tiré dans `[0, S]` selon un profil réaliste — la plupart
   des produits sont correctement approvisionnés, une minorité est en tension :
   - 62 % : stock sain, entre `s` et `S`
   - 18 % : sous le point de commande (réapprovisionnement à déclencher)
   - 8 %  : rupture ou quasi-rupture (< 20 % du point de commande)
   - 12 % : surstock (> `S`, immobilisation de trésorerie)
8. **Péremption** (spécifique au diagnostic in vitro) : les réactifs portent une
   DLC. Durée de vie 12 à 24 mois selon la famille ; la date de péremption du
   lot en cours est tirée en cohérence avec la rotation du produit.
9. **Prix unitaire** : dérivé du **coût de revient réel** (`client_margin`),
   pour que la valorisation du stock soit cohérente avec la comptabilité.

Tout est reproductible : `SIMULATION_SEED = 42`.

Usage :
    python -m ml_engine.stock.generator          # génère / régénère
    python -m ml_engine.stock.generator --stats  # statistiques seulement
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

SIMULATION_SEED = 42


def _rng_pour(cle: str) -> np.random.Generator:
    """Générateur aléatoire PROPRE à une clé (produit, ou couple client-produit).

    Un flux unique partagé par toutes les lignes rendait chaque valeur
    dépendante de TOUT ce qui avait été tiré avant elle : il suffisait que deux
    lignes de même chiffre d'affaires se départagent autrement — ce que SQL
    n'ordonne pas sans clé de tri unique — pour décaler la séquence entière et
    changer la simulation, malgré la graine fixée.

    En dérivant un générateur de la graine ET de la clé de la ligne, chaque
    valeur ne dépend plus que d'elle-même. La simulation devient insensible à
    l'ordre des lignes, à l'ajout d'un produit ou au retrait d'un autre — ce qui
    est la condition réelle de la reproductibilité, plus forte qu'un simple tri
    stable.

    `blake2b` est choisi pour être stable d'une exécution à l'autre, ce que
    `hash()` n'est pas en Python (randomisation des chaînes par processus).
    """
    empreinte = hashlib.blake2b(cle.encode("utf-8"), digest_size=8).digest()
    return np.random.default_rng([SIMULATION_SEED, int.from_bytes(empreinte, "big")])

# Paramètres par famille de produit (délai fournisseur, couverture, durée de vie)
FAMILY_PARAMS: Dict[str, Dict[str, Any]] = {
    "REACTIF":      {"lead_time": 45, "couverture": 60, "duree_vie_mois": 18, "perissable": True},
    "EQUIPEMENT":   {"lead_time": 75, "couverture": 90, "duree_vie_mois": 0,  "perissable": False},
    "CONSOMMABLE":  {"lead_time": 30, "couverture": 45, "duree_vie_mois": 24, "perissable": True},
    "_DEFAUT":      {"lead_time": 40, "couverture": 60, "duree_vie_mois": 18, "perissable": True},
}
FAMILLES_SANS_STOCK = ("SERVICE",)      # SAV, formation… : pas de stock physique

Z_SERVICE_95 = 1.65                     # taux de service visé : 95 %

# Profil de situation de stock (somme = 1.0)
PROFIL_SITUATION = {
    "sain":       0.62,   # entre point de commande et niveau cible
    "a_commander": 0.18,  # sous le point de commande
    "rupture":    0.08,   # < 20 % du point de commande
    "surstock":   0.12,   # au-dessus du niveau cible
}


def _connect(read_only: bool = True):
    import duckdb
    from ml_engine.analytics.kpi_engine import STORE_PATH
    return duckdb.connect(str(STORE_PATH), read_only=read_only)


def _family_params(famille: Optional[str]) -> Dict[str, Any]:
    f = (famille or "").upper()
    for key in FAMILY_PARAMS:
        if key != "_DEFAUT" and key in f:
            return FAMILY_PARAMS[key]
    return FAMILY_PARAMS["_DEFAUT"]


def _collect_demand(con) -> List[Dict[str, Any]]:
    """Demande RÉELLE par produit : volumes, variabilité, famille, prix."""
    rows = con.execute("""
        WITH annuel AS (
            SELECT produit, year, sum(qte) qte, sum(ca) ca
            FROM product_sales
            WHERE produit IS NOT NULL AND qte > 0
            GROUP BY produit, year
        ),
        agg AS (
            SELECT produit,
                   sum(qte)                         AS qte_totale,
                   avg(qte)                         AS qte_moy_an,
                   coalesce(stddev_samp(qte), 0)    AS qte_std_an,
                   count(*)                         AS n_annees,
                   max(year)                        AS derniere_annee,
                   sum(ca) / NULLIF(sum(qte), 0)    AS prix_unitaire
            FROM annuel GROUP BY produit
        )
        SELECT produit, qte_totale, qte_moy_an, qte_std_an, n_annees,
               derniere_annee, prix_unitaire
        FROM agg
        WHERE qte_moy_an >= 1        -- au moins une unité par an en moyenne
        -- Tri STRICTEMENT déterministe : `produit` départage les ex-aequo de
        -- volume. Sans cela, l'ordre varie d'une exécution à l'autre et la
        -- séquence de tirages aléatoires change → simulation non reproductible.
        ORDER BY qte_totale DESC, produit ASC
    """).fetchall()
    return [{"produit": r[0], "qte_totale": float(r[1] or 0),
             "qte_moy_an": float(r[2] or 0), "qte_std_an": float(r[3] or 0),
             "n_annees": int(r[4] or 1), "derniere_annee": int(r[5] or 2026),
             "prix_unitaire": float(r[6] or 0)} for r in rows]


def _famille_par_produit(con) -> Dict[str, str]:
    """Associe chaque produit à sa famille (via les libellés réels)."""
    try:
        rows = con.execute("""
            SELECT DISTINCT famille FROM product_family WHERE famille IS NOT NULL
        """).fetchall()
        familles = [r[0] for r in rows if r[0]]
    except Exception:
        familles = []
    # L'entrepôt n'associe pas produit → famille directement : on infère depuis
    # le libellé du produit (les désignations portent le type de matériel).
    mapping: Dict[str, str] = {}
    for f in familles:
        mapping[f.upper()] = f
    return mapping


def _infer_famille(produit: str, familles: Dict[str, str]) -> str:
    """Infère la famille depuis le libellé produit (réactif, équipement…)."""
    p = (produit or "").upper()
    if any(k in p for k in ("VIDAS", "KIT", "TEST", "REACTIF", "REAGENT",
                            "PANEL", "STRIP", "BANDELETTE", "CARTE", "SERUM",
                            "MILIEU", "GELOSE", "COLUMBIA", "CHOCOLAT")):
        return "REACTIF"
    if any(k in p for k in ("AUTOMATE", "ANALYSEUR", "APPAREIL", "SYSTEM",
                            "INSTRUMENT", "CENTRIFUG", "MICROSCOPE", "ETUVE")):
        return "EQUIPEMENT"
    if any(k in p for k in ("MAINTENANCE", "FORMATION", "SAV", "INSTALLATION",
                            "PRESTATION", "SERVICE")):
        return "SERVICE"
    if any(k in p for k in ("CONE", "TUBE", "PIPETTE", "EMBOUT", "PLAQUE",
                            "TIP", "LAME", "GANT", "ACCESSORY")):
        return "CONSOMMABLE"
    return "REACTIF"        # dominante du catalogue (diagnostic in vitro)


def _collect_client_demand(con) -> List[Dict[str, Any]]:
    """Demande RÉELLE par client et par produit : volumes et prix."""
    try:
        rows = con.execute("""
            SELECT
                s.client_name                       AS client,
                c.produit                           AS produit,
                c.qte_totale                        AS qte_totale,
                c.ca_total                          AS ca_total,
                c.n_annees                          AS n_annees,
                c.ca_total / NULLIF(c.qte_totale, 0) AS prix_unitaire
            FROM client_product_demand c
            JOIN (
                SELECT DISTINCT client, client_name 
                FROM sales 
                WHERE client_name IS NOT NULL AND trim(client_name) <> ''
            ) s ON c.client = s.client
            WHERE c.qte_totale > 0 AND c.produit IS NOT NULL AND trim(c.produit) <> ''
            -- `produit` clôt l'ordre : sans ce départage, deux références de
            -- même chiffre d'affaires (cas très fréquent sur les petites
            -- lignes, et systématique à CA nul) sortent dans un ordre non
            -- garanti par DuckDB. Comme les tirages aléatoires sont consommés
            -- ligne à ligne, cela suffisait à rendre TOUTE la simulation
            -- non reproductible malgré la graine fixée.
            -- `c.client` (le CODE) clôt définitivement le tri : deux codes
            -- clients distincts peuvent porter le même libellé, et le triplet
            -- précédent ne les départageait donc pas.
            ORDER BY s.client_name ASC, c.ca_total DESC, c.produit ASC, c.client ASC
        """).fetchall()
        return [{"client": r[0], "produit": r[1], "qte_totale": float(r[2] or 0),
                 "ca_total": float(r[3] or 0), "n_annees": int(r[4] or 1),
                 "prix_unitaire": float(r[5] or 0)} for r in rows]
    except Exception:
        return []


def _signature_demande(con) -> str:
    """Empreinte de la demande servant de calibrage.

    Résume `product_sales` — nombre de produits, quantités et montants cumulés —
    de sorte que toute correction de l'entrepôt (passage aux quantités signées,
    déduplication des lignes…) modifie l'empreinte et déclenche une
    régénération. Sans cela, le stock reste calibré sur des chiffres périmés
    sans que rien ne l'indique.
    """
    try:
        r = con.execute("""
            SELECT count(*), coalesce(sum(qte), 0), coalesce(sum(ca), 0),
                   coalesce(count(DISTINCT produit), 0)
            FROM product_sales
        """).fetchone()
        return f"v1:{r[0]}:{float(r[1]):.3f}:{float(r[2]):.3f}:{r[3]}"
    except Exception:
        return "v1:indisponible"


def generate_stock(force: bool = False, verbose: bool = True) -> Dict[str, Any]:
    """Génère le stock simulé et le matérialise dans l'entrepôt.

    Returns: statistiques de génération (nombre de produits, valorisation…).
    """
    # Pas de flux aléatoire global ici : chaque ligne dérive le sien de sa
    # propre clé (`_rng_pour`), ce qui rend la simulation indépendante de
    # l'ordre dans lequel les produits sont parcourus.
    con = _connect(read_only=False)

    # Signature de la demande sur laquelle le stock est calibré.
    # L'ancien test d'idempotence se contentait de « la table existe et n'est
    # pas vide ». Il ne pouvait donc PAS voir qu'une correction de l'entrepôt
    # avait changé la demande : le stock restait calibré sur des quantités
    # périmées, silencieusement. C'est la même faiblesse que celle qui a laissé
    # passer un CA faux — un contrôle de fraîcheur qui ne contrôle rien.
    signature_demande = _signature_demande(con)

    if not force:
        try:
            n = con.execute("SELECT count(*) FROM stock_simule").fetchone()[0]
            sig_stockee = None
            try:
                sig_stockee = con.execute(
                    "SELECT signature_demande FROM stock_simule_meta LIMIT 1").fetchone()[0]
            except Exception:
                pass                      # métadonnées d'une version antérieure
            if n and sig_stockee == signature_demande:
                con.close()
                if verbose:
                    print(f"[stock] déjà généré ({n} lignes). --force pour régénérer.")
                return {"produits": int(n), "regenere": False, "is_simulated": True}
            if n and verbose:
                print("[stock] la demande de référence a changé — régénération.")
        except Exception:
            pass

    produits_globaux = _collect_demand(con)
    produits_clients = _collect_client_demand(con)
    familles = _famille_par_produit(con)
    if not produits_globaux:
        con.close()
        raise RuntimeError("Aucune donnée de vente : impossible de calibrer le stock.")

    # Date d'observation = dernière facture réelle (cohérence avec le reste)
    ref = con.execute("SELECT max(date) FROM sales").fetchone()[0] or date.today()
    if not isinstance(ref, date):
        ref = date.today()

    situations = list(PROFIL_SITUATION.keys())
    poids = [PROFIL_SITUATION[s] for s in situations]

    lignes: List[tuple] = []

    # 1. Génération globale (client = None)
    for p in produits_globaux:
        famille = _infer_famille(p["produit"], familles)
        if famille in FAMILLES_SANS_STOCK:
            continue
        par = _family_params(famille)

        d_jour = p["qte_moy_an"] / 365.0
        sigma_jour = (p["qte_std_an"] / 365.0) if p["n_annees"] > 1 else d_jour * 0.35
        sigma_jour = max(sigma_jour, d_jour * 0.15)

        L = int(par["lead_time"])
        ss = Z_SERVICE_95 * sigma_jour * math.sqrt(L)
        point_commande = d_jour * L + ss
        niveau_cible = point_commande + d_jour * par["couverture"]

        # Flux propre à ce produit : voir `_rng_pour`.
        r = _rng_pour(f"global|{p['produit']}")
        situation = r.choice(situations, p=poids)
        if situation == "sain":
            stock = r.uniform(point_commande, max(niveau_cible, point_commande * 1.05))
        elif situation == "a_commander":
            stock = r.uniform(point_commande * 0.35, point_commande)
        elif situation == "rupture":
            stock = r.uniform(0, point_commande * 0.2)
        else:
            stock = r.uniform(niveau_cible, niveau_cible * 1.9)
        # Un produit tiré comme « sain », « à commander » ou « en surstock » a par
        # DÉFINITION du stock. L'arrondi à l'entier ramenait pourtant à zéro toute
        # valeur inférieure à 0,5 — cas fréquent des références à faible rotation,
        # dont le point de commande vaut moins d'une unité. La simulation
        # produisait ainsi 856 ruptures sur 1 892 références (45 %) là où son
        # profil n'en prévoit que 8 %, et le briefing annonçait une pénurie
        # généralisée qui n'existait que dans l'arrondi.
        stock = round(stock)
        stock = float(max(0.0, stock) if situation == "rupture" else max(1.0, stock))

        date_peremption = None
        if par["perissable"] and stock > 0:
            duree = int(par["duree_vie_mois"])
            rotation = (d_jour * 365) / stock if stock > 0 else 0
            usure = r.uniform(0.25, 0.85 if rotation < 2 else 0.6)
            restant_j = max(5, int(duree * 30 * (1 - usure)))
            date_peremption = ref + timedelta(days=restant_j)

        prix = p["prix_unitaire"] if p["prix_unitaire"] > 0 else 0.0
        cout_unitaire = prix * 0.72

        lignes.append((
            None, p["produit"], famille, stock,
            round(d_jour, 6), round(sigma_jour, 6), L,
            round(ss, 6), round(point_commande, 6), round(niveau_cible, 6),
            round(cout_unitaire, 3), round(stock * cout_unitaire, 2),
            date_peremption, str(situation), True,
        ))

    # 2. Génération par client (client = client_name)
    for pc in produits_clients:
        famille = _infer_famille(pc["produit"], familles)
        if famille in FAMILLES_SANS_STOCK:
            continue
        par = _family_params(famille)

        # Quantité annuelle estimée pour CE client sur SES achats
        qte_an = pc["qte_totale"] / max(1, pc["n_annees"])
        d_jour = qte_an / 365.0
        if d_jour <= 0:
            continue
        sigma_jour = max(d_jour * 0.3, 0.01)

        L = int(par["lead_time"])
        ss = Z_SERVICE_95 * sigma_jour * math.sqrt(L)
        point_commande = d_jour * L + ss
        niveau_cible = point_commande + d_jour * par["couverture"]

        # Flux propre à ce couple client-produit : voir `_rng_pour`.
        r = _rng_pour(f"client|{pc['client']}|{pc['produit']}")
        situation = r.choice(situations, p=poids)
        if situation == "sain":
            stock = r.uniform(point_commande, max(niveau_cible, point_commande * 1.05))
        elif situation == "a_commander":
            stock = r.uniform(point_commande * 0.35, point_commande)
        elif situation == "rupture":
            stock = r.uniform(0, point_commande * 0.2)
        else:
            stock = r.uniform(niveau_cible, niveau_cible * 1.9)
        # Un produit tiré comme « sain », « à commander » ou « en surstock » a par
        # DÉFINITION du stock. L'arrondi à l'entier ramenait pourtant à zéro toute
        # valeur inférieure à 0,5 — cas fréquent des références à faible rotation,
        # dont le point de commande vaut moins d'une unité. La simulation
        # produisait ainsi 856 ruptures sur 1 892 références (45 %) là où son
        # profil n'en prévoit que 8 %, et le briefing annonçait une pénurie
        # généralisée qui n'existait que dans l'arrondi.
        stock = round(stock)
        stock = float(max(0.0, stock) if situation == "rupture" else max(1.0, stock))

        date_peremption = None
        if par["perissable"] and stock > 0:
            duree = int(par["duree_vie_mois"])
            rotation = (d_jour * 365) / stock if stock > 0 else 0
            usure = r.uniform(0.25, 0.85 if rotation < 2 else 0.6)
            restant_j = max(5, int(duree * 30 * (1 - usure)))
            date_peremption = ref + timedelta(days=restant_j)

        prix = pc["prix_unitaire"] if pc["prix_unitaire"] > 0 else 0.0
        cout_unitaire = prix * 0.72

        lignes.append((
            pc["client"], pc["produit"], famille, stock,
            round(d_jour, 6), round(sigma_jour, 6), L,
            round(ss, 6), round(point_commande, 6), round(niveau_cible, 6),
            round(cout_unitaire, 3), round(stock * cout_unitaire, 2),
            date_peremption, str(situation), True,
        ))

    con.execute("DROP TABLE IF EXISTS stock_simule")
    con.execute("""
        CREATE TABLE stock_simule (
            client            VARCHAR,
            produit           VARCHAR,
            famille           VARCHAR,
            stock_actuel      DOUBLE,
            demande_jour      DOUBLE,
            sigma_jour        DOUBLE,
            lead_time_jours   INTEGER,
            stock_securite    DOUBLE,
            point_commande    DOUBLE,
            niveau_cible      DOUBLE,
            cout_unitaire     DOUBLE,
            valeur_stock      DOUBLE,
            date_peremption   DATE,
            situation         VARCHAR,
            is_simulated      BOOLEAN
        )
    """)
    con.executemany(
        "INSERT INTO stock_simule VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", lignes)

    # Métadonnées de génération (traçabilité de la simulation)
    con.execute("DROP TABLE IF EXISTS stock_simule_meta")
    con.execute("""
        CREATE TABLE stock_simule_meta (
            genere_le TIMESTAMP, seed INTEGER, n_produits INTEGER,
            date_observation DATE, modele VARCHAR, avertissement VARCHAR,
            signature_demande VARCHAR
        )
    """)
    con.execute("""
        INSERT INTO stock_simule_meta VALUES (now(), ?, ?, ?, ?, ?, ?)
    """, [SIMULATION_SEED, len(lignes), ref,
          "politique (s,S) : s = d×L + z·σ·√L (z=1.65, service 95%) ; "
          "S = s + d×couverture ; calibrage sur la demande réelle 6 ans",
          "DONNÉES SIMULÉES — l'ERP ne contient aucune donnée de stock. "
          "Ces valeurs démontrent la chaîne de gestion, elles ne mesurent rien.",
          signature_demande])

    stats = con.execute("""
        SELECT count(*), sum(valeur_stock),
               count(*) FILTER (WHERE situation = 'rupture'),
               count(*) FILTER (WHERE situation = 'a_commander'),
               count(*) FILTER (WHERE situation = 'surstock')
        FROM stock_simule
    """).fetchone()
    con.close()

    out = {
        "produits": int(stats[0]), "valeur_stock_dt": round(float(stats[1] or 0), 0),
        "en_rupture": int(stats[2]), "a_commander": int(stats[3]),
        "en_surstock": int(stats[4]), "seed": SIMULATION_SEED,
        "regenere": True, "is_simulated": True,
    }
    if verbose:
        print(f"[stock] {out['produits']} produits générés (graine {SIMULATION_SEED})")
        print(f"[stock] valorisation : {out['valeur_stock_dt']:,.0f} DT".replace(",", " "))
        print(f"[stock] rupture={out['en_rupture']} à_commander={out['a_commander']} "
              f"surstock={out['en_surstock']}")
        print("[stock] DONNEES SIMULEES -- voir docs/STOCK_SIMULE.md")
    return out


if __name__ == "__main__":
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Génère le stock simulé")
    ap.add_argument("--force", action="store_true", help="régénérer")
    ap.add_argument("--stats", action="store_true", help="statistiques seulement")
    args = ap.parse_args()

    if args.stats:
        con = _connect()
        try:
            for r in con.execute("""
                SELECT situation, count(*), round(sum(valeur_stock)) FROM stock_simule
                GROUP BY 1 ORDER BY 2 DESC""").fetchall():
                print(f"  {r[0]:14} {r[1]:>5} produits  {r[2]:>14,.0f} DT".replace(",", " "))
        finally:
            con.close()
    else:
        generate_stock(force=args.force)
