"""
tests/test_stock.py
===================
Tests du module de stock SIMULÉ.

Deux familles de tests, d'importance égale :

1. **Cohérence du modèle** — la simulation doit respecter les règles de gestion
   qu'elle prétend appliquer : politique (s,S), stock de sécurité, couverture,
   reproductibilité par la graine.

2. **Garde-fous d'honnêteté** — le marquage « données simulées » doit être
   présent partout. Un test qui échoue ici signale un risque de présenter du
   synthétique comme du réel : c'est le plus important du fichier.

Exécution :
    python -m pytest tests/test_stock.py -v
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from ml_engine.analytics.kpi_engine import STORE_PATH
from ml_engine.stock.generator import (FAMILY_PARAMS, PROFIL_SITUATION,
                                       SIMULATION_SEED, Z_SERVICE_95,
                                       _infer_famille)
from ml_engine.stock.stock_engine import (AVERTISSEMENT, compute_stock_kpis,
                                          stock_available)

besoin_stock = pytest.mark.skipif(
    not (os.path.exists(str(STORE_PATH)) and stock_available()),
    reason="stock simulé non généré")


# ── 1. GARDE-FOUS D'HONNÊTETÉ (les plus importants) ─────────────────────────
def test_avertissement_dit_simule():
    a = AVERTISSEMENT.upper()
    assert "SIMUL" in a, "l'avertissement doit contenir le mot « simulé »"
    assert "AUCUNE DONNÉE DE STOCK" in a or "AUCUNE DONNEE DE STOCK" in a


@besoin_stock
def test_toute_reponse_porte_le_drapeau():
    k = compute_stock_kpis()
    assert k["is_simulated"] is True, "is_simulated doit TOUJOURS être True"
    assert k["avertissement"], "l'avertissement doit accompagner chaque réponse"


@besoin_stock
def test_chaque_ligne_est_marquee_en_base():
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    n_total, n_marque = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE is_simulated) FROM stock_simule"
    ).fetchone()
    con.close()
    assert n_total == n_marque, "chaque ligne doit porter is_simulated = TRUE"


@besoin_stock
def test_metadonnees_de_simulation_tracees():
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    m = con.execute("SELECT seed, modele, avertissement FROM stock_simule_meta").fetchone()
    con.close()
    assert m[0] == SIMULATION_SEED
    assert "s,S" in m[1] or "(s,S)" in m[1], "le modèle doit être décrit"
    assert "SIMUL" in m[2].upper()


@besoin_stock
def test_agent_stock_ne_presente_jamais_la_simulation_comme_reelle():
    """Le constat du briefing ne doit jamais laisser croire à une observation.

    L'ancienne version de ce test attendait un constat marqué `[SIMULATION]`.
    Elle ne vérifiait plus rien : l'agent ne lit plus du tout le stock simulé,
    et sans flux réels il se tait — le `if` sautait l'assertion. La garantie
    est désormais plus forte, et le test l'affirme sans condition :

      * simulation présente en base, flux réels absents → aucun constat ;
      * flux réels présents → constat marqué `is_simulated = False`, origine
        des chiffres déclarée (les factures).
    """
    from agents.fleet.nodes import constat_stock
    sans_reel = constat_stock({"kpis": {"stock_flux_reel": {"disponible": False}}})
    assert not sans_reel.get("findings"), "le volet stock est retombé sur la simulation"

    reel = constat_stock({"kpis": {"stock_flux_reel": {
        "disponible": True, "valeur_immobilisee_dt": 1_000_000,
        "n_references_accumulees": 10}}})
    f = reel["findings"][0]
    assert f["is_simulated"] is False
    assert "factures" in f["origine_des_chiffres"]


# ── 2. COHÉRENCE DU MODÈLE ──────────────────────────────────────────────────
def test_profil_situation_somme_a_1():
    assert sum(PROFIL_SITUATION.values()) == pytest.approx(1.0)


def test_parametres_familles_plausibles():
    for nom, p in FAMILY_PARAMS.items():
        assert 7 <= p["lead_time"] <= 120, f"délai fournisseur irréaliste : {nom}"
        assert 15 <= p["couverture"] <= 180
        if p["perissable"]:
            assert p["duree_vie_mois"] > 0


def test_inference_famille():
    assert _infer_famille("VIDAS TSH 60 tests", {}) == "REACTIF"
    assert _infer_famille("AUTOMATE D'IMMUNOANALYSES", {}) == "EQUIPEMENT"
    assert _infer_famille("MAINTENANCE ANNUELLE SAV", {}) == "SERVICE"
    assert _infer_famille("CONE 1000 UL", {}) == "CONSOMMABLE"


@besoin_stock
def test_politique_s_S_respectee():
    """point_commande = d×L + SS et niveau_cible > point_commande, pour tous."""
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    rows = con.execute("""
        SELECT demande_jour, lead_time_jours, stock_securite,
               point_commande, niveau_cible, sigma_jour
        FROM stock_simule LIMIT 500
    """).fetchall()
    con.close()
    for d, L, ss, s, S, sigma in rows:
        attendu_ss = Z_SERVICE_95 * sigma * math.sqrt(L)
        assert ss == pytest.approx(attendu_ss, rel=0.02), "stock de sécurité incohérent"
        assert s == pytest.approx(d * L + ss, rel=0.02), "point de commande incohérent"
        assert S > s, "le niveau cible doit dépasser le point de commande"


@besoin_stock
def test_aucun_stock_negatif():
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    n = con.execute("SELECT count(*) FROM stock_simule WHERE stock_actuel < 0 "
                    "OR valeur_stock < 0").fetchone()[0]
    con.close()
    assert n == 0


@besoin_stock
def test_services_exclus_du_stock():
    """Une prestation (SAV, formation) n'a pas de stock physique."""
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    n = con.execute("SELECT count(*) FROM stock_simule WHERE famille = 'SERVICE'").fetchone()[0]
    con.close()
    assert n == 0


@besoin_stock
def test_calibrage_sur_la_demande_reelle():
    """La demande journalière doit provenir des ventes réelles, pas du hasard.

    Le calcul de référence reproduit EXACTEMENT le filtre du générateur
    (`_collect_demand`) : les années de demande nette nulle ou négative sont
    écartées AVANT la moyenne. Sans ce filtre, le test comparait deux grandeurs
    différentes — ce qui restait invisible tant que les quantités étaient toutes
    positives, et a cessé de l'être avec le passage aux quantités signées.
    """
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    r = con.execute("""
        WITH annuel AS (
            SELECT produit, year, sum(qte) AS qte
            FROM product_sales
            WHERE produit IS NOT NULL AND qte > 0
            GROUP BY produit, year
        )
        SELECT s.demande_jour, sum(a.qte) / 365.0 / count(*) AS attendu
        FROM stock_simule s JOIN annuel a ON a.produit = s.produit
        GROUP BY s.produit, s.demande_jour LIMIT 200
    """).fetchall()
    con.close()
    assert r, "jointure stock ↔ ventes vide"
    ecarts = [abs(a - b) / max(b, 1e-9) for a, b in r if b > 0]
    # tolérance large : moyenne annuelle vs somme/années, arrondis
    part = sum(1 for e in ecarts if e < 0.5) / len(ecarts)
    assert part > 0.8, (
        f"seuls {part:.0%} des produits suivent la demande réelle — "
        "le stock est probablement calibré sur une version périmée de "
        "`product_sales` (voir la signature de demande du générateur).")


@besoin_stock
def test_reproductibilite_de_la_graine():
    """Même graine → mêmes valeurs. Condition d'un travail scientifique."""
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    avant = con.execute("SELECT produit, stock_actuel FROM stock_simule "
                        "ORDER BY produit LIMIT 40").fetchall()
    con.close()
    from ml_engine.stock.generator import generate_stock
    generate_stock(force=True, verbose=False)
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    apres = con.execute("SELECT produit, stock_actuel FROM stock_simule "
                        "ORDER BY produit LIMIT 40").fetchall()
    con.close()
    assert avant == apres, "la génération doit être reproductible (graine fixée)"


def test_le_tirage_ne_depend_que_de_la_cle():
    """Reproductibilité par CONSTRUCTION, et non par chance d'ordonnancement.

    Un flux aléatoire unique partagé par toutes les lignes rendait chaque valeur
    dépendante de tout ce qui avait été tiré avant elle : deux lignes de même
    chiffre d'affaires se départageant autrement — ce que SQL ne garantit pas
    sans clé de tri unique — suffisait à décaler la simulation entière.

    En dérivant le générateur de la graine ET de la clé de la ligne, la valeur
    d'un produit ne dépend plus que de lui-même. C'est une garantie plus forte
    qu'un tri stable : elle survit à l'ajout ou au retrait d'un autre produit.
    """
    from ml_engine.stock.generator import _rng_pour

    # Même clé → même séquence, à chaque appel.
    a = _rng_pour("global|PRODUIT X").uniform(0, 1, 5).tolist()
    b = _rng_pour("global|PRODUIT X").uniform(0, 1, 5).tolist()
    assert a == b, "une même clé doit toujours donner la même séquence"

    # Clés différentes → séquences indépendantes.
    c = _rng_pour("global|PRODUIT Y").uniform(0, 1, 5).tolist()
    assert a != c, "deux clés distinctes ne doivent pas se superposer"

    # Stable d'un PROCESSUS à l'autre : `hash()` ne l'est pas en Python, la
    # randomisation des chaînes changerait la simulation à chaque exécution.
    assert _rng_pour("global|PRODUIT X").uniform(0, 1) == pytest.approx(a[0])


# ── 3. INDICATEURS ──────────────────────────────────────────────────────────
@besoin_stock
def test_indicateurs_globaux_plausibles():
    k = compute_stock_kpis()
    assert k["n_produits"] > 100
    assert k["valeur_stock_dt"] > 0
    assert 0 <= k["taux_service_estime_pct"] <= 100
    assert k["taux_rotation"] > 0
    assert k["couverture_moyenne_jours"] > 0


@besoin_stock
def test_alertes_reappro_actionnables():
    """Une alerte doit toujours porter une quantité à commander exploitable."""
    k = compute_stock_kpis(limit_alertes=10)
    for a in k["alertes_reappro"]:
        assert a["quantite_a_commander"] >= 1, "pas d'alerte pour moins d'une unité"
        assert a["stock_actuel"] <= a["point_commande"]
        assert a["lead_time_jours"] > 0


@besoin_stock
def test_alertes_peremption_coherentes():
    """La perte annoncée = quantité qui expirera avant d'être consommée."""
    k = compute_stock_kpis(limit_alertes=10)
    for p in k["alertes_peremption"]:
        assert p["jours_restants"] > 0
        assert p["quantite_perdue"] > 0
        assert p["perte_estimee_dt"] >= 0


@besoin_stock
def test_filtre_par_famille():
    k = compute_stock_kpis(famille="REACTIF")
    assert k["n_produits"] > 0
    assert all(f["famille"] == "REACTIF" for f in k["par_famille"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
